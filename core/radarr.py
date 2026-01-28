"""Radarr API integration"""
import requests
import logging

logger = logging.getLogger(__name__)


class RadarrClient:
    """Client for interacting with Radarr API"""
    
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
        """Get all root folders from Radarr"""
        response = requests.get(f"{self.base_url}/rootfolder", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def get_all_movies(self):
        """Get all movies from Radarr"""
        response = requests.get(f"{self.base_url}/movie", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def get_movie(self, movie_id):
        """Get specific movie by ID"""
        response = requests.get(f"{self.base_url}/movie/{movie_id}", headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    def update_movie(self, movie_id, movie_data):
        """Update movie in Radarr"""
        response = requests.put(
            f"{self.base_url}/movie/{movie_id}",
            headers=self.headers,
            json=movie_data
        )
        response.raise_for_status()
        return response.json()
    
    def rescan_movie(self, movie_id):
        """Trigger rescan for specific movie"""
        response = requests.post(
            f"{self.base_url}/command",
            headers=self.headers,
            json={
                'name': 'RescanMovie',
                'movieId': movie_id
            }
        )
        response.raise_for_status()
        return response.json()
    
    def filter_movies_by_root_folder(self, root_folder_path):
        """Get movies in specific root folder"""
        all_movies = self.get_all_movies()
        return [
            movie for movie in all_movies
            if movie.get('path', '').startswith(root_folder_path)
            and movie.get('hasFile', False)
        ]