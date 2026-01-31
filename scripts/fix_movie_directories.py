#!/usr/bin/env python3
"""
Script to check and fix movie directory names in Radarr.

This script:
1. Connects to Radarr API
2. Gets all movies from all root folders
3. Checks if directory names match the format: {Movie.Collection.}{Release.Year}.{Movie.CleanTitle}
4. Renames directories that don't match
5. Updates the path in Radarr

Usage:
    python scripts/fix_movie_directories.py           # Normal mode - makes actual changes
    python scripts/fix_movie_directories.py --dry-run # Dry-run mode - only shows what would be changed
"""
import os
import sys
import logging
import re
import shutil
import argparse
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


def map_path(path, path_mappings):
    """
    Map Docker container path to host path using path mappings.
    
    Args:
        path: Path from Radarr (Docker container path)
        path_mappings: List of mapping dictionaries with 'docker' and 'host' keys
        
    Returns:
        Mapped host path, or original path if no mapping found
        
    Example mappings in config.json:
        "path_mappings": [
            {
                "docker": "/media/movies_ssd",
                "host": "/mnt/storage/movies_ssd"
            },
            {
                "docker": "/media/movies_hdd",
                "host": "/mnt/storage/movies_hdd"
            }
        ]
    """
    if not path_mappings:
        return path
    
    for mapping in path_mappings:
        docker_path = mapping.get('docker', '')
        host_path = mapping.get('host', '')
        
        if not docker_path or not host_path:
            continue
        
        # Normalize paths (remove trailing slashes)
        docker_path = docker_path.rstrip('/')
        host_path = host_path.rstrip('/')
        
        # Check if path starts with docker path
        if path.startswith(docker_path):
            # Replace docker path with host path
            mapped_path = path.replace(docker_path, host_path, 1)
            logger.debug(f"Path mapping: {path} -> {mapped_path}")
            return mapped_path
    
    # No mapping found, return original path
    return path


def unmap_path(path, path_mappings):
    """
    Map host path back to Docker container path using path mappings.
    
    Args:
        path: Host path
        path_mappings: List of mapping dictionaries with 'docker' and 'host' keys
        
    Returns:
        Mapped Docker path, or original path if no mapping found
    """
    if not path_mappings:
        return path
    
    for mapping in path_mappings:
        docker_path = mapping.get('docker', '')
        host_path = mapping.get('host', '')
        
        if not docker_path or not host_path:
            continue
        
        # Normalize paths (remove trailing slashes)
        docker_path = docker_path.rstrip('/')
        host_path = host_path.rstrip('/')
        
        # Check if path starts with host path
        if path.startswith(host_path):
            # Replace host path with docker path
            unmapped_path = path.replace(host_path, docker_path, 1)
            logger.debug(f"Path unmapping: {path} -> {unmapped_path}")
            return unmapped_path
    
    # No mapping found, return original path
    return path


def clean_title(title):
    """
    Clean movie title for directory name.
    Removes special characters and replaces spaces with dots.
    Applies standard conversions like & -> and
    """
    # Standard character replacements
    cleaned = title
    cleaned = cleaned.replace('&', 'and')
    cleaned = cleaned.replace('+', 'plus')
    
    # Replace hyphens with spaces (will become dots later)
    cleaned = cleaned.replace('-', ' ')
    
    # Remove special characters except spaces and dots
    cleaned = re.sub(r'[^\w\s\.]', '', cleaned)
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
    
    # Check for collection - it might be under different keys
    collection = movie.get('collection')
    
    # Debug: log collection info
    if collection:
        logger.debug(f"Collection found: {collection}")
    
    clean_movie_title = clean_title(title)
    
    # Build directory name
    parts = []
    
    # Add collection name if exists
    # Collection can be a dict with 'name' or 'title' key
    if collection:
        collection_name = None
        if isinstance(collection, dict):
            collection_name = collection.get('name') or collection.get('title')
        elif isinstance(collection, str):
            collection_name = collection
        
        if collection_name:
            clean_collection_name = clean_title(collection_name)
            parts.append(clean_collection_name)
            logger.debug(f"Using collection name: {clean_collection_name}")
    
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


def rename_directory(old_path, new_path, dry_run=False):
    """
    Rename directory from old_path to new_path.
    
    Args:
        old_path: Current directory path
        new_path: New directory path
        dry_run: If True, only simulate the rename without actually doing it
        
    Returns:
        True if successful (or would be successful in dry-run), False otherwise
    """
    try:
        logger.info(f"{'[DRY-RUN] Would rename' if dry_run else 'Renaming'} directory:")
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
        
        if dry_run:
            logger.info(f"✓ [DRY-RUN] Would successfully rename directory")
            return True
        
        # Perform rename
        shutil.move(old_path, new_path)
        logger.info(f"✓ Successfully renamed directory")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to rename directory: {str(e)}")
        return False


def update_movie_path_in_radarr(radarr_client, movie, new_path, dry_run=False):
    """
    Update movie path in Radarr.
    
    Args:
        radarr_client: RadarrClient instance
        movie: Movie object from Radarr
        new_path: New path for the movie
        dry_run: If True, only simulate the update without actually doing it
        
    Returns:
        True if successful (or would be successful in dry-run), False otherwise
    """
    try:
        movie_id = movie['id']
        logger.info(f"{'[DRY-RUN] Would update' if dry_run else 'Updating'} movie path in Radarr (ID: {movie_id})...")
        
        if dry_run:
            logger.info(f"✓ [DRY-RUN] Would successfully update path in Radarr")
            logger.info(f"✓ [DRY-RUN] Would trigger rescan for movie")
            return True
        
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


def process_root_folder(radarr_client, root_folder_path, root_folder_name, path_mappings, dry_run=False):
    """
    Process all movies in a specific root folder and fix directory names.
    
    Args:
        radarr_client: RadarrClient instance
        root_folder_path: Path to root folder (Docker path)
        root_folder_name: Name/label for the root folder
        path_mappings: List of path mapping dictionaries
        dry_run: If True, only simulate changes without actually making them
        
    Returns:
        Dictionary with statistics
    """
    logger.info("=" * 80)
    logger.info(f"Processing Root Folder: {root_folder_name}")
    logger.info("=" * 80)
    logger.info(f"Root Folder Path (Docker): {root_folder_path}")
    
    # Map root folder to host path
    root_folder_host = map_path(root_folder_path, path_mappings)
    logger.info(f"Root Folder Path (Host):   {root_folder_host}")
    logger.info("")
    
    # Get all movies from this root folder
    logger.info(f"Fetching movies from {root_folder_name}...")
    movies = radarr_client.filter_movies_by_root_folder(root_folder_path)
    logger.info(f"Found {len(movies)} movies in {root_folder_name}")
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
        current_path_docker = movie.get('path', '')
        
        # Map Docker path to host path
        current_path_host = map_path(current_path_docker, path_mappings)
        
        logger.info("-" * 80)
        logger.info(f"[{idx}/{total_movies}] Processing: {movie_title} (ID: {movie_id})")
        logger.info(f"Current path (Docker): {current_path_docker}")
        if current_path_docker != current_path_host:
            logger.info(f"Current path (Host):   {current_path_host}")
        
        # Debug: log movie data for troubleshooting
        logger.debug(f"Movie data: title={movie.get('title')}, year={movie.get('year')}, "
                    f"collection={movie.get('collection')}")
        
        # Get expected directory name
        expected_dir_name = get_expected_directory_name(movie)
        current_dir_name = get_current_directory_name(current_path_host)
        
        logger.info(f"Current directory name: {current_dir_name}")
        logger.info(f"Expected directory name: {expected_dir_name}")
        
        # Show collection info if present
        collection = movie.get('collection')
        if collection:
            if isinstance(collection, dict):
                coll_name = collection.get('name') or collection.get('title', 'N/A')
            else:
                coll_name = str(collection)
            logger.info(f"Collection: {coll_name}")
        
        # Check if directory name matches expected format
        if current_dir_name == expected_dir_name:
            logger.info("✓ Directory name is correct, no action needed")
            movies_correct += 1
            logger.info("")
            continue
        
        # Directory needs to be fixed
        logger.warning("✗ Directory name does not match expected format")
        movies_to_fix += 1
        
        # Calculate new paths (both host and docker)
        parent_dir_host = os.path.dirname(current_path_host)
        new_path_host = os.path.join(parent_dir_host, expected_dir_name)
        new_path_docker = unmap_path(new_path_host, path_mappings)
        
        # Rename directory on host filesystem
        if rename_directory(current_path_host, new_path_host, dry_run):
            # Update path in Radarr with Docker path
            if update_movie_path_in_radarr(radarr_client, movie, new_path_docker, dry_run):
                movies_fixed += 1
                logger.info(f"✓ Movie {'would be' if dry_run else 'successfully'} processed")
            else:
                movies_failed += 1
                if not dry_run:
                    logger.error("✗ Failed to update Radarr, attempting to rollback...")
                    # Try to rollback directory rename on host
                    if os.path.exists(new_path_host) and not os.path.exists(current_path_host):
                        try:
                            shutil.move(new_path_host, current_path_host)
                            logger.info("✓ Rollback successful")
                        except Exception as e:
                            logger.error(f"✗ Rollback failed: {str(e)}")
        else:
            movies_failed += 1
            logger.error(f"✗ {'Would fail' if dry_run else 'Failed'} to rename directory")
        
        logger.info("")
    
    # Print summary for this root folder
    logger.info("=" * 80)
    logger.info(f"SUMMARY for {root_folder_name} {'[DRY-RUN MODE]' if dry_run else ''}")
    logger.info("=" * 80)
    logger.info(f"Total movies processed: {total_movies}")
    logger.info(f"Movies with correct names: {movies_correct}")
    logger.info(f"Movies that {'would need' if dry_run else 'needed'} fixing: {movies_to_fix}")
    logger.info(f"Movies {'that would be' if dry_run else 'successfully'} fixed: {movies_fixed}")
    logger.info(f"Movies {'that would' if dry_run else 'that'} fail{'ed' if not dry_run else ''} to fix: {movies_failed}")
    logger.info("=" * 80)
    logger.info("")
    
    return {
        'total': total_movies,
        'correct': movies_correct,
        'to_fix': movies_to_fix,
        'fixed': movies_fixed,
        'failed': movies_failed
    }


def process_all_root_folders(radarr_client, path_mappings, dry_run=False):
    """
    Process all movies in all root folders and fix directory names.
    
    Args:
        radarr_client: RadarrClient instance
        path_mappings: List of path mapping dictionaries
        dry_run: If True, only simulate changes without actually making them
    """
    logger.info("=" * 80)
    logger.info(f"Starting movie directory check and fix process {'[DRY-RUN MODE]' if dry_run else ''}")
    logger.info("=" * 80)
    
    if path_mappings:
        logger.info(f"Path mappings configured: {len(path_mappings)} mapping(s)")
        for idx, mapping in enumerate(path_mappings, 1):
            logger.info(f"  [{idx}] {mapping.get('docker', 'N/A')} -> {mapping.get('host', 'N/A')}")
    else:
        logger.warning("⚠️  No path mappings configured - using paths as-is")
    
    if dry_run:
        logger.info("⚠️  DRY-RUN MODE: No actual changes will be made")
    logger.info("")
    
    # Get all root folders from Radarr
    logger.info("Fetching root folders from Radarr...")
    root_folders = radarr_client.get_root_folders()
    logger.info(f"Found {len(root_folders)} root folder(s)")
    logger.info("")
    
    # Display all root folders
    for idx, rf in enumerate(root_folders, 1):
        path = rf.get('path', 'N/A')
        host_path = map_path(path, path_mappings)
        logger.info(f"  [{idx}] {path}")
        if path != host_path:
            logger.info(f"      → {host_path} (host)")
    logger.info("")
    
    # Process each root folder
    all_stats = []
    for idx, root_folder in enumerate(root_folders, 1):
        root_folder_path = root_folder.get('path', '')
        root_folder_id = root_folder.get('id', 'unknown')
        
        if not root_folder_path:
            logger.warning(f"Skipping root folder {root_folder_id} - no path")
            continue
        
        # Verify root folder exists on host
        root_folder_host = map_path(root_folder_path, path_mappings)
        if not os.path.exists(root_folder_host):
            logger.warning(f"⚠️  Skipping root folder - does not exist on host: {root_folder_host}")
            if root_folder_path != root_folder_host:
                logger.warning(f"    (Mapped from Docker path: {root_folder_path})")
            logger.info("")
            continue
        
        # Process this root folder
        root_folder_name = f"Root Folder #{idx} ({os.path.basename(root_folder_path)})"
        stats = process_root_folder(
            radarr_client,
            root_folder_path,
            root_folder_name,
            path_mappings,
            dry_run
        )
        all_stats.append({
            'name': root_folder_name,
            'path': root_folder_path,
            'stats': stats
        })
    
    # Print overall summary
    logger.info("=" * 80)
    logger.info(f"OVERALL SUMMARY {'[DRY-RUN MODE]' if dry_run else ''}")
    logger.info("=" * 80)
    
    total_all = sum(s['stats']['total'] for s in all_stats)
    correct_all = sum(s['stats']['correct'] for s in all_stats)
    to_fix_all = sum(s['stats']['to_fix'] for s in all_stats)
    fixed_all = sum(s['stats']['fixed'] for s in all_stats)
    failed_all = sum(s['stats']['failed'] for s in all_stats)
    
    logger.info(f"Root folders processed: {len(all_stats)}")
    logger.info(f"Total movies across all folders: {total_all}")
    logger.info(f"Movies with correct names: {correct_all}")
    logger.info(f"Movies that {'would need' if dry_run else 'needed'} fixing: {to_fix_all}")
    logger.info(f"Movies {'that would be' if dry_run else 'successfully'} fixed: {fixed_all}")
    logger.info(f"Movies {'that would' if dry_run else 'that'} fail{'ed' if not dry_run else ''} to fix: {failed_all}")
    
    if all_stats:
        logger.info("")
        logger.info("Breakdown by root folder:")
        for item in all_stats:
            stats = item['stats']
            logger.info(f"  {item['name']}:")
            logger.info(f"    Total: {stats['total']}, Correct: {stats['correct']}, "
                       f"Fixed: {stats['fixed']}, Failed: {stats['failed']}")
    
    if dry_run:
        logger.info("")
        logger.info("⚠️  This was a DRY-RUN. No actual changes were made.")
        logger.info("Run without --dry-run to apply these changes.")
    logger.info("=" * 80)


def main():
    """Main entry point"""
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(
            description='Check and fix movie directory names in Radarr',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s              # Normal mode - makes actual changes
  %(prog)s --dry-run    # Dry-run mode - only shows what would be changed
            """
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate changes without actually making them'
        )
        args = parser.parse_args()
        
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
        
        path_mappings = config.get('path_mappings', [])
        
        # Validate path mappings
        if path_mappings:
            logger.info(f"Found {len(path_mappings)} path mapping(s) in configuration")
            for idx, mapping in enumerate(path_mappings, 1):
                if not isinstance(mapping, dict):
                    logger.error(f"Path mapping {idx} is not a dictionary")
                    sys.exit(1)
                if 'docker' not in mapping or 'host' not in mapping:
                    logger.error(f"Path mapping {idx} missing 'docker' or 'host' key")
                    sys.exit(1)
                logger.info(f"  [{idx}] Docker: {mapping['docker']} -> Host: {mapping['host']}")
        else:
            logger.warning("⚠️  No path mappings configured")
            logger.warning("    If running from host with Docker Radarr, you should configure path_mappings")
            logger.warning("    in data/config.json")
        
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
        
        # Process all root folders
        process_all_root_folders(radarr_client, path_mappings, dry_run=args.dry_run)
        
        logger.info(f"Script completed successfully {'[DRY-RUN MODE]' if args.dry_run else ''}")
        
    except KeyboardInterrupt:
        logger.info("\nScript interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()