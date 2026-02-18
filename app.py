"""
Ultimate Radarr Toolbox - Refactored version
Main Flask application using modular architecture
"""
from flask import Flask, render_template, jsonify, request
import logging
import re
import os

# Core modules
from core.config import ConfigManager
from core.radarr import RadarrClient
from core.sonarr import SonarrClient
from core.queue import OperationQueue

# Operation-specific modules
from operations.copy_operation import CopyOperationHandler
from operations.convert_operation import ConvertOperationHandler
from operations.leftovers import LeftoversManager
from operations.media_operations import get_audio_stream_info, find_dts_audio_track
from operations.verify_operation import VerificationStorage, VerificationHandler

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

# Initialize operation handlers
copy_operation_handler = CopyOperationHandler(config_manager)
convert_operation_handler = ConvertOperationHandler(config_manager)

# Initialize unified queue with multiple operation handlers
unified_queue = OperationQueue(
    queue_file='data/queue.json',
    history_file='data/history.json',
    operation_handlers={
        'copy': copy_operation_handler,
        'convert': convert_operation_handler
    }
)

# Start unified queue processor
unified_queue.start_processor()

# Initialize verification components
verification_storage = VerificationStorage('data/shows_verification.json')
verification_handler = VerificationHandler(verification_storage)


def get_radarr_client():
    """Get configured Radarr client"""
    config = config_manager.config
    return RadarrClient(
        config['radarr_host'],
        config['radarr_port'],
        config['radarr_api_key']
    )


def get_sonarr_client():
    """Get configured Sonarr client"""
    config = config_manager.config
    return SonarrClient(
        config['sonarr_host'],
        config['sonarr_port'],
        config['sonarr_api_key']
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
    if 'sonarr_host' in data:
        updates['sonarr_host'] = data['sonarr_host']
    if 'sonarr_port' in data:
        updates['sonarr_port'] = data['sonarr_port']
    if 'sonarr_api_key' in data and data['sonarr_api_key'] != '***':
        updates['sonarr_api_key'] = data['sonarr_api_key']
    
    config_manager.update(updates)
    
    result = {
        'success': True,
        'ssd_root_folder': config_manager.get('ssd_root_folder', ''),
        'hdd_root_folder': config_manager.get('hdd_root_folder', ''),
        'shows_hdd_root_folder': config_manager.get('shows_hdd_root_folder', '')
    }
    
    # Auto-detect Radarr root folders
    try:
        if updates.get('radarr_host') or updates.get('radarr_port') or updates.get('radarr_api_key'):
            radarr = get_radarr_client()
            root_folders = radarr.get_root_folders()
            result['root_folders'] = root_folders
            
            # Look for SSD and HDD folders
            for rf in root_folders:
                path = rf['path']
                if 'movies_ssd' in path.lower() or path.endswith('/media/movies_ssd'):
                    config_manager.set('ssd_root_folder', path)
                    result['ssd_root_folder'] = path
                elif 'movies_hdd' in path.lower() or path.endswith('/media/movies_hdd'):
                    config_manager.set('hdd_root_folder', path)
                    result['hdd_root_folder'] = path
    except Exception as e:
        logger.warning(f"Could not auto-detect Radarr folders: {str(e)}")
    
    # Auto-detect Sonarr root folders
    try:
        if updates.get('sonarr_host') or updates.get('sonarr_port') or updates.get('sonarr_api_key'):
            sonarr = get_sonarr_client()
            sonarr_root_folders = sonarr.get_root_folders()
            result['sonarr_root_folders'] = sonarr_root_folders
            
            # Look for shows_hdd folder
            for rf in sonarr_root_folders:
                path = rf['path']
                if 'shows_hdd' in path.lower() or path.endswith('/media/shows_hdd'):
                    config_manager.set('shows_hdd_root_folder', path)
                    result['shows_hdd_root_folder'] = path
    except Exception as e:
        logger.warning(f"Could not auto-detect Sonarr folders: {str(e)}")
    
    return jsonify(result)


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


@app.route('/api/movies/dts', methods=['GET'])
def get_dts_movies():
    """Get movies with DTS 5.1 audio from Radarr"""
    try:
        radarr = get_radarr_client()
        all_movies = radarr.get_all_movies()
        
        # Filter movies with DTS and 5.1 in filename (NOT 7.1)
        # Pattern: DTS (case insensitive) AND 5.1
        dts_pattern = re.compile(r'dts.*5\.1|5\.1.*dts', re.IGNORECASE)
        dts_movies = []
        
        for movie in all_movies:
            movie_file = movie.get('movieFile', {})
            if movie_file:
                relative_path = movie_file.get('relativePath', '')
                if dts_pattern.search(relative_path):
                    dts_movies.append(movie)
        
        return jsonify(dts_movies)
    except Exception as e:
        logger.error(f"Error getting DTS movies: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


@app.route('/api/movies/<int:movie_id>/audio-info', methods=['GET'])
def get_movie_audio_info(movie_id):
    """Get audio codec information for a movie using ffprobe"""
    try:
        radarr = get_radarr_client()
        movie = radarr.get_movie(movie_id)
        
        movie_file = movie.get('movieFile', {})
        if not movie_file:
            return jsonify({'error': 'Movie has no file'}), 404
        
        file_path = movie_file.get('path')
        if not file_path:
            return jsonify({'error': 'Movie file path not found'}), 404
        
        # Use common media operations function
        audio_info = get_audio_stream_info(file_path, stream_index=0)
        return jsonify(audio_info)
        
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error getting audio info: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# ROUTES - Queue Management
# ============================================================================

@app.route('/api/queue', methods=['GET'])
def get_queue():
    """Get current unified operation queue"""
    return jsonify(unified_queue.get_queue())


@app.route('/api/queue/add', methods=['POST'])
def add_to_queue():
    """Add movie to unified queue with operation type"""
    data = request.json
    movie = data.get('movie')
    operation_type = data.get('operation_type')  # 'copy' or 'convert'
    
    if not movie:
        return jsonify({'error': 'No movie provided'}), 400
    
    if not operation_type:
        return jsonify({'error': 'No operation_type provided'}), 400
    
    try:
        unified_queue.add_to_queue(movie, operation_type)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error adding to queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/queue/<item_id>', methods=['DELETE'])
def remove_from_queue(item_id):
    """Remove item from unified queue"""
    try:
        unified_queue.remove_from_queue(item_id)
        return jsonify({'success': True})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error removing from queue: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/queue/clear', methods=['POST'])
def clear_queue():
    """Force clear entire unified queue"""
    try:
        count = unified_queue.clear_queue()
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
    """Get unified operation history (last 10 operations)"""
    return jsonify(unified_queue.get_history())


@app.route('/api/convert/retry', methods=['POST'])
def retry_conversion():
    """Retry a failed conversion by finding the file and re-queuing it"""
    try:
        data = request.json
        movie_path = data.get('movie_path')
        
        if not movie_path:
            return jsonify({'error': 'No movie_path provided'}), 400
        
        # Check if file exists
        if not os.path.exists(movie_path):
            return jsonify({'error': f'File not found: {movie_path}'}), 404
        
        # Find DTS track to validate
        logger.info(f"Validating DTS track in: {movie_path}")
        dts_track_index, audio_info = find_dts_audio_track(movie_path)
        
        if dts_track_index is None:
            return jsonify({'error': 'No DTS 5.1(side) audio track found in file'}), 400
        
        logger.info(f"Found DTS track at index {dts_track_index}")
        
        # Try to find movie in Radarr by path
        radarr = get_radarr_client()
        all_movies = radarr.get_all_movies()
        
        movie = None
        for m in all_movies:
            movie_file = m.get('movieFile', {})
            if movie_file.get('path') == movie_path:
                movie = m
                break
        
        if not movie:
            return jsonify({'error': 'Movie not found in Radarr database'}), 404
        
        # Add to queue
        unified_queue.add_to_queue(movie, 'convert')
        
        logger.info(f"Re-queued movie for conversion: {movie['title']}")
        return jsonify({
            'success': True,
            'message': f'Added "{movie["title"]}" to conversion queue',
            'audio_info': audio_info
        })
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error retrying conversion: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


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
        
        # Add to unified queue with 'copy' operation type
        unified_queue.add_to_queue(movie, 'copy')
        
        logger.info(f"Re-added movie {movie['title']} to copy queue from {ssd_path}")
        return jsonify({'success': True, 'message': f'Added {movie["title"]} to queue'})
        
    except (ValueError, FileNotFoundError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error re-copying leftover: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES - TV Shows (Sonarr)
# ============================================================================

@app.route('/api/shows', methods=['GET'])
def get_shows():
    """Get TV shows from shows_hdd root folder"""
    try:
        shows_hdd_root = config_manager.get('shows_hdd_root_folder')
        if not shows_hdd_root:
            return jsonify({'error': 'Shows HDD root folder not configured'}), 400
        
        sonarr = get_sonarr_client()
        series_list = sonarr.filter_series_by_root_folder(shows_hdd_root)
        
        # Enrich with verification data
        for series in series_list:
            series_data = verification_storage.get_series_data(series['id'])
            series['verification_data'] = series_data
        
        return jsonify(series_list)
    except Exception as e:
        logger.error(f"Error getting shows: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


@app.route('/api/shows/<int:series_id>/seasons', methods=['GET'])
def get_series_seasons(series_id):
    """Get seasons with files for a series"""
    try:
        sonarr = get_sonarr_client()
        seasons = sonarr.get_seasons_with_files(series_id)
        
        # Enrich with verification data
        series_data = verification_storage.get_series_data(series_id)
        for season in seasons:
            season_number = season['seasonNumber']
            season_data = series_data['seasons'].get(str(season_number), {
                'season_number': season_number,
                'status': 'unchecked',
                'verified_files': [],
                'broken_files': [],
                'last_checked': None,
                'total_files': season['fileCount']
            })
            season['verification_data'] = season_data
        
        return jsonify(seasons)
    except Exception as e:
        logger.error(f"Error getting seasons: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400


@app.route('/api/shows/<int:series_id>/verify', methods=['POST'])
def verify_series(series_id):
    """Start verification for entire series"""
    try:
        data = request.json or {}
        
        sonarr = get_sonarr_client()
        seasons_data = sonarr.get_seasons_with_files(series_id)
        
        if not seasons_data:
            return jsonify({'error': 'No seasons found for this series'}), 404
        
        verification_handler.start_verification(series_id, None, seasons_data)
        
        return jsonify({
            'success': True,
            'message': 'Verification started for entire series'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting series verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/shows/<int:series_id>/seasons/<int:season_number>/verify', methods=['POST'])
def verify_season(series_id, season_number):
    """Start verification for specific season"""
    try:
        logger.info(f"Verify season endpoint called: series={series_id}, season={season_number}")
        sonarr = get_sonarr_client()
        logger.info("Getting seasons data from Sonarr")
        seasons_data = sonarr.get_seasons_with_files(series_id)
        logger.info(f"Got {len(seasons_data)} seasons")
        
        # Find the specific season
        season_data = next((s for s in seasons_data if s['seasonNumber'] == season_number), None)
        if not season_data:
            logger.error(f"Season {season_number} not found")
            return jsonify({'error': f'Season {season_number} not found'}), 404
        
        logger.info(f"Starting verification for season {season_number}")
        verification_handler.start_verification(series_id, season_number, seasons_data)
        logger.info("Verification started successfully")
        
        return jsonify({
            'success': True,
            'message': f'Verification started for season {season_number}'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting season verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/verification/stop', methods=['POST'])
def stop_verification():
    """Stop active verification"""
    try:
        verification_handler.stop_verification()
        return jsonify({
            'success': True,
            'message': 'Verification stopped'
        })
    except Exception as e:
        logger.error(f"Error stopping verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/verification/status', methods=['GET'])
def get_verification_status():
    """Get current verification status"""
    try:
        status = verification_handler.get_verification_status()
        return jsonify(status if status else {'is_active': False})
    except Exception as e:
        logger.error(f"Error getting verification status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500



# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6970, debug=False)