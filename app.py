from flask import Flask, render_template, jsonify, request
import requests
import json
import os
import shutil
import hashlib
import subprocess
import threading
import time
import logging
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration file path
CONFIG_FILE = 'data/config.json'
QUEUE_FILE = 'data/queue.json'

# Global state
copy_queue = []
current_copy = None
copy_lock = threading.Lock()

def ensure_data_dir():
    """Ensure data directory exists"""
    os.makedirs('data', exist_ok=True)

def load_config():
    """Load configuration from file"""
    ensure_data_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        'radarr_host': '',
        'radarr_port': '',
        'radarr_api_key': '',
        'ssd_root_folder': '',
        'hdd_root_folder': ''
    }

def save_config(config):
    """Save configuration to file"""
    ensure_data_dir()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def load_queue():
    """Load copy queue from file"""
    global copy_queue
    ensure_data_dir()
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as f:
            copy_queue = json.load(f)
    return copy_queue

def save_queue():
    """Save copy queue to file"""
    ensure_data_dir()
    with open(QUEUE_FILE, 'w') as f:
        json.dump(copy_queue, f, indent=2)

def get_radarr_url(config):
    """Build Radarr base URL"""
    return f"http://{config['radarr_host']}:{config['radarr_port']}/api/v3"

def get_radarr_headers(config):
    """Get headers for Radarr API requests"""
    return {
        'X-Api-Key': config['radarr_api_key'],
        'Content-Type': 'application/json'
    }

def calculate_checksum(filepath, algorithm='sha256', progress_callback=None):
    """Calculate file checksum with progress reporting"""
    hash_func = hashlib.new(algorithm)
    file_size = os.path.getsize(filepath)
    bytes_read = 0
    chunk_size = 8192 * 1024  # 8MB chunks for faster processing
    
    logger.info(f"Calculating {algorithm} checksum for {filepath} ({file_size / 1024 / 1024 / 1024:.2f} GB)")
    
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

def copy_file_with_nice(src, dst, progress_callback=None):
    """Copy file using rsync with ionice and nice for minimal system impact"""
    # Ensure destination directory exists
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    
    # Use rsync with progress output
    # ionice -c3: idle class (only when no other process needs I/O)
    # nice -n19: lowest CPU priority
    # rsync options:
    #   -a: archive mode (preserves permissions, timestamps, etc.)
    #   --info=progress2: show overall progress
    #   --no-i-r: disable incremental recursion for better progress reporting
    cmd = [
        'ionice', '-c3',
        'nice', '-n19',
        'rsync', '-a', '--info=progress2', '--no-i-r',
        src, dst
    ]
    
    # Run rsync and capture output
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    # Read output line by line
    for line in process.stdout:
        line = line.strip()
        if line:
            # Log progress
            logger.info(f"Copy progress: {line}")
            if progress_callback:
                progress_callback(line)
    
    # Wait for process to complete
    process.wait()
    
    if process.returncode != 0:
        stderr = process.stderr.read()
        raise Exception(f"Copy failed: {stderr}")
    
    return dst

def process_copy_queue():
    """Background thread to process copy queue"""
    global current_copy, copy_queue
    
    logger.info("Copy queue processor started")
    
    while True:
        # Check if there's work to do
        with copy_lock:
            if not copy_queue or current_copy:
                # Sleep before checking again
                pass
            else:
                # Get next item from queue
                current_copy = copy_queue[0]
                current_copy['status'] = 'copying'
                current_copy['started_at'] = datetime.now().isoformat()
                save_queue()
        
        # Sleep if no work
        if not current_copy:
            time.sleep(1)
            continue
        
        try:
            movie = current_copy['movie']
            config = load_config()
            
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
            
            # Update status
            with copy_lock:
                current_copy['status'] = 'copying'
                current_copy['progress'] = 'Copying file...'
                save_queue()
            
            # Progress callback to update status
            def update_progress(progress_line):
                with copy_lock:
                    current_copy['progress'] = f'Copying: {progress_line}'
                    save_queue()
            
            # Copy file with nice/ionice and progress tracking
            logger.info(f"Starting copy: {src_path} -> {dst_path}")
            copy_file_with_nice(src_path, dst_path, progress_callback=update_progress)
            logger.info(f"Copy completed: {dst_path}")
            
            # Update status
            with copy_lock:
                current_copy['status'] = 'verifying'
                current_copy['progress'] = 'Verifying checksum...'
                save_queue()
            
            # Verify checksum with progress
            logger.info("Starting checksum verification...")
            
            def update_verify_progress(progress):
                with copy_lock:
                    current_copy['progress'] = f'Verifying source: {progress}'
                    save_queue()
            
            src_checksum = calculate_checksum(src_path, progress_callback=update_verify_progress)
            
            def update_verify_progress_dst(progress):
                with copy_lock:
                    current_copy['progress'] = f'Verifying destination: {progress}'
                    save_queue()
            
            dst_checksum = calculate_checksum(dst_path, progress_callback=update_verify_progress_dst)
            
            logger.info(f"Source checksum: {src_checksum}")
            logger.info(f"Destination checksum: {dst_checksum}")
            
            if src_checksum != dst_checksum:
                logger.error("Checksum mismatch! Removing corrupted file.")
                # Remove corrupted file
                os.remove(dst_path)
                raise Exception("Checksum verification failed")
            
            logger.info("Checksum verification passed")
            
            # Update status
            with copy_lock:
                current_copy['status'] = 'updating'
                current_copy['progress'] = 'Updating Radarr...'
                save_queue()
            
            # Update movie in Radarr
            movie_id = movie['id']
            new_path = os.path.dirname(dst_path)
            movie['path'] = new_path
            movie['rootFolderPath'] = hdd_root
            
            logger.info(f"Updating Radarr for movie ID {movie_id}")
            logger.info(f"New path: {new_path}")
            logger.info(f"New root folder: {hdd_root}")
            
            radarr_url = get_radarr_url(config)
            headers = get_radarr_headers(config)
            
            # Update movie
            logger.info(f"Sending PUT request to {radarr_url}/movie/{movie_id}")
            response = requests.put(
                f"{radarr_url}/movie/{movie_id}",
                headers=headers,
                json=movie
            )
            response.raise_for_status()
            logger.info(f"Movie updated successfully in Radarr")
            
            # Trigger rescan
            logger.info(f"Triggering rescan for movie ID {movie_id}")
            rescan_response = requests.post(
                f"{radarr_url}/command",
                headers=headers,
                json={
                    'name': 'RescanMovie',
                    'movieId': movie_id
                }
            )
            rescan_response.raise_for_status()
            logger.info("Rescan triggered successfully")
            
            # Mark as completed
            logger.info(f"Successfully completed processing: {movie['title']}")
            with copy_lock:
                current_copy['status'] = 'completed'
                current_copy['progress'] = 'Completed successfully'
                current_copy['completed_at'] = datetime.now().isoformat()
                current_copy['dst_path'] = dst_path
                
                # Remove from queue immediately (not after delay)
                item_id = current_copy['id']
                copy_queue = [item for item in copy_queue if item['id'] != item_id]
                save_queue()
                
                logger.info(f"Removed completed item from queue. Remaining items: {len(copy_queue)}")
                current_copy = None
                
        except Exception as e:
            logger.error(f"Error processing queue item: {str(e)}", exc_info=True)
            with copy_lock:
                if current_copy:
                    current_copy['status'] = 'failed'
                    current_copy['progress'] = f'Error: {str(e)}'
                    current_copy['failed_at'] = datetime.now().isoformat()
                    
                    # Keep failed items in queue for manual review
                    save_queue()
                    current_copy = None

def remove_completed_item(item_id):
    """Remove completed item from queue (legacy function, not used anymore)"""
    global copy_queue
    with copy_lock:
        copy_queue = [item for item in copy_queue if item['id'] != item_id]
        save_queue()
        logger.info(f"Removed item {item_id} from queue")

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    config = load_config()
    # Don't send API key to client
    safe_config = config.copy()
    if safe_config.get('radarr_api_key'):
        safe_config['radarr_api_key'] = '***'
    return jsonify(safe_config)

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    data = request.json
    config = load_config()
    
    # Update config
    if 'radarr_host' in data:
        config['radarr_host'] = data['radarr_host']
    if 'radarr_port' in data:
        config['radarr_port'] = data['radarr_port']
    if 'radarr_api_key' in data and data['radarr_api_key'] != '***':
        config['radarr_api_key'] = data['radarr_api_key']
    
    # Fetch root folders from Radarr and auto-detect SSD/HDD
    try:
        radarr_url = get_radarr_url(config)
        headers = get_radarr_headers(config)
        
        response = requests.get(f"{radarr_url}/rootfolder", headers=headers)
        response.raise_for_status()
        root_folders = response.json()
        
        # Auto-detect SSD and HDD root folders based on path
        # Look for /media/movies_ssd and /media/movies_hdd
        for rf in root_folders:
            path = rf['path']
            if 'movies_ssd' in path.lower() or path.endswith('/media/movies_ssd'):
                config['ssd_root_folder'] = path
            elif 'movies_hdd' in path.lower() or path.endswith('/media/movies_hdd'):
                config['hdd_root_folder'] = path
        
        save_config(config)
        return jsonify({
            'success': True,
            'root_folders': root_folders,
            'ssd_root_folder': config.get('ssd_root_folder', ''),
            'hdd_root_folder': config.get('hdd_root_folder', '')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/rootfolders', methods=['GET'])
def get_root_folders():
    """Get root folders from Radarr"""
    try:
        config = load_config()
        radarr_url = get_radarr_url(config)
        headers = get_radarr_headers(config)
        
        response = requests.get(f"{radarr_url}/rootfolder", headers=headers)
        response.raise_for_status()
        
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/movies', methods=['GET'])
def get_movies():
    """Get movies from SSD root folder"""
    try:
        config = load_config()
        
        if not config.get('ssd_root_folder'):
            return jsonify({'error': 'SSD root folder not configured'}), 400
        
        radarr_url = get_radarr_url(config)
        headers = get_radarr_headers(config)
        
        response = requests.get(f"{radarr_url}/movie", headers=headers)
        response.raise_for_status()
        
        all_movies = response.json()
        
        # Filter movies in SSD root folder
        ssd_movies = [
            movie for movie in all_movies
            if movie.get('path', '').startswith(config['ssd_root_folder'])
            and movie.get('hasFile', False)
        ]
        
        return jsonify(ssd_movies)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/queue', methods=['GET'])
def get_queue():
    """Get current copy queue"""
    return jsonify(copy_queue)

@app.route('/api/queue', methods=['POST'])
def add_to_queue():
    """Add movie to copy queue"""
    global copy_queue
    
    data = request.json
    movie = data.get('movie')
    
    if not movie:
        return jsonify({'error': 'No movie provided'}), 400
    
    with copy_lock:
        # Check if already in queue
        if any(item['movie']['id'] == movie['id'] for item in copy_queue):
            return jsonify({'error': 'Movie already in queue'}), 400
        
        # Add to queue
        queue_item = {
            'id': f"{movie['id']}_{datetime.now().timestamp()}",
            'movie': movie,
            'status': 'pending',
            'progress': 'Waiting in queue...',
            'added_at': datetime.now().isoformat()
        }
        
        copy_queue.append(queue_item)
        save_queue()
    
    return jsonify({'success': True})

@app.route('/api/queue/<item_id>', methods=['DELETE'])
def remove_from_queue(item_id):
    """Remove item from queue"""
    global copy_queue, current_copy
    
    with copy_lock:
        # Don't allow removing currently copying item
        if current_copy and current_copy['id'] == item_id:
            return jsonify({'error': 'Cannot remove item currently being copied'}), 400
        
        copy_queue = [item for item in copy_queue if item['id'] != item_id]
        save_queue()
    
    return jsonify({'success': True})

@app.route('/api/leftovers', methods=['GET'])
def get_leftovers():
    """Find files on filesystem that don't have corresponding movies in Radarr"""
    try:
        config = load_config()
        
        if not config.get('ssd_root_folder') or not config.get('hdd_root_folder'):
            return jsonify({'error': 'Root folders not configured'}), 400
        
        ssd_root = config['ssd_root_folder']
        hdd_root = config['hdd_root_folder']
        
        # Get all movies from Radarr
        radarr_url = get_radarr_url(config)
        headers = get_radarr_headers(config)
        
        response = requests.get(f"{radarr_url}/movie", headers=headers)
        response.raise_for_status()
        all_movies = response.json()
        
        # Build maps of movie paths and movies by directory name
        radarr_ssd_paths = set()
        hdd_movies_by_name = {}
        
        for movie in all_movies:
            movie_path = movie.get('path', '')
            if movie_path:
                if movie_path.startswith(ssd_root):
                    radarr_ssd_paths.add(movie_path)
                elif movie_path.startswith(hdd_root):
                    # Store HDD movies by directory name for matching
                    dir_name = os.path.basename(movie_path)
                    hdd_movies_by_name[dir_name] = movie
        
        # Scan filesystem for directories in SSD root
        leftovers = []
        if os.path.exists(ssd_root):
            for item in os.listdir(ssd_root):
                item_path = os.path.join(ssd_root, item)
                
                # Only check directories
                if os.path.isdir(item_path):
                    # Check if this directory is in Radarr SSD paths
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
                            # Check if the movie file actually exists on HDD
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
        return jsonify(leftovers)
        
    except Exception as e:
        logger.error(f"Error finding leftovers: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

@app.route('/api/leftovers', methods=['DELETE'])
def delete_leftover():
    """Delete a leftover directory"""
    try:
        data = request.json
        path = data.get('path')
        
        if not path:
            return jsonify({'error': 'No path provided'}), 400
        
        config = load_config()
        ssd_root = config.get('ssd_root_folder')
        
        # Security check: ensure path is within SSD root
        if not ssd_root or not path.startswith(ssd_root):
            return jsonify({'error': 'Invalid path'}), 400
        
        # Check if path exists
        if not os.path.exists(path):
            return jsonify({'error': 'Path does not exist'}), 404
        
        # Delete directory and all contents
        logger.info(f"Deleting leftover directory: {path}")
        shutil.rmtree(path)
        logger.info(f"Successfully deleted: {path}")
        
        return jsonify({'success': True, 'message': f'Deleted {path}'})
        
    except Exception as e:
        logger.error(f"Error deleting leftover: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

@app.route('/api/leftovers/recopy', methods=['POST'])
def recopy_leftover():
    """Re-add a leftover movie to the copy queue"""
    try:
        data = request.json
        movie_id = data.get('movie_id')
        ssd_path = data.get('ssd_path')
        
        if not movie_id or not ssd_path:
            return jsonify({'error': 'movie_id and ssd_path required'}), 400
        
        config = load_config()
        ssd_root = config.get('ssd_root_folder')
        
        # Security check
        if not ssd_root or not ssd_path.startswith(ssd_root):
            return jsonify({'error': 'Invalid SSD path'}), 400
        
        # Check if SSD path exists
        if not os.path.exists(ssd_path):
            return jsonify({'error': 'SSD path does not exist'}), 404
        
        radarr_url = get_radarr_url(config)
        headers = get_radarr_headers(config)
        
        # Get movie details from Radarr
        response = requests.get(f"{radarr_url}/movie/{movie_id}", headers=headers)
        response.raise_for_status()
        movie = response.json()
        
        # Find the movie file on SSD
        movie_file = None
        for dirpath, dirnames, filenames in os.walk(ssd_path):
            for filename in filenames:
                # Look for video files
                if filename.lower().endswith(('.mkv', '.mp4', '.avi', '.m4v', '.mov')):
                    filepath = os.path.join(dirpath, filename)
                    file_size = os.path.getsize(filepath)
                    
                    # Create a movieFile object
                    movie_file = {
                        'path': filepath,
                        'size': file_size,
                        'quality': movie.get('movieFile', {}).get('quality', {}),
                    }
                    break
            if movie_file:
                break
        
        if not movie_file:
            return jsonify({'error': 'No video file found in SSD directory'}), 404
        
        # Update movie object with SSD file info
        movie['movieFile'] = movie_file
        movie['hasFile'] = True
        
        # Add to queue
        global copy_queue
        with copy_lock:
            # Check if already in queue
            if any(item['movie']['id'] == movie['id'] for item in copy_queue):
                return jsonify({'error': 'Movie already in queue'}), 400
            
            # Add to queue
            queue_item = {
                'id': f"{movie['id']}_{datetime.now().timestamp()}",
                'movie': movie,
                'status': 'pending',
                'progress': 'Waiting in queue...',
                'added_at': datetime.now().isoformat()
            }
            
            copy_queue.append(queue_item)
            save_queue()
        
        logger.info(f"Re-added movie {movie['title']} to copy queue from {ssd_path}")
        return jsonify({'success': True, 'message': f'Added {movie["title"]} to queue'})
        
    except Exception as e:
        logger.error(f"Error re-copying leftover: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

@app.route('/api/queue/clear', methods=['POST'])
def clear_queue():
    """Force clear the entire queue"""
    global copy_queue, current_copy
    
    try:
        with copy_lock:
            queue_count = len(copy_queue)
            copy_queue = []
            current_copy = None
            save_queue()
        
        logger.warning(f"Queue forcefully cleared. Removed {queue_count} items.")
        return jsonify({'success': True, 'message': f'Cleared {queue_count} items from queue'})
        
    except Exception as e:
        logger.error(f"Error clearing queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400

# Initialize queue processor on module load (works with Gunicorn)
def init_queue_processor():
    """Initialize the copy queue processor"""
    logger.info("Initializing copy queue processor...")
    load_queue()
    copy_thread = threading.Thread(target=process_copy_queue, daemon=True)
    copy_thread.start()
    logger.info("Copy queue processor initialized")

# Start processor when module is loaded
init_queue_processor()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6970, debug=False)