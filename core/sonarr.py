"""Sonarr API integration"""
import requests
import logging

logger = logging.getLogger(__name__)


class SonarrClient:
    """Client for interacting with Sonarr API"""
    
    def __init__(self, host, port, api_key):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.base_url = f"http://{host}:{port}/api/v3"
        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }
    
    def get_root_folders(self):
        """Get all root folders from Sonarr"""
        response = requests.get(f"{self.base_url}/rootfolder", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def get_all_series(self):
        """Get all series from Sonarr"""
        response = requests.get(f"{self.base_url}/series", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def get_series(self, series_id):
        """Get specific series by ID"""
        response = requests.get(f"{self.base_url}/series/{series_id}", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def get_episode_files(self, series_id):
        """Get all episode files for a series"""
        response = requests.get(
            f"{self.base_url}/episodefile",
            headers=self.headers,
            params={'seriesId': series_id}
        )
        response.raise_for_status()
        return response.json()
    
    def filter_series_by_root_folder(self, root_folder_path):
        """Get series in specific root folder"""
        all_series = self.get_all_series()
        return [
            series for series in all_series
            if series.get('path', '').startswith(root_folder_path)
        ]
    
    def get_seasons_with_files(self, series_id):
        """Get seasons with their episode files grouped"""
        try:
            # Get series info to know all seasons
            series = self.get_series(series_id)
            logger.info(f"Getting seasons for series: {series.get('title')} (ID: {series_id})")
            
            # Get episode files
            episode_files = self.get_episode_files(series_id)
            logger.info(f"Found {len(episode_files)} episode files for series {series_id}")
            
            # Get all seasons from series info
            all_seasons = series.get('seasons', [])
            logger.info(f"Series has {len(all_seasons)} seasons defined")
            
            # Group files by season
            seasons_with_files = {}
            for ep_file in episode_files:
                season_num = ep_file.get('seasonNumber', 0)
                if season_num not in seasons_with_files:
                    seasons_with_files[season_num] = []
                seasons_with_files[season_num].append(ep_file)
            
            # Build season list including seasons without files
            season_list = []
            for season in all_seasons:
                season_num = season.get('seasonNumber', 0)
                files = seasons_with_files.get(season_num, [])
                
                # Only include seasons that have files
                if files:
                    season_list.append({
                        'seasonNumber': season_num,
                        'fileCount': len(files),
                        'files': files
                    })
            
            logger.info(f"Returning {len(season_list)} seasons with files")
            return season_list
            
        except Exception as e:
            logger.error(f"Error getting seasons for series {series_id}: {str(e)}", exc_info=True)
            raise