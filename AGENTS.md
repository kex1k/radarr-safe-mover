# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview
Ultimate Radarr Toolbox - Flask web app for Radarr automation: safe SSD→HDD movie transfers with checksum verification, DTS→FLAC 7.1 audio conversion, and media integrity checking.

## Build/Run Commands
```bash
./start.sh                    # Auto-detects docker-compose v1/v2, builds and runs
docker compose up -d          # Direct run (v2)
docker compose logs -f        # View logs
```

## Non-Obvious Architecture
- **Unified Queue System**: Single [`OperationQueue`](core/queue.py:13) processes both 'copy' and 'convert' operations via handler pattern
- **Operation Handlers**: Must extend [`OperationHandler`](core/queue.py:252) ABC and implement `execute(movie, update_status, update_progress)`
- **Data persistence**: All state stored in `data/*.json` files (config, queue, history, integrity)
- **TEMP_DIR env var**: Conversion uses `TEMP_DIR` env (default `/tmp`) for temp files - critical for avoiding eMMC wear

## Critical Patterns
- **Checksum**: Uses xxHash3_128 (not SHA256) via [`calculate_checksum()`](operations/file_operations.py:11) - 50-100x faster
- **HDD operations**: Always use `ionice -c3 nice -n19` wrapper for HDD files (idle I/O class)
- **Safe file replacement**: [`safe_replace_file()`](operations/file_operations.py:163) creates backup, copies, verifies checksum, then removes backup
- **mkvmerge return codes**: Return code 1 = warnings (OK), only >1 is error - see [`_merge_audio_track()`](operations/convert_operation.py:191)

## Code Style
- Logging: Use module-level `logger = logging.getLogger(__name__)`
- Config access: Via [`ConfigManager`](core/config.py:9) instance, not direct file reads
- Radarr API: Via [`RadarrClient`](core/radarr.py:8) class, uses `/api/v3` endpoints
- Error handling: Raise exceptions in handlers, queue processor catches and records to history

## External Dependencies (in Docker)
- `ffmpeg`, `ffprobe` - media analysis and conversion
- `mkvtoolnix` (mkvmerge) - MKV track manipulation
- `rsync` - file copying with progress
- `ionice`, `nice` - I/O priority control