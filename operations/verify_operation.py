"""TV Show verification operation handler"""
import os
import json
import logging
import subprocess
import time
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


class VerificationStorage:
    """Manage verification state storage"""
    
    def __init__(self, storage_file='data/shows_verification.json'):
        self.storage_file = storage_file
        self._ensure_data_dir()
        self.data = self.load()
        self.lock = threading.Lock()
    
    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
    
    def load(self):
        """Load verification data from file"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading verification data: {e}")
                return {'series': {}, 'active_verification': None}
        return {'series': {}, 'active_verification': None}
    
    def save(self):
        """Save verification data to file"""
        with self.lock:
            with open(self.storage_file, 'w') as f:
                json.dump(self.data, f, indent=2)
    
    def get_series_data(self, series_id):
        """Get verification data for a series"""
        return self.data['series'].get(str(series_id), {
            'series_id': series_id,
            'seasons': {},
            'last_updated': None
        })
    
    def update_series_data(self, series_id, series_data):
        """Update verification data for a series"""
        with self.lock:
            self.data['series'][str(series_id)] = series_data
            self.save()
    
    def get_season_data(self, series_id, season_number):
        """Get verification data for a season"""
        series_data = self.get_series_data(series_id)
        return series_data['seasons'].get(str(season_number), {
            'season_number': season_number,
            'status': 'unchecked',
            'verified_files': [],
            'broken_files': [],
            'last_checked': None,
            'last_checked_file': None,
            'total_files': 0
        })
    
    def update_season_data(self, series_id, season_number, season_data):
        """Update verification data for a season"""
        with self.lock:
            series_data = self.get_series_data(series_id)
            series_data['seasons'][str(season_number)] = season_data
            series_data['last_updated'] = datetime.now().isoformat()
            self.data['series'][str(series_id)] = series_data
            self.save()
    
    def set_active_verification(self, verification_data):
        """Set active verification process"""
        with self.lock:
            self.data['active_verification'] = verification_data
            self.save()
    
    def get_active_verification(self):
        """Get active verification process"""
        return self.data.get('active_verification')
    
    def clear_active_verification(self):
        """Clear active verification process"""
        with self.lock:
            self.data['active_verification'] = None
            self.save()


class VerificationHandler:
    """Handle TV show file verification operations"""
    
    def __init__(self, storage):
        self.storage = storage
        self.stop_flag = threading.Event()
        self.verification_thread = None
    
    def verify_file(self, file_path):
        """Verify a single MKV file using ffmpeg
        Returns: (is_valid, duration_seconds)
        """
        start_time = time.time()
        
        try:
            # Use ionice and nice for low priority I/O and CPU
            cmd = [
                'ionice', '-c3',
                'nice', '-n19',
                'ffmpeg',
                '-v', 'error',
                '-xerror',
                '-err_detect', 'explode',
                '-skip_frame', 'nokey',
                '-i', file_path,
                '-map', '0:v',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3600  # 1 hour timeout per file
            )
            
            duration = time.time() - start_time
            is_valid = result.returncode == 0
            
            return is_valid, duration
            
        except subprocess.TimeoutExpired:
            logger.error(f"Verification timeout for {file_path}")
            return False, time.time() - start_time
        except Exception as e:
            logger.error(f"Error verifying {file_path}: {e}")
            return False, time.time() - start_time
    
    def verify_season(self, series_id, season_number, files):
        """Verify all files in a season"""
        season_data = self.storage.get_season_data(series_id, season_number)
        
        # Initialize if first run
        if season_data['status'] == 'unchecked':
            season_data['total_files'] = len(files)
            season_data['verified_files'] = []
            season_data['broken_files'] = []
        
        season_data['status'] = 'checking'
        self.storage.update_season_data(series_id, season_number, season_data)
        
        # Find starting point
        start_index = 0
        if season_data.get('last_checked_file'):
            # Resume from last checked file
            for i, f in enumerate(files):
                if f['path'] == season_data['last_checked_file']:
                    start_index = i + 1
                    break
        
        # Verify files
        for i in range(start_index, len(files)):
            if self.stop_flag.is_set():
                logger.info(f"Verification stopped for season {season_number}")
                season_data['status'] = 'paused'
                self.storage.update_season_data(series_id, season_number, season_data)
                return False
            
            file_info = files[i]
            file_path = file_info['path']
            
            # Update active verification progress
            active = self.storage.get_active_verification()
            if active:
                active['current_file'] = os.path.basename(file_path)
                active['current_index'] = len(season_data['verified_files']) + len(season_data['broken_files'])
                active['total_files'] = season_data['total_files']
                self.storage.set_active_verification(active)
            
            logger.info(f"Verifying: {file_path}")
            is_valid, duration = self.verify_file(file_path)
            
            # Update season data
            season_data['last_checked_file'] = file_path
            
            if is_valid:
                season_data['verified_files'].append({
                    'path': file_path,
                    'seasonNumber': file_info.get('seasonNumber'),
                    'episodeNumbers': file_info.get('episodeNumbers', []),
                    'relativePath': file_info.get('relativePath'),
                    'checked_at': datetime.now().isoformat(),
                    'duration': duration
                })
            else:
                season_data['broken_files'].append({
                    'path': file_path,
                    'seasonNumber': file_info.get('seasonNumber'),
                    'episodeNumbers': file_info.get('episodeNumbers', []),
                    'relativePath': file_info.get('relativePath'),
                    'checked_at': datetime.now().isoformat()
                })
            
            # Update active verification with last duration
            active = self.storage.get_active_verification()
            if active:
                active['last_duration'] = duration
                self.storage.set_active_verification(active)
            
            self.storage.update_season_data(series_id, season_number, season_data)
        
        # Mark as complete
        season_data['status'] = 'completed'
        season_data['last_checked'] = datetime.now().isoformat()
        self.storage.update_season_data(series_id, season_number, season_data)
        
        return True
    
    def verify_series(self, series_id, seasons_data):
        """Verify all seasons in a series"""
        for season in seasons_data:
            if self.stop_flag.is_set():
                break
            
            season_number = season['seasonNumber']
            files = season['files']
            
            self.verify_season(series_id, season_number, files)
    
    def start_verification(self, series_id, season_number, seasons_data):
        """Start verification process in background thread"""
        if self.verification_thread and self.verification_thread.is_alive():
            raise ValueError("Verification already in progress")
        
        self.stop_flag.clear()
        
        # Set active verification
        self.storage.set_active_verification({
            'series_id': series_id,
            'season_number': season_number,
            'started_at': datetime.now().isoformat(),
            'current_file': None,
            'current_index': 0,
            'total_files': 0,
            'last_duration': 0
        })
        
        def verification_worker():
            try:
                if season_number is None:
                    # Verify entire series
                    self.verify_series(series_id, seasons_data)
                else:
                    # Verify specific season
                    season_data = next((s for s in seasons_data if s['seasonNumber'] == season_number), None)
                    if season_data:
                        self.verify_season(series_id, season_number, season_data['files'])
            finally:
                self.storage.clear_active_verification()
        
        self.verification_thread = threading.Thread(target=verification_worker, daemon=True)
        self.verification_thread.start()
    
    def stop_verification(self):
        """Stop active verification"""
        self.stop_flag.set()
        if self.verification_thread:
            self.verification_thread.join(timeout=5)
    
    def get_verification_status(self):
        """Get current verification status"""
        active = self.storage.get_active_verification()
        if not active:
            return None
        
        # Calculate progress
        progress = {
            'series_id': active['series_id'],
            'season_number': active.get('season_number'),
            'started_at': active['started_at'],
            'current_file': active.get('current_file'),
            'current_index': active.get('current_index', 0),
            'total_files': active.get('total_files', 0),
            'last_duration': active.get('last_duration', 0),
            'is_active': self.verification_thread and self.verification_thread.is_alive()
        }
        
        # Calculate estimated time remaining
        if progress['current_index'] > 0 and progress['last_duration'] > 0:
            remaining_files = progress['total_files'] - progress['current_index']
            progress['estimated_remaining'] = remaining_files * progress['last_duration']
        else:
            progress['estimated_remaining'] = 0
        
        return progress