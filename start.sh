#!/bin/bash

# Start script for Radarr Safe Mover

echo "🎬 Starting Radarr Safe Mover..."
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

# Build and start the container
echo "🔨 Building Docker image..."
docker-compose build

echo ""
echo "🚀 Starting container..."
docker-compose up -d

echo ""
echo "✅ Radarr Safe Mover is now running!"
echo ""
echo "📱 Open your browser and navigate to:"
echo "   http://localhost:9696"
echo ""
echo "📋 To view logs, run:"
echo "   docker-compose logs -f"
echo ""
echo "🛑 To stop the application, run:"
echo "   docker-compose down"
echo ""