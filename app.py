from flask import Flask, render_template, jsonify, request
import requests
import json
import os
import shutil
import hashlib
import subprocess
import threading
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

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

def calculate_checksum(filepath, algorithm='sha256'):
    """Calculate file checksum"""
    hash_func = hashlib.new(algorithm)
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)
    return hash_func.hexdigest()

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
            app.logger.info(f"Copy progress: {line}")
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
    
    import time
    
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
            app.logger.info(f"Starting copy: {src_path} -> {dst_path}")
            copy_file_with_nice(src_path, dst_path, progress_callback=update_progress)
            app.logger.info(f"Copy completed: {dst_path}")
            
            # Update status
            with copy_lock:
                current_copy['status'] = 'verifying'
                current_copy['progress'] = 'Verifying checksum...'
                save_queue()
            
            # Verify checksum
            src_checksum = calculate_checksum(src_path)
            dst_checksum = calculate_checksum(dst_path)
            
            if src_checksum != dst_checksum:
                # Remove corrupted file
                os.remove(dst_path)
                raise Exception("Checksum verification failed")
            
            # Update status
            with copy_lock:
                current_copy['status'] = 'updating'
                current_copy['progress'] = 'Updating Radarr...'
                save_queue()
            
            # Update movie in Radarr
            movie_id = movie['id']
            movie['path'] = os.path.dirname(dst_path)
            movie['rootFolderPath'] = hdd_root
            
            radarr_url = get_radarr_url(config)
            headers = get_radarr_headers(config)
            
            # Update movie
            response = requests.put(
                f"{radarr_url}/movie/{movie_id}",
                headers=headers,
                json=movie
            )
            response.raise_for_status()
            
            # Trigger rescan
            requests.post(
                f"{radarr_url}/command",
                headers=headers,
                json={
                    'name': 'RescanMovie',
                    'movieId': movie_id
                }
            )
            
            # Mark as completed
            with copy_lock:
                current_copy['status'] = 'completed'
                current_copy['progress'] = 'Completed successfully'
                current_copy['completed_at'] = datetime.now().isoformat()
                current_copy['dst_path'] = dst_path
                save_queue()
                
                # Remove from queue after a delay
                threading.Timer(5.0, lambda: remove_completed_item(current_copy['id'])).start()
                current_copy = None
                
        except Exception as e:
            with copy_lock:
                if current_copy:
                    current_copy['status'] = 'failed'
                    current_copy['progress'] = f'Error: {str(e)}'
                    current_copy['failed_at'] = datetime.now().isoformat()
                    save_queue()
                    current_copy = None

def remove_completed_item(item_id):
    """Remove completed item from queue"""
    global copy_queue
    with copy_lock:
        copy_queue = [item for item in copy_queue if item['id'] != item_id or item['status'] != 'completed']
        save_queue()

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

if __name__ == '__main__':
    # Load queue on startup
    load_queue()
    
    # Start copy queue processor
    copy_thread = threading.Thread(target=process_copy_queue, daemon=True)
    copy_thread.start()
    
    app.run(host='0.0.0.0', port=6970, debug=False)