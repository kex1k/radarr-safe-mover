# Ultimate Radarr Toolbox - Project Context

## Overview
Многофункциональное веб-приложение для автоматизации работы с Radarr. Включает два основных модуля:
1. **Safe Copy** - безопасное перемещение фильмов между SSD и HDD с проверкой целостности
2. **DTS Converter** - автоматическая конвертация DTS аудио в FLAC 7.1

## Problem Statement
Медиа-серверы часто используют быстрое SSD хранилище для активного контента и медленное HDD для архивов. Также многие фильмы имеют DTS аудио, которое не все устройства могут воспроизводить. Ручное управление этими задачами отнимает время и чревато ошибками.

## Solution
Единое веб-приложение с табовым интерфейсом, которое:

### Модуль Safe Copy:
1. Показывает фильмы на SSD через Radarr API
2. Ставит фильмы в очередь копирования с отслеживанием статуса
3. Копирует файлы с минимальной нагрузкой (rsync + ionice/nice)
4. Проверяет целостность через SHA256 checksums
5. Автоматически обновляет пути в Radarr
6. Находит и управляет потерянными файлами

### Модуль DTS Converter:
1. Автоматически находит фильмы с DTS аудио
2. Ставит в очередь конвертации
3. Конвертирует DTS 5.1(side) в FLAC 7.1
4. Использует ionice/nice для файлов на HDD
5. Заменяет оригинальный файл
6. Триггерит пересканирование в Radarr

## Technical Architecture

### Backend (Flask)
- **Framework**: Flask 3.0.0 with Gunicorn
- **Language**: Python 3.11
- **Architecture**: Modular (core + operations)
- **Key Libraries**: 
  - requests (Radarr API)
  - hashlib (checksums)
  - subprocess (ffmpeg, rsync)
- **Concurrency**: Отдельные потоки для каждой очереди
- **Storage**: JSON файлы для конфигурации и очередей

### Frontend (Vanilla JS)
- **Style**: Mobile-first responsive design
- **Framework**: None (vanilla JavaScript)
- **Updates**: Auto-refresh очередей каждые 2 секунды
- **Theme**: Dark mode optimized
- **Navigation**: Tab-based interface

### Infrastructure
- **Container**: Docker с ffmpeg
- **Port**: 6970 (HTTP)
- **Volumes**:
  - `./data` → `/app/data` (config/queues/history)
  - SSD path → `/media/movies_ssd`
  - HDD path → `/media/movies_hdd`

### Project Structure
```
ultimate-radarr-toolbox/
├── core/                      # Reusable modules
│   ├── config.py             # Configuration management
│   ├── radarr.py             # Radarr API client
│   └── queue.py              # Generic operation queue
├── operations/                # Operation-specific code
│   ├── copy_operation.py     # Copy with verification
│   ├── convert_operation.py  # DTS to FLAC conversion
│   └── leftovers.py          # Leftover files management
├── app.py                     # Main Flask application
└── templates/index.html       # Web UI with tabs
```

## Key Features

### 1. Safe File Copying
- Uses `rsync` for reliable file transfer
- Uses `ionice -c3` (idle I/O priority)
- Uses `nice -n19` (lowest CPU priority)
- Automatic permission setting: `--chmod=D0755,F0644`
- Progress reporting during copy
- SHA256 checksum verification

### 2. DTS to FLAC Conversion
- Automatic detection of DTS audio files
- Validates DTS 5.1(side) format
- Converts to FLAC 7.1 with proper channel mapping
- Uses ionice/nice for HDD files
- Replaces original file in-place
- Triggers Radarr rescan

### 3. Dual Queue System
- Separate queues for copy and convert operations
- Independent processing threads
- Persistent queues survive restarts
- Real-time status updates
- Emergency clear for each queue

### 4. Radarr Integration
- Fetches movie list via API v3
- Filters by root folder path
- Auto-detects SSD/HDD root folders
- Updates movie paths after operations
- Triggers rescan for metadata refresh

### 5. Tab-Based UI
- **Safe Copy Tab**: Original functionality
- **DTS Converter Tab**: Audio conversion
- **Settings Tab**: Configuration
- Smooth tab switching
- Independent data loading per tab

## API Endpoints

### Configuration
- `GET /api/config` - Get current settings
- `POST /api/config` - Save settings

### Movies
- `GET /api/movies` - List movies on SSD
- `GET /api/movies/dts` - List movies with DTS audio

### Copy Queue
- `GET /api/queue/copy` - Get copy queue
- `POST /api/queue/copy` - Add to copy queue
- `DELETE /api/queue/copy/<id>` - Remove from copy queue
- `POST /api/queue/copy/clear` - Clear copy queue

### Convert Queue
- `GET /api/queue/convert` - Get convert queue
- `POST /api/queue/convert` - Add to convert queue
- `DELETE /api/queue/convert/<id>` - Remove from convert queue
- `POST /api/queue/convert/clear` - Clear convert queue

### History
- `GET /api/history/copy` - Copy operation history
- `GET /api/history/convert` - Convert operation history

### Leftover Files
- `GET /api/leftovers` - Find leftover files
- `DELETE /api/leftovers` - Delete leftover file
- `POST /api/leftovers/recopy` - Re-copy file

## Data Flow

```
User Action → API Request → Backend Processing → Radarr API / File System
                                     ↓
                             Queue Persistence (JSON)
                                     ↓
                             Background Thread Processing
                                     ↓
                             Status Updates → Frontend
```

## Copy Process Flow

1. **Queue Addition**: User adds movie (status: pending)
2. **Queue Processing**: Background thread picks up item
3. **File Copy**: rsync with ionice/nice, progress reporting
4. **Verification**: SHA256 checksums comparison
5. **Radarr Update**: Update movie path, trigger rescan
6. **Completion**: Remove from queue, add to history

## Convert Process Flow

1. **Queue Addition**: User adds movie with DTS audio
2. **Validation**: Check DTS 5.1(side) format
3. **Audio Extraction**: Extract and convert to FLAC 7.1
   - Use ionice/nice if file on HDD
   - Proper channel mapping
4. **Merge**: Add FLAC track as first audio stream
5. **Replace**: Replace original file
6. **Radarr Update**: Trigger rescan
7. **Completion**: Remove from queue, add to history

## Configuration

### Required Settings
- **Radarr Host**: IP or hostname
- **Radarr Port**: Usually 7878
- **Radarr API Key**: From Radarr settings

### Auto-Detected Settings
- **SSD Root Folder**: Path containing `movies_ssd`
- **HDD Root Folder**: Path containing `movies_hdd`

### Storage
- `data/config.json`: User settings
- `data/copy_queue.json`: Copy queue state
- `data/copy_history.json`: Copy history
- `data/convert_queue.json`: Convert queue state
- `data/convert_history.json`: Convert history

## Performance Characteristics

### Copy Speed
- Limited by disk I/O (intentionally)
- ionice idle class: only when disk idle
- nice -n19: lowest CPU priority
- Minimal impact on other services

### Convert Speed
- Limited by CPU and disk I/O
- ionice/nice for HDD files
- FLAC compression level 8
- Progress reporting via ffmpeg stats

### Resource Usage
- Low CPU (lowest priority)
- Low memory (streaming operations)
- Network: Only Radarr API calls
- Disk: One operation per queue at a time

## Security Considerations

### Design Assumptions
- Deployed in trusted home network
- No authentication required
- API key stored locally
- Not exposed to internet

### Recommendations
- Keep port 6970 internal only
- Use firewall rules if needed
- Regular backups of data directory
- Monitor disk space

## Error Handling

### Copy Failures
- Checksum mismatch: Delete corrupted file
- Disk full: Mark as failed
- Permission errors: Mark as failed with message

### Convert Failures
- Invalid audio format: Mark as failed
- ffmpeg error: Mark as failed with details
- Disk full: Mark as failed

### Recovery
- Queues persist across restarts
- Failed items remain in queue
- Manual retry by removing and re-adding

## Implemented Features

### v2.0 - Ultimate Radarr Toolbox
- Renamed from "Radarr Safe Mover"
- Tab-based interface
- DTS to FLAC converter module
- Dual queue system
- Settings moved to separate tab
- Independent operation histories

### v1.3 - Emergency Controls & Permissions
- Emergency queue clear
- Automatic file permissions
- Enhanced error handling

### v1.2 - Leftover Management
- Find untracked files
- Delete leftover files
- Re-copy missing files

### v1.1 - Enhanced Reliability
- Fixed queue processor bugs
- Improved logging
- Thread initialization

### v1.0 - Core Functionality
- Basic copy queue
- SHA256 verification
- Radarr integration
- Mobile-first UI

## Future Enhancements

Potential improvements:
- Batch operations
- Detailed progress bars with ETA
- Email/webhook notifications
- Scheduled operations
- Support for other audio formats
- Subtitle management
- Quality upgrade automation

## Development Notes

### Testing
- Test with various file sizes
- Verify DTS detection works
- Test conversion with different DTS variants
- Confirm mobile responsiveness
- Test both Docker Compose v1 and v2

### Debugging
- Check logs: `docker compose logs -f`
- Inspect queues: `cat data/*_queue.json`
- Verify ffmpeg: `docker exec -it container ffmpeg -version`
- Test Radarr API: Use browser or curl

## License
MIT License - Free for personal and commercial use