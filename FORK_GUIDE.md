# Fork Guide: Creating Your Own Radarr Operation Tool

This guide shows you how to fork this project and create your own Radarr-based automation tool with a different operation.

## What's Reusable vs. What's Specific

### ✅ Reusable (Keep These)

**Core Modules** (`core/` directory):
- `core/config.py` - Configuration management
- `core/radarr.py` - Radarr API client
- `core/queue.py` - Generic operation queue system

**Infrastructure**:
- `docker-compose.yml` - Docker setup
- `Dockerfile` - Container configuration
- `requirements.txt` - Python dependencies
- `templates/index.html` - Web UI (with modifications)

### ❌ Operation-Specific (Replace These)

**Operation Modules** (`operations/` directory):
- `operations/copy_operation.py` - Copy with checksum verification
- `operations/leftovers.py` - Leftover files management

These are specific to the "safe mover" use case and should be replaced with your own operation logic.

## Step-by-Step Fork Instructions

### 1. Fork the Repository

```bash
git clone https://github.com/your-username/radarr-safe-mover.git
cd radarr-safe-mover
git checkout -b my-operation
```

### 2. Create Your Operation Handler

Create a new file `operations/my_operation.py`:

```python
"""My custom operation for Radarr movies"""
from core.queue import OperationHandler
from core.radarr import RadarrClient
import logging

logger = logging.getLogger(__name__)


class MyOperationHandler(OperationHandler):
    """Handler for my custom operation"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        """
        Execute your custom operation
        
        Args:
            movie: Movie data from Radarr API
            update_status: Callback to update status (e.g., 'processing', 'analyzing')
            update_progress: Callback to update progress text
        
        Raises:
            Exception: If operation fails
        """
        # Get configuration
        config = self.config_manager.config
        
        # Initialize Radarr client
        radarr = RadarrClient(
            config['radarr_host'],
            config['radarr_port'],
            config['radarr_api_key']
        )
        
        # Step 1: Your first operation step
        update_status('step1')
        update_progress('Doing step 1...')
        logger.info(f"Processing movie: {movie['title']}")
        
        # Your logic here
        # ...
        
        # Step 2: Your second operation step
        update_status('step2')
        update_progress('Doing step 2...')
        
        # More logic here
        # ...
        
        # Step 3: Update Radarr if needed
        if needs_update:
            update_status('updating')
            update_progress('Updating Radarr...')
            radarr.update_movie(movie['id'], updated_movie_data)
            radarr.rescan_movie(movie['id'])
        
        logger.info(f"Successfully completed: {movie['title']}")
```

### 3. Update Main Application

Edit `app.py` to use your operation:

```python
# Change this import:
from operations.copy_operation import CopyOperationHandler

# To this:
from operations.my_operation import MyOperationHandler

# And update the initialization:
operation_handler = MyOperationHandler(config_manager)
```

### 4. Remove Unused Features (Optional)

If you don't need leftover files functionality:

**A. Delete the file:**
```bash
rm operations/leftovers.py
```

**B. Remove routes from `app.py`:**

Delete these route handlers:
- `@app.route('/api/leftovers', methods=['GET'])`
- `@app.route('/api/leftovers', methods=['DELETE'])`
- `@app.route('/api/leftovers/recopy', methods=['POST'])`

**C. Update UI (`templates/index.html`):**

Remove the Leftovers section:
```html
<!-- Remove this entire section -->
<div class="section">
    <div class="section-title">
        <span>🗑️ Leftover Files</span>
        ...
    </div>
    ...
</div>
```

### 5. Customize UI

Update `templates/index.html` to match your operation:

**Change page title:**
```html
<title>My Radarr Tool</title>
<h1>🎬 My Radarr Tool</h1>
```

**Update section titles:**
```html
<div class="section-title">
    <span>📋 Operation Queue</span>  <!-- Instead of "Copy Queue" -->
</div>
```

**Customize status badges:**

Add your custom statuses in the CSS:
```css
.status.step1 {
    background: #42A5F5;
    color: #fff;
}

.status.step2 {
    background: #AB47BC;
    color: #fff;
}
```

And in the JavaScript:
```javascript
// Update status display logic
const statusIcon = {
    'pending': '🟠',
    'step1': '🔵',
    'step2': '🟣',
    'updating': '🔵',
    'completed': '🟢',
    'failed': '🔴'
};
```

### 6. Update Configuration (If Needed)

If your operation needs additional config:

**A. Update default config in `core/config.py`:**
```python
def _default_config(self):
    return {
        'radarr_host': '',
        'radarr_port': '',
        'radarr_api_key': '',
        'ssd_root_folder': '',
        'hdd_root_folder': '',
        'my_custom_setting': ''  # Add your setting
    }
```

**B. Add UI field in `templates/index.html`:**
```html
<div class="form-group">
    <label>My Custom Setting:</label>
    <input type="text" id="my_custom_setting" placeholder="value">
</div>
```

**C. Update save/load logic in JavaScript:**
```javascript
// In saveSettings():
const config = {
    radarr_host: document.getElementById('radarr_host').value,
    radarr_port: document.getElementById('radarr_port').value,
    radarr_api_key: document.getElementById('radarr_api_key').value,
    my_custom_setting: document.getElementById('my_custom_setting').value
};

// In loadConfig():
document.getElementById('my_custom_setting').value = config.my_custom_setting || '';
```

### 7. Update Documentation

**A. Update `README.md`:**
- Change project name and description
- Update features list
- Modify usage instructions
- Update technical details

**B. Update `PROJECT_CONTEXT.md`:**
- Describe your operation
- Update problem statement
- Modify solution description

### 8. Test Your Fork

```bash
# Build and run
docker compose down
docker compose up -d --build

# Check logs
docker compose logs -f

# Test in browser
open http://localhost:6970
```

### 9. Rename Project

```bash
# Update project name in files
sed -i 's/radarr-safe-mover/my-radarr-tool/g' README.md
sed -i 's/Radarr Safe Mover/My Radarr Tool/g' README.md

# Rename repository
git remote set-url origin https://github.com/your-username/my-radarr-tool.git
```

## Example: Quality Analyzer

Here's a complete example of a forked operation:

```python
# operations/quality_analyzer.py
from core.queue import OperationHandler
from core.radarr import RadarrClient
import logging

logger = logging.getLogger(__name__)


class QualityAnalyzerHandler(OperationHandler):
    """Analyze movie quality and suggest upgrades"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        config = self.config_manager.config
        radarr = RadarrClient(
            config['radarr_host'],
            config['radarr_port'],
            config['radarr_api_key']
        )
        
        # Analyze current quality
        update_status('analyzing')
        update_progress('Analyzing video quality...')
        
        movie_file = movie.get('movieFile', {})
        quality = movie_file.get('quality', {}).get('quality', {})
        current_quality = quality.get('name', 'Unknown')
        
        logger.info(f"Current quality: {current_quality}")
        
        # Check if upgrade available
        update_status('checking')
        update_progress('Checking for better quality...')
        
        target_quality = config.get('target_quality', 'Bluray-1080p')
        
        if current_quality != target_quality:
            # Tag movie for upgrade
            update_status('tagging')
            update_progress('Tagging for quality upgrade...')
            
            tags = movie.get('tags', [])
            if 'needs-upgrade' not in tags:
                tags.append('needs-upgrade')
                movie['tags'] = tags
                radarr.update_movie(movie['id'], movie)
            
            logger.info(f"Tagged {movie['title']} for upgrade")
        else:
            logger.info(f"{movie['title']} already at target quality")
```

## Common Patterns

### Pattern 1: File Operations

```python
def execute(self, movie, update_status, update_progress):
    movie_file = movie.get('movieFile', {})
    file_path = movie_file.get('path')
    
    # Work with the file
    import os
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        # Do something with the file
```

### Pattern 2: External API Calls

```python
def execute(self, movie, update_status, update_progress):
    import requests
    
    update_status('fetching')
    update_progress('Fetching data from external API...')
    
    response = requests.get(f'https://api.example.com/movie/{movie["tmdbId"]}')
    data = response.json()
    
    # Process data
```

### Pattern 3: Batch Processing

```python
def execute(self, movie, update_status, update_progress):
    # Process multiple files
    movie_file = movie.get('movieFile', {})
    file_path = movie_file.get('path')
    directory = os.path.dirname(file_path)
    
    for filename in os.listdir(directory):
        update_progress(f'Processing {filename}...')
        # Process each file
```

## Tips for Success

1. **Keep Core Modules Unchanged**: Don't modify `core/` unless absolutely necessary
2. **Use Logging**: Add plenty of `logger.info()` calls for debugging
3. **Handle Errors**: Wrap risky operations in try/except blocks
4. **Update Progress**: Call `update_progress()` frequently for user feedback
5. **Test Incrementally**: Test each step of your operation separately
6. **Document Your Changes**: Update README with your operation's specifics

## Getting Help

- Read [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed architecture info
- Check original `app.py` for reference implementation
- Look at `operations/copy_operation.py` for a complete example
- Review Radarr API docs: https://radarr.video/docs/api/

## License

Your fork inherits the MIT license. Remember to update copyright information if needed.