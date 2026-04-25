#!/bin/bash
# Build script for Joplin Knowledge Graph Plugin

set -e

cd "$(dirname "$0")"

echo "Building Knowledge Graph Plugin for Joplin..."

# Install dependencies
echo "Installing dependencies..."
npm install

# Build TypeScript
echo "Building TypeScript..."
npm run build

# Pack plugin
echo "Packing plugin..."
npm run pack

echo ""
echo "Build complete!"
echo "Plugin file: ../knowledge-graph.jpl"
echo ""
echo "To install:"
echo "1. Open Joplin"
echo "2. Go to Tools > Options > Plugins"
echo "3. Click 'Install from file'"
echo "4. Select knowledge-graph.jpl"