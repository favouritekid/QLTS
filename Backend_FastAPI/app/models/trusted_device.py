# app/models/trusted_device.py
"""
TrustedDevice model for login security.

When a user marks a device as "trusted", future logins from that device
will not trigger suspicious login alerts, even if the IP changes.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


class TrustedDevice(Base):
    """
    Trusted device for a user.
    
    When a device is trusted:
    - No "new device" alerts will be triggered
    - Reduced risk score for logins from this device
    - User can optionally name the device for easy identification
    """
    __tablename__ = "trusted_device"
    
    # Unique constraint for user + device fingerprint
    __table_args__ = (
        UniqueConstraint("user_id", "device_fingerprint", name="uq_trusted_device_user_fingerprint"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # Device fingerprint (hash of browser + OS + other stable attributes)
    device_fingerprint = Column(String(64), nullable=False, index=True)
    
    # User-friendly device name (e.g., "My Work Laptop", "iPhone 15")
    name = Column(String(100), nullable=True)
    
    # Browser and OS info (for display purposes)
    browser = Column(String(100), nullable=True)
    os = Column(String(100), nullable=True)
    
    # When this device was first seen and trusted
    first_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    trusted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    
    # Last login from this device
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    # IP address when trust was established (for audit)
    trusted_from_ip = Column(String(45), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="trusted_devices")

    def __repr__(self) -> str:
        return (
            f"<TrustedDevice(id={self.id}, user_id={self.user_id}, "
            f"name={self.name}, fingerprint={self.device_fingerprint[:8]}...)>"
        )

    def update_last_used(self) -> None:
        """Update the last_used_at timestamp."""
        self.last_used_at = datetime.now(timezone.utc)
