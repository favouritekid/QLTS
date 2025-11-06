#!/usr/bin/env python3
"""
Script to download MaxMind GeoLite2-City database
Requires MaxMind license key (free account)
Cross-platform Python version
"""

import argparse
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import HTTPError, URLError


def download_geoip_database(license_key=None):
    """Download and install GeoLite2-City database"""

    # Configuration
    GEOIP_DIR = "Backend_FastAPI/geoip"
    DB_FILE = "GeoLite2-City.mmdb"

    # Get project root (two levels up from this script)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    geoip_path = project_root / GEOIP_DIR
    db_path = geoip_path / DB_FILE

    print("=" * 48)
    print("MaxMind GeoLite2-City Database Download Script")
    print("=" * 48)
    print()

    # Create geoip directory if it doesn't exist
    geoip_path.mkdir(parents=True, exist_ok=True)

    # Check if database already exists
    if db_path.exists():
        print(f"✓ GeoLite2-City.mmdb already exists at: {GEOIP_DIR}/{DB_FILE}")
        print()
        response = input("Do you want to re-download and replace it? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Skipping download. Existing database will be used.")
            return 0

    # Check for license key (parameter takes precedence over environment variable)
    if not license_key:
        license_key = os.environ.get("MAXMIND_LICENSE_KEY")

    if not license_key:
        print("❌ Error: MaxMind license key not provided")
        print()
        print("To download GeoLite2 database, you need a free MaxMind license key.")
        print()
        print("Steps to get a license key:")
        print("1. Create a free account at: https://www.maxmind.com/en/geolite2/signup")
        print("2. Login and navigate to: Account > Manage License Keys")
        print("3. Generate a new license key")
        print()
        print("Usage options:")
        print("  Option 1 - Command line argument (recommended for Windows):")
        print("    python download_geoip_db.py --license-key YOUR_KEY_HERE")
        print()
        print("  Option 2 - Environment variable:")
        print("    Linux/Mac: export MAXMIND_LICENSE_KEY='your_key_here'")
        print("    Windows PowerShell: $env:MAXMIND_LICENSE_KEY='your_key_here'")
        print("    Windows CMD: set MAXMIND_LICENSE_KEY=your_key_here")
        print()
        return 1

    print("📥 Downloading GeoLite2-City database...")
    print("This may take a few minutes...")
    print()

    # MaxMind permalink URL
    download_url = (
        f"https://download.maxmind.com/app/geoip_download"
        f"?edition_id=GeoLite2-City"
        f"&license_key={license_key}"
        f"&suffix=tar.gz"
    )

    # Create temporary files
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    temp_dir = tempfile.mkdtemp()

    try:
        # Download the tar.gz file
        try:
            urlretrieve(download_url, temp_file.name)
            print("✓ Download successful")
        except (HTTPError, URLError) as e:
            print(f"❌ Download failed: {e}")
            print("Please check your license key and internet connection.")
            return 1

        # Extract the database file
        print("📦 Extracting database...")
        with tarfile.open(temp_file.name, 'r:gz') as tar:
            tar.extractall(temp_dir)

        # Find the .mmdb file (it's nested in a versioned directory)
        mmdb_files = list(Path(temp_dir).rglob("*.mmdb"))
        if not mmdb_files:
            print("❌ Error: Could not find .mmdb file in downloaded archive")
            return 1

        mmdb_file = mmdb_files[0]

        # Move to target location
        import shutil
        shutil.move(str(mmdb_file), str(db_path))

        print("✓ Database extracted successfully")
        print()
        print(f"✅ GeoLite2-City database installed at: {GEOIP_DIR}/{DB_FILE}")
        print()

        # Get file size
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"File size: {size_mb:.1f} MB")
        print()
        print("You can now use GeoIP lookup in your application!")
        print()
        print("Note: The database should be updated monthly.")
        print("      You can re-run this script to get the latest version.")

        return 0

    finally:
        # Cleanup
        try:
            os.unlink(temp_file.name)
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download MaxMind GeoLite2-City database for GeoIP lookups"
    )
    parser.add_argument(
        "--license-key",
        "-k",
        type=str,
        help="MaxMind license key (alternatively set MAXMIND_LICENSE_KEY environment variable)",
    )
    args = parser.parse_args()

    sys.exit(download_geoip_database(license_key=args.license_key))
