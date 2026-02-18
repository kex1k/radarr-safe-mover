"""Configuration management"""
import json
import os
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manage application configuration"""
    
    def __init__(self, config_file='data/config.json'):
        self.config_file = config_file
        self._ensure_data_dir()
        self.config = self.load()
    
    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
    
    def load(self):
        """Load configuration from file"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return self._default_config()
    
    def save(self, config=None):
        """Save configuration to file"""
        if config:
            self.config = config
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def _default_config(self):
        """Return default configuration"""
        return {
            'radarr_host': '',
            'radarr_port': '',
            'radarr_api_key': '',
            'ssd_root_folder': '',
            'hdd_root_folder': '',
            'sonarr_host': '',
            'sonarr_port': '',
            'sonarr_api_key': '',
            'shows_hdd_root_folder': '',
            'path_mappings': []
        }
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set configuration value"""
        self.config[key] = value
        self.save()
    
    def update(self, updates):
        """Update multiple configuration values"""
        self.config.update(updates)
        self.save()
    
    def get_safe_config(self):
        """Get config with sensitive data masked"""
        safe_config = self.config.copy()
        if safe_config.get('radarr_api_key'):
            safe_config['radarr_api_key'] = '***'
        if safe_config.get('sonarr_api_key'):
            safe_config['sonarr_api_key'] = '***'
        return safe_config