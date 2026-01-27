#!/bin/bash

# Start script for Radarr Safe Mover

echo "🎬 Starting Radarr Safe Mover..."
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Detect Docker Compose command (v1 or v2)
COMPOSE_CMD=""
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
    echo "✓ Found docker-compose (v1)"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
    echo "✓ Found docker compose (v2)"
else
    echo "❌ Docker Compose is not installed."
    echo "   Please install Docker Compose:"
    echo "   - For v1: https://docs.docker.com/compose/install/"
    echo "   - For v2: Included with Docker Desktop or install docker-compose-plugin"
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

# Build and start the container
echo ""
echo "🔨 Building Docker image..."
$COMPOSE_CMD build

echo ""
echo "🚀 Starting container..."
$COMPOSE_CMD up -d

echo ""
echo "✅ Radarr Safe Mover is now running!"
echo ""
echo "📱 Open your browser and navigate to:"
echo "   http://localhost:9696"
echo ""
echo "📋 To view logs, run:"
echo "   $COMPOSE_CMD logs -f"
echo ""
echo "🛑 To stop the application, run:"
echo "   $COMPOSE_CMD down"
echo ""