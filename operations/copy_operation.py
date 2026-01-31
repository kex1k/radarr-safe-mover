"""Copy operation with verification - specific to safe mover"""
import os
import logging
from core.queue import OperationHandler
from core.radarr import RadarrClient
from operations.file_operations import safe_copy_file

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
        
        # Step 1: Copy file with verification (always use nice for HDD)
        update_status('copying')
        update_progress('Copying file with verification...')
        
        def progress_callback(message):
            update_progress(message)
        
        logger.info(f"Starting safe copy: {src_path} -> {dst_path}")
        safe_copy_file(src_path, dst_path, use_nice=True, progress_callback=progress_callback)
        logger.info(f"Safe copy completed: {dst_path}")
        
        # Step 2: Update Radarr
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
        
        # Step 3: Trigger rescan
        logger.info(f"Triggering rescan for movie ID {movie_id}")
        radarr.rescan_movie(movie_id)
        logger.info("Rescan triggered successfully")
    