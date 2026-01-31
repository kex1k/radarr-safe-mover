"""Unified queue management for multiple operation types"""
import json
import os
import threading
import time
import logging
from datetime import datetime
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class OperationQueue:
    """Unified queue for processing multiple operation types on movies"""
    
    def __init__(self, queue_file, history_file, operation_handlers):
        """
        Initialize unified queue with multiple operation handlers
        
        Args:
            queue_file: Path to queue JSON file
            history_file: Path to history JSON file
            operation_handlers: Dict of {operation_type: handler_instance}
                               e.g., {'copy': CopyHandler(), 'convert': ConvertHandler()}
        """
        self.queue_file = queue_file
        self.history_file = history_file
        self.operation_handlers = operation_handlers  # Dict of handlers by type
        
        self.queue = []
        self.history = []
        self.current_item = None
        self.lock = threading.Lock()
        
        self._ensure_data_dir()
        self.load_queue()
        self.load_history()
    
    def _ensure_data_dir(self):
        """Ensure data directory exists"""
        os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
    
    def load_queue(self):
        """Load queue from file"""
        if os.path.exists(self.queue_file):
            with open(self.queue_file, 'r') as f:
                self.queue = json.load(f)
        return self.queue
    
    def save_queue(self):
        """Save queue to file"""
        with open(self.queue_file, 'w') as f:
            json.dump(self.queue, f, indent=2)
    
    def load_history(self):
        """Load history from file"""
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                self.history = json.load(f)
        return self.history
    
    def save_history(self):
        """Save history to file"""
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f, indent=2)
    
    def add_to_history(self, movie_title, operation_type, success, error_message=None):
        """Add operation to history (max 10 items)"""
        history_item = {
            'movie_title': movie_title,
            'operation_type': operation_type,
            'success': success,
            'timestamp': datetime.now().isoformat(),
            'error': error_message if not success else None
        }
        
        # Add to beginning (most recent first)
        self.history.insert(0, history_item)
        
        # Keep only last 10 items
        self.history = self.history[:10]
        
        self.save_history()
        logger.info(f"Added to history: {movie_title} ({operation_type}) - {'Success' if success else 'Failed'}")
    
    def add_to_queue(self, movie, operation_type):
        """
        Add movie to unified queue with specified operation type
        
        Args:
            movie: Movie data from Radarr
            operation_type: Type of operation ('copy', 'convert', etc.)
        """
        # Validate operation type
        if operation_type not in self.operation_handlers:
            raise ValueError(f"Unknown operation type: {operation_type}")
        
        with self.lock:
            # Check if already in queue
            if any(item['movie']['id'] == movie['id'] for item in self.queue):
                raise ValueError('Movie already in queue')
            
            queue_item = {
                'id': f"{movie['id']}_{operation_type}_{datetime.now().timestamp()}",
                'movie': movie,
                'operation_type': operation_type,
                'status': 'pending',
                'progress': 'Waiting in queue...',
                'added_at': datetime.now().isoformat()
            }
            
            self.queue.append(queue_item)
            self.save_queue()
            logger.info(f"Added to queue: {movie['title']} (operation: {operation_type})")
            return queue_item
    
    def remove_from_queue(self, item_id):
        """Remove item from queue"""
        with self.lock:
            # Don't allow removing currently processing item
            if self.current_item and self.current_item['id'] == item_id:
                raise ValueError('Cannot remove item currently being processed')
            
            self.queue = [item for item in self.queue if item['id'] != item_id]
            self.save_queue()
    
    def clear_queue(self):
        """Force clear entire queue"""
        with self.lock:
            queue_count = len(self.queue)
            self.queue = []
            self.current_item = None
            self.save_queue()
            logger.warning(f"Unified queue forcefully cleared. Removed {queue_count} items.")
            return queue_count
    
    def get_queue(self):
        """Get current queue"""
        return self.queue
    
    def get_history(self):
        """Get operation history"""
        return self.history
    
    def process_queue(self):
        """Background thread to process unified queue"""
        logger.info("Unified queue processor started")
        
        while True:
            # Check if there's work to do
            with self.lock:
                if not self.queue or self.current_item:
                    pass
                else:
                    # Get next item from queue
                    self.current_item = self.queue[0]
                    self.current_item['status'] = 'processing'
                    self.current_item['started_at'] = datetime.now().isoformat()
                    self.save_queue()
            
            # Sleep if no work
            if not self.current_item:
                time.sleep(1)
                continue
            
            # Process item with appropriate handler
            movie = self.current_item['movie']
            movie_title = movie['title']
            operation_type = self.current_item['operation_type']
            
            # Get appropriate handler
            handler = self.operation_handlers.get(operation_type)
            if not handler:
                logger.error(f"No handler for operation type: {operation_type}")
                with self.lock:
                    self.current_item = None
                continue
            
            try:
                logger.info(f"Processing: {movie_title} (operation: {operation_type})")
                
                # Call operation handler
                handler.execute(
                    movie=movie,
                    update_status=self._update_status,
                    update_progress=self._update_progress
                )
                
                # Mark as completed
                logger.info(f"Successfully completed: {movie_title} ({operation_type})")
                with self.lock:
                    self.current_item['status'] = 'completed'
                    self.current_item['progress'] = 'Completed successfully'
                    self.current_item['completed_at'] = datetime.now().isoformat()
                    
                    # Add to history
                    self.add_to_history(movie_title, operation_type, success=True)
                    
                    # Remove from queue
                    item_id = self.current_item['id']
                    self.queue = [item for item in self.queue if item['id'] != item_id]
                    self.save_queue()
                    
                    logger.info(f"Removed completed item from queue. Remaining: {len(self.queue)}")
                    self.current_item = None
                    
            except Exception as e:
                logger.error(f"Error processing: {movie_title} ({operation_type}) - {str(e)}", exc_info=True)
                with self.lock:
                    if self.current_item:
                        error_msg = str(e)
                        
                        self.current_item['status'] = 'failed'
                        self.current_item['progress'] = f'Error: {error_msg}'
                        self.current_item['failed_at'] = datetime.now().isoformat()
                        
                        # Add to history
                        self.add_to_history(movie_title, operation_type, success=False, error_message=error_msg)
                        
                        # Remove from queue (one attempt only)
                        item_id = self.current_item['id']
                        self.queue = [item for item in self.queue if item['id'] != item_id]
                        self.save_queue()
                        
                        logger.info(f"Removed failed item from queue. Remaining: {len(self.queue)}")
                        self.current_item = None
    
    def _update_status(self, status):
        """Update current item status"""
        with self.lock:
            if self.current_item:
                self.current_item['status'] = status
                self.save_queue()
    
    def _update_progress(self, progress):
        """Update current item progress"""
        with self.lock:
            if self.current_item:
                self.current_item['progress'] = progress
                self.save_queue()
    
    def start_processor(self):
        """Start background queue processor"""
        processor_thread = threading.Thread(target=self.process_queue, daemon=True)
        processor_thread.start()
        logger.info("Unified queue processor thread started")


class OperationHandler(ABC):
    """Abstract base class for operation handlers"""
    
    @abstractmethod
    def execute(self, movie, update_status, update_progress):
        """
        Execute operation on movie
        
        Args:
            movie: Movie data from Radarr
            update_status: Callback to update status (e.g., 'copying', 'verifying')
            update_progress: Callback to update progress text
        
        Raises:
            Exception: If operation fails
        """
        pass