"""Hotfix R8 (Phase 3 close-out): X-Forwarded-For aware client IP utility.

Behind nginx (production setup, see ``nginx/conf.d/default.conf.template:60-61``),
``request.client.host`` is always the nginx container IP. Per-IP rate limits keyed
on ``request.client.host`` collapse to a single bucket shared by ALL real clients,
which blew the legacy ``/api/admissions/confirm/{token}`` ``100/day`` cap into a
prod-wide ceiling.

This helper trusts ``X-Forwarded-For`` because:

  - Direct backend port (``8000``) is bound inside the docker network only; the
    only path from the public internet is nginx → backend, and nginx always sets
    the header (verified in default.conf.template).
  - The first hop in XFF is the original client (per RFC 7239 / nginx
    ``$proxy_add_x_forwarded_for`` semantics).

If the deployment topology changes (e.g. backend exposed directly, additional
proxy layer in front of nginx), revisit this helper — XFF spoofing becomes
reachable.
"""
from __future__ import annotations

from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """Return the first hop in ``X-Forwarded-For`` (real client) or fall back
    to ``request.client.host`` when the header is absent.

    Used as ``key_func`` for slowapi per-IP limits; correctness matters because
    ``request.client.host`` is the nginx container IP in production.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
