#!/bin/bash

DIR="${1:-.}"
LOGFILE="$HOME/mkv_video_fast_$(date +%F_%H-%M-%S).log"
BROKEN_LIST="$HOME/mkv_video_fast_broken_$(date +%F_%H-%M-%S).txt"

THREADS=$(nproc)

echo "Start: $(date)" | tee -a "$LOGFILE"
echo "Directory: $DIR" | tee -a "$LOGFILE"
echo "Threads: $THREADS" | tee -a "$LOGFILE"
echo "-------------------------------------" | tee -a "$LOGFILE"

shopt -s nullglob
FILES=("$DIR"/*.mkv)
TOTAL=${#FILES[@]}

echo "Total files: $TOTAL" | tee -a "$LOGFILE"
echo "-------------------------------------" | tee -a "$LOGFILE"

if [ "$TOTAL" -eq 0 ]; then
    echo "No MKV files found." | tee -a "$LOGFILE"
    exit 0
fi

printf "%s\n" "${FILES[@]}" | \
xargs -P "$THREADS" -I {} bash -c '
f="$1"
if ! ffmpeg -v error -xerror -err_detect explode -skip_frame nokey -i "$f" -map 0:v -f null - > /dev/null 2>&1; then
    echo "BROKEN: $f"
fi
' _ {} | tee >(grep "^BROKEN:" >> "$BROKEN_LIST") | tee -a "$LOGFILE"

echo "-------------------------------------" | tee -a "$LOGFILE"
echo "Finished: $(date)" | tee -a "$LOGFILE"

if [ -f "$BROKEN_LIST" ]; then
    echo "Broken files:" | tee -a "$LOGFILE"
    cat "$BROKEN_LIST" | tee -a "$LOGFILE"
else
    echo "No broken files found." | tee -a "$LOGFILE"
fi
