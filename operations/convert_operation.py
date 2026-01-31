"""DTS to FLAC conversion operation"""
import os
import subprocess
import logging
import re
import tempfile
from core.queue import OperationHandler
from core.radarr import RadarrClient

logger = logging.getLogger(__name__)

# Get temp directory from environment or use default
TEMP_DIR = os.environ.get('TEMP_DIR', '/tmp')


class ConvertOperationHandler(OperationHandler):
    """Handler for converting DTS audio to FLAC 7.1"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        """
        Execute DTS to FLAC conversion
        
        Steps:
        1. Extract DTS audio and convert to FLAC 7.1
        2. Merge FLAC track back into MKV
        3. Replace original file or create new one
        4. Trigger Radarr rescan
        """
        config = self.config_manager.config
        
        # Get movie file path
        movie_file = movie.get('movieFile', {})
        if not movie_file:
            raise Exception("Movie has no file")
        
        src_path = movie_file.get('path')
        if not src_path:
            raise Exception("Movie file has no path")
        
        # Check if file is on HDD (for ionice/nice)
        hdd_root = config.get('hdd_root_folder', '')
        is_on_hdd = hdd_root and src_path.startswith(hdd_root)
        
        # Step 1: Validate audio format
        update_status('copying')  # Using 'copying' status for conversion start
        update_progress('Validating audio format...')
        
        logger.info(f"Validating audio format for: {src_path}")
        duration = self._validate_audio_format(src_path)
        logger.info(f"Audio validation passed, duration: {duration}s")
        
        # Step 2: Convert audio to FLAC 7.1
        update_status('copying')
        update_progress('Converting DTS to FLAC 7.1...')
        
        # Ensure temp directory exists
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        temp_audio = os.path.join(TEMP_DIR, f"convert_audio_{os.getpid()}.flac")
        
        try:
            logger.info(f"Starting conversion to FLAC 7.1...")
            self._convert_to_flac(src_path, temp_audio, duration, is_on_hdd, update_progress)
            logger.info(f"Conversion completed: {temp_audio}")
            
            # Step 3: Merge audio track
            update_status('verifying')
            update_progress('Merging audio track into MKV...')
            
            temp_output = os.path.join(TEMP_DIR, f"convert_output_{os.getpid()}.mkv")
            
            logger.info("Merging audio track...")
            self._merge_audio_track(src_path, temp_audio, temp_output, is_on_hdd)
            logger.info("Audio track merged successfully")
            
            # Step 4: Replace original file
            update_status('updating')
            update_progress('Replacing original file...')
            
            logger.info(f"Replacing original file: {src_path}")
            self._replace_file(src_path, temp_output)
            logger.info("File replaced successfully")
            
            # Step 5: Trigger Radarr rescan
            update_progress('Triggering Radarr rescan...')
            
            radarr = RadarrClient(
                config['radarr_host'],
                config['radarr_port'],
                config['radarr_api_key']
            )
            
            movie_id = movie['id']
            logger.info(f"Triggering rescan for movie ID {movie_id}")
            radarr.rescan_movie(movie_id)
            logger.info("Rescan triggered successfully")
            
        finally:
            # Cleanup temporary files
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
            if os.path.exists(temp_output):
                os.remove(temp_output)
    
    def _validate_audio_format(self, filepath):
        """Validate that file has DTS audio and return duration"""
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', '-select_streams', 'a:0',
            filepath
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception("Failed to probe media file")
        
        import json
        media_info = json.loads(result.stdout)
        
        # Extract audio stream info
        streams = media_info.get('streams', [])
        if not streams:
            raise Exception("No audio streams found")
        
        audio_stream = streams[0]
        codec_name = audio_stream.get('codec_name', '')
        channel_layout = audio_stream.get('channel_layout', '')
        
        # Check if codec is DTS
        if not codec_name.startswith('dts'):
            raise Exception(f"Audio codec is not DTS (found: {codec_name})")
        
        # Check if channel layout is 5.1(side)
        if channel_layout != '5.1(side)':
            raise Exception(f"Channel layout is not 5.1(side) (found: {channel_layout})")
        
        # Get duration
        format_info = media_info.get('format', {})
        duration = float(format_info.get('duration', 0))
        
        return duration
    
    def _convert_to_flac(self, input_file, output_file, duration, use_nice, progress_callback):
        """Convert DTS audio to FLAC 7.1"""
        cmd = []
        
        # Add ionice/nice if file is on HDD
        if use_nice:
            cmd.extend(['ionice', '-c3', 'nice', '-n19'])
        
        cmd.extend([
            'ffmpeg', '-y', '-i', input_file,
            '-vn',
            '-c:a', 'flac',
            '-compression_level', '8',
            '-channel_layout', '7.1',
            '-ac', '8',
            '-af', 'pan=7.1|FL=FL|FR=FR|FC=FC|LFE=LFE|BL=SL|BR=SR|SL=SL|SR=SR',
            '-loglevel', 'warning',
            '-stats',
            output_file
        ])
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Monitor progress
        for line in process.stderr:
            line = line.strip()
            if line and progress_callback:
                # Extract time from ffmpeg output
                time_match = re.search(r'time=(\d+:\d+:\d+\.\d+)', line)
                if time_match and duration > 0:
                    time_str = time_match.group(1)
                    h, m, s = time_str.split(':')
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    progress = (current_seconds / duration) * 100
                    progress_callback(f'Converting: {progress:.1f}%')
        
        process.wait()
        
        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ''
            raise Exception(f"Conversion failed: {stderr}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
    
    def _merge_audio_track(self, original_file, audio_file, output_file, use_nice):
        """Merge FLAC audio track into MKV"""
        cmd = []
        
        # Add ionice/nice if file is on HDD
        if use_nice:
            cmd.extend(['ionice', '-c3', 'nice', '-n19'])
        
        cmd.extend([
            'ffmpeg', '-i', audio_file, '-i', original_file,
            '-map', '1:v',
            '-map', '0:a:0',
            '-map', '1:a',
            '-map', '1:s?',
            '-c', 'copy',
            '-metadata:s:a:0', 'title=FLAC 7.1',
            '-metadata:s:a:0', 'language=eng',
            '-disposition:a:0', 'default',
            '-loglevel', 'error',
            output_file
        ])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to merge audio track: {result.stderr}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
    
    def _replace_file(self, original_path, new_path):
        """Replace original file with new one, preserving permissions"""
        # Get original permissions
        try:
            stat_info = os.stat(original_path)
            original_mode = stat_info.st_mode
        except:
            original_mode = 0o644
        
        # Remove original
        os.remove(original_path)
        
        # Move new file to original location
        os.rename(new_path, original_path)
        
        # Restore permissions
        try:
            os.chmod(original_path, original_mode)
        except:
            pass