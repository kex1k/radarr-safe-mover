#!/bin/bash

# Start script for Radarr Safe Mover with Podman

echo "🎬 Starting Radarr Safe Mover with Podman..."
echo ""

# Check if Podman is installed
if ! command -v podman &> /dev/null; then
    echo "❌ Podman is not installed. Please install Podman first."
    exit 1
fi

# Check if podman-compose is installed
if ! command -v podman-compose &> /dev/null; then
    echo "❌ podman-compose is not installed. Please install podman-compose first."
    echo "   You can install it with: pip install podman-compose"
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

# Build and start the container
echo "🔨 Building Podman image..."
podman-compose -f podman-compose.yml build

echo ""
echo "🚀 Starting container..."
podman-compose -f podman-compose.yml up -d

echo ""
echo "✅ Radarr Safe Mover is now running with Podman!"
echo ""
echo "📱 Open your browser and navigate to:"
echo "   http://localhost:9696"
echo ""
echo "📋 To view logs, run:"
echo "   podman-compose -f podman-compose.yml logs -f"
echo ""
echo "🛑 To stop the application, run:"
echo "   podman-compose -f podman-compose.yml down"
echo ""