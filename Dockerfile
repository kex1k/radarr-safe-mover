FROM python:3.11-slim

# Install ionice, nice, and rsync utilities
RUN apt-get update && apt-get install -y \
    util-linux \
    coreutils \
    rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 6970

CMD ["gunicorn", "--bind", "0.0.0.0:6970", "--workers", "1", "--threads", "2", "--timeout", "0", "app:app"]