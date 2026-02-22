"""Common file operations with verification"""
import os
import subprocess
import logging
import xxhash
import shutil

logger = logging.getLogger(__name__)


def calculate_checksum(filepath, progress_callback=None):
    """
    Calculate xxHash3_128 checksum with optional progress reporting
    
    Uses xxHash3_128 for fast, non-cryptographic checksumming.
    ~50-100x faster than SHA256 for large files.
    
    Args:
        filepath: Path to file
        progress_callback: Optional callback function(progress_percent)
    
    Returns:
        str: xxHash3_128 checksum hex string
    """
    hash_func = xxhash.xxh3_128()
    file_size = os.path.getsize(filepath)
    bytes_read = 0
    chunk_size = 8192 * 1024  # 8MB chunks
    
    logger.info(f"Calculating xxHash3_128 checksum for {filepath} ({file_size / 1024 / 1024 / 1024:.2f} GB)")
    
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
    """
    Copy file using rsync with ionice and nice for low-priority I/O
    
    Args:
        src: Source file path
        dst: Destination file path
        progress_callback: Optional callback function(progress_line)
    
    Returns:
        str: Destination file path
    """
    # Ensure destination directory exists with proper permissions
    dst_dir = os.path.dirname(dst)
    os.makedirs(dst_dir, exist_ok=True)
    os.chmod(dst_dir, 0o755)
    
    # rsync with ionice/nice and permission setting
    cmd = [
        'ionice', '-c3',
        'nice', '-n19',
        'rsync', '-a', '--chmod=D0755,F0644', '--info=progress2', '--no-i-r',
        src, dst
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    for line in process.stdout:
        line = line.strip()
        if line:
            logger.info(f"Copy progress: {line}")
            if progress_callback:
                progress_callback(line)
    
    process.wait()
    
    if process.returncode != 0:
        stderr = process.stderr.read()
        raise Exception(f"Copy failed: {stderr}")
    
    return dst


def safe_copy_file(src, dst, use_nice=False, progress_callback=None):
    """
    Safely copy file with checksum verification
    
    Args:
        src: Source file path
        dst: Destination file path
        use_nice: If True, use ionice/nice for low-priority I/O (for HDD)
        progress_callback: Optional callback function(message)
    
    Returns:
        str: Destination file path
    
    Raises:
        Exception: If copy fails or checksum verification fails
    """
    logger.info(f"Safe copy: {src} -> {dst} (nice mode: {use_nice})")
    
    # Step 1: Calculate source checksum
    if progress_callback:
        progress_callback("Calculating source checksum...")
    
    def src_progress(progress):
        if progress_callback:
            progress_callback(f"Source checksum: {progress}")
    
    src_checksum = calculate_checksum(src, src_progress)
    
    # Step 2: Copy file
    if progress_callback:
        progress_callback("Copying file...")
    
    if use_nice:
        copy_file_with_nice(src, dst, progress_callback)
    else:
        # Direct copy for SSD
        dst_dir = os.path.dirname(dst)
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
    
    # Step 3: Verify destination checksum
    if progress_callback:
        progress_callback("Verifying destination checksum...")
    
    def dst_progress(progress):
        if progress_callback:
            progress_callback(f"Destination checksum: {progress}")
    
    dst_checksum = calculate_checksum(dst, dst_progress)
    
    # Step 4: Compare checksums
    logger.info(f"Source checksum: {src_checksum}")
    logger.info(f"Destination checksum: {dst_checksum}")
    
    if src_checksum != dst_checksum:
        logger.error("Checksum mismatch! Removing corrupted file.")
        os.remove(dst)
        raise Exception("Checksum verification failed")
    
    logger.info("Checksum verification passed")
    return dst


def safe_replace_file(original_path, new_path, use_nice=False):
    """
    Safely replace original file with new one using checksum verification
    
    Creates backup, copies with verification, restores on failure
    
    Args:
        original_path: Path to original file to replace
        new_path: Path to new file (will be copied to original_path)
        use_nice: If True, use ionice/nice for low-priority I/O (for HDD)
    
    Raises:
        Exception: If replacement fails or checksum verification fails
    """
    # Get original permissions
    try:
        stat_info = os.stat(original_path)
        original_mode = stat_info.st_mode
    except:
        original_mode = 0o644
    
    logger.info(f"Replacing file with safe copy (nice mode: {use_nice})")
    
    # Step 1: Calculate checksum of new file
    logger.info("Calculating checksum of new file...")
    new_checksum = calculate_checksum(new_path)
    logger.info(f"New file checksum: {new_checksum}")
    
    # Step 2: Create backup
    backup_path = original_path + '.backup'
    logger.info(f"Creating backup: {backup_path}")
    
    try:
        # Rename original to backup
        os.rename(original_path, backup_path)
        
        # Step 3: Copy new file to original location
        if use_nice:
            logger.info("Using ionice/nice for HDD copy...")
            copy_file_with_nice(new_path, original_path)
        else:
            logger.info("Direct copy for SSD...")
            shutil.copy2(new_path, original_path)
        
        # Step 4: Verify checksum of copied file
        logger.info("Verifying checksum of copied file...")
        copied_checksum = calculate_checksum(original_path)
        logger.info(f"Copied file checksum: {copied_checksum}")
        
        if new_checksum != copied_checksum:
            logger.error("Checksum mismatch! Restoring backup.")
            os.remove(original_path)
            os.rename(backup_path, original_path)
            raise Exception("Checksum verification failed during file replacement")
        
        logger.info("Checksum verification passed")
        
        # Step 5: Remove backup
        logger.info("Removing backup file...")
        os.remove(backup_path)
        
        # Restore permissions
        try:
            os.chmod(original_path, original_mode)
        except:
            pass
        
        logger.info("File replaced successfully")
        
    except Exception as e:
        # Restore backup if it exists
        if os.path.exists(backup_path):
            logger.error(f"Error during replacement: {e}. Restoring backup...")
            if os.path.exists(original_path):
                os.remove(original_path)
            os.rename(backup_path, original_path)
        raise