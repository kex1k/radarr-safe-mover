# Ultimate Radarr Toolbox

Flask web application for Radarr automation: safe SSD→HDD movie transfers with checksum verification, DTS→FLAC 7.1 audio conversion, and media integrity checking.

## Features

### 📦 Safe Copy Module
- Mobile-first web interface
- Fetch movies from SSD via Radarr API
- Copy queue with real-time status tracking
- Safe copying using rsync with ionice/nice (low I/O priority)
- xxHash3_128 checksum verification after copy
- Automatic Radarr update after successful copy
- Find orphaned files on SSD (not tracked by Radarr)
- Re-copy files missing on HDD
- Emergency queue clear
- Automatic permissions (0755/0644)

### 🎵 DTS Converter Module
- Auto-detect movies with DTS audio
- Convert DTS 5.1(side) to FLAC 7.1
- Separate conversion queue with progress
- ionice/nice for HDD files (minimal system load)
- Automatic original file replacement
- Radarr rescan trigger after conversion
- Proper 7.1 channel mapping

### 🔍 Media Integrity Checker
- Scan directories for video files
- Full ffmpeg decode verification (keyframes)
- xxHash3_128 checksum storage and comparison
- Detect corrupted or changed files
- Background processing with pause/resume

### ⚙️ General
- Tabbed interface for module switching
- Unified queue system for all operations
- Auto-refresh every 2 seconds
- Operation history (last 10)
- Emergency controls for each queue

## Requirements

- Docker
- Docker Compose (v1 or v2)
- Radarr API access
- ffmpeg, mkvtoolnix (included in Docker image)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ultimate-radarr-toolbox
```

2. Edit `docker-compose.yml` and set your SSD/HDD paths:
```yaml
volumes:
  - ./data:/app/data
  - ./temp:/app/temp  # Temp directory for conversion
  - /path/to/your/ssd/movies:/media/movies_ssd
  - /path/to/your/hdd/movies:/media/movies_hdd
  - /path/to/your/hdd/shows:/media/shows_hdd
environment:
  - TEMP_DIR=/app/temp  # Critical for avoiding eMMC wear
```

**Note:** Container paths (`/media/movies_ssd`, `/media/movies_hdd`) must match Radarr root folders.

3. Start the application:
```bash
./start.sh
```

Or manually:
```bash
docker compose up -d      # v2
docker-compose up -d      # v1
```

4. View logs:
```bash
docker compose logs -f
```

## Configuration

1. Open the web interface
2. Go to "⚙️ Settings" tab
3. Fill in Radarr settings:
   - **Radarr Host**: IP or hostname (e.g., `192.168.1.100`)
   - **Radarr Port**: Usually `7878`
   - **Radarr API Key**: From Radarr Settings → General → Security
4. Click "Save Settings"

Root folders are auto-detected from Radarr after saving.

## Usage

### Safe Copy
1. Go to "📦 Safe Copy" tab
2. Click "🔄 Refresh" to load SSD movies
3. Click "➕ Add to Queue" to queue a movie
4. Monitor progress in "Copy Queue" section

**Statuses:**
- 🟠 PENDING - Waiting in queue
- 🔵 COPYING - File transfer in progress
- 🟣 VERIFYING - Checksum verification
- 🔵 UPDATING - Updating Radarr
- 🟢 COMPLETED - Success
- 🔴 FAILED - Error occurred

### DTS Converter
1. Go to "🎵 DTS Converter" tab
2. Click "🔄 Refresh" to find DTS movies
3. Click "🎵 Convert to FLAC" to queue conversion
4. Monitor progress in "Conversion Queue" section

**Requirements:**
- Codec: DTS (any variant)
- Channel layout: 5.1(side)
- Result: FLAC 7.1 with proper channel mapping

### Media Integrity Checker
1. Go to "🔍 Integrity" tab
2. Configure watch directories
3. Run "Scan" to index files
4. Run "Verify" to check integrity
5. Run "Recheck" to compare checksums

## Technical Details

### Copy Process
1. Calculate source xxHash3_128 checksum
2. Copy with `ionice -c3 nice -n19 rsync --chmod=D0755,F0644`
3. Calculate destination checksum
4. Compare checksums (delete on mismatch)
5. Update movie path in Radarr
6. Trigger Radarr rescan

### Conversion Process
1. Find DTS 5.1(side) audio track via ffprobe
2. Convert to FLAC 7.1 with ffmpeg (compression level 8)
3. Merge new track with mkvmerge (replace existing FLAC)
4. Safe replace original file (backup → copy → verify → delete backup)
5. Rename file to reflect FLAC.7.1
6. Trigger Radarr rescan

### Integrity Check Process
1. **Scan**: Index video files with size/mtime fingerprint
2. **Verify**: ffmpeg decode check + xxHash3_128 calculation
3. **Recheck**: Compare stored checksums, detect changes

## Project Structure

```
ultimate-radarr-toolbox/
├── core/                      # Reusable modules
│   ├── config.py             # Configuration management
│   ├── radarr.py             # Radarr API client
│   └── queue.py              # Unified operation queue
├── operations/                # Operation implementations
│   ├── copy_operation.py     # Safe copy with verification
│   ├── convert_operation.py  # DTS to FLAC conversion
│   ├── file_operations.py    # Common file utilities
│   ├── media_operations.py   # ffprobe/ffmpeg utilities
│   ├── integrity_checker.py  # Media integrity system
│   └── leftovers.py          # Orphaned file management
├── templates/
│   └── index.html            # Web interface
├── data/                      # Runtime data (auto-created)
│   ├── config.json           # Settings
│   ├── queue.json            # Operation queue
│   ├── history.json          # Operation history
│   └── media_integrity.json  # Integrity data
├── app.py                     # Flask application
├── Dockerfile
├── docker-compose.yml
├── start.sh                   # Startup script
└── requirements.txt
```

## API Endpoints

### Configuration
- `GET /api/config` - Get settings (API key masked)
- `POST /api/config` - Update settings

### Movies
- `GET /api/movies` - Get SSD movies
- `GET /api/movies/dts` - Get movies with DTS audio
- `GET /api/movies/<id>/audio-info` - Get audio codec info

### Queue
- `GET /api/queue` - Get operation queue
- `POST /api/queue/add` - Add to queue (`{movie, operation_type}`)
- `DELETE /api/queue/<id>` - Remove from queue
- `POST /api/queue/clear` - Clear entire queue

### History
- `GET /api/history` - Get operation history (last 10)
- `POST /api/convert/retry` - Retry failed conversion

### Leftovers
- `GET /api/leftovers` - Find orphaned files
- `DELETE /api/leftovers` - Delete orphaned directory
- `POST /api/leftovers/recopy` - Re-copy orphaned file

### Integrity
- `GET /api/integrity/config` - Get integrity config
- `POST /api/integrity/config` - Update integrity config
- `POST /api/integrity/scan/start` - Start scan
- `POST /api/integrity/scan/stop` - Stop scan
- `GET /api/integrity/scan/status` - Get scan status
- `POST /api/integrity/verify/start` - Start verification
- `POST /api/integrity/verify/stop` - Stop verification
- `POST /api/integrity/verify/resume` - Resume verification
- `GET /api/integrity/verify/status` - Get verification status
- `POST /api/integrity/recheck/start` - Start recheck
- `POST /api/integrity/recheck/stop` - Stop recheck
- `GET /api/integrity/recheck/status` - Get recheck status
- `GET /api/integrity/files` - Get all indexed files
- `GET /api/integrity/files/broken` - Get broken files
- `GET /api/integrity/files/changed` - Get changed files
- `GET /api/integrity/stats` - Get statistics
- `POST /api/integrity/reset` - Reset all data
- `POST /api/integrity/clear-reports` - Clear reports
- `POST /api/integrity/reset-broken` - Reset broken to pending
- `GET /api/integrity/export-issues` - Export issues as text

## Security

This application is designed for home network use:
- Do not expose port 6970 to the internet
- Use in a protected local network
- Regularly backup your data

## Troubleshooting

### Cannot connect to Radarr
- Verify Radarr is running and accessible
- Check IP address and port
- Verify API key in Radarr settings

### Copy errors
- Ensure container has access to both folders
- Check file permissions
- Verify sufficient free space on HDD

### Conversion errors
- Verify file has DTS 5.1(side) audio
- Check logs for ffmpeg/mkvmerge errors
- Ensure TEMP_DIR has sufficient space

### Movies not showing
- Check Radarr settings
- Verify movies exist in configured folders
- Click "Refresh" to reload

## Logs

```bash
docker compose logs -f ultimate-radarr-toolbox
```

## Stop Application

```bash
docker compose down
```

## License

MIT License