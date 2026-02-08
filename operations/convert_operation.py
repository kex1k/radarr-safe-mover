"""DTS to FLAC conversion operation"""
import os
import subprocess
import logging
import re
import tempfile
from core.queue import OperationHandler
from core.radarr import RadarrClient
from operations.file_operations import safe_replace_file
from operations.media_operations import validate_audio_format, find_dts_audio_track, probe_media_file

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
        
        # Step 1: Find DTS 5.1(side) audio track
        update_status('copying')  # Using 'copying' status for conversion start
        update_progress('Searching for DTS 5.1(side) audio track...')
        
        logger.info(f"Searching for DTS audio track in: {src_path}")
        dts_track_index, audio_info = find_dts_audio_track(src_path)
        
        if dts_track_index is None:
            raise Exception("No DTS 5.1(side) audio track found in file")
        
        logger.info(f"Found DTS track at index {dts_track_index}: {audio_info['codec_name']}")
        
        # Get duration for progress tracking
        media_info = probe_media_file(src_path)
        duration = float(media_info.get('format', {}).get('duration', 0))
        logger.info(f"Media duration: {duration}s")
        
        # Step 2: Convert audio to FLAC 7.1
        update_status('copying')
        update_progress('Converting DTS to FLAC 7.1...')
        
        # Ensure temp directory exists
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        temp_audio = os.path.join(TEMP_DIR, f"convert_audio_{os.getpid()}.flac")
        
        try:
            logger.info(f"Starting conversion of track {dts_track_index} to FLAC 7.1...")
            self._convert_to_flac(src_path, temp_audio, duration, is_on_hdd, dts_track_index, update_progress)
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
            
            # Step 5: Rename file to reflect new audio format
            update_progress('Renaming file to reflect FLAC 7.1...')
            
            new_path = self._rename_to_flac(src_path)
            logger.info(f"File renamed: {src_path} -> {new_path}")
            
            # Step 6: Trigger Radarr rescan
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
        # Use common media operations function
        return validate_audio_format(
            filepath,
            expected_codec='dts',
            expected_layout='5.1(side)'
        )
    
    def _convert_to_flac(self, input_file, output_file, duration, use_nice, audio_track_index, progress_callback):
        """Convert DTS audio to FLAC 7.1"""
        cmd = []
        
        # Add ionice/nice if file is on HDD
        if use_nice:
            cmd.extend(['ionice', '-c3', 'nice', '-n19'])
        
        cmd.extend([
            'ffmpeg', '-y',
            '-i', input_file,
            '-vn',
            '-map', f'0:a:{audio_track_index}',  # Use specific audio track
            '-af', 'channelmap=map=FL-FL|FR-FR|FC-FC|LFE-LFE|SL-SL|SR-SR|BL=SL|BR=SR:layout=7.1',
            '-c:a', 'flac',
            '-compression_level', '8',
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
            # stderr already consumed in the loop, get remaining output
            remaining_stderr = process.stderr.read() if process.stderr else ''
            raise Exception(f"Conversion failed: {remaining_stderr}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
    
    def _merge_audio_track(self, original_file, audio_file, output_file, use_nice):
        """
        Merge FLAC audio track into MKV, replacing existing FLAC if present
        
        Strategy:
        1. Map video from original
        2. Map new FLAC as first audio track
        3. Map all other audio tracks EXCEPT existing FLAC tracks
        4. Map subtitles
        """
        cmd = []
        
        # Add ionice/nice if file is on HDD
        if use_nice:
            cmd.extend(['ionice', '-c3', 'nice', '-n19'])
        
        # Build ffmpeg command to replace FLAC tracks
        cmd.extend([
            'ffmpeg',
            '-i', audio_file,      # Input 0: new FLAC track
            '-i', original_file,   # Input 1: original file
            '-map', '1:v',         # Map video from original
            '-map', '0:a:0',       # Map new FLAC as first audio track
            '-c:v', 'copy',        # Copy video codec
            '-c:a:0', 'copy',      # Copy new FLAC audio
            '-metadata:s:a:0', 'title=FLAC 7.1',
            '-metadata:s:a:0', 'language=eng',
            '-disposition:a:0', 'default',
        ])
        
        # Map other audio tracks (skip FLAC tracks from original)
        # We need to check each audio track and skip FLAC ones
        media_info = probe_media_file(original_file)
        audio_track_count = 0
        for stream in media_info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                codec_name = stream.get('codec_name', '')
                if codec_name != 'flac':  # Skip existing FLAC tracks
                    stream_index = stream.get('index', 0)
                    cmd.extend(['-map', f'1:{stream_index}', '-c:a:{audio_track_count + 1}', 'copy'])
                    audio_track_count += 1
        
        # Map subtitles
        cmd.extend([
            '-map', '1:s?',
            '-c:s', 'copy',
            '-loglevel', 'error',
            output_file
        ])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to merge audio track: {result.stderr}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
    
    def _replace_file(self, original_path, new_path):
        """
        Replace original file with new one using safe copy with checksum verification.
        
        For HDD files: uses ionice/nice for safe copying
        For SSD files: direct copy without ionice/nice
        """
        # Determine if file is on HDD
        config = self.config_manager.config
        hdd_root = config.get('hdd_root_folder', '')
        is_on_hdd = hdd_root and original_path.startswith(hdd_root)
        
        logger.info(f"Replacing file with safe copy (HDD mode: {is_on_hdd})")
        
        # Use common safe_replace_file function
        safe_replace_file(original_path, new_path, use_nice=is_on_hdd)
    
    def _rename_to_flac(self, filepath):
        """
        Rename file to reflect FLAC 7.1 audio format
        
        Replaces DTS audio patterns with FLAC.7.1 in filename
        Patterns to replace:
        - DTS.5.1 -> FLAC.7.1
        - DTS-HD.MA.5.1 -> FLAC.7.1
        - DTS.MA.5.1 -> FLAC.7.1
        - DTS-5.1 -> FLAC.7.1
        - 5.1.DTS -> FLAC.7.1
        
        Returns:
            str: New file path after rename
        """
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        
        # Define patterns to replace (case insensitive)
        # Order matters - more specific patterns first
        patterns = [
            (r'DTS[-.]?HD[-.]?MA[-.]?5\.1', 'FLAC.7.1'),
            (r'DTS[-.]?MA[-.]?5\.1', 'FLAC.7.1'),
            (r'DTS[-.]?5\.1', 'FLAC.7.1'),
            (r'5\.1[-.]?DTS', 'FLAC.7.1'),
        ]
        
        new_filename = filename
        replaced = False
        
        for pattern, replacement in patterns:
            if re.search(pattern, new_filename, re.IGNORECASE):
                new_filename = re.sub(pattern, replacement, new_filename, flags=re.IGNORECASE)
                replaced = True
                logger.info(f"Replaced pattern '{pattern}' with '{replacement}'")
                break
        
        if not replaced:
            # If no pattern matched, try to insert FLAC.7.1 before file extension
            name, ext = os.path.splitext(new_filename)
            new_filename = f"{name}.FLAC.7.1{ext}"
            logger.info(f"No DTS pattern found, appending FLAC.7.1 before extension")
        
        new_filepath = os.path.join(directory, new_filename)
        
        # Only rename if filename actually changed
        if new_filepath != filepath:
            logger.info(f"Renaming: {filename} -> {new_filename}")
            os.rename(filepath, new_filepath)
            return new_filepath
        else:
            logger.info("Filename unchanged, skipping rename")
            return filepath