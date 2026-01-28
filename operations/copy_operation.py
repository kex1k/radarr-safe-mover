"""Copy operation with verification - specific to safe mover"""
import os
import hashlib
import subprocess
import logging
from core.queue import OperationHandler
from core.radarr import RadarrClient

logger = logging.getLogger(__name__)


class CopyOperationHandler(OperationHandler):
    """Handler for copying movies from SSD to HDD with verification"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    def execute(self, movie, update_status, update_progress):
        """
        Execute copy operation with checksum verification
        
        Steps:
        1. Copy file using rsync with ionice/nice
        2. Verify checksums (SHA256)
        3. Update Radarr with new path
        4. Trigger rescan
        """
        config = self.config_manager.config
        
        # Get movie file path
        movie_file = movie.get('movieFile', {})
        if not movie_file:
            raise Exception("Movie has no file")
        
        src_path = movie_file.get('path')
        if not src_path:
            raise Exception("Movie file has no path")
        
        # Calculate destination path
        ssd_root = config['ssd_root_folder']
        hdd_root = config['hdd_root_folder']
        
        if not src_path.startswith(ssd_root):
            raise Exception(f"Source path doesn't start with SSD root folder")
        
        relative_path = src_path[len(ssd_root):].lstrip('/')
        dst_path = os.path.join(hdd_root, relative_path)
        
        # Step 1: Copy file
        update_status('copying')
        update_progress('Copying file...')
        
        def progress_callback(line):
            update_progress(f'Copying: {line}')
        
        logger.info(f"Starting copy: {src_path} -> {dst_path}")
        self._copy_file_with_nice(src_path, dst_path, progress_callback)
        logger.info(f"Copy completed: {dst_path}")
        
        # Step 2: Verify checksum
        update_status('verifying')
        update_progress('Verifying checksum...')
        
        logger.info("Starting checksum verification...")
        
        def verify_src_progress(progress):
            update_progress(f'Verifying source: {progress}')
        
        src_checksum = self._calculate_checksum(src_path, verify_src_progress)
        
        def verify_dst_progress(progress):
            update_progress(f'Verifying destination: {progress}')
        
        dst_checksum = self._calculate_checksum(dst_path, verify_dst_progress)
        
        logger.info(f"Source checksum: {src_checksum}")
        logger.info(f"Destination checksum: {dst_checksum}")
        
        if src_checksum != dst_checksum:
            logger.error("Checksum mismatch! Removing corrupted file.")
            os.remove(dst_path)
            raise Exception("Checksum verification failed")
        
        logger.info("Checksum verification passed")
        
        # Step 3: Update Radarr
        update_status('updating')
        update_progress('Updating Radarr...')
        
        radarr = RadarrClient(
            config['radarr_host'],
            config['radarr_port'],
            config['radarr_api_key']
        )
        
        movie_id = movie['id']
        new_path = os.path.dirname(dst_path)
        movie['path'] = new_path
        movie['rootFolderPath'] = hdd_root
        
        logger.info(f"Updating Radarr for movie ID {movie_id}")
        logger.info(f"New path: {new_path}")
        logger.info(f"New root folder: {hdd_root}")
        
        radarr.update_movie(movie_id, movie)
        logger.info(f"Movie updated successfully in Radarr")
        
        # Step 4: Trigger rescan
        logger.info(f"Triggering rescan for movie ID {movie_id}")
        radarr.rescan_movie(movie_id)
        logger.info("Rescan triggered successfully")
    
    def _copy_file_with_nice(self, src, dst, progress_callback=None):
        """Copy file using rsync with ionice and nice"""
        # Ensure destination directory exists with proper permissions
        dst_dir = os.path.dirname(dst)
        os.makedirs(dst_dir, exist_ok=True)
        os.chmod(dst_dir, 0o755)
        
        # rsync with ionice/nice and permission setting
        cmd = [
            'ionice', '-c3',
            'nice', '-n19',
            'rsync', '-a', '--chmod=D0755,F0644', '--info=progress2', '--no-i-r',
            src, dst
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        for line in process.stdout:
            line = line.strip()
            if line:
                logger.info(f"Copy progress: {line}")
                if progress_callback:
                    progress_callback(line)
        
        process.wait()
        
        if process.returncode != 0:
            stderr = process.stderr.read()
            raise Exception(f"Copy failed: {stderr}")
        
        return dst
    
    def _calculate_checksum(self, filepath, progress_callback=None):
        """Calculate SHA256 checksum with progress reporting"""
        hash_func = hashlib.sha256()
        file_size = os.path.getsize(filepath)
        bytes_read = 0
        chunk_size = 8192 * 1024  # 8MB chunks
        
        logger.info(f"Calculating SHA256 checksum for {filepath} ({file_size / 1024 / 1024 / 1024:.2f} GB)")
        
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hash_func.update(chunk)
                bytes_read += len(chunk)
                
                # Report progress every 10%
                if progress_callback and file_size > 0:
                    progress = (bytes_read / file_size) * 100
                    if int(progress) % 10 == 0:
                        progress_callback(f"{progress:.0f}%")
        
        checksum = hash_func.hexdigest()
        logger.info(f"Checksum calculated: {checksum}")
        return checksum