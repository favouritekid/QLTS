# app/models/user_session.py
"""
Model for tracking user sessions to detect unauthorized access and manage active devices.
"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from .base import Base


class UserSession(Base):
    """
    Model để tracking các session đang hoạt động.
    
    Mỗi session tương ứng với một refresh token và device/browser cụ thể.
    Được sử dụng để:
    - Hiển thị danh sách active sessions cho user
    - Phát hiện login từ IP/device mới (anomaly detection)
    - Cho phép user revoke sessions từ devices cụ thể
    - Audit trail cho security events
    """
    __tablename__ = "user_session"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Session identification
    # refresh_jti là unique identifier cho mỗi refresh token
    # Khi refresh token được rotate, refresh_jti cũng được update
    refresh_jti = Column(String(36), unique=True, nullable=False, index=True)
    
    # Device/Browser info (extracted from User-Agent header)
    ip_address = Column(String(45), nullable=True)  # IPv6 support (max 45 chars)
    user_agent = Column(String(512), nullable=True)  # Full User-Agent string
    device_type = Column(String(50), nullable=True)  # mobile, desktop, tablet
    browser = Column(String(100), nullable=True)  # e.g., "Chrome 120.0"
    os = Column(String(100), nullable=True)  # e.g., "Windows 10"
    
    # Location (optional, requires IP geolocation service like MaxMind GeoIP2)
    country = Column(String(100), nullable=True)  # e.g., "Vietnam"
    city = Column(String(100), nullable=True)  # e.g., "Ho Chi Minh City"
    
    # Session lifecycle
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False
    )
    
    # Security flags
    is_suspicious = Column(Boolean, default=False, nullable=False)  # Flagged by anomaly detection
    revoked_at = Column(DateTime(timezone=True), nullable=True)  # NULL = active, NOT NULL = revoked
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    
    def __repr__(self) -> str:
        return (
            f"<UserSession(id={self.id}, user_id={self.user_id}, "
            f"device={self.device_type}, ip={self.ip_address}, "
            f"active={self.revoked_at is None})>"
        )
    
    @property
    def is_active(self) -> bool:
        """Check if session is still active (not revoked and not expired)."""
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and self.expires_at > now
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

