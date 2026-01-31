FROM python:3.11-slim

# Install ionice, nice, rsync, and ffmpeg utilities
RUN apt-get update && apt-get install -y \
    util-linux \
    coreutils \
    rsync \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy core and operations modules
COPY core/ ./core/
COPY operations/ ./operations/

# Copy application files
COPY app.py .
COPY templates/ ./templates/

EXPOSE 6970

CMD ["gunicorn", "--bind", "0.0.0.0:6970", "--workers", "1", "--threads", "2", "--timeout", "0", "app:app"]