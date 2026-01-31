# Architecture Documentation

## Overview

Ultimate Radarr Toolbox построен с модульной архитектурой, разделяющей **core функциональность** (переиспользуемую для разных операций) от **operation-specific реализаций** (копирование, конвертация и т.д.).

## Project Structure

```
ultimate-radarr-toolbox/
├── core/                          # Core reusable modules
│   ├── __init__.py
│   ├── config.py                  # Configuration management
│   ├── radarr.py                  # Radarr API client
│   └── queue.py                   # Generic operation queue
│
├── operations/                    # Operation-specific implementations
│   ├── __init__.py
│   ├── copy_operation.py          # Copy with checksum verification
│   ├── convert_operation.py       # DTS to FLAC conversion
│   └── leftovers.py               # Leftover files management
│
├── templates/
│   └── index.html                 # Web UI with tabs
│
├── app.py                         # Main Flask application
├── docker-compose.yml
├── Dockerfile
├── convert-dts-to-flac.sh        # Original conversion script
└── requirements.txt
```

## Core Modules (Reusable)

### 1. `core/config.py` - ConfigManager

**Purpose**: Manage application configuration with file persistence.

**Key Methods**:
- `load()` - Load config from JSON file
- `save()` - Save config to JSON file
- `get(key)` - Get configuration value
- `set(key, value)` - Set configuration value
- `get_safe_config()` - Get config with sensitive data masked

**Usage**:
```python
from core.config import ConfigManager

config_manager = ConfigManager('data/config.json')
api_key = config_manager.get('radarr_api_key')
config_manager.set('ssd_root_folder', '/media/movies_ssd')
```

### 2. `core/radarr.py` - RadarrClient

**Purpose**: Interact with Radarr API v3.

**Key Methods**:
- `get_root_folders()` - Get all root folders
- `get_movies()` - Get all movies
- `get_movie(movie_id)` - Get specific movie
- `update_movie(movie_id, data)` - Update movie
- `rescan_movie(movie_id)` - Trigger rescan
- `filter_movies_by_root_folder(path)` - Filter movies by location

**Usage**:
```python
from core.radarr import RadarrClient

radarr = RadarrClient('192.168.1.100', '7878', 'api-key')
movies = radarr.filter_movies_by_root_folder('/media/movies_ssd')
radarr.update_movie(123, updated_movie_data)
```

### 3. `core/queue.py` - OperationQueue & OperationHandler

**Purpose**: Generic queue system for processing operations on movies.

**OperationQueue** manages:
- Queue persistence (JSON file)
- History tracking (last 5 operations)
- Background processing thread
- Status updates

**OperationHandler** (abstract base class):
- Defines interface for custom operations
- Must implement `execute(movie, update_status, update_progress)`

**Key Methods**:
- `add_to_queue(movie)` - Add movie to queue
- `remove_from_queue(item_id)` - Remove from queue
- `clear_queue()` - Emergency clear
- `get_queue()` - Get current queue
- `get_history()` - Get operation history
- `start_processor()` - Start background thread

**Usage**:
```python
from core.queue import OperationQueue, OperationHandler

class MyOperation(OperationHandler):
    def execute(self, movie, update_status, update_progress):
        update_status('processing')
        update_progress('Doing something...')
        # Your operation logic here
        
queue = OperationQueue(
    queue_file='data/queue.json',
    history_file='data/history.json',
    operation_handler=MyOperation()
)
queue.start_processor()
```

## Operation-Specific Modules

### 1. `operations/copy_operation.py` - CopyOperationHandler

**Purpose**: Copy movies from SSD to HDD with verification.

**Features**:
- rsync with ionice/nice for minimal system impact
- SHA256 checksum verification
- Automatic permission setting (0755/0644)
- Progress reporting
- Radarr path update after copy

**Implementation**:
```python
class CopyOperationHandler(OperationHandler):
    def execute(self, movie, update_status, update_progress):
        # 1. Copy file with rsync
        # 2. Verify checksums
        # 3. Update Radarr
        # 4. Trigger rescan
```

### 2. `operations/convert_operation.py` - ConvertOperationHandler

**Purpose**: Convert DTS audio to FLAC 7.1.

**Features**:
- Validates DTS 5.1(side) format
- Converts to FLAC 7.1 with proper channel mapping
- Uses ionice/nice for HDD files
- Replaces original file in-place
- Triggers Radarr rescan

**Implementation**:
```python
class ConvertOperationHandler(OperationHandler):
    def execute(self, movie, update_status, update_progress):
        # 1. Validate audio format
        # 2. Convert DTS to FLAC 7.1
        # 3. Merge audio track
        # 4. Replace original file
        # 5. Trigger rescan
```

### 3. `operations/leftovers.py` - LeftoversManager

**Purpose**: Find and manage files on SSD not tracked by Radarr.

**Features**:
- Scan SSD for untracked directories
- Identify missing HDD files
- Delete leftover files
- Prepare movies for re-copying

## Multi-Module Architecture

### Dual Queue System

Приложение использует две независимые очереди:

```python
# Copy queue
copy_queue = OperationQueue(
    queue_file='data/copy_queue.json',
    history_file='data/copy_history.json',
    operation_handler=copy_operation_handler
)

# Convert queue
convert_queue = OperationQueue(
    queue_file='data/convert_queue.json',
    history_file='data/convert_history.json',
    operation_handler=convert_operation_handler
)
```

Каждая очередь:
- Работает в отдельном потоке
- Имеет свою историю операций
- Независимо обрабатывает задачи
- Может быть очищена отдельно

### Tab-Based UI

Интерфейс разделен на три вкладки:

1. **Safe Copy Tab** - Копирование файлов
   - Movies on SSD
   - Copy Queue
   - Copy History
   - Leftovers

2. **DTS Converter Tab** - Конвертация аудио
   - Movies with DTS Audio
   - Conversion Queue
   - Conversion History

3. **Settings Tab** - Настройки
   - Radarr Configuration
   - Auto-detected Root Folders

## How to Add New Operations

### Step 1: Create Operation Handler

```python
# operations/new_operation.py
from core.queue import OperationHandler
from core.radarr import RadarrClient

class NewOperationHandler(OperationHandler):
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        # Your operation logic
        pass
```

### Step 2: Add Queue in app.py

```python
from operations.new_operation import NewOperationHandler

new_operation_handler = NewOperationHandler(config_manager)
new_queue = OperationQueue(
    queue_file='data/new_queue.json',
    history_file='data/new_history.json',
    operation_handler=new_operation_handler
)
new_queue.start_processor()
```

### Step 3: Add API Endpoints

```python
@app.route('/api/queue/new', methods=['GET'])
def get_new_queue():
    return jsonify(new_queue.get_queue())

@app.route('/api/queue/new', methods=['POST'])
def add_to_new_queue():
    data = request.json
    movie = data.get('movie')
    new_queue.add_to_queue(movie)
    return jsonify({'success': True})
```

### Step 4: Add UI Tab

```html
<!-- Add tab button -->
<button class="tab" onclick="switchTab('new-operation')">🆕 New Operation</button>

<!-- Add tab content -->
<div id="new-operation" class="tab-content">
    <!-- Your UI here -->
</div>
```

## Benefits of This Architecture

1. **Separation of Concerns**: Core logic separated from operation-specific code
2. **Reusability**: Core modules can be used in any Radarr-based tool
3. **Testability**: Each module can be tested independently
4. **Maintainability**: Changes to operations don't affect core functionality
5. **Extensibility**: Easy to add new operations without modifying core
6. **Scalability**: Multiple operations can run simultaneously

## Deployment

To deploy the application:
```bash
docker compose down
docker compose up -d --build
```

## API Compatibility

The application maintains consistent API patterns:
- All queue endpoints follow `/api/queue/<operation>` pattern
- All history endpoints follow `/api/history/<operation>` pattern
- Request/response formats are consistent across operations

This ensures easy integration and predictable behavior.