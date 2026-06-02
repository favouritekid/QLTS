"""PR1 Commit 5 anchor: payment return_url allowlist + MoMo IPN host guard
(A01 open-redirect / A06 SSRF).

build_safe_return_url normalizes/allowlists the client-supplied return_url
(the gateway echoes it back to the user), and the MoMo IPN URL is derived
from the trusted PUBLIC_BACKEND_URL instead of that return_url.
"""
from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.config import settings
from app.gateways.momo import MoMoAdapter
from app.services.payment_intent_service import build_safe_return_url
from app.utils.exceptions import BusinessRuleViolation

CANONICAL = f"{settings.FRONTEND_URL.rstrip('/')}/finance/payments/return"


def test_none_or_empty_returns_canonical_default():
    assert build_safe_return_url(None) == CANONICAL
    assert build_safe_return_url("") == CANONICAL


def test_same_origin_return_url_kept():
    url = f"{settings.FRONTEND_URL.rstrip('/')}/finance/payments/return?x=1"
    assert build_safe_return_url(url) == url


def test_foreign_host_rejected():
    with pytest.raises(BusinessRuleViolation):
        build_safe_return_url("https://attacker.evil/finance/payments/return")


def test_suffix_confusion_host_rejected():
    # A naive `FRONTEND_URL in url` / startswith check would ACCEPT this
    # look-alike host; the netloc tuple compare must reject it.
    p = urlparse(settings.FRONTEND_URL)
    attack = f"{p.scheme}://{p.netloc}.evil.com/finance/payments/return"
    with pytest.raises(BusinessRuleViolation):
        build_safe_return_url(attack)


def test_userinfo_host_rejected():
    # The real host is after '@' (evil.com); a naive substring check would see
    # the FRONTEND host in the userinfo and wrongly accept it.
    p = urlparse(settings.FRONTEND_URL)
    attack = f"{p.scheme}://{p.netloc}@evil.com/finance/payments/return"
    with pytest.raises(BusinessRuleViolation):
        build_safe_return_url(attack)


def test_scheme_mismatch_rejected():
    # Origin is scheme+host; same host but a different scheme is rejected.
    p = urlparse(settings.FRONTEND_URL)
    other = "https" if p.scheme == "http" else "http"
    with pytest.raises(BusinessRuleViolation):
        build_safe_return_url(f"{other}://{p.netloc}/finance/payments/return")


def test_momo_ipn_url_from_public_backend_not_return_url():
    adapter = MoMoAdapter(
        partner_code="P",
        access_key="A",
        secret_key="S",
        public_backend_url="https://backend.test",
    )
    assert adapter._build_ipn_url() == (
        "https://backend.test/api/payments/callback/momo"
    )


def test_momo_from_settings_wires_public_backend_url():
    adapter = MoMoAdapter.from_settings(settings)
    assert adapter.public_backend_url == settings.PUBLIC_BACKEND_URL


def test_register_default_gateways_wires_momo_public_backend_url(monkeypatch):
    # The REAL runtime registration path (NOT from_settings) must also wire
    # public_backend_url — else the IPN URL loses its host and the SSRF guard
    # is silently defeated. Regression lock for the gate finding.
    from app.services.payment_intent_service import (
        PaymentIntentService,
        register_default_gateways,
    )

    monkeypatch.setattr(settings, "MOMO_PARTNER_CODE", "P")
    monkeypatch.setattr(settings, "MOMO_ACCESS_KEY", "A")
    monkeypatch.setattr(settings, "MOMO_SECRET_KEY", "S")
    monkeypatch.setattr(settings, "MOMO_ENDPOINT", "https://momo.test")
    monkeypatch.setattr(settings, "PUBLIC_BACKEND_URL", "https://backend.test")

    service = PaymentIntentService(None)
    register_default_gateways(service)

    adapter = service._gateway_adapters.get("momo")
    assert adapter is not None, "momo must register when creds are set"
    assert adapter.public_backend_url == "https://backend.test"
    assert adapter._build_ipn_url() == (
        "https://backend.test/api/payments/callback/momo"
    )
