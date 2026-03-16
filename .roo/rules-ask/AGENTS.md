# Ask Mode Rules (Non-Obvious Only)

## Project Structure Clarifications
- `core/` - Reusable infrastructure (config, queue, Radarr client)
- `operations/` - Specific operation implementations (copy, convert, integrity)
- `data/` - Runtime JSON storage (gitignored, created automatically)
- `scripts/` - Standalone utility scripts (not part of main app)

## Counterintuitive Naming
- "Safe Copy" = copy with checksum verification, not just safe deletion
- `use_nice=True` = use ionice/nice for HDD (low I/O priority), not "be nice"
- `verify_status` in integrity checker = ffmpeg decode check, not checksum
- `checksum_status` = xxHash comparison status

## API Structure
- All endpoints under `/api/` prefix
- Unified queue at `/api/queue` handles both copy and convert operations
- Operation type specified in POST body as `operation_type: 'copy' | 'convert'`
- Radarr API version: v3 (hardcoded in RadarrClient)

## Documentation Locations
- Main README.md has full API endpoint list and usage instructions
- Architecture details referenced in README but ARCHITECTURE.md/FORK_GUIDE.md don't exist
- Russian language in README and some code comments