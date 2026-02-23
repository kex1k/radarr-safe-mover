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
        temp_output = os.path.join(TEMP_DIR, f"convert_output_{os.getpid()}.mkv")
        
        try:
            logger.info(f"Starting conversion of track {dts_track_index} to FLAC 7.1...")
            self._convert_to_flac(src_path, temp_audio, duration, is_on_hdd, dts_track_index, update_progress)
            logger.info(f"Conversion completed: {temp_audio}")
            
            # Step 3: Merge audio track
            update_status('verifying')
            update_progress('Merging audio track into MKV...')
            
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
            '-map', f'0:{audio_track_index}',  # Select specific DTS track
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
        
        # Collect all stderr lines for error reporting
        stderr_lines = []
        
        # Monitor progress
        for line in process.stderr:
            line = line.strip()
            stderr_lines.append(line)  # Save all lines
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
            # Use collected stderr lines for error message
            error_output = '\n'.join(stderr_lines) if stderr_lines else 'Unknown error'
            raise Exception(f"Conversion failed (exit code {process.returncode}): {error_output}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
    
    def _merge_audio_track(self, original_file, audio_file, output_file, use_nice):
        """
        Merge FLAC audio track into MKV using mkvmerge, replacing existing FLAC if present
        
        Strategy:
        1. Use mkvmerge for proper MKV handling
        2. Add new FLAC as first audio track with default flag
        3. Keep all other non-FLAC audio tracks without default flag
        4. Keep all video and subtitle tracks
        """
        logger.info("Starting mkvmerge audio track merge...")
        cmd = []
        
        # Add ionice/nice if file is on HDD
        if use_nice:
            cmd.extend(['ionice', '-c3', 'nice', '-n19'])
            logger.info("Using ionice/nice for HDD")
        
        # Build mkvmerge command
        cmd.extend([
            'mkvmerge',
            '-o', output_file,
            audio_file,  # New FLAC track (will be first audio)
        ])
        
        # Get info about original file to selectively add tracks
        logger.info("Analyzing original file tracks...")
        media_info = probe_media_file(original_file)
        
        # Build track selection for original file
        audio_tracks = []
        flac_count = 0
        for stream in media_info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                codec_name = stream.get('codec_name', '')
                stream_index = stream.get('index', 0)
                if codec_name == 'flac':
                    flac_count += 1
                    logger.info(f"Skipping existing FLAC track at index {stream_index}")
                else:
                    audio_tracks.append(str(stream_index))
                    logger.info(f"Keeping {codec_name} track at index {stream_index}")
        
        logger.info(f"Found {flac_count} FLAC track(s) to remove, {len(audio_tracks)} other audio track(s) to keep")
        
        # Add original file with selective tracks
        if audio_tracks:
            # Only include non-FLAC audio tracks
            cmd.extend([
                '--audio-tracks', ','.join(audio_tracks),
                '--no-video',  # Video will be added separately
                '--no-subtitles',  # Subtitles will be added separately
                original_file
            ])
        
        # Add video and subtitles from original
        cmd.extend([
            '--no-audio',  # Don't take audio again
            '--video-tracks', '0',  # Take video
            '--subtitle-tracks', '0',  # Take all subtitles
            original_file
        ])
        
        # Set track flags
        cmd.extend([
            '--default-track', '0:1',  # FLAC is default
            '--track-name', '0:FLAC 7.1',  # Set FLAC track name
            '--language', '0:eng',  # Set FLAC language
        ])
        
        # Remove default flag from other audio tracks
        for i, _ in enumerate(audio_tracks, start=1):
            cmd.extend(['--default-track', f'{i}:0'])
        
        logger.info(f"Executing mkvmerge with {len(audio_tracks) + 1} audio track(s)")
        logger.debug(f"Command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode not in [0, 1]:  # mkvmerge returns 1 for warnings
            logger.error(f"mkvmerge failed with return code {result.returncode}")
            logger.error(f"stderr: {result.stderr}")
            raise Exception(f"Failed to merge audio track: {result.stderr}")
        
        if result.returncode == 1:
            logger.warning(f"mkvmerge completed with warnings: {result.stderr}")
        else:
            logger.info("mkvmerge completed successfully")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
        
        output_size = os.path.getsize(output_file) / (1024 * 1024 * 1024)
        logger.info(f"Output file created: {output_size:.2f} GB")
    
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
        
        Also handles retry case where FLAC.7.1 already exists in filename
        
        Returns:
            str: New file path after rename
        """
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        
        # Check if already has FLAC.7.1 in filename (retry case)
        if re.search(r'FLAC\.7\.1', filename, re.IGNORECASE):
            logger.info("File already has FLAC.7.1 in name, skipping rename")
            return filepath
        
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