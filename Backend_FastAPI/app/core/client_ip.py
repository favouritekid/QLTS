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
    """Return the real client IP for per-IP rate limits / hashing.

    Prefer ``X-Real-IP`` (nginx sets it to ``$remote_addr`` and OVERWRITES any
    client-supplied value — see default.conf.template:82), so it is NOT
    spoofable. Fall back to the first ``X-Forwarded-For`` hop (note: nginx uses
    ``$proxy_add_x_forwarded_for`` which APPENDS, so the first hop is
    client-controlled and spoofable — only used when X-Real-IP is absent, e.g.
    no nginx in front), then ``request.client.host``.

    Single trusted nginx hop only. A multi-proxy topology (CDN→nginx→backend)
    would make X-Real-IP the CDN IP — revisit then.
    """
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
