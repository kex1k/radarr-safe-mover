"""Media file operations using ffprobe and ffmpeg"""
import os
import subprocess
import logging
import json

logger = logging.getLogger(__name__)


def probe_media_file(filepath, select_streams=None):
    """
    Probe media file using ffprobe and return parsed JSON data
    
    Args:
        filepath: Path to media file
        select_streams: Optional stream selector (e.g., 'a:0' for first audio stream)
    
    Returns:
        dict: Parsed ffprobe output with 'streams' and 'format' keys
    
    Raises:
        Exception: If ffprobe fails or file doesn't exist
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Media file not found: {filepath}")
    
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_streams', '-show_format'
    ]
    
    if select_streams:
        cmd.extend(['-select_streams', select_streams])
    
    cmd.append(filepath)
    
    logger.info(f"Probing media file: {filepath}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Failed to probe media file: {result.stderr}")
    
    try:
        media_info = json.loads(result.stdout)
        logger.info(f"Successfully probed media file: {len(media_info.get('streams', []))} streams found")
        return media_info
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse ffprobe output: {e}")


def get_audio_stream_info(filepath, stream_index=0):
    """
    Get detailed information about an audio stream
    
    Args:
        filepath: Path to media file
        stream_index: Audio stream index (default: 0 for first audio stream)
    
    Returns:
        dict: Audio stream information with keys:
            - codec_name: Audio codec name (e.g., 'dts', 'flac')
            - codec_long_name: Full codec name
            - channels: Number of audio channels
            - channel_layout: Channel layout (e.g., '5.1(side)', '7.1')
            - sample_rate: Sample rate in Hz
            - bit_rate: Bit rate (if available)
    
    Raises:
        Exception: If no audio stream found or probe fails
    """
    media_info = probe_media_file(filepath, select_streams=f'a:{stream_index}')
    
    streams = media_info.get('streams', [])
    if not streams:
        raise Exception(f"No audio stream found at index {stream_index}")
    
    audio_stream = streams[0]
    
    return {
        'codec_name': audio_stream.get('codec_name', 'Unknown'),
        'codec_long_name': audio_stream.get('codec_long_name', 'Unknown'),
        'channels': audio_stream.get('channels', 0),
        'channel_layout': audio_stream.get('channel_layout', 'Unknown'),
        'sample_rate': audio_stream.get('sample_rate', 'Unknown'),
        'bit_rate': audio_stream.get('bit_rate', 'Unknown')
    }


def validate_audio_format(filepath, expected_codec=None, expected_layout=None):
    """
    Validate audio format and return duration
    
    Args:
        filepath: Path to media file
        expected_codec: Expected codec name prefix (e.g., 'dts')
        expected_layout: Expected channel layout (e.g., '5.1(side)')
    
    Returns:
        float: Media duration in seconds
    
    Raises:
        Exception: If validation fails
    """
    media_info = probe_media_file(filepath, select_streams='a:0')
    
    # Extract audio stream info
    streams = media_info.get('streams', [])
    if not streams:
        raise Exception("No audio streams found")
    
    audio_stream = streams[0]
    codec_name = audio_stream.get('codec_name', '')
    channel_layout = audio_stream.get('channel_layout', '')
    
    # Validate codec if specified
    if expected_codec and not codec_name.startswith(expected_codec):
        raise Exception(f"Audio codec is not {expected_codec} (found: {codec_name})")
    
    # Validate channel layout if specified
    if expected_layout and channel_layout != expected_layout:
        raise Exception(f"Channel layout is not {expected_layout} (found: {channel_layout})")
    
    # Get duration
    format_info = media_info.get('format', {})
    duration = float(format_info.get('duration', 0))
    
    logger.info(f"Audio validation passed: codec={codec_name}, layout={channel_layout}, duration={duration}s")
    
    return duration


def get_media_duration(filepath):
    """
    Get media file duration in seconds
    
    Args:
        filepath: Path to media file
    
    Returns:
        float: Duration in seconds
    """
    media_info = probe_media_file(filepath)
    format_info = media_info.get('format', {})
    return float(format_info.get('duration', 0))


def find_dts_audio_track(filepath):
    """
    Find first DTS 5.1(side) audio track in media file
    
    Args:
        filepath: Path to media file
    
    Returns:
        tuple: (track_index, audio_info) or (None, None) if not found
        
    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Media file not found: {filepath}")
    
    media_info = probe_media_file(filepath)
    streams = media_info.get('streams', [])
    
    # Find first DTS 5.1(side) audio track
    for idx, stream in enumerate(streams):
        if stream.get('codec_type') != 'audio':
            continue
            
        codec_name = stream.get('codec_name', '')
        channel_layout = stream.get('channel_layout', '')
        
        # Check if it's DTS with 5.1(side) layout
        if codec_name.startswith('dts') and channel_layout == '5.1(side)':
            audio_info = {
                'index': idx,
                'codec_name': codec_name,
                'codec_long_name': stream.get('codec_long_name', 'Unknown'),
                'channels': stream.get('channels', 0),
                'channel_layout': channel_layout,
                'sample_rate': stream.get('sample_rate', 'Unknown'),
                'bit_rate': stream.get('bit_rate', 'Unknown')
            }
            logger.info(f"Found DTS 5.1(side) track at index {idx}: {codec_name}")
            return idx, audio_info
    
    logger.warning(f"No DTS 5.1(side) audio track found in {filepath}")
    return None, None