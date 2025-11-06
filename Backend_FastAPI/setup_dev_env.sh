#!/bin/bash
# Script to setup .env file for development with GeoIP testing enabled

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

echo "================================"
echo "Backend Development Environment Setup"
echo "================================"
echo ""

# Check if .env.example exists
if [ ! -f "$ENV_EXAMPLE" ]; then
    echo "❌ Error: .env.example not found at $ENV_EXAMPLE"
    exit 1
fi

# Check if .env already exists
if [ -f "$ENV_FILE" ]; then
    echo "⚠️  Warning: .env file already exists at $ENV_FILE"
    echo ""
    read -p "Do you want to overwrite it? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env file."
        echo ""
        echo "To enable GeoIP testing, edit $ENV_FILE and uncomment:"
        echo "  DEV_GEOIP_TEST_IP=103.28.36.1"
        exit 0
    fi
fi

# Copy .env.example to .env
echo "📝 Creating .env from .env.example..."
cp "$ENV_EXAMPLE" "$ENV_FILE"

# Uncomment DEV_GEOIP_TEST_IP line
echo "🔧 Enabling DEV_GEOIP_TEST_IP for localhost testing..."
sed -i 's/^# DEV_GEOIP_TEST_IP=103.28.36.1/DEV_GEOIP_TEST_IP=103.28.36.1/' "$ENV_FILE"

echo ""
echo "✅ Success! .env file created and configured."
echo ""
echo "📍 GeoIP Test IP is set to: 103.28.36.1 (Hanoi, Vietnam)"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your database credentials, JWT secrets, etc."
echo "2. Restart backend server:"
echo "   uvicorn app.main:app --reload"
echo "3. Login from localhost -> Should show 'Hanoi, Vietnam'"
echo ""
echo "To change test location, edit DEV_GEOIP_TEST_IP in .env:"
echo "  - 103.28.36.1 = Hanoi, Vietnam"
echo "  - 8.8.8.8 = Mountain View, USA"
echo "  - 1.1.1.1 = Sydney, Australia"
echo ""
