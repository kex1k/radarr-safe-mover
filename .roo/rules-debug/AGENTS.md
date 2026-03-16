# Debug Mode Rules (Non-Obvious Only)

## Log Locations
- Application logs: `docker compose logs -f` (stdout/stderr)
- No file-based logging configured - all via Python logging module to stdout

## Common Silent Failures
- **Missing TEMP_DIR**: Conversion fails silently if `/tmp` is read-only (eMMC systems) - check `TEMP_DIR` env var
- **mkvmerge warnings**: Exit code 1 is OK, only >1 is actual error
- **ffmpeg false positives**: Non-critical errors like `non monotonically increasing dts` are filtered in [`_is_critical_error()`](../../operations/integrity_checker.py:314)

## Debugging Media Operations
- Use `ffprobe -v quiet -print_format json -show_streams -show_format <file>` to inspect media
- DTS track must have BOTH `codec_name` starting with 'dts' AND `channel_layout == '5.1(side)'`
- Timeout for ffmpeg verification: 1 min per GB, min 5 min, max 60 min

## Queue Debugging
- Queue state persisted in `data/queue.json` - can inspect/edit while stopped
- History in `data/history.json` - last 10 operations with error messages
- `current_item` in queue processor indicates active operation

## Docker Debugging
- Container runs as root with `privileged: true` for ionice access
- Volume mounts must match Radarr's root folder paths exactly