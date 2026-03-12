# tests/api/test_meta_kpi_catalog.py
"""
API tests for GET /api/meta/kpi-catalog.

Validates:
- Public access (no auth required)
- Response matches get_catalog_api_response()
- Cache-Control header present
- Response shape stability
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
class TestMetaKpiCatalog:

    async def test_public_access_no_auth(self, client: AsyncClient):
        """Endpoint must be accessible without authentication."""
        response = await client.get("/api/meta/kpi-catalog")
        assert response.status_code == 200

    async def test_response_is_list_of_8(self, client: AsyncClient):
        response = await client.get("/api/meta/kpi-catalog")
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 8

    async def test_response_matches_catalog(self, client: AsyncClient):
        """API response must be byte-identical to get_catalog_api_response()."""
        from app.services.kpi_catalog import get_catalog_api_response

        response = await client.get("/api/meta/kpi-catalog")
        data = response.json()
        expected = get_catalog_api_response()

        # Sort both by code for stable comparison
        data_sorted = sorted(data, key=lambda x: x["code"])
        expected_sorted = sorted(expected, key=lambda x: x["code"])

        assert data_sorted == expected_sorted

    async def test_cache_control_header(self, client: AsyncClient):
        response = await client.get("/api/meta/kpi-catalog")
        cc = response.headers.get("cache-control", "")
        assert "public" in cc
        assert "max-age=86400" in cc

    async def test_response_entry_shape(self, client: AsyncClient):
        """Each entry must have the exact expected fields."""
        response = await client.get("/api/meta/kpi-catalog")
        data = response.json()

        expected_top_keys = {
            "code", "display_name", "unit", "period_type",
            "default_value", "higher_is_better", "actual_kind",
            "comparison", "display_aliases",
        }
        expected_comparison_keys = {
            "comparable", "requires_period_match", "target_period", "caveat",
        }
        expected_alias_keys = {
            "dashboard", "planning", "config", "annual_progress",
        }

        for entry in data:
            assert set(entry.keys()) == expected_top_keys, f"Wrong keys for {entry.get('code')}"
            assert set(entry["comparison"].keys()) == expected_comparison_keys
            assert set(entry["display_aliases"].keys()) == expected_alias_keys

    async def test_codes_match_canonical_set(self, client: AsyncClient):
        response = await client.get("/api/meta/kpi-catalog")
        data = response.json()
        codes = {entry["code"] for entry in data}
        assert codes == {
            "consultations_daily", "conversion_rate", "win_rate",
            "response_time_hours", "enrollments_monthly", "enrollments_annual",
            "sla_compliance_rate", "consultation_effectiveness",
        }

    async def test_no_internal_fields_exposed(self, client: AsyncClient):
        """plan_field and config_source are backend-internal."""
        response = await client.get("/api/meta/kpi-catalog")
        data = response.json()
        for entry in data:
            assert "plan_field" not in entry
            assert "config_source" not in entry
