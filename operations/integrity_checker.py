"""Media Integrity Checker - проверка целостности медиа-файлов на HDD"""
import os
import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class IntegrityStorage:
    """Управление хранением данных проверки целостности"""
    
    def __init__(self, storage_file='data/media_integrity.json'):
        self.storage_file = storage_file
        self._ensure_data_dir()
        self.data = self.load()
        self.lock = threading.Lock()
    
    def _ensure_data_dir(self):
        """Создать директорию для данных"""
        os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
    
    def load(self):
        """Загрузить данные из файла"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading integrity data: {e}", exc_info=True)
                return self._default_data()
        logger.info(f"Integrity storage file does not exist, creating: {self.storage_file}")
        return self._default_data()
    
    def _default_data(self):
        """Структура данных по умолчанию"""
        return {
            'config': {
                'watch_directories': ['/shows_hdd', '/movies_hdd'],
                'checksum_algorithm': 'xxhash3_128',
                'test_directory': None
            },
            'progress': {
                'scan': {'status': 'idle'},
                'verify': {'status': 'idle'},
                'recheck': {'status': 'idle'}
            },
            'files': {}
        }
    
    def save(self):
        """Сохранить данные в файл"""
        try:
            with self.lock:
                with open(self.storage_file, 'w') as f:
                    json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving integrity data: {e}", exc_info=True)
            raise
    
    def get_config(self):
        """Получить конфигурацию"""
        return self.data.get('config', {})
    
    def update_config(self, updates):
        """Обновить конфигурацию"""
        self.data['config'].update(updates)
        self.save()
    
    def get_file(self, path):
        """Получить данные файла"""
        return self.data['files'].get(path)
    
    def update_file(self, path, updates):
        """Обновить данные файла"""
        if path not in self.data['files']:
            self.data['files'][path] = {}
        self.data['files'][path].update(updates)
        self.save()
    
    def get_all_files(self):
        """Получить все файлы"""
        return self.data['files']
    
    def get_progress(self, pass_name):
        """Получить прогресс прохода"""
        return self.data['progress'].get(pass_name, {})
    
    def update_progress(self, pass_name, updates):
        """Обновить прогресс прохода"""
        if pass_name not in self.data['progress']:
            self.data['progress'][pass_name] = {}
        self.data['progress'][pass_name].update(updates)
        self.save()
    
    def reset_all(self):
        """Полная очистка всех данных"""
        logger.warning("Resetting all integrity data")
        self.data = self._default_data()
        self.save()
    
    def clear_reports(self):
        """Очистить отчёты (broken/changed статусы)"""
        logger.info("Clearing integrity reports")
        for path, file_data in self.data['files'].items():
            if file_data.get('verify_status') in ['broken', 'error']:
                file_data['verify_status'] = 'pending'
                file_data['error'] = None
            if file_data.get('checksum_status') == 'changed':
                file_data['checksum_status'] = 'verified'
        self.save()


class IntegrityScanner:
    """Проход 1: Быстрое сканирование директорий"""
    
    VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.ts'}
    
    def __init__(self, storage):
        self.storage = storage
        self.stop_flag = threading.Event()
        self.scan_thread = None
    
    def _is_video(self, entry):
        """Проверить что файл - видео"""
        return entry.is_file() and Path(entry.path).suffix.lower() in self.VIDEO_EXTENSIONS
    
    def _make_fingerprint(self, entry):
        """Создать fingerprint файла: size:mtime"""
        stat = entry.stat()
        return f"{stat.st_size}:{stat.st_mtime}"
    
    def _walk_fast(self, directory):
        """Быстрый обход директории"""
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if self.stop_flag.is_set():
                        break
                    
                    if entry.is_dir(follow_symlinks=False):
                        # Рекурсивно обходим поддиректории
                        yield from self._walk_fast(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield entry
        except PermissionError:
            logger.warning(f"Permission denied: {directory}")
        except Exception as e:
            logger.error(f"Error scanning {directory}: {e}")
    
    def scan(self, directories):
        """Быстрое сканирование директорий"""
        files_found = {}
        total_size = 0
        
        for directory in directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory not found: {directory}")
                continue
            
            logger.info(f"Scanning directory: {directory}")
            
            for entry in self._walk_fast(directory):
                if self.stop_flag.is_set():
                    break
                
                if self._is_video(entry):
                    stat = entry.stat()
                    files_found[entry.path] = {
                        'path': entry.path,
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'fingerprint': self._make_fingerprint(entry),
                        'scan_status': 'indexed',
                        'verify_status': 'pending',
                        'checksum_status': 'pending'
                    }
                    total_size += stat.st_size
        
        logger.info(f"Scan complete: {len(files_found)} files, {total_size / 1024**3:.2f} GB")
        return files_found
    
    def start_scan(self):
        """Запустить сканирование в фоновом потоке"""
        if self.scan_thread and self.scan_thread.is_alive():
            raise ValueError("Scan already in progress")
        
        self.stop_flag.clear()
        
        def scan_worker():
            try:
                config = self.storage.get_config()
                
                # Определить директории для сканирования
                if config.get('test_directory'):
                    directories = [config['test_directory']]
                else:
                    directories = config.get('watch_directories', [])
                
                # Обновить статус
                self.storage.update_progress('scan', {
                    'status': 'in_progress',
                    'started': datetime.now().isoformat()
                })
                
                # Сканировать
                files_found = self.scan(directories)
                
                # Обновить базу файлов
                for path, file_data in files_found.items():
                    existing = self.storage.get_file(path)
                    if existing:
                        # Файл уже есть - обновить только если изменился
                        if existing.get('fingerprint') != file_data['fingerprint']:
                            # Файл изменился - сбросить статусы
                            file_data['verify_status'] = 'pending'
                            file_data['checksum_status'] = 'pending'
                            file_data['checksum'] = None
                            file_data['error'] = None
                        else:
                            # Файл не изменился - сохранить старые данные
                            file_data.update({
                                'verify_status': existing.get('verify_status', 'pending'),
                                'checksum_status': existing.get('checksum_status', 'pending'),
                                'checksum': existing.get('checksum'),
                                'verified_at': existing.get('verified_at'),
                                'last_checked': existing.get('last_checked'),
                                'media_info': existing.get('media_info')
                            })
                    
                    self.storage.update_file(path, file_data)
                
                # Завершить
                self.storage.update_progress('scan', {
                    'status': 'completed',
                    'completed': datetime.now().isoformat(),
                    'total_files': len(files_found)
                })
                
            except Exception as e:
                logger.error(f"Error in scan worker: {e}", exc_info=True)
                self.storage.update_progress('scan', {
                    'status': 'error',
                    'error': str(e)
                })
        
        self.scan_thread = threading.Thread(target=scan_worker, daemon=True)
        self.scan_thread.start()
    
    def stop_scan(self):
        """Остановить сканирование"""
        self.stop_flag.set()
        if self.scan_thread:
            self.scan_thread.join(timeout=5)


class IntegrityVerifier:
    """Проход 2: Проверка файлов через ffprobe + checksums"""
    
    def __init__(self, storage):
        self.storage = storage
        self.stop_flag = threading.Event()
        self.verify_thread = None
    
    def _is_critical_error(self, error_msg):
        """Проверить является ли ошибка критической (реальное повреждение)"""
        # Паттерны ложных срабатываний (игнорируем)
        false_positive_patterns = [
            'non monotonically increasing dts',  # проблема timestamps, не повреждение
            'Duplicate POC in a sequence',       # нестандартный порядок кадров HEVC
            'Application provided invalid',      # связано с DTS
        ]
        
        # Паттерны реальных повреждений (критические)
        critical_patterns = [
            'moov atom not found',               # сломанная структура MP4/MOV
            'Invalid NAL unit size',             # битый H.264/H.265 поток
            'Truncated',                         # обрезанный файл
            'End of file',                       # неожиданный конец файла
            'No such file or directory',         # файл не найден
            'Permission denied',                 # нет доступа
            'Input/output error',                # ошибка чтения с диска
        ]
        
        error_lower = error_msg.lower()
        
        # Проверяем критические паттерны
        for pattern in critical_patterns:
            if pattern.lower() in error_lower:
                return True
        
        # Проверяем ложные срабатывания
        for pattern in false_positive_patterns:
            if pattern.lower() in error_lower:
                return False
        
        # Если есть "Error" но не в списке ложных - считаем критической
        # Но только если это не просто "Error submitting packet" после DTS ошибок
        if 'error submitting packet to decoder' in error_lower:
            # Это следствие DTS/POC ошибок, игнорируем
            return False
        
        if 'error processing packet in decoder' in error_lower:
            # Это тоже следствие DTS/POC ошибок
            return False
        
        # Если есть другие ошибки - считаем критическими
        if 'error' in error_lower and 'warning' not in error_lower:
            return True
        
        return False
    
    def _ffmpeg_check(self, filepath):
        """Полная проверка через ffmpeg с декодированием видео"""
        try:
            # Используем ionice + nice для минимального приоритета
            cmd = [
                'ionice', '-c3',  # idle class
                'nice', '-n19',   # lowest CPU priority
                'ffmpeg',
                '-v', 'error',
                '-xerror',  # exit on error
                '-err_detect', 'explode',  # aggressive error detection
                '-skip_frame', 'nokey',  # check only keyframes (faster)
                '-i', filepath,
                '-map', '0:v',  # only video stream
                '-f', 'null',   # decode but don't write
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300  # 5 minutes timeout for large files
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.decode('utf-8', errors='ignore')
                
                # Фильтруем ошибки - проверяем только критические
                if self._is_critical_error(error_msg):
                    return False, error_msg
                else:
                    # Некритическая ошибка (DTS/POC) - считаем файл OK
                    logger.debug(f"Non-critical ffmpeg errors ignored for {filepath}: {error_msg[:200]}")
                    return True, None
            
            return True, None
                
        except subprocess.TimeoutExpired:
            return False, "ffmpeg timeout (>5 min)"
        except Exception as e:
            return False, str(e)
    
    def _get_duration(self, filepath):
        """Получить duration через ffprobe (быстро)"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'json',
                filepath
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    return float(data.get('format', {}).get('duration', 0))
                except:
                    pass
            return 0
        except:
            return 0
    
    def _calculate_xxhash(self, filepath):
        """Вычислить xxHash с ionice/nice"""
        try:
            import xxhash
        except ImportError:
            logger.error("xxhash not installed, falling back to SHA256")
            import hashlib
            h = hashlib.sha256()
            algorithm = 'sha256'
        else:
            h = xxhash.xxh3_128()
            algorithm = 'xxhash3_128'
        
        chunk_size = 8 * 1024 * 1024  # 8MB chunks
        
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                if self.stop_flag.is_set():
                    return None, None
                h.update(chunk)
        
        return h.hexdigest(), algorithm
    
    def verify_file(self, file_path):
        """Проверить один файл"""
        start_time = time.time()
        
        # 1. ffmpeg check (полная проверка с декодированием)
        is_valid, error = self._ffmpeg_check(file_path)
        
        if not is_valid:
            return {
                'verify_status': 'broken',
                'error': f"ffmpeg: {error}",
                'verified_at': datetime.now().isoformat()
            }
        
        # 2. Get duration (быстро через ffprobe)
        duration = self._get_duration(file_path)
        
        # 3. Calculate checksum (с ionice/nice через subprocess)
        checksum, algorithm = self._calculate_xxhash(file_path)
        
        if checksum is None:
            # Остановлено
            return None
        
        verify_duration = time.time() - start_time
        
        return {
            'verify_status': 'ok',
            'checksum': checksum,
            'checksum_status': 'verified',
            'verified_at': datetime.now().isoformat(),
            'media_info': {
                'duration': duration
            },
            'verify_duration': verify_duration
        }
    
    def start_verify(self, resume=False):
        """Запустить проверку в фоновом потоке"""
        if self.verify_thread and self.verify_thread.is_alive():
            raise ValueError("Verification already in progress")
        
        self.stop_flag.clear()
        
        def verify_worker():
            try:
                # Получить список файлов для проверки
                all_files = self.storage.get_all_files()
                files_to_verify = [
                    (path, data) for path, data in all_files.items()
                    if data.get('verify_status') == 'pending'
                ]
                
                if not files_to_verify:
                    logger.info("No files to verify")
                    self.storage.update_progress('verify', {
                        'status': 'completed',
                        'message': 'No files to verify'
                    })
                    return
                
                # Обновить статус
                self.storage.update_progress('verify', {
                    'status': 'in_progress',
                    'started': datetime.now().isoformat(),
                    'total_files': len(files_to_verify),
                    'current_index': 0
                })
                
                # Проверить файлы
                for i, (path, file_data) in enumerate(files_to_verify):
                    if self.stop_flag.is_set():
                        logger.info("Verification stopped")
                        self.storage.update_progress('verify', {
                            'status': 'paused',
                            'current_index': i
                        })
                        return
                    
                    logger.info(f"Verifying [{i+1}/{len(files_to_verify)}]: {path}")
                    
                    # Обновить прогресс
                    self.storage.update_progress('verify', {
                        'current_file': path,
                        'current_index': i + 1
                    })
                    
                    # Проверить файл
                    result = self.verify_file(path)
                    
                    if result is None:
                        # Остановлено
                        break
                    
                    # Обновить данные файла
                    self.storage.update_file(path, result)
                
                # Завершить
                self.storage.update_progress('verify', {
                    'status': 'completed',
                    'completed': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error in verify worker: {e}", exc_info=True)
                self.storage.update_progress('verify', {
                    'status': 'error',
                    'error': str(e)
                })
        
        self.verify_thread = threading.Thread(target=verify_worker, daemon=True)
        self.verify_thread.start()
    
    def stop_verify(self):
        """Остановить проверку"""
        self.stop_flag.set()
        if self.verify_thread:
            self.verify_thread.join(timeout=5)


class IntegrityReChecker:
    """Проход 3: Перепроверка checksums"""
    
    def __init__(self, storage):
        self.storage = storage
        self.stop_flag = threading.Event()
        self.recheck_thread = None
    
    def _calculate_xxhash(self, filepath):
        """Вычислить xxHash"""
        try:
            import xxhash
            h = xxhash.xxh3_128()
        except ImportError:
            import hashlib
            h = hashlib.sha256()
        
        chunk_size = 8 * 1024 * 1024
        
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                if self.stop_flag.is_set():
                    return None
                h.update(chunk)
        
        return h.hexdigest()
    
    def _check_file_changed(self, file_path, stored_data):
        """Проверить изменился ли файл по fingerprint"""
        try:
            stat = os.stat(file_path)
            current_fingerprint = f"{stat.st_size}:{stat.st_mtime}"
            stored_fingerprint = stored_data.get('fingerprint')
            return current_fingerprint != stored_fingerprint, current_fingerprint
        except:
            return True, None
    
    def start_recheck(self):
        """Запустить перепроверку в фоновом потоке"""
        if self.recheck_thread and self.recheck_thread.is_alive():
            raise ValueError("Recheck already in progress")
        
        self.stop_flag.clear()
        
        def recheck_worker():
            try:
                # Получить файлы с checksums
                all_files = self.storage.get_all_files()
                files_to_check = [
                    (path, data) for path, data in all_files.items()
                    if data.get('checksum_status') in ['verified', 'ok']
                ]
                
                if not files_to_check:
                    logger.info("No files to recheck")
                    self.storage.update_progress('recheck', {
                        'status': 'completed',
                        'message': 'No files to recheck'
                    })
                    return
                
                # Обновить статус
                self.storage.update_progress('recheck', {
                    'status': 'in_progress',
                    'started': datetime.now().isoformat(),
                    'total_files': len(files_to_check),
                    'current_index': 0
                })
                
                # Перепроверить файлы
                for i, (path, file_data) in enumerate(files_to_check):
                    if self.stop_flag.is_set():
                        logger.info("Recheck stopped")
                        self.storage.update_progress('recheck', {
                            'status': 'paused',
                            'current_index': i
                        })
                        return
                    
                    logger.info(f"Rechecking [{i+1}/{len(files_to_check)}]: {path}")
                    
                    # Обновить прогресс
                    self.storage.update_progress('recheck', {
                        'current_file': path,
                        'current_index': i + 1
                    })
                    
                    # Проверить что файл не изменился
                    changed, new_fingerprint = self._check_file_changed(path, file_data)
                    
                    if changed:
                        logger.info(f"File changed, resetting: {path}")
                        self.storage.update_file(path, {
                            'fingerprint': new_fingerprint,
                            'verify_status': 'pending',
                            'checksum_status': 'pending',
                            'checksum': None,
                            'error': None
                        })
                        continue
                    
                    # Пересчитать checksum
                    current_checksum = self._calculate_xxhash(path)
                    
                    if current_checksum is None:
                        # Остановлено
                        break
                    
                    stored_checksum = file_data.get('checksum')
                    
                    if current_checksum == stored_checksum:
                        self.storage.update_file(path, {
                            'checksum_status': 'ok',
                            'last_checked': datetime.now().isoformat()
                        })
                    else:
                        logger.warning(f"Checksum mismatch: {path}")
                        self.storage.update_file(path, {
                            'checksum_status': 'changed',
                            'error': 'Checksum mismatch - possible corruption',
                            'last_checked': datetime.now().isoformat()
                        })
                
                # Завершить
                self.storage.update_progress('recheck', {
                    'status': 'completed',
                    'completed': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error in recheck worker: {e}", exc_info=True)
                self.storage.update_progress('recheck', {
                    'status': 'error',
                    'error': str(e)
                })
        
        self.recheck_thread = threading.Thread(target=recheck_worker, daemon=True)
        self.recheck_thread.start()
    
    def stop_recheck(self):
        """Остановить перепроверку"""
        self.stop_flag.set()
        if self.recheck_thread:
            self.recheck_thread.join(timeout=5)