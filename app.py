"""
Radarr Safe Mover - Refactored version
Main Flask application using modular architecture
"""
from flask import Flask, render_template, jsonify, request
import logging

# Core modules
from core.config import ConfigManager
from core.radarr import RadarrClient
from core.queue import OperationQueue

# Operation-specific modules
from operations.copy_operation import CopyOperationHandler
from operations.leftovers import LeftoversManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Initialize core components
config_manager = ConfigManager('data/config.json')
operation_handler = CopyOperationHandler(config_manager)
operation_queue = OperationQueue(
    queue_file='data/queue.json',
    history_file='data/history.json',
    operation_handler=operation_handler
)

# Start queue processor
operation_queue.start_processor()


def get_radarr_client():
    """Get configured Radarr client"""
    config = config_manager.config
    return RadarrClient(
        config['radarr_host'],
        config['radarr_port'],
        config['radarr_api_key']
    )


# ============================================================================
# ROUTES - Main Page
# ============================================================================

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


# ============================================================================
# ROUTES - Configuration
# ============================================================================

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration (API key masked)"""
    return jsonify(config_manager.get_safe_config())


@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration and auto-detect root folders"""
    data = request.json
    
    # Update basic config
    updates = {}
    if 'radarr_host' in data:
        updates['radarr_host'] = data['radarr_host']
    if 'radarr_port' in data:
        updates['radarr_port'] = data['radarr_port']
    if 'radarr_api_key' in data and data['radarr_api_key'] != '***':
        updates['radarr_api_key'] = data['radarr_api_key']
    
    config_manager.update(updates)
    
    # Auto-detect root folders
    try:
        radarr = get_radarr_client()
        root_folders = radarr.get_root_folders()
        
        # Look for SSD and HDD folders
        for rf in root_folders:
            path = rf['path']
            if 'movies_ssd' in path.lower() or path.endswith('/media/movies_ssd'):
                config_manager.set('ssd_root_folder', path)
            elif 'movies_hdd' in path.lower() or path.endswith('/media/movies_hdd'):
                config_manager.set('hdd_root_folder', path)
        
        return jsonify({
            'success': True,
            'root_folders': root_folders,
            'ssd_root_folder': config_manager.get('ssd_root_folder', ''),
            'hdd_root_folder': config_manager.get('hdd_root_folder', '')
        })
        
    except Exception as e:
        logger.error(f"Error updating config: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/rootfolders', methods=['GET'])
def get_root_folders():
    """Get root folders from Radarr"""
    try:
        radarr = get_radarr_client()
        return jsonify(radarr.get_root_folders())
    except Exception as e:
        logger.error(f"Error getting root folders: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


# ============================================================================
# ROUTES - Movies
# ============================================================================

@app.route('/api/movies', methods=['GET'])
def get_movies():
    """Get movies from SSD root folder"""
    try:
        ssd_root = config_manager.get('ssd_root_folder')
        if not ssd_root:
            return jsonify({'error': 'SSD root folder not configured'}), 400
        
        radarr = get_radarr_client()
        movies = radarr.filter_movies_by_root_folder(ssd_root)
        
        return jsonify(movies)
    except Exception as e:
        logger.error(f"Error getting movies: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


# ============================================================================
# ROUTES - Queue Management
# ============================================================================

@app.route('/api/queue', methods=['GET'])
def get_queue():
    """Get current operation queue"""
    return jsonify(operation_queue.get_queue())


@app.route('/api/queue', methods=['POST'])
def add_to_queue():
    """Add movie to operation queue"""
    data = request.json
    movie = data.get('movie')
    
    if not movie:
        return jsonify({'error': 'No movie provided'}), 400
    
    try:
        operation_queue.add_to_queue(movie)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error adding to queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/queue/<item_id>', methods=['DELETE'])
def remove_from_queue(item_id):
    """Remove item from queue"""
    try:
        operation_queue.remove_from_queue(item_id)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error removing from queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/queue/clear', methods=['POST'])
def clear_queue():
    """Force clear entire queue"""
    try:
        count = operation_queue.clear_queue()
        return jsonify({
            'success': True,
            'message': f'Cleared {count} items from queue'
        })
    except Exception as e:
        logger.error(f"Error clearing queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# ROUTES - History
# ============================================================================

@app.route('/api/history', methods=['GET'])
def get_history():
    """Get operation history (last 5 operations)"""
    return jsonify(operation_queue.get_history())


# ============================================================================
# ROUTES - Leftovers (Operation-specific)
# ============================================================================

@app.route('/api/leftovers', methods=['GET'])
def get_leftovers():
    """Find leftover files on SSD not tracked by Radarr"""
    try:
        radarr = get_radarr_client()
        leftovers_manager = LeftoversManager(config_manager, radarr)
        leftovers = leftovers_manager.find_leftovers()
        return jsonify(leftovers)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error finding leftovers: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/leftovers', methods=['DELETE'])
def delete_leftover():
    """Delete a leftover directory"""
    try:
        data = request.json
        path = data.get('path')
        
        if not path:
            return jsonify({'error': 'No path provided'}), 400
        
        radarr = get_radarr_client()
        leftovers_manager = LeftoversManager(config_manager, radarr)
        leftovers_manager.delete_leftover(path)
        
        return jsonify({'success': True, 'message': f'Deleted {path}'})
    except (ValueError, FileNotFoundError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error deleting leftover: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/leftovers/recopy', methods=['POST'])
def recopy_leftover():
    """Re-add a leftover movie to the copy queue"""
    try:
        data = request.json
        movie_id = data.get('movie_id')
        ssd_path = data.get('ssd_path')
        
        if not movie_id or not ssd_path:
            return jsonify({'error': 'movie_id and ssd_path required'}), 400
        
        radarr = get_radarr_client()
        leftovers_manager = LeftoversManager(config_manager, radarr)
        
        # Prepare movie for re-copying
        movie = leftovers_manager.prepare_recopy(movie_id, ssd_path)
        
        # Add to queue
        operation_queue.add_to_queue(movie)
        
        logger.info(f"Re-added movie {movie['title']} to copy queue from {ssd_path}")
        return jsonify({'success': True, 'message': f'Added {movie["title"]} to queue'})
        
    except (ValueError, FileNotFoundError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error re-copying leftover: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6970, debug=False)