"""Operations module - specific implementations"""

from operations.file_operations import (
    calculate_checksum,
    copy_file_with_nice,
    safe_copy_file,
    safe_replace_file
)

from operations.media_operations import (
    probe_media_file,
    get_audio_stream_info,
    validate_audio_format,
    get_media_duration
)

__all__ = [
    # File operations
    'calculate_checksum',
    'copy_file_with_nice',
    'safe_copy_file',
    'safe_replace_file',
    # Media operations
    'probe_media_file',
    'get_audio_stream_info',
    'validate_audio_format',
    'get_media_duration'
]