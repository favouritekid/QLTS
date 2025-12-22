# app/models/login_history.py
"""
Model for tracking user login history to detect suspicious access patterns.

Following Architecture Guidelines:
- Model only defines data structure
- No business logic
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class LoginHistory(Base):
    """
    Model để lưu lịch sử đăng nhập.
    
    Khác với UserSession (chỉ lưu active sessions và bị xóa khi revoke),
    LoginHistory lưu TẤT CẢ login attempts để:
    - Phát hiện login từ IP/device mới (anomaly detection)
    - Audit trail cho security events
    - Cho phép user xem lịch sử login và phát hiện xâm nhập
    """

    __tablename__ = "login_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Login timestamp
    login_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # IP/Location info
    ip_address = Column(String(45), nullable=True)  # IPv6 support
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)

    # Device/Browser info (extracted from User-Agent header)
    device_type = Column(String(50), nullable=True)  # mobile, desktop, tablet
    browser = Column(String(100), nullable=True)  # e.g., "Chrome 120.0"
    os = Column(String(100), nullable=True)  # e.g., "Windows 10"

    # Anomaly flags (calculated at login time)
    is_new_ip = Column(Boolean, default=False, nullable=False)
    is_new_device = Column(Boolean, default=False, nullable=False)
    is_new_location = Column(Boolean, default=False, nullable=False)
    
    # Risk score (0-100, calculated based on anomaly flags)
    risk_score = Column(Integer, default=0, nullable=False)

    # User response for suspicious logins
    # NULL = pending, 'confirmed' = user verified, 'secured' = user secured account
    user_response = Column(String(20), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    # OAuth provider if social login (NULL = username/password)
    oauth_provider = Column(String(20), nullable=True)  # 'google' | 'facebook' | NULL

    # Relationships
    user = relationship("User", back_populates="login_history")

    def __repr__(self) -> str:
        return (
            f"<LoginHistory(id={self.id}, user_id={self.user_id}, "
            f"ip={self.ip_address}, login_at={self.login_at})>"
        )

    @property
    def is_suspicious(self) -> bool:
        """Check if this login has any anomaly flags."""
        return self.is_new_ip or self.is_new_device or self.is_new_location

    @property
    def is_pending_review(self) -> bool:
        """Check if user hasn't responded to this suspicious login."""
        return self.is_suspicious and self.user_response is None
