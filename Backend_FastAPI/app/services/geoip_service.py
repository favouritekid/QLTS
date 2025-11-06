# app/services/geoip_service.py
"""
GeoIP service for IP address geolocation lookup using MaxMind GeoLite2.
"""
from pathlib import Path
from typing import Optional, Tuple

import structlog

from ..config import settings

try:
    import geoip2.database
    import geoip2.errors
    GEOIP2_AVAILABLE = True
except ImportError:
    GEOIP2_AVAILABLE = False

log = structlog.get_logger(__name__)

# Path to GeoLite2 database
BASE_DIR = Path(__file__).resolve().parent.parent.parent
GEOIP_DB_PATH = BASE_DIR / "geoip" / "GeoLite2-City.mmdb"


class GeoIPService:
    """
    Service for looking up geographic location from IP addresses.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize GeoIP service.

        Args:
            db_path: Path to GeoLite2-City.mmdb database file
        """
        self.db_path = db_path or GEOIP_DB_PATH
        self.reader = None
        self._initialize_reader()

    def _initialize_reader(self):
        """Initialize the GeoIP2 database reader."""
        if not GEOIP2_AVAILABLE:
            log.warning(
                "geoip2 library not installed. Install with: pip install geoip2"
            )
            return

        if not self.db_path.exists():
            log.warning(
                "GeoIP database not found",
                path=str(self.db_path),
                hint="Run: python scripts/download_geoip_db.py",
            )
            return

        try:
            self.reader = geoip2.database.Reader(str(self.db_path))
            log.info("GeoIP database loaded successfully", path=str(self.db_path))
        except Exception as e:
            log.error("Failed to load GeoIP database", error=str(e), path=str(self.db_path))

    def lookup(self, ip_address: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Lookup geographic location from IP address.

        Args:
            ip_address: IP address to lookup

        Returns:
            Tuple of (country, city) or (None, None) if lookup fails
        """
        if not self.reader:
            return (None, None)

        # DEVELOPMENT: Override IP for testing with localhost
        # Set DEV_GEOIP_TEST_IP in .env file to test GeoIP with a public IP
        # Example: DEV_GEOIP_TEST_IP=8.8.8.8 (Google DNS - Mountain View, USA)
        dev_test_ip = settings.DEV_GEOIP_TEST_IP
        if dev_test_ip and self._is_private_ip(ip_address):
            log.info(
                "DEV MODE: Using test IP instead of private IP",
                original_ip=ip_address,
                test_ip=dev_test_ip,
            )
            ip_address = dev_test_ip

        # Skip private/local IP addresses
        if self._is_private_ip(ip_address):
            log.debug("Skipping GeoIP lookup for private IP", ip=ip_address)
            return (None, None)

        try:
            response = self.reader.city(ip_address)
            country = response.country.name
            city = response.city.name

            log.debug(
                "GeoIP lookup successful",
                ip=ip_address,
                country=country,
                city=city,
            )
            return (country, city)

        except geoip2.errors.AddressNotFoundError:
            log.debug("IP address not found in GeoIP database", ip=ip_address)
            return (None, None)

        except Exception as e:
            log.warning("GeoIP lookup failed", ip=ip_address, error=str(e))
            return (None, None)

    def _is_private_ip(self, ip_address: str) -> bool:
        """
        Check if IP address is private/local.

        Args:
            ip_address: IP address to check

        Returns:
            True if IP is private/local
        """
        # Common private IP ranges and localhost
        private_ranges = [
            "127.",  # Localhost
            "10.",  # Private Class A
            "192.168.",  # Private Class C
            "172.16.", "172.17.", "172.18.", "172.19.",  # Private Class B
            "172.20.", "172.21.", "172.22.", "172.23.",
            "172.24.", "172.25.", "172.26.", "172.27.",
            "172.28.", "172.29.", "172.30.", "172.31.",
            "::1",  # IPv6 localhost
            "fe80:",  # IPv6 link-local
        ]

        return any(ip_address.startswith(prefix) for prefix in private_ranges)

    def close(self):
        """Close the database reader."""
        if self.reader:
            self.reader.close()
            log.info("GeoIP database reader closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Singleton instance
_geoip_service: Optional[GeoIPService] = None


def get_geoip_service() -> GeoIPService:
    """
    Get singleton GeoIP service instance.

    Returns:
        GeoIPService instance
    """
    global _geoip_service
    if _geoip_service is None:
        _geoip_service = GeoIPService()
    return _geoip_service
