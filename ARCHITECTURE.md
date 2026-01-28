# Architecture Documentation

## Overview

This project is designed with modularity in mind, separating **core functionality** (reusable across different operations) from **operation-specific implementations** (like copying with verification).

## Project Structure

```
radarr-safe-mover/
├── core/                          # Core reusable modules
│   ├── __init__.py
│   ├── config.py                  # Configuration management
│   ├── radarr.py                  # Radarr API client
│   └── queue.py                   # Generic operation queue
│
├── operations/                    # Operation-specific implementations
│   ├── __init__.py
│   ├── copy_operation.py          # Copy with checksum verification
│   └── leftovers.py               # Leftover files management
│
├── templates/
│   └── index.html                 # Web UI
│
├── app.py                         # Original monolithic app (legacy)
├── app_refactored.py              # New modular app
├── docker-compose.yml
├── Dockerfile
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
- `get_all_movies()` - Get all movies
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

**Purpose**: Copy movies from SSD to HDD with verification (specific to this app).

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

### 2. `operations/leftovers.py` - LeftoversManager

**Purpose**: Find and manage files on SSD not tracked by Radarr (specific to this app).

**Features**:
- Scan SSD for untracked directories
- Identify missing HDD files
- Delete leftover files
- Prepare movies for re-copying

## How to Fork for Different Operations

### Step 1: Keep Core Modules

The `core/` directory contains all reusable functionality:
- ✅ Keep `core/config.py`
- ✅ Keep `core/radarr.py`
- ✅ Keep `core/queue.py`

### Step 2: Replace Operation-Specific Code

Create your own operation handler in `operations/`:

```python
# operations/my_operation.py
from core.queue import OperationHandler
from core.radarr import RadarrClient

class MyOperationHandler(OperationHandler):
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        """
        Implement your custom operation here
        
        Args:
            movie: Movie data from Radarr
            update_status: Callback to update status (e.g., 'processing', 'analyzing')
            update_progress: Callback to update progress text
        """
        # Example: Analyze movie quality
        update_status('analyzing')
        update_progress('Checking video quality...')
        
        # Your logic here
        movie_file = movie.get('movieFile', {})
        quality = movie_file.get('quality', {})
        
        # Update Radarr if needed
        radarr = RadarrClient(
            self.config_manager.get('radarr_host'),
            self.config_manager.get('radarr_port'),
            self.config_manager.get('radarr_api_key')
        )
        
        # Do something with the movie
        # ...
        
        update_progress('Completed!')
```

### Step 3: Update Main App

Modify `app_refactored.py` to use your operation:

```python
# Replace this:
from operations.copy_operation import CopyOperationHandler

# With this:
from operations.my_operation import MyOperationHandler

# And update initialization:
operation_handler = MyOperationHandler(config_manager)
```

### Step 4: Remove Unused Features

If you don't need leftovers functionality:
1. Delete `operations/leftovers.py`
2. Remove leftover routes from `app_refactored.py`:
   - `/api/leftovers` (GET, DELETE)
   - `/api/leftovers/recopy` (POST)
3. Remove leftover section from `templates/index.html`

### Step 5: Update UI

Modify `templates/index.html` to match your operation:
- Change section titles
- Update button labels
- Adjust status messages
- Customize progress display

## Example: Quality Upgrade Operation

Here's a complete example of forking for a different operation:

```python
# operations/quality_upgrade.py
from core.queue import OperationHandler
from core.radarr import RadarrClient
import requests

class QualityUpgradeHandler(OperationHandler):
    """Automatically upgrade movie quality if better version available"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        update_status('searching')
        update_progress('Searching for better quality...')
        
        radarr = RadarrClient(
            self.config_manager.get('radarr_host'),
            self.config_manager.get('radarr_port'),
            self.config_manager.get('radarr_api_key')
        )
        
        # Trigger automatic search in Radarr
        update_status('upgrading')
        update_progress('Triggering quality upgrade...')
        
        response = requests.post(
            f"{radarr.base_url}/command",
            headers=radarr.headers,
            json={
                'name': 'MoviesSearch',
                'movieIds': [movie['id']]
            }
        )
        response.raise_for_status()
        
        update_progress('Upgrade search initiated!')
```

## Benefits of This Architecture

1. **Separation of Concerns**: Core logic separated from operation-specific code
2. **Reusability**: Core modules can be used in any Radarr-based tool
3. **Testability**: Each module can be tested independently
4. **Maintainability**: Changes to operations don't affect core functionality
5. **Extensibility**: Easy to add new operations without modifying core

## Deployment

To deploy the application:
```bash
docker compose down
docker compose up -d --build
```

## API Compatibility

The refactored version maintains **100% API compatibility** with the original:
- All endpoints remain the same
- Request/response formats unchanged
- Frontend requires no modifications

This ensures a smooth transition without breaking existing integrations.