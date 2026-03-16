# Code Mode Rules (Non-Obvious Only)

## Critical Implementation Patterns
- **New operation types**: Extend [`OperationHandler`](../../core/queue.py:252) ABC, register in [`app.py`](../../app.py:48) `operation_handlers` dict
- **File operations on HDD**: MUST use `use_nice=True` parameter - calls `ionice -c3 nice -n19` wrapper
- **Checksum function**: Use [`calculate_checksum()`](../../operations/file_operations.py:11) (xxHash3_128), NOT hashlib.sha256
- **Safe file replacement**: Use [`safe_replace_file()`](../../operations/file_operations.py:163) - handles backup/restore on failure

## ffmpeg/mkvmerge Gotchas
- **mkvmerge exit code 1**: Means warnings, NOT errors - only fail on returncode > 1
- **ffmpeg progress parsing**: Extract time from stderr via regex `r'time=(\d+:\d+:\d+\.\d+)'`
- **DTS track detection**: Must check both `codec_name.startswith('dts')` AND `channel_layout == '5.1(side)'`

## Queue System
- Status callbacks: `update_status(status_string)` and `update_progress(message_string)`
- Exceptions in handlers are caught by queue processor and recorded to history
- Queue items auto-removed after completion or failure (no retry logic)

## Data Files
- All JSON in `data/` directory - created automatically via `_ensure_data_dir()`
- Never write JSON directly - use ConfigManager or storage class methods