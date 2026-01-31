#!/bin/bash

# DTS 5.1(side) to FLAC 7.1 Converter
# Converts DTS 5.1(side) audio to FLAC 7.1 and adds it as a new track to the MKV file

set -uo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored messages
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if required tools are installed
check_dependencies() {
    local missing_deps=()
    
    if ! command -v ffmpeg &> /dev/null; then
        missing_deps+=("ffmpeg")
    fi
    
    if ! command -v ffprobe &> /dev/null; then
        missing_deps+=("ffprobe")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_info "Please install them before running this script"
        exit 1
    fi
}

# Function to get all media info in one call
get_media_info() {
    local file="$1"
    
    ffprobe -v quiet -print_format json -show_streams -show_format -select_streams a:0 "$file" 2>&1
}

# Function to validate audio format and extract info
validate_and_extract_info() {
    local file="$1"
    
    local media_info
    media_info=$(get_media_info "$file")
    
    if [ -z "$media_info" ]; then
        echo "ERROR: Failed to get media info from ffprobe" >&2
        return 1
    fi
    
    # Extract audio info using jq-like parsing or simple grep
    local codec_name
    codec_name=$(echo "$media_info" | grep -Eo '"codec_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"codec_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    
    local channel_layout
    channel_layout=$(echo "$media_info" | grep -Eo '"channel_layout"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"channel_layout"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    
    local channels
    channels=$(echo "$media_info" | grep -Eo '"channels"[[:space:]]*:[[:space:]]*[0-9]+' | head -1 | sed 's/.*:[[:space:]]*\([0-9]*\).*/\1/')
    
    local sample_rate
    sample_rate=$(echo "$media_info" | grep -Eo '"sample_rate"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"sample_rate"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    
    # Extract duration
    local duration
    duration=$(echo "$media_info" | grep -Eo '"duration"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"duration"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    
    # Log to stderr so it doesn't interfere with return value
    echo "[INFO] Audio format: $codec_name, channels: $channel_layout ($channels), sample rate: $sample_rate" >&2
    
    # Calculate minutes (compatible with BSD awk on macOS)
    local minutes
    if [ -n "$duration" ] && [ "$duration" != "0" ]; then
        minutes=$(echo "$duration" | awk '{printf "%.2f", $1/60}')
        echo "[INFO] Duration: ${duration}s ($minutes minutes)" >&2
    else
        echo "[INFO] Duration: ${duration}s" >&2
    fi
    
    # Check if codec is DTS family
    if [[ ! "$codec_name" =~ ^dts ]]; then
        echo "ERROR: Audio codec is not DTS (found: $codec_name)" >&2
        return 1
    fi
    
    # Check if channel layout is 5.1(side)
    if [[ "$channel_layout" != "5.1(side)" ]]; then
        echo "ERROR: Channel layout is not 5.1(side) (found: $channel_layout)" >&2
        return 1
    fi
    
    echo "[SUCCESS] Audio format validation passed" >&2
    
    # Return ONLY duration via stdout (will be captured by caller)
    echo "$duration"
    return 0
}

# Function to convert audio to FLAC 7.1
convert_to_flac() {
    local input_file="$1"
    local output_file="$2"
    local duration="$3"
    
    log_info "Starting conversion to FLAC 7.1..."
    
    # Calculate minutes for display
    local minutes
    if [ -n "$duration" ] && [ "$duration" != "0" ]; then
        minutes=$(echo "$duration" | awk '{printf "%.2f", $1/60}')
        log_info "Duration: ${duration}s ($minutes minutes)"
    else
        log_info "Duration: ${duration}s"
    fi
    
    # Remove output file if it exists
    rm -f "$output_file"
    
    log_info "Running ffmpeg conversion (this may take a while)..."
    
    # Run ffmpeg conversion synchronously (not in background)
    # This ensures the file is complete before we proceed
    ffmpeg -y -i "$input_file" \
        -vn \
        -c:a flac \
        -compression_level 8 \
        -channel_layout 7.1 \
        -ac 8 \
        -af "pan=7.1|FL=FL|FR=FR|FC=FC|LFE=LFE|BL=SL|BR=SR|SL=SL|SR=SR" \
        -loglevel warning \
        -stats \
        "$output_file"
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ] && [ -f "$output_file" ]; then
        log_success "Audio conversion completed: $output_file"
        return 0
    else
        log_error "Conversion failed (exit code: $exit_code)"
        return 1
    fi
}

# Function to merge audio track into MKV using ffmpeg
merge_audio_track() {
    local original_file="$1"
    local audio_file="$2"
    local final_output="$3"
    
    log_info "Merging new audio track into MKV..."
    
    # Use ffmpeg to add the new audio track as the first audio stream
    # -i audio_file: input new FLAC audio (first input, will be stream 0)
    # -i original_file: input original MKV (second input)
    # -map 1:v: copy video from second input (original file)
    # -map 0:a:0: add new FLAC audio as first audio stream
    # -map 1:a: copy all original audio streams after the new one
    # -map 1:s?: copy all subtitle streams if they exist
    # -c copy: copy all streams without re-encoding
    # -metadata:s:a:0: set metadata for the new audio track (index 0, first audio)
    # -disposition:a:0 default: mark the new audio track as default
    ffmpeg -i "$audio_file" -i "$original_file" \
        -map 1:v \
        -map 0:a:0 \
        -map 1:a \
        -map 1:s? \
        -c copy \
        -metadata:s:a:0 title="FLAC 7.1" \
        -metadata:s:a:0 language=eng \
        -disposition:a:0 default \
        -loglevel error \
        "$final_output"
    
    if [ $? -eq 0 ]; then
        log_success "Audio track merged successfully (FLAC 7.1 as first audio track, marked as English)"
        return 0
    else
        log_error "Failed to merge audio track"
        return 1
    fi
}

# Function to generate output filename
generate_output_filename() {
    local input_file="$1"
    
    local dir
    dir=$(dirname "$input_file")
    
    local filename
    filename=$(basename "$input_file")
    
    local base_name="${filename%.*}"
    local extension="${filename##*.}"
    
    # Replace DTS.*5.1 with FLAC.7.1
    # Use [.A-Za-z-] instead of [.\-A-Za-z] to avoid BSD sed character range issues
    base_name=$(echo "$base_name" | sed -E 's/DTS[.A-Za-z-]*5\.1/FLAC.7.1/')
    
    local output_path="${dir}/${base_name}.${extension}"
    
    # Check if file exists and add counter if needed
    local counter=1
    while [ -f "$output_path" ]; do
        output_path="${dir}/${base_name}_${counter}.${extension}"
        ((counter++))
    done
    
    echo "$output_path"
}

# Function to rename original file to .bak
rename_to_bak() {
    local file="$1"
    local bak_path="${file}.bak"
    
    # Check if .bak already exists
    local counter=1
    while [ -f "$bak_path" ]; do
        bak_path="${file}.bak.${counter}"
        ((counter++))
    done
    
    log_info "Renaming original file to: $bak_path"
    mv "$file" "$bak_path"
    
    if [ $? -eq 0 ]; then
        log_success "Original file renamed to .bak"
        return 0
    else
        log_error "Failed to rename original file"
        return 1
    fi
}

# Main function
main() {
    # Parse command line arguments
    local reckless_mode=false
    local input_file=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --reckless|-r)
                reckless_mode=true
                shift
                ;;
            -*)
                log_error "Unknown option: $1"
                log_info "Usage: $0 [--reckless|-r] <input_file.mkv>"
                log_info "Options:"
                log_info "  --reckless, -r    Overwrite original file (no backup, same filename)"
                log_info "Example: $0 movie.DTS-HD.MA.5.1.mkv"
                log_info "Example: $0 --reckless movie.DTS-HD.MA.5.1.mkv"
                exit 1
                ;;
            *)
                input_file="$1"
                shift
                ;;
        esac
    done
    
    # Check if input file is provided
    if [ -z "$input_file" ]; then
        log_error "Usage: $0 [--reckless|-r] <input_file.mkv>"
        log_info "Options:"
        log_info "  --reckless, -r    Overwrite original file (no backup, same filename)"
        log_info "Example: $0 movie.DTS-HD.MA.5.1.mkv"
        log_info "Example: $0 --reckless movie.DTS-HD.MA.5.1.mkv"
        exit 1
    fi
    
    # Check if file exists
    if [ ! -f "$input_file" ]; then
        log_error "File not found: $input_file"
        exit 1
    fi
    
    log_info "Processing file: $input_file"
    
    # Check dependencies
    check_dependencies
    
    log_info "Analyzing media file..."
    
    # Validate audio format and get duration in one call
    # stderr goes to terminal, stdout (duration) is captured
    local duration
    duration=$(validate_and_extract_info "$input_file")
    local validation_status=$?
    
    if [ $validation_status -ne 0 ]; then
        log_error "Audio validation failed. File must have DTS codec with 5.1(side) channel layout."
        exit 1
    fi
    
    if [ -z "$duration" ] || [ "$duration" = "N/A" ]; then
        log_warning "Could not determine video duration, progress may not be accurate"
        duration=0
    fi
    
    # Generate output filename
    local output_file
    local temp_output_file
    
    if [ "$reckless_mode" = true ]; then
        # In reckless mode, use a temporary file first, then replace original
        temp_output_file=$(mktemp /tmp/convert_output.XXXXXX)
        rm -f "$temp_output_file"
        temp_output_file="${temp_output_file}.mkv"
        output_file="$temp_output_file"
        log_warning "RECKLESS MODE: Will overwrite original file: $input_file"
    else
        output_file=$(generate_output_filename "$input_file")
        temp_output_file=""
        log_info "Output file will be: $output_file"
    fi
    
    # Create temporary file for converted audio (BSD mktemp compatible)
    local temp_audio
    temp_audio=$(mktemp /tmp/convert_audio.XXXXXX)
    # Remove the temp file and recreate with .flac extension
    rm -f "$temp_audio"
    temp_audio="${temp_audio}.flac"
    
    # Convert audio to FLAC 7.1
    if ! convert_to_flac "$input_file" "$temp_audio" "$duration"; then
        log_error "Conversion failed"
        rm -f "$temp_audio"
        exit 1
    fi
    
    # Merge audio track into MKV
    if ! merge_audio_track "$input_file" "$temp_audio" "$output_file"; then
        log_error "Merging failed"
        rm -f "$temp_audio"
        exit 1
    fi
    
    # Clean up temporary audio file
    rm -f "$temp_audio"
    
    # Verify output file was created
    if [ ! -f "$output_file" ]; then
        log_error "Output file was not created: $output_file"
        exit 1
    fi
    
    log_success "Output file created: $output_file"
    
    # Handle reckless mode: replace original file
    if [ "$reckless_mode" = true ]; then
        log_info "Replacing original file with converted version..."
        
        # Save original file permissions and timestamps
        local original_perms
        original_perms=$(stat -f "%p" "$input_file" 2>/dev/null || stat -c "%a" "$input_file" 2>/dev/null)
        
        # Remove original file
        rm -f "$input_file"
        
        # Move temp file to original location
        mv "$output_file" "$input_file"
        
        # Restore permissions if we got them
        if [ -n "$original_perms" ]; then
            chmod "$original_perms" "$input_file" 2>/dev/null || true
        fi
        
        log_success "Conversion completed successfully!"
        log_warning "RECKLESS MODE: Original file was replaced"
        log_info "File: $input_file"
    else
        # Normal mode: rename original to .bak
        if ! rename_to_bak "$input_file"; then
            log_warning "Could not rename original file to .bak, but conversion was successful"
        fi
        
        log_success "Conversion completed successfully!"
        log_info "Original file: ${input_file}.bak"
        log_info "New file: $output_file"
    fi
}

# Run main function
main "$@"