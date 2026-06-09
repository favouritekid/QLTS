"""BR3: officer-reset Casbin policy — template ↔ migration agreement lock.

Route officer RESET (``POST /api/admissions/{id}/documents/{doc_code}/reset``)
phải vừa nằm trong ``OFFICER_TEMPLATE`` (dev/test auto-seed dựa vào đây) VỪA
được migration ``resetcasbin01`` seed (prod — auto-sync template TẮT). Nếu một
bên thiếu → dev PASS nhưng prod officer-reset 403 (bug ẩn dev-prod). Test này
khóa cả hai khớp nhau.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from app.casbin_config.policy_templates import OFFICER_TEMPLATE


RESET_ROUTE = "/api/admissions/{id}/documents/{doc_code}/reset"

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "resetcasbin01_20260609_officer_reset_casbin.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "resetcasbin01_mig", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_officer_template_grants_reset_route():
    """OFFICER_TEMPLATE phải cấp route reset (dev/test auto-seed dựa vào đây)."""
    matches = [
        p
        for p in OFFICER_TEMPLATE["policies"]
        if p.get("object") == RESET_ROUTE and p.get("action") == "POST"
    ]
    assert matches, (
        "OFFICER_TEMPLATE thiếu route reset → dev/test auto-seed không cấp "
        "officer reset (trong khi prod migration lại có → drift)."
    )


def test_migration_seeds_officer_reset_with_eft():
    """Migration seed đúng 1 row role:officer reset + eft='allow' (v3 bắt buộc)."""
    mig = _load_migration()
    assert mig._OFFICER_RESET_POLICIES == [
        ("role:officer", RESET_ROUTE, "POST", "allow")
    ], mig._OFFICER_RESET_POLICIES
    assert mig.revision == "resetcasbin01"
    assert mig.down_revision == "ampfix01_20260609"


def test_template_and_migration_agree_on_route():
    """Route reset trong migration phải có trong OFFICER_TEMPLATE (chống drift)."""
    mig = _load_migration()
    mig_routes = {row[1] for row in mig._OFFICER_RESET_POLICIES}
    tmpl_routes = {
        p["object"]
        for p in OFFICER_TEMPLATE["policies"]
        if p.get("action") == "POST" and p.get("object", "").endswith("/reset")
    }
    assert mig_routes <= tmpl_routes, (
        f"migration route {mig_routes} không có trong OFFICER_TEMPLATE {tmpl_routes}"
    )
