#!/usr/bin/env python3
"""
Script to check media files for HDR and Dolby Vision support
Recursively scans directory and categorizes files into:
- DV + HDR10
- HDR10  
- HDR
- SDR
"""

import os
import sys
import json
import subprocess
import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Supported video extensions
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.ts', '.mov', '.webm'}

def get_video_files(directory: str) -> List[str]:
    """Recursively find all video files in directory"""
    video_files = []
    directory_path = Path(directory)
    
    if not directory_path.exists():
        print(f"Error: Directory {directory} does not exist")
        sys.exit(1)
    
    for file_path in directory_path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
            # Skip macOS metadata files
            if not file_path.name.startswith('._'):
                video_files.append(str(file_path))
    
    return sorted(video_files)

def get_stream_info(filepath: str) -> Optional[Dict]:
    """Get stream information using ffprobe"""
    try:
        # Get basic stream info including color metadata
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,codec_tag_string,profile,color_space,color_primaries,color_transfer',
            '-of', 'json', filepath
        ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True
        )
        
        stream_info = {}
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('streams'):
                stream_info = data['streams'][0]
        
        # Get side_data_type separately (this is the key for DV detection!)
        cmd_side_data = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream_side_data=side_data_type',
            '-of', 'json', filepath
        ]
        
        result_side_data = subprocess.run(
            cmd_side_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True
        )
        
        if result_side_data.returncode == 0:
            side_data = json.loads(result_side_data.stdout)
            # Extract side_data_list from the response
            if side_data.get('streams') and side_data['streams'][0].get('side_data_list'):
                stream_info['side_data_list'] = side_data['streams'][0]['side_data_list']
        
        return stream_info if stream_info else None
        
    except (subprocess.TimeoutExpired, json.JSONDecodeError, subprocess.SubprocessError) as e:
        print(f"Error probing {filepath}: {e}", file=sys.stderr)
    
    return None

def check_dolby_vision(stream_info: Dict, filepath: str = None) -> bool:
    """Check if file has Dolby Vision using ffprobe side_data_list"""
    
    # Primary method: Check side_data_list for DOVI configuration record
    # This is fast and reliable when using -show_entries stream_side_data=side_data_type
    side_data = stream_info.get('side_data_list', [])
    if side_data:
        for data in side_data:
            if isinstance(data, dict):
                side_data_type = data.get('side_data_type', '').lower()
                # "DOVI configuration record" is the key indicator for Dolby Vision
                if 'dovi' in side_data_type or 'dolby vision' in side_data_type:
                    return True
    
    # Fallback: Check codec_tag_string for DV codecs (for MP4 files)
    codec_tag = stream_info.get('codec_tag_string', '').lower()
    dv_codec_tags = ['dvh1', 'dvhe', 'dva1', 'dvav', 'dav1']
    if any(tag in codec_tag for tag in dv_codec_tags):
        return True
    
    # Fallback: Check profile for DV profiles
    profile = stream_info.get('profile', '').lower()
    if 'dolby vision' in profile:
        return True
    
    return False


def parse_filename_claims(filepath: str) -> Dict[str, bool]:
    """Parse filename to detect claimed HDR/DV formats"""
    filename = Path(filepath).name.lower()
    
    claims = {
        'dv': False,
        'hdr10': False,
        'hdr10plus': False,
        'hdr': False,
        'hlg': False
    }
    
    # Check for DV/Dolby Vision in filename (various patterns)
    # Patterns: .DV. .DV- -DV. -DV- DV.HDR DV.h265 etc.
    dv_pattern = r'[.\-_]dv[.\-_]|[.\-_]dovi[.\-_]|dolby[\.\-_]?vision'
    if re.search(dv_pattern, filename):
        claims['dv'] = True
    
    # Check for HDR10+ (must check before HDR10)
    hdr10plus_pattern = r'hdr10[\.\-_]?plus|hdr10\+'
    if re.search(hdr10plus_pattern, filename):
        claims['hdr10plus'] = True
        claims['hdr10'] = True  # HDR10+ implies HDR10
    # Check for HDR10
    elif 'hdr10' in filename:
        claims['hdr10'] = True
    
    # Check for generic HDR (but not HDR10)
    hdr_pattern = r'[.\-_]hdr[.\-_]'
    if re.search(hdr_pattern, filename) and not claims['hdr10']:
        claims['hdr'] = True
    
    # Check for HLG
    if re.search(r'[.\-_]hlg[.\-_]', filename):
        claims['hlg'] = True
    
    return claims


def check_liar_status(filepath: str, actual_category: str) -> Optional[str]:
    """Check if filename claims don't match actual content"""
    claims = parse_filename_claims(filepath)
    
    actual_has_dv = actual_category in ['DV + HDR10', 'DV']
    actual_has_hdr10 = actual_category in ['DV + HDR10', 'HDR10']
    actual_has_hdr = actual_category in ['DV + HDR10', 'DV', 'HDR10', 'HDR']
    
    issues = []
    
    # Check DV claims
    if claims['dv'] and not actual_has_dv:
        issues.append(f"claims DV but is {actual_category}")
    
    # Check HDR10 claims
    if claims['hdr10'] and not actual_has_hdr10 and not actual_has_dv:
        issues.append(f"claims HDR10 but is {actual_category}")
    
    # Check generic HDR claims
    if claims['hdr'] and not actual_has_hdr:
        issues.append(f"claims HDR but is {actual_category}")
    
    if issues:
        return "; ".join(issues)
    
    return None


def classify_file(filepath: str, stream_info: Dict) -> str:
    """Classify file based on stream information"""
    
    # Check for Dolby Vision using ffprobe side_data
    has_dv = check_dolby_vision(stream_info)
    
    # Check HDR10 metadata
    color_space = stream_info.get('color_space', '').lower()
    color_primaries = stream_info.get('color_primaries', '').lower()
    color_transfer = stream_info.get('color_transfer', '').lower()
    
    has_hdr10 = (
        color_space in ['bt2020nc', 'bt2020c'] and
        color_primaries == 'bt2020' and
        color_transfer == 'smpte2084'
    )
    
    # Check for any HDR (less strict)
    has_hdr = (
        'bt2020' in color_space or
        'bt2020' in color_primaries or
        'smpte2084' in color_transfer or
        'arib-std-b67' in color_transfer  # HLG
    )
    
    # Classify
    if has_dv and has_hdr10:
        return 'DV + HDR10'
    elif has_dv:
        return 'DV'  # DV without HDR10 fallback
    elif has_hdr10:
        return 'HDR10'
    elif has_hdr:
        return 'HDR'
    else:
        return 'SDR'

def check_files(directory: str, verbose: bool = False) -> tuple:
    """Check all files in directory and categorize them
    
    Returns:
        tuple: (categories dict, liars list of tuples (filepath, issue))
    """
    
    categories = {
        'DV + HDR10': [],
        'DV': [],
        'HDR10': [],
        'HDR': [],
        'SDR': []
    }
    
    liars = []  # List of (filepath, issue_description)
    
    video_files = get_video_files(directory)
    total_files = len(video_files)
    
    if total_files == 0:
        print(f"No video files found in {directory}")
        return categories, liars
    
    print(f"Found {total_files} video files. Checking...")
    
    for i, filepath in enumerate(video_files, 1):
        if verbose:
            print(f"[{i}/{total_files}] Checking: {filepath}")
        else:
            print(f"\rProgress: {i}/{total_files}", end='', flush=True)
        
        stream_info = get_stream_info(filepath)
        
        if stream_info:
            category = classify_file(filepath, stream_info)
            categories[category].append(filepath)
            
            # Check for liars (filename doesn't match content)
            liar_issue = check_liar_status(filepath, category)
            if liar_issue:
                liars.append((filepath, liar_issue))
            
            if verbose:
                if liar_issue:
                    print(f"  -> {category} ⚠️ LIAR: {liar_issue}")
                else:
                    print(f"  -> {category}")
        else:
            # File couldn't be read - put in SDR and check if it claims HDR/DV
            categories['SDR'].append(filepath)
            
            # Check for liars (filename claims HDR/DV but file is unreadable)
            liar_issue = check_liar_status(filepath, 'SDR')
            if liar_issue:
                liars.append((filepath, liar_issue))
            
            if verbose:
                if liar_issue:
                    print(f"  -> ERROR: Could not read stream info ⚠️ LIAR: {liar_issue}")
                else:
                    print(f"  -> ERROR: Could not read stream info")
    
    if not verbose:
        print()  # New line after progress
    
    return categories, liars

def print_results(categories: Dict[str, List[str]], liars: List[tuple], show_details: bool = False):
    """Print categorized results"""
    
    print("\n" + "="*80)
    print("MEDIA FILES CLASSIFICATION")
    print("="*80)
    
    for category in ['DV + HDR10', 'DV', 'HDR10', 'HDR', 'SDR']:
        files = categories[category]
        print(f"\n{category} ({len(files)} files):")
        print("-" * 40)
        
        if files:
            if show_details:
                for filepath in files:
                    print(f"  {filepath}")
            else:
                # Show first 5 files and count if more
                for filepath in files[:5]:
                    print(f"  {filepath}")
                if len(files) > 5:
                    print(f"  ... and {len(files) - 5} more files")
        else:
            print("  (none)")
    
    # Print LIARS section
    print(f"\n⚠️  LIARS ({len(liars)} files) - filename doesn't match content:")
    print("-" * 40)
    if liars:
        if show_details:
            for filepath, issue in liars:
                print(f"  {filepath}")
                print(f"      → {issue}")
        else:
            for filepath, issue in liars[:10]:
                filename = Path(filepath).name
                print(f"  {filename}")
                print(f"      → {issue}")
            if len(liars) > 10:
                print(f"  ... and {len(liars) - 10} more liars")
    else:
        print("  (none - all filenames match content)")
    
    # Summary
    total_files = sum(len(files) for files in categories.values())
    print(f"\n" + "="*80)
    print(f"SUMMARY: {total_files} total files")
    if total_files > 0:
        print(f"  DV + HDR10: {len(categories['DV + HDR10'])} ({len(categories['DV + HDR10'])/total_files*100:.1f}%)")
        print(f"  DV:         {len(categories['DV'])} ({len(categories['DV'])/total_files*100:.1f}%)")
        print(f"  HDR10:      {len(categories['HDR10'])} ({len(categories['HDR10'])/total_files*100:.1f}%)")
        print(f"  HDR:        {len(categories['HDR'])} ({len(categories['HDR'])/total_files*100:.1f}%)")
        print(f"  SDR:        {len(categories['SDR'])} ({len(categories['SDR'])/total_files*100:.1f}%)")
    else:
        print(f"  DV + HDR10: {len(categories['DV + HDR10'])} (0.0%)")
        print(f"  DV:         {len(categories['DV'])} (0.0%)")
        print(f"  HDR10:      {len(categories['HDR10'])} (0.0%)")
        print(f"  HDR:        {len(categories['HDR'])} (0.0%)")
        print(f"  SDR:        {len(categories['SDR'])} (0.0%)")
    
    if liars:
        print(f"\n  ⚠️  LIARS:    {len(liars)} files with mismatched filenames")
    print("="*80)

def save_results(categories: Dict[str, List[str]], liars: List[tuple], output_file: str):
    """Save results to file"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("MEDIA FILES CLASSIFICATION\n")
        f.write("="*80 + "\n\n")
        
        for category in ['DV + HDR10', 'DV', 'HDR10', 'HDR', 'SDR']:
            files = categories[category]
            f.write(f"{category} ({len(files)} files):\n")
            f.write("-" * 40 + "\n")
            
            for filepath in files:
                f.write(f"{filepath}\n")
            
            f.write("\n")
        
        # Liars section
        f.write(f"LIARS ({len(liars)} files) - filename doesn't match content:\n")
        f.write("-" * 40 + "\n")
        for filepath, issue in liars:
            f.write(f"{filepath}\n")
            f.write(f"    -> {issue}\n")
        f.write("\n")
        
        # Summary
        total_files = sum(len(files) for files in categories.values())
        f.write("="*80 + "\n")
        f.write(f"SUMMARY: {total_files} total files\n")
        f.write(f"  DV + HDR10: {len(categories['DV + HDR10'])}\n")
        f.write(f"  DV:         {len(categories['DV'])}\n")
        f.write(f"  HDR10:      {len(categories['HDR10'])}\n")
        f.write(f"  HDR:        {len(categories['HDR'])}\n")
        f.write(f"  SDR:        {len(categories['SDR'])}\n")
        if liars:
            f.write(f"\n  LIARS:      {len(liars)} files with mismatched filenames\n")

def main():
    parser = argparse.ArgumentParser(
        description='Check media files for HDR and Dolby Vision support',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/movies
  %(prog)s /path/to/movies --verbose
  %(prog)s /path/to/movies --details --output results.txt
        """
    )
    
    parser.add_argument('directory', help='Directory to scan recursively')
    parser.add_argument('-v', '--verbose', action='store_true', 
                       help='Show detailed progress')
    parser.add_argument('-d', '--details', action='store_true',
                       help='Show all file paths in results')
    parser.add_argument('-o', '--output', metavar='FILE',
                       help='Save results to file')
    
    args = parser.parse_args()
    
    # Check if ffprobe is available
    try:
        subprocess.run(['ffprobe', '-version'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL, 
                      check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: ffprobe not found. Please install ffmpeg with ffprobe.")
        sys.exit(1)
    
    # Check files
    categories, liars = check_files(args.directory, args.verbose)
    
    # Print results
    print_results(categories, liars, args.details)
    
    # Save to file if requested
    if args.output:
        save_results(categories, liars, args.output)
        print(f"\nResults saved to: {args.output}")

if __name__ == '__main__':
    main()