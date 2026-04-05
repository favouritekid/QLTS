# app/models/zalo_token_store.py
"""
Zalo Token Store — persistent backup for OAuth tokens.

Redis is the primary token store (fast reads, TTL-based expiry).
This DB table provides crash recovery: if Redis loses tokens on restart,
the gateway reloads from this singleton row.

Phase C1: One row per OA (currently single-OA, enforced by unique oa_id).
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from .base import Base


class ZaloTokenStore(Base):
    __tablename__ = "zalo_token_store"

    id = Column(Integer, primary_key=True, index=True)

    # OA identifier (unique — one row per OA)
    oa_id = Column(
        String(50), nullable=False, unique=True,
        comment="Zalo OA ID — unique per OA",
    )

    # OAuth tokens
    access_token = Column(
        Text, nullable=False,
        comment="Current Zalo OA access token",
    )
    refresh_token = Column(
        Text, nullable=False,
        comment="Current Zalo OA refresh token (single-use, rotated on each refresh)",
    )

    # Expiry tracking
    access_token_expires_at = Column(
        DateTime(timezone=True), nullable=False,
        comment="When the access token expires (typically 25 hours after refresh)",
    )
    refresh_token_expires_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When the refresh token expires (typically 3 months)",
    )

    # Audit
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ZaloTokenStore oa_id={self.oa_id} "
            f"expires_at={self.access_token_expires_at}>"
        )
