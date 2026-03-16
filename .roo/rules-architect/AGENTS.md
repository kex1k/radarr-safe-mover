# Architect Mode Rules (Non-Obvious Only)

## Architecture Constraints
- **Single-threaded queue**: One background thread processes all operations sequentially - no parallelism
- **Handler pattern**: Operations decoupled via [`OperationHandler`](../../core/queue.py:252) ABC - add new types without modifying queue
- **No database**: All persistence via JSON files in `data/` - simple but not concurrent-safe
- **Docker-only**: External tools (ffmpeg, mkvmerge, rsync, ionice) assumed available in container

## Hidden Coupling
- [`CopyOperationHandler`](../../operations/copy_operation.py:11) and [`ConvertOperationHandler`](../../operations/convert_operation.py:18) both depend on RadarrClient for post-operation updates
- Integrity checker is independent subsystem - doesn't use main queue, has own storage
- Config paths hardcoded: `data/config.json`, `data/queue.json`, `data/history.json`

## Performance Considerations
- xxHash3_128 chosen over SHA256 for 50-100x faster checksums on large files
- `ionice -c3` (idle class) prevents I/O starvation on HDD operations
- ffmpeg integrity check uses `-skip_frame nokey` for faster keyframe-only validation
- 8MB chunk size for checksum calculation balances memory and performance

## Extension Points
- Add new operation: Create handler extending OperationHandler, register in app.py
- Add new media type: Extend `VIDEO_EXTENSIONS` in [`IntegrityScanner`](../../operations/integrity_checker.py:148)
- Custom Radarr endpoints: Add methods to [`RadarrClient`](../../core/radarr.py:8)