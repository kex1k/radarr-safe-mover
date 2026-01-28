"""Leftover files management - specific to safe mover"""
import os
import shutil
import logging

logger = logging.getLogger(__name__)


class LeftoversManager:
    """Manage leftover files on SSD not tracked by Radarr"""
    
    def __init__(self, config_manager, radarr_client):
        self.config_manager = config_manager
        self.radarr_client = radarr_client
    
    def find_leftovers(self):
        """Find files on SSD that don't have corresponding movies in Radarr"""
        config = self.config_manager.config
        
        ssd_root = config.get('ssd_root_folder')
        hdd_root = config.get('hdd_root_folder')
        
        if not ssd_root or not hdd_root:
            raise ValueError('Root folders not configured')
        
        # Get all movies from Radarr
        all_movies = self.radarr_client.get_all_movies()
        
        # Build maps of movie paths
        radarr_ssd_paths = set()
        hdd_movies_by_name = {}
        
        for movie in all_movies:
            movie_path = movie.get('path', '')
            if movie_path:
                if movie_path.startswith(ssd_root):
                    radarr_ssd_paths.add(movie_path)
                elif movie_path.startswith(hdd_root):
                    dir_name = os.path.basename(movie_path)
                    hdd_movies_by_name[dir_name] = movie
        
        # Scan filesystem for directories in SSD root
        leftovers = []
        if os.path.exists(ssd_root):
            for item in os.listdir(ssd_root):
                item_path = os.path.join(ssd_root, item)
                
                if os.path.isdir(item_path):
                    if item_path not in radarr_ssd_paths:
                        # Calculate directory size
                        total_size = 0
                        file_count = 0
                        for dirpath, dirnames, filenames in os.walk(item_path):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                try:
                                    total_size += os.path.getsize(filepath)
                                    file_count += 1
                                except:
                                    pass
                        
                        # Check if there's a movie in HDD with same name but file missing
                        can_recopy = False
                        movie_id = None
                        if item in hdd_movies_by_name:
                            hdd_movie = hdd_movies_by_name[item]
                            movie_id = hdd_movie['id']
                            if hdd_movie.get('hasFile'):
                                movie_file_path = hdd_movie.get('movieFile', {}).get('path')
                                if movie_file_path and not os.path.exists(movie_file_path):
                                    can_recopy = True
                                    logger.info(f"Found missing HDD file for {item}, can recopy")
                        
                        leftovers.append({
                            'path': item_path,
                            'name': item,
                            'size': total_size,
                            'file_count': file_count,
                            'can_recopy': can_recopy,
                            'movie_id': movie_id
                        })
        
        logger.info(f"Found {len(leftovers)} leftover directories")
        return leftovers
    
    def delete_leftover(self, path):
        """Delete a leftover directory"""
        config = self.config_manager.config
        ssd_root = config.get('ssd_root_folder')
        
        # Security check
        if not ssd_root or not path.startswith(ssd_root):
            raise ValueError('Invalid path')
        
        if not os.path.exists(path):
            raise FileNotFoundError('Path does not exist')
        
        logger.info(f"Deleting leftover directory: {path}")
        shutil.rmtree(path)
        logger.info(f"Successfully deleted: {path}")
    
    def prepare_recopy(self, movie_id, ssd_path):
        """Prepare movie for re-copying from SSD to HDD"""
        config = self.config_manager.config
        ssd_root = config.get('ssd_root_folder')
        
        # Security check
        if not ssd_root or not ssd_path.startswith(ssd_root):
            raise ValueError('Invalid SSD path')
        
        if not os.path.exists(ssd_path):
            raise FileNotFoundError('SSD path does not exist')
        
        # Get movie details from Radarr
        movie = self.radarr_client.get_movie(movie_id)
        
        # Find the movie file on SSD
        movie_file = None
        for dirpath, dirnames, filenames in os.walk(ssd_path):
            for filename in filenames:
                if filename.lower().endswith(('.mkv', '.mp4', '.avi', '.m4v', '.mov')):
                    filepath = os.path.join(dirpath, filename)
                    file_size = os.path.getsize(filepath)
                    
                    movie_file = {
                        'path': filepath,
                        'size': file_size,
                        'quality': movie.get('movieFile', {}).get('quality', {}),
                    }
                    break
            if movie_file:
                break
        
        if not movie_file:
            raise FileNotFoundError('No video file found in SSD directory')
        
        # Update movie object with SSD file info
        movie['movieFile'] = movie_file
        movie['hasFile'] = True
        
        return movie