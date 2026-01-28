# Radarr Safe Mover - Project Context

## Overview
A web-based tool for safely moving movies between SSD and HDD storage with full Radarr integration. Designed for home media server environments where you want to free up fast SSD storage by moving watched or less-accessed movies to slower HDD storage.

## Problem Statement
Media servers often use fast SSD storage for active content and slower HDD storage for archives. Manually moving files and updating Radarr is error-prone and time-consuming. This tool automates the process safely with verification.

## Solution
A single-page web application that:
1. Lists movies on SSD via Radarr API
2. Queues movies for transfer with real-time status tracking
3. Copies files with minimal system impact (rsync + ionice/nice)
4. Verifies integrity with SHA256 checksums (with progress reporting)
5. Updates Radarr automatically with new paths
6. Finds and manages leftover files not tracked by Radarr
7. Re-copies missing files from SSD to HDD
8. Emergency queue clearing for stuck operations

## Technical Architecture

### Backend (Flask)
- **Framework**: Flask 3.0.0 with Gunicorn
- **Language**: Python 3.11
- **Architecture**: Modular (core + operations)
- **Key Libraries**: requests (Radarr API), hashlib (checksums)
- **Concurrency**: Threading for background operation queue
- **Storage**: JSON files for config, queue, and history

### Frontend (Vanilla JS)
- **Style**: Mobile-first responsive design
- **Framework**: None (vanilla JavaScript)
- **Updates**: Auto-refresh queue every 2 seconds
- **Theme**: Dark mode optimized

### Infrastructure
- **Container**: Docker (Compose v1 & v2 support)
- **Port**: 6970 (HTTP)
- **Volumes**:
  - `./data` → `/app/data` (config/queue/history)
  - SSD path → `/media/movies_ssd`
  - HDD path → `/media/movies_hdd`

### Project Structure
```
radarr-safe-mover/
├── core/                    # Reusable modules
│   ├── config.py           # Configuration management
│   ├── radarr.py           # Radarr API client
│   └── queue.py            # Generic operation queue
├── operations/              # Operation-specific code
│   ├── copy_operation.py   # Copy with verification
│   └── leftovers.py        # Leftover files management
├── app.py                   # Main Flask application
└── templates/index.html     # Web UI
```

## Key Features

### 1. Safe File Copying
- Uses `rsync` for reliable file transfer
- Uses `ionice -c3` (idle I/O priority - only copies when disk is idle)
- Uses `nice -n19` (lowest CPU priority)
- Automatic permission setting: `--chmod=D0755,F0644`
  - Directories: `0755` (rwxr-xr-x) - readable by all, writable by owner
  - Files: `0644` (rw-r--r--) - readable by all, writable by owner
- Minimizes impact on system performance
- Progress reporting during copy

### 2. Integrity Verification
- SHA256 checksum before and after copy
- Progress reporting during verification (10% increments)
- Automatic cleanup of corrupted copies
- Prevents data loss
- Large file optimization (8MB chunks)

### 3. Radarr Integration
- Fetches movie list via API v3
- Filters by root folder path
- Auto-detects SSD/HDD root folders
- Updates movie paths after successful copy
- Triggers rescan for metadata refresh

### 4. Queue Management
- Sequential processing (one at a time)
- Status tracking: pending → copying → verifying → updating → completed
- Persistent queue survives restarts
- Remove pending items before processing
- Automatic removal of completed items
- Emergency queue clear for stuck operations

### 5. Leftover File Management
- Scans SSD for files not in Radarr
- Identifies movies on HDD with missing files
- Delete unwanted leftover files
- Re-copy missing files from SSD to HDD
- Size and file count reporting

### 6. User Interface
- Mobile-optimized (works on phones/tablets)
- Four sections: Movies, Queue, Leftovers, Settings
- Real-time status updates (auto-refresh every 2s)
- One-click operations
- Emergency controls

## API Endpoints

### Configuration
- `GET /api/config` - Get current settings (API key masked)
- `POST /api/config` - Save settings and auto-detect root folders

### Radarr Integration
- `GET /api/rootfolders` - List available root folders from Radarr
- `GET /api/movies` - List movies on SSD root folder

### Queue Management
- `GET /api/queue` - Get current queue with status
- `POST /api/queue` - Add movie to queue
- `DELETE /api/queue/<id>` - Remove pending item from queue
- `POST /api/queue/clear` - Emergency clear entire queue

### Leftover Files
- `GET /api/leftovers` - Find files on SSD not in Radarr
- `DELETE /api/leftovers` - Delete leftover directory
- `POST /api/leftovers/recopy` - Re-add movie to queue for copying

## Data Flow

```
User Action → API Request → Backend Processing → Radarr API → File System
                                    ↓
                            Queue Persistence (JSON)
                                    ↓
                            Background Thread Processing
                                    ↓
                            Status Updates → Frontend
```

## Copy Process Flow

1. **Queue Addition**: User adds movie to queue (status: pending)
2. **Queue Processing**: Background thread picks up first item
3. **File Copy**:
   - Status: copying
   - Uses rsync with ionice/nice for minimal impact
   - Reports progress in real-time
   - Sets permissions automatically (D0755, F0644)
4. **Verification**:
   - Status: verifying
   - Calculate SHA256 of source file (with progress)
   - Calculate SHA256 of destination file (with progress)
   - Compare checksums
   - Delete destination if mismatch
5. **Radarr Update**:
   - Status: updating
   - Update movie path via PUT /api/v3/movie/{id}
   - Trigger RescanMovie command
6. **Completion**:
   - Status: completed
   - Remove from queue immediately
   - Log success

### Error Handling
- **Copy failure**: Mark as failed, keep in queue, log error
- **Checksum mismatch**: Delete corrupted file, mark as failed
- **Radarr API error**: Mark as failed, keep in queue
- **Any exception**: Mark as failed, log full traceback

## Configuration

### Required Settings
- **Radarr Host**: IP or hostname of Radarr server
- **Radarr Port**: Usually 7878
- **Radarr API Key**: From Radarr Settings → General → Security

### Auto-Detected Settings
- **SSD Root Folder**: Automatically detected from Radarr (path containing `movies_ssd`)
- **HDD Root Folder**: Automatically detected from Radarr (path containing `movies_hdd`)

### Storage
- `data/config.json`: User settings
- `data/queue.json`: Current queue state

## Deployment Scenarios

### Docker Compose v1
```bash
docker-compose up -d
```

### Docker Compose v2
```bash
docker compose up -d
```

### Smart Start Script
```bash
./start.sh  # Automatically detects v1 or v2
```

## Security Considerations

### Design Assumptions
- Deployed in trusted home network
- No authentication required
- API key stored locally in JSON file
- Not exposed to internet

### Recommendations
- Keep port 6970 internal only
- Use firewall rules if needed
- Regular backups of data directory
- Monitor disk space on both drives
- Leftover file deletion is permanent (no recycle bin)

### File Permissions
- Directories: `0755` (rwxr-xr-x)
- Files: `0644` (rw-r--r--)
- Owner can read/write, others can only read
- Suitable for multi-user home media servers

## Performance Characteristics

### Copy Speed
- Limited by disk I/O (intentionally)
- ionice idle class: only copies when disk is idle
- nice -n19: lowest CPU priority
- rsync streaming: efficient for large files
- Minimal impact on other services (Plex, Radarr, etc.)

### Resource Usage
- Low CPU (single-threaded copy, lowest priority)
- Low memory (streaming copy with 8MB chunks)
- Network: Only Radarr API calls (minimal)
- Disk: One active copy at a time
- Background thread: daemon mode, auto-starts with Gunicorn

### Checksum Performance
- 8MB chunks for faster processing
- Progress reporting every 10%
- Optimized for large video files (10-50GB)

## Error Handling

### Copy Failures
- Checksum mismatch: Delete corrupted file
- Disk full: Mark as failed, keep in queue
- Permission errors: Mark as failed with error message

### Radarr API Errors
- Connection failed: Show error in UI
- Invalid API key: Show error in settings
- Movie not found: Skip update, mark as failed

### Recovery
- Queue persists across restarts
- Failed items remain in queue
- Manual retry by removing and re-adding

## Implemented Features (Latest)

### v1.0 - Core Functionality
- Basic copy queue with rsync
- SHA256 verification
- Radarr API integration
- Mobile-first UI

### v1.1 - Enhanced Reliability
- Fixed infinite loop bug in queue processor
- Added proper sleep intervals
- Improved logging with Python logging module
- Thread initialization for Gunicorn compatibility

### v1.2 - Leftover Management
- Find files on SSD not in Radarr
- Detect missing HDD files
- Delete leftover files
- Re-copy missing files

### v1.3 - Emergency Controls & Permissions
- Emergency queue clear button
- Automatic file permissions (0755/0644)
- Fixed re-copy using wrong paths
- Enhanced error handling

## Future Enhancements (Not Implemented)

Potential improvements:
- Automatic cleanup of source files after successful copy
- Batch operations (select multiple movies)
- Detailed progress bars with ETA
- Email/webhook notifications on completion
- Scheduled automatic transfers
- Bandwidth limiting options
- Support for other *arr applications (Sonarr, Lidarr, etc.)
- Pause/resume functionality
- Copy history and statistics

## Development Notes

### Testing
- Test with various file sizes
- Verify checksum validation works
- Test Radarr API error handling
- Confirm mobile responsiveness
- Test both Docker Compose v1 and v2

### Debugging
- Check logs: `docker-compose logs -f`
- Inspect queue: `cat data/queue.json`
- Verify volumes: `docker inspect radarr-safe-mover`
- Test Radarr API: Use browser or curl

### Common Issues
1. **Movies not showing**: Check SSD root folder path
2. **Copy fails**: Verify volume mounts and permissions
3. **Radarr not updating**: Check API key and connectivity
4. **Checksum fails**: Disk errors or insufficient space

## License
MIT License - Free for personal and commercial use