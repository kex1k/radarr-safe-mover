# Radarr Safe Mover - Project Context

## Overview
A web-based tool for safely moving movies between SSD and HDD storage with full Radarr integration. Designed for home media server environments where you want to free up fast SSD storage by moving watched or less-accessed movies to slower HDD storage.

## Problem Statement
Media servers often use fast SSD storage for active content and slower HDD storage for archives. Manually moving files and updating Radarr is error-prone and time-consuming. This tool automates the process safely with verification.

## Solution
A single-page web application that:
1. Lists movies on SSD via Radarr API
2. Queues movies for transfer
3. Copies files with minimal system impact (ionice/nice)
4. Verifies integrity with SHA256 checksums
5. Updates Radarr automatically with new paths

## Technical Architecture

### Backend (Flask)
- **Framework**: Flask 3.0.0 with Gunicorn
- **Language**: Python 3.11
- **Key Libraries**: requests (Radarr API), hashlib (checksums)
- **Concurrency**: Threading for background copy queue
- **Storage**: JSON files for config and queue state

### Frontend (Vanilla JS)
- **Style**: Mobile-first responsive design
- **Framework**: None (vanilla JavaScript)
- **Updates**: Auto-refresh queue every 2 seconds
- **Theme**: Dark mode optimized

### Infrastructure
- **Container**: Docker (Compose v1 & v2 support)
- **Port**: 9696 (HTTP)
- **Volumes**:
  - `./data` → `/app/data` (config/queue)
  - SSD path → `/media/movies_ssd`
  - HDD path → `/media/movies_hdd`

## Key Features

### 1. Safe File Copying
- Uses `ionice -c3` (idle I/O priority)
- Uses `nice -n19` (lowest CPU priority)
- Minimizes impact on system performance
- Preserves file attributes with `cp -p`

### 2. Integrity Verification
- SHA256 checksum before and after copy
- Automatic cleanup of corrupted copies
- Prevents data loss

### 3. Radarr Integration
- Fetches movie list via API v3
- Filters by root folder path
- Updates movie paths after successful copy
- Triggers rescan for metadata refresh

### 4. Queue Management
- Sequential processing (one at a time)
- Status tracking: pending → copying → verifying → updating → completed
- Persistent queue survives restarts
- Remove pending items before processing

### 5. User Interface
- Mobile-optimized (works on phones/tablets)
- Three sections: Movies, Queue, Settings
- Real-time status updates
- One-click operations

## API Endpoints

### Configuration
- `GET /api/config` - Get current settings
- `POST /api/config` - Save settings and fetch root folders

### Radarr Integration
- `GET /api/rootfolders` - List available root folders
- `GET /api/movies` - List movies on SSD

### Queue Management
- `GET /api/queue` - Get current queue
- `POST /api/queue` - Add movie to queue
- `DELETE /api/queue/<id>` - Remove from queue

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

1. **Queue Addition**: User adds movie to queue
2. **Queue Processing**: Background thread picks up item
3. **File Copy**: Copy with ionice/nice to minimize impact
4. **Verification**: Calculate and compare SHA256 checksums
5. **Radarr Update**: Update movie path via API
6. **Rescan**: Trigger Radarr to rescan movie
7. **Completion**: Mark as completed, auto-remove after 5s

## Configuration

### Required Settings
- **Radarr Host**: IP or hostname of Radarr server
- **Radarr Port**: Usually 7878
- **Radarr API Key**: From Radarr Settings → General → Security
- **SSD Root Folder**: Source location (e.g., `/media/movies_ssd`)
- **HDD Root Folder**: Destination location (e.g., `/media/movies_hdd`)

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
- API key stored locally
- Not exposed to internet

### Recommendations
- Keep port 9696 internal only
- Use firewall rules if needed
- Regular backups of data directory
- Monitor disk space on both drives

## Performance Characteristics

### Copy Speed
- Limited by disk I/O (intentionally)
- ionice idle class: only copies when disk is idle
- nice -n19: lowest CPU priority
- Minimal impact on other services

### Resource Usage
- Low CPU (single-threaded copy)
- Low memory (streaming copy)
- Network: Only Radarr API calls
- Disk: One active copy at a time

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

## Future Enhancements (Not Implemented)

Potential improvements:
- Automatic cleanup of source files after successful copy
- Batch operations (select multiple movies)
- Progress bars for large files
- Email notifications on completion
- Scheduled automatic transfers
- Bandwidth limiting options
- Support for other *arr applications (Sonarr, etc.)

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