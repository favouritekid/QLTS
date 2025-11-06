#!/bin/bash
# Script to download MaxMind GeoLite2-City database
# Requires MaxMind license key (free account)

set -e

# Configuration
GEOIP_DIR="Backend_FastAPI/geoip"
DB_FILE="GeoLite2-City.mmdb"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "================================================"
echo "MaxMind GeoLite2-City Database Download Script"
echo "================================================"
echo ""

# Create geoip directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/$GEOIP_DIR"

# Check if database already exists
if [ -f "$PROJECT_ROOT/$GEOIP_DIR/$DB_FILE" ]; then
    echo "✓ GeoLite2-City.mmdb already exists at: $GEOIP_DIR/$DB_FILE"
    echo ""
    read -p "Do you want to re-download and replace it? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping download. Existing database will be used."
        exit 0
    fi
fi

# Check if LICENSE_KEY environment variable is set
if [ -z "$MAXMIND_LICENSE_KEY" ]; then
    echo "❌ Error: MAXMIND_LICENSE_KEY environment variable not set"
    echo ""
    echo "To download GeoLite2 database, you need a free MaxMind license key."
    echo ""
    echo "Steps to get a license key:"
    echo "1. Create a free account at: https://www.maxmind.com/en/geolite2/signup"
    echo "2. Login and navigate to: Account > Manage License Keys"
    echo "3. Generate a new license key"
    echo "4. Set the environment variable:"
    echo "   export MAXMIND_LICENSE_KEY='your_license_key_here'"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo "📥 Downloading GeoLite2-City database..."
echo "This may take a few minutes..."
echo ""

# MaxMind permalink URL (requires license key)
DOWNLOAD_URL="https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz"

# Download to temporary file
TEMP_FILE=$(mktemp)
TEMP_DIR=$(mktemp -d)

trap "rm -rf $TEMP_FILE $TEMP_DIR" EXIT

# Download the tar.gz file
if curl -L -f -o "$TEMP_FILE" "$DOWNLOAD_URL"; then
    echo "✓ Download successful"
else
    echo "❌ Download failed. Please check your license key and internet connection."
    exit 1
fi

# Extract the database file
echo "📦 Extracting database..."
tar -xzf "$TEMP_FILE" -C "$TEMP_DIR"

# Find the .mmdb file (it's nested in a versioned directory)
MMDB_FILE=$(find "$TEMP_DIR" -name "*.mmdb" -type f | head -n 1)

if [ -z "$MMDB_FILE" ]; then
    echo "❌ Error: Could not find .mmdb file in downloaded archive"
    exit 1
fi

# Move to target location
mv "$MMDB_FILE" "$PROJECT_ROOT/$GEOIP_DIR/$DB_FILE"

echo "✓ Database extracted successfully"
echo ""
echo "✅ GeoLite2-City database installed at: $GEOIP_DIR/$DB_FILE"
echo ""
echo "File size: $(du -h "$PROJECT_ROOT/$GEOIP_DIR/$DB_FILE" | cut -f1)"
echo ""
echo "You can now use GeoIP lookup in your application!"
echo ""
echo "Note: The database should be updated monthly."
echo "      You can re-run this script to get the latest version."
