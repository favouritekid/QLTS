"""PR1 Commit 6 (+ C5) anchor: _validate_production_secrets fails fast on
missing/weak payment + MFA config in production (A02 / A04).

Sets every earlier prod check to a valid value so the validator reaches the
specific check under test, then asserts the RuntimeError.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import settings


def _set_valid_prod(monkeypatch):
    """Make every prod check except the one under test pass."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "s" * 40)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "j" * 40)
    monkeypatch.setattr(settings, "DEVICE_FINGERPRINT_SALT", "real-salt-value")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@remote/db?sslmode=require",
    )
    monkeypatch.setattr(settings, "ALLOW_DOCKER_INTERNAL_NETWORK", True)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.prod")
    monkeypatch.setattr(settings, "PUBLIC_BACKEND_URL", "https://backend.prod")
    monkeypatch.setattr(
        settings, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


def test_valid_production_config_passes(monkeypatch):
    _set_valid_prod(monkeypatch)
    settings._validate_production_secrets()  # must not raise


def test_mfa_encryption_key_required(monkeypatch):
    _set_valid_prod(monkeypatch)
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="MFA_ENCRYPTION_KEY"):
        settings._validate_production_secrets()


def test_mfa_encryption_key_must_be_valid_fernet(monkeypatch):
    _set_valid_prod(monkeypatch)
    # Non-empty but NOT a valid Fernet key (32 url-safe base64 bytes) — would
    # pass a naive "is set" check yet crash MFA at runtime.
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(RuntimeError, match="MFA_ENCRYPTION_KEY"):
        settings._validate_production_secrets()


def test_frontend_url_must_be_https(monkeypatch):
    _set_valid_prod(monkeypatch)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")
    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        settings._validate_production_secrets()


def test_public_backend_url_must_be_https(monkeypatch):
    _set_valid_prod(monkeypatch)
    monkeypatch.setattr(settings, "PUBLIC_BACKEND_URL", "http://backend.prod")
    with pytest.raises(RuntimeError, match="PUBLIC_BACKEND_URL"):
        settings._validate_production_secrets()
