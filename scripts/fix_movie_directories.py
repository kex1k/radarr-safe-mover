#!/usr/bin/env python3
"""
Script to check and fix movie directory names in Radarr.

This script:
1. Connects to Radarr API
2. Gets all movies from SSD root folder
3. Checks if directory names match the format: {Movie.Collection.}{Release.Year}.{Movie.CleanTitle}
4. Renames directories that don't match
5. Updates the path in Radarr
"""
import os
import sys
import logging
import re
import shutil
from pathlib import Path

# Add parent directory to path to import core modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import ConfigManager
from core.radarr import RadarrClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_title(title):
    """
    Clean movie title for directory name.
    Removes special characters and replaces spaces with dots.
    """
    # Remove special characters except spaces, dots, and hyphens
    cleaned = re.sub(r'[^\w\s\.\-]', '', title)
    # Replace spaces with dots
    cleaned = cleaned.replace(' ', '.')
    # Remove multiple consecutive dots
    cleaned = re.sub(r'\.+', '.', cleaned)
    # Remove leading/trailing dots
    cleaned = cleaned.strip('.')
    return cleaned


def get_expected_directory_name(movie):
    """
    Generate expected directory name based on Radarr format:
    {Movie.Collection.}{Release.Year}.{Movie.CleanTitle}
    
    Args:
        movie: Movie object from Radarr API
        
    Returns:
        Expected directory name string
    """
    title = movie.get('title', '')
    year = movie.get('year', '')
    collection = movie.get('collection', {})
    
    clean_movie_title = clean_title(title)
    
    # Build directory name
    parts = []
    
    # Add collection name if exists
    if collection and collection.get('name'):
        collection_name = clean_title(collection['name'])
        parts.append(collection_name)
    
    # Add year
    parts.append(str(year))
    
    # Add clean title
    parts.append(clean_movie_title)
    
    return '.'.join(parts)


def get_current_directory_name(movie_path):
    """
    Extract current directory name from full movie path.
    
    Args:
        movie_path: Full path to movie directory
        
    Returns:
        Directory name (last component of path)
    """
    return os.path.basename(movie_path.rstrip('/'))


def rename_directory(old_path, new_path):
    """
    Rename directory from old_path to new_path.
    
    Args:
        old_path: Current directory path
        new_path: New directory path
        
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Renaming directory:")
        logger.info(f"  FROM: {old_path}")
        logger.info(f"  TO:   {new_path}")
        
        # Check if old path exists
        if not os.path.exists(old_path):
            logger.error(f"Source directory does not exist: {old_path}")
            return False
        
        # Check if new path already exists
        if os.path.exists(new_path):
            logger.error(f"Target directory already exists: {new_path}")
            return False
        
        # Perform rename
        shutil.move(old_path, new_path)
        logger.info(f"✓ Successfully renamed directory")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to rename directory: {str(e)}")
        return False


def update_movie_path_in_radarr(radarr_client, movie, new_path):
    """
    Update movie path in Radarr.
    
    Args:
        radarr_client: RadarrClient instance
        movie: Movie object from Radarr
        new_path: New path for the movie
        
    Returns:
        True if successful, False otherwise
    """
    try:
        movie_id = movie['id']
        logger.info(f"Updating movie path in Radarr (ID: {movie_id})...")
        
        # Update movie data with new path
        movie['path'] = new_path
        
        # Send update to Radarr
        radarr_client.update_movie(movie_id, movie)
        logger.info(f"✓ Successfully updated path in Radarr")
        
        # Trigger rescan to update file info
        logger.info(f"Triggering rescan for movie...")
        radarr_client.rescan_movie(movie_id)
        logger.info(f"✓ Rescan triggered")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update movie in Radarr: {str(e)}")
        return False


def process_movies(radarr_client, ssd_root_folder):
    """
    Process all movies in SSD root folder and fix directory names.
    
    Args:
        radarr_client: RadarrClient instance
        ssd_root_folder: Path to SSD root folder
    """
    logger.info("=" * 80)
    logger.info("Starting movie directory check and fix process")
    logger.info("=" * 80)
    logger.info(f"SSD Root Folder: {ssd_root_folder}")
    logger.info("")
    
    # Get all movies from SSD
    logger.info("Fetching movies from Radarr...")
    movies = radarr_client.filter_movies_by_root_folder(ssd_root_folder)
    logger.info(f"Found {len(movies)} movies in SSD root folder")
    logger.info("")
    
    # Statistics
    total_movies = len(movies)
    movies_to_fix = 0
    movies_fixed = 0
    movies_failed = 0
    movies_correct = 0
    
    # Process each movie
    for idx, movie in enumerate(movies, 1):
        movie_title = movie.get('title', 'Unknown')
        movie_id = movie.get('id', 'Unknown')
        current_path = movie.get('path', '')
        
        logger.info("-" * 80)
        logger.info(f"[{idx}/{total_movies}] Processing: {movie_title} (ID: {movie_id})")
        logger.info(f"Current path: {current_path}")
        
        # Get expected directory name
        expected_dir_name = get_expected_directory_name(movie)
        current_dir_name = get_current_directory_name(current_path)
        
        logger.info(f"Current directory name: {current_dir_name}")
        logger.info(f"Expected directory name: {expected_dir_name}")
        
        # Check if directory name matches expected format
        if current_dir_name == expected_dir_name:
            logger.info("✓ Directory name is correct, no action needed")
            movies_correct += 1
            logger.info("")
            continue
        
        # Directory needs to be fixed
        logger.warning("✗ Directory name does not match expected format")
        movies_to_fix += 1
        
        # Calculate new path
        parent_dir = os.path.dirname(current_path)
        new_path = os.path.join(parent_dir, expected_dir_name)
        
        # Rename directory
        if rename_directory(current_path, new_path):
            # Update path in Radarr
            if update_movie_path_in_radarr(radarr_client, movie, new_path):
                movies_fixed += 1
                logger.info("✓ Movie successfully processed")
            else:
                movies_failed += 1
                logger.error("✗ Failed to update Radarr, attempting to rollback...")
                # Try to rollback directory rename
                if os.path.exists(new_path) and not os.path.exists(current_path):
                    try:
                        shutil.move(new_path, current_path)
                        logger.info("✓ Rollback successful")
                    except Exception as e:
                        logger.error(f"✗ Rollback failed: {str(e)}")
        else:
            movies_failed += 1
            logger.error("✗ Failed to rename directory")
        
        logger.info("")
    
    # Print summary
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total movies processed: {total_movies}")
    logger.info(f"Movies with correct names: {movies_correct}")
    logger.info(f"Movies that needed fixing: {movies_to_fix}")
    logger.info(f"Movies successfully fixed: {movies_fixed}")
    logger.info(f"Movies failed to fix: {movies_failed}")
    logger.info("=" * 80)


def main():
    """Main entry point"""
    try:
        # Load configuration
        logger.info("Loading configuration...")
        config_manager = ConfigManager('data/config.json')
        config = config_manager.config
        
        # Validate configuration
        if not config.get('radarr_host'):
            logger.error("Radarr host not configured")
            sys.exit(1)
        
        if not config.get('radarr_port'):
            logger.error("Radarr port not configured")
            sys.exit(1)
        
        if not config.get('radarr_api_key'):
            logger.error("Radarr API key not configured")
            sys.exit(1)
        
        if not config.get('ssd_root_folder'):
            logger.error("SSD root folder not configured")
            sys.exit(1)
        
        ssd_root_folder = config['ssd_root_folder']
        
        # Verify SSD root folder exists
        if not os.path.exists(ssd_root_folder):
            logger.error(f"SSD root folder does not exist: {ssd_root_folder}")
            sys.exit(1)
        
        logger.info("✓ Configuration loaded successfully")
        logger.info("")
        
        # Initialize Radarr client
        logger.info("Connecting to Radarr...")
        radarr_client = RadarrClient(
            config['radarr_host'],
            config['radarr_port'],
            config['radarr_api_key']
        )
        logger.info("✓ Connected to Radarr")
        logger.info("")
        
        # Process movies
        process_movies(radarr_client, ssd_root_folder)
        
        logger.info("Script completed successfully")
        
    except KeyboardInterrupt:
        logger.info("\nScript interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()