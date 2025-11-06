# GeoIP Setup Guide

This guide explains how to set up and use GeoIP lookup functionality in the QLTS application.

## Overview

The application uses MaxMind's GeoLite2-City database to determine geographic location (country and city) from IP addresses. This information is used for:

- **Session Management**: Display user login locations in session list
- **Security**: Detect suspicious logins from unusual locations (impossible travel)
- **Analytics**: Track user geographic distribution

## Features

### GeoIP Lookup (`app/services/geoip_service.py`)

- Converts IP addresses to geographic locations (country, city)
- Handles private IP addresses (127.0.0.1, 192.168.x.x, etc.) gracefully
- Singleton pattern for efficient memory usage
- Automatic fallback when database is unavailable

### Anomaly Detection (`app/services/anomaly_detection.py`)

The GeoIP data feeds into the anomaly detection system, which flags suspicious logins based on:

1. **New IP Address**: First time login from this IP
2. **New Device**: New device/browser/OS combination
3. **Impossible Travel**: Login from different country within 2 hours
4. **Excessive Sessions**: More than 10 active sessions
5. **Unusual Time**: Login between 2-6 AM (configurable)

When suspicious activity is detected:
- Session is marked with `is_suspicious = True`
- User receives an email alert with login details
- Security team can review suspicious sessions in admin dashboard

## Installation

### Step 1: Get MaxMind License Key

1. Create a free account at: https://www.maxmind.com/en/geolite2/signup
2. Login and navigate to: **Account → Manage License Keys**
3. Click **Generate new license key**
4. Save your license key (you'll need it for download)

### Step 2: Download GeoLite2-City Database

#### Option A: Using Shell Script (Linux/Mac)

```bash
# Set your license key
export MAXMIND_LICENSE_KEY='your_license_key_here'

# Run download script
cd Backend_FastAPI
./scripts/download_geoip_db.sh
```

#### Option B: Using Python Script (Cross-platform - **Recommended for Windows**)

**Method 1: Command-line argument (easiest for Windows)**

```bash
cd Backend_FastAPI
python scripts/download_geoip_db.py --license-key YOUR_LICENSE_KEY_HERE
```

**Method 2: Environment variable**

```bash
# Linux/Mac:
export MAXMIND_LICENSE_KEY='your_license_key_here'
python scripts/download_geoip_db.py

# Windows (PowerShell):
$env:MAXMIND_LICENSE_KEY='your_license_key_here'
python scripts/download_geoip_db.py

# Windows (Command Prompt):
set MAXMIND_LICENSE_KEY=your_license_key_here
python scripts/download_geoip_db.py
```

#### Option C: Manual Download

1. Download from: https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=YOUR_LICENSE_KEY&suffix=tar.gz
2. Extract the archive
3. Copy `GeoLite2-City.mmdb` to `Backend_FastAPI/geoip/GeoLite2-City.mmdb`

### Step 3: Verify Installation

```bash
# Check if database file exists
ls -lh Backend_FastAPI/geoip/GeoLite2-City.mmdb

# Expected output:
# -rw-r--r-- 1 user user 60M Nov 6 10:30 Backend_FastAPI/geoip/GeoLite2-City.mmdb
```

### Step 4: Install Python Dependencies

```bash
cd Backend_FastAPI
pip install -r requirements.txt
```

This will install `geoip2==4.8.0` which is required for GeoIP lookups.

## Configuration

### Environment Variables

No environment variables are required for GeoIP functionality. The database path is configured in `app/services/geoip_service.py`:

```python
GEOIP_DB_PATH = Path(__file__).parent.parent / "geoip" / "GeoLite2-City.mmdb"
```

### Graceful Degradation

If the GeoIP database is not available:
- The application will continue to work normally
- `country` and `city` fields will be `None`
- A warning will be logged: `"GeoIP database not found"`
- Sessions will still be created and tracked

## Usage

### In Session Creation

GeoIP lookup is automatically performed during session creation in `app/services/session_service.py`:

```python
from .geoip_service import get_geoip_service

# Lookup location from IP address
geoip = get_geoip_service()
country, city = geoip.lookup(ip_address)

# Store in session
session = models.UserSession(
    user_id=user_id,
    ip_address=ip_address,
    country=country,  # e.g., "United States"
    city=city,        # e.g., "San Francisco"
    # ... other fields
)
```

### In Anomaly Detection

Geographic data is used to detect impossible travel:

```python
# Check if user logged in from different country within 2 hours
if last_session.country != current_country:
    time_diff = current_time - last_session.created_at
    if time_diff < timedelta(hours=2):
        anomalies["impossible_travel"] = True
        anomalies["is_suspicious"] = True
```

### In Frontend Display

Session cards display location information from `frontend/src/types/session.ts`:

```typescript
export function formatLocation(session: UserSession): string {
  const parts: string[] = [];

  if (session.city) parts.push(session.city);
  if (session.country) parts.push(session.country);

  return parts.join(", ") || session.ip_address || "Unknown Location";
}
```

## Testing

### Test GeoIP Lookup

```python
from app.services.geoip_service import get_geoip_service

geoip = get_geoip_service()

# Test with public IP
country, city = geoip.lookup("8.8.8.8")
print(f"Location: {city}, {country}")
# Expected: Mountain View, United States

# Test with private IP
country, city = geoip.lookup("192.168.1.1")
print(f"Location: {city}, {country}")
# Expected: None, None
```

### Test Login from Different Locations

1. Login with a VPN from one country
2. Immediately switch VPN to different country and login again
3. Check email for suspicious login alert
4. Verify session is marked `is_suspicious: true`

## Maintenance

### Database Updates

MaxMind releases GeoLite2 updates on the first Tuesday of each month. To update:

```bash
# Re-run the download script
cd Backend_FastAPI
./scripts/download_geoip_db.sh
```

Or set up a cron job (Linux/Mac):

```bash
# Edit crontab
crontab -e

# Add monthly update (first Tuesday at 3 AM)
0 3 1-7 * * [ "$(date +\%u)" -eq 2 ] && cd /path/to/QLTS/Backend_FastAPI && ./scripts/download_geoip_db.sh
```

### Monitoring

Check logs for GeoIP lookup issues:

```bash
# In application logs, look for:
grep "GeoIP" logs/app.log

# Success example:
# INFO: GeoIP lookup successful | user_id=123 ip_address=203.0.113.42 country=Japan city=Tokyo

# Warning example:
# WARNING: GeoIP lookup failed | ip_address=203.0.113.42 error=Database not found
```

## Troubleshooting

### Issue: "GeoIP database not found"

**Solution**: Download the database using the setup script

```bash
export MAXMIND_LICENSE_KEY='your_key_here'
./scripts/download_geoip_db.sh
```

### Issue: "Invalid license key"

**Solution**: Verify your license key is correct

1. Login to MaxMind account
2. Go to Account → Manage License Keys
3. Copy the exact license key
4. Make sure there are no extra spaces or quotes

### Issue: "Module 'geoip2' not found"

**Solution**: Install the required dependency

```bash
pip install geoip2==4.8.0
```

### Issue: Sessions show "Unknown Location" for public IPs

**Possible causes:**

1. **Database not installed**: Run `ls Backend_FastAPI/geoip/GeoLite2-City.mmdb`
2. **Database outdated**: IP ranges change, re-download latest database
3. **IP not in database**: Some IPs are not in GeoLite2 (less common IPs)

### Issue: Private IPs showing location

**This is expected**: Private IPs (127.0.0.1, 192.168.x.x, 10.x.x.x) are automatically skipped and return `(None, None)`. This is by design for security and performance.

## Security Considerations

1. **License Key Protection**: Never commit your MaxMind license key to Git. Use environment variables.

2. **Database in .gitignore**: The database file is excluded from Git (60+ MB) and must be downloaded separately on each deployment.

3. **Privacy**: Geographic location data is considered personal information. Ensure compliance with GDPR/privacy regulations:
   - Include location tracking in privacy policy
   - Allow users to view their session locations
   - Delete location data when sessions are deleted

4. **Rate Limiting**: GeoIP lookups are performed in-memory (no API calls), so there's no rate limiting concern.

5. **False Positives**: Impossible travel detection may flag VPN users or users traveling frequently. Consider:
   - Allowing users to mark sessions as "trusted"
   - Adjusting the 2-hour window based on your user base
   - Adding user preference to disable alerts

## Performance

- **Memory Usage**: ~60 MB when database is loaded (singleton, loaded once)
- **Lookup Speed**: < 1ms per lookup (in-memory binary search)
- **No External API**: All lookups are local, no network latency
- **Thread Safe**: Singleton pattern ensures one database instance per process

## License

MaxMind GeoLite2 database is licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License](https://creativecommons.org/licenses/by-sa/4.0/).

You must:
- Include attribution to MaxMind in your application
- Include a link to the database source
- State if you modified the data

Example attribution in your app's footer or about page:

```
This product includes GeoLite2 data created by MaxMind, available from
https://www.maxmind.com
```

## References

- **MaxMind GeoLite2**: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
- **MaxMind GeoIP2 Python API**: https://geoip2.readthedocs.io/
- **License Information**: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data#license
- **Accuracy**: https://www.maxmind.com/en/geoip2-city-accuracy-comparison

---

**Last Updated**: November 6, 2025
**Version**: 1.0.0
