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
from core.queue import OperationQueue

# Operation-specific modules
from operations.copy_operation import CopyOperationHandler
from operations.convert_operation import ConvertOperationHandler
from operations.leftovers import LeftoversManager
from operations.media_operations import get_audio_stream_info, find_dts_audio_track
from operations.integrity_checker import (
    IntegrityStorage,
    IntegrityScanner,
    IntegrityVerifier,
    IntegrityReChecker
)

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

# Initialize integrity checker components
integrity_storage = IntegrityStorage('data/media_integrity.json')
integrity_scanner = IntegrityScanner(integrity_storage)
integrity_verifier = IntegrityVerifier(integrity_storage)
integrity_rechecker = IntegrityReChecker(integrity_storage)


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
    
    result = {
        'success': True,
        'ssd_root_folder': config_manager.get('ssd_root_folder', ''),
        'hdd_root_folder': config_manager.get('hdd_root_folder', '')
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
        pass
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
# ROUTES - Media Integrity Checker
# ============================================================================

@app.route('/api/integrity/config', methods=['GET'])
def get_integrity_config():
    """Get integrity checker configuration"""
    try:
        config = integrity_storage.get_config()
        return jsonify(config)
    except Exception as e:
        logger.error(f"Error getting integrity config: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/config', methods=['POST'])
def update_integrity_config():
    """Update integrity checker configuration"""
    try:
        data = request.json
        updates = {}
        
        if 'watch_directories' in data:
            updates['watch_directories'] = data['watch_directories']
        if 'test_directory' in data:
            updates['test_directory'] = data['test_directory']
        
        integrity_storage.update_config(updates)
        
        return jsonify({
            'success': True,
            'config': integrity_storage.get_config()
        })
    except Exception as e:
        logger.error(f"Error updating integrity config: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/scan/start', methods=['POST'])
def start_integrity_scan():
    """Start integrity scan"""
    try:
        integrity_scanner.start_scan()
        return jsonify({
            'success': True,
            'message': 'Scan started'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting scan: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/scan/stop', methods=['POST'])
def stop_integrity_scan():
    """Stop integrity scan"""
    try:
        integrity_scanner.stop_scan()
        return jsonify({
            'success': True,
            'message': 'Scan stopped'
        })
    except Exception as e:
        logger.error(f"Error stopping scan: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/scan/status', methods=['GET'])
def get_integrity_scan_status():
    """Get integrity scan status"""
    try:
        progress = integrity_storage.get_progress('scan')
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting scan status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/verify/start', methods=['POST'])
def start_integrity_verify():
    """Start integrity verification"""
    try:
        integrity_verifier.start_verify()
        return jsonify({
            'success': True,
            'message': 'Verification started'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/verify/stop', methods=['POST'])
def stop_integrity_verify():
    """Stop integrity verification"""
    try:
        integrity_verifier.stop_verify()
        return jsonify({
            'success': True,
            'message': 'Verification stopped'
        })
    except Exception as e:
        logger.error(f"Error stopping verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/verify/resume', methods=['POST'])
def resume_integrity_verify():
    """Resume integrity verification from first incomplete"""
    try:
        integrity_verifier.start_verify(resume=True)
        return jsonify({
            'success': True,
            'message': 'Verification resumed'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error resuming verification: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/verify/status', methods=['GET'])
def get_integrity_verify_status():
    """Get integrity verification status"""
    try:
        progress = integrity_storage.get_progress('verify')
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting verification status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/recheck/start', methods=['POST'])
def start_integrity_recheck():
    """Start integrity recheck"""
    try:
        integrity_rechecker.start_recheck()
        return jsonify({
            'success': True,
            'message': 'Recheck started'
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting recheck: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/recheck/stop', methods=['POST'])
def stop_integrity_recheck():
    """Stop integrity recheck"""
    try:
        integrity_rechecker.stop_recheck()
        return jsonify({
            'success': True,
            'message': 'Recheck stopped'
        })
    except Exception as e:
        logger.error(f"Error stopping recheck: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/recheck/status', methods=['GET'])
def get_integrity_recheck_status():
    """Get integrity recheck status"""
    try:
        progress = integrity_storage.get_progress('recheck')
        return jsonify(progress)
    except Exception as e:
        logger.error(f"Error getting recheck status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/files', methods=['GET'])
def get_integrity_files():
    """Get all integrity files"""
    try:
        files = integrity_storage.get_all_files()
        return jsonify(files)
    except Exception as e:
        logger.error(f"Error getting files: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/files/broken', methods=['GET'])
def get_integrity_broken_files():
    """Get broken files"""
    try:
        all_files = integrity_storage.get_all_files()
        broken = {
            path: data for path, data in all_files.items()
            if data.get('verify_status') in ['broken', 'error']
        }
        return jsonify(broken)
    except Exception as e:
        logger.error(f"Error getting broken files: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/files/changed', methods=['GET'])
def get_integrity_changed_files():
    """Get files with changed checksums"""
    try:
        all_files = integrity_storage.get_all_files()
        changed = {
            path: data for path, data in all_files.items()
            if data.get('checksum_status') == 'changed'
        }
        return jsonify(changed)
    except Exception as e:
        logger.error(f"Error getting changed files: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/stats', methods=['GET'])
def get_integrity_stats():
    """Get integrity statistics"""
    try:
        all_files = integrity_storage.get_all_files()
        
        stats = {
            'total': len(all_files),
            'verified_ok': 0,
            'broken': 0,
            'changed': 0,
            'pending': 0
        }
        
        for data in all_files.values():
            verify_status = data.get('verify_status')
            checksum_status = data.get('checksum_status')
            
            if verify_status in ['broken', 'error']:
                stats['broken'] += 1
            elif checksum_status == 'changed':
                stats['changed'] += 1
            elif verify_status == 'ok' and checksum_status in ['verified', 'ok']:
                stats['verified_ok'] += 1
            else:
                stats['pending'] += 1
        
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/reset', methods=['POST'])
def reset_integrity_data():
    """Reset all integrity data"""
    try:
        integrity_storage.reset_all()
        return jsonify({
            'success': True,
            'message': 'All integrity data reset'
        })
    except Exception as e:
        logger.error(f"Error resetting data: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/clear-reports', methods=['POST'])
def clear_integrity_reports():
    """Clear integrity reports (broken/changed statuses)"""
    try:
        integrity_storage.clear_reports()
        return jsonify({
            'success': True,
            'message': 'Reports cleared'
        })
    except Exception as e:
        logger.error(f"Error clearing reports: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/reset-broken', methods=['POST'])
def reset_broken_files():
    """Reset broken files to pending status"""
    try:
        count = integrity_storage.reset_broken_files()
        
        return jsonify({
            'success': True,
            'message': f'Reset {count} broken file(s) to pending',
            'count': count
        })
    except Exception as e:
        logger.error(f"Error resetting broken files: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrity/export-issues', methods=['GET'])
def export_integrity_issues():
    """Export all broken and changed files to text format"""
    try:
        all_files = integrity_storage.get_all_files()
        
        # Collect broken files
        broken_files = {
            path: data for path, data in all_files.items()
            if data.get('verify_status') in ['broken', 'error']
        }
        
        # Collect changed files
        changed_files = {
            path: data for path, data in all_files.items()
            if data.get('checksum_status') == 'changed'
        }
        
        # Format as text
        lines = []
        lines.append("=" * 80)
        lines.append("MEDIA INTEGRITY ISSUES REPORT")
        lines.append("=" * 80)
        lines.append("")
        
        if broken_files:
            lines.append(f"BROKEN FILES ({len(broken_files)}):")
            lines.append("-" * 80)
            for path, data in broken_files.items():
                lines.append(f"\nFile: {path}")
                lines.append(f"Error: {data.get('error', 'Unknown error')}")
                if data.get('warning'):
                    lines.append(f"Warning: {data.get('warning')}")
                lines.append("")
        
        if changed_files:
            lines.append("")
            lines.append(f"CHANGED CHECKSUMS ({len(changed_files)}):")
            lines.append("-" * 80)
            for path, data in changed_files.items():
                lines.append(f"\nFile: {path}")
                lines.append(f"Error: {data.get('error', 'Checksum mismatch')}")
                lines.append("")
        
        if not broken_files and not changed_files:
            lines.append("No issues found!")
        
        lines.append("")
        lines.append("=" * 80)
        
        text_content = "\n".join(lines)
        
        # Return as plain text with proper headers for download
        from flask import Response
        return Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': 'attachment; filename=integrity_issues.txt'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting issues: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6970, debug=False)