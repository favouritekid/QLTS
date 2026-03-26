"""
Phase E2: Template Per Action — Unit Tests

Covers:
  - Action with template_code renders from template (dispatcher)
  - Action without template_code falls back to rule defaults (dispatcher)
  - Invalid template_code rejected when creating/updating rule (CRUD)
  - Template that doesn't support channel rejected (CRUD)

Strategy: test component functions directly (helpers, services, repos)
using mock/patch pattern following existing C2 test conventions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# E2-1: _render_template_snapshot helper
# ---------------------------------------------------------------------------

class TestRenderTemplateSnapshot:
    """Test the per-action template rendering helper in the dispatcher."""

    def _make_template(self, **overrides):
        tpl = MagicMock()
        tpl.title_template = overrides.get("title_template", "TPL Title: $lead_name")
        tpl.message_template = overrides.get("message_template", "TPL Msg for $lead_name")
        tpl.link_template = overrides.get("link_template", "/leads/$lead_id")
        tpl.template_code = overrides.get("template_code", "TPL_TEST")
        tpl.supported_channels = overrides.get("supported_channels", ["browser", "email"])
        return tpl

    def test_render_from_template(self):
        from app.services.notification_dispatcher import _render_template_snapshot

        tpl = self._make_template()
        payload = {"lead_name": "Nguyen Van A", "lead_id": "42"}
        fallback = {"title": "fallback", "message": "fallback", "link": None, "type": "info"}

        result = _render_template_snapshot(tpl, payload, fallback)

        assert result["title"] == "TPL Title: Nguyen Van A"
        assert result["message"] == "TPL Msg for Nguyen Van A"
        assert result["link"] == "/leads/42"
        assert result["type"] == "info"

    def test_render_preserves_type_from_fallback(self):
        from app.services.notification_dispatcher import _render_template_snapshot

        tpl = self._make_template()
        payload = {"lead_name": "Test"}
        fallback = {"title": "x", "message": "x", "link": None, "type": "warning"}

        result = _render_template_snapshot(tpl, payload, fallback)
        assert result["type"] == "warning"

    def test_render_unresolved_placeholder_kept(self):
        """safe_substitute leaves $unknown as-is."""
        from app.services.notification_dispatcher import _render_template_snapshot

        tpl = self._make_template(title_template="Hello $unknown_var")
        payload = {"lead_name": "Test"}
        fallback = {"title": "fb", "message": "fb", "link": None, "type": "info"}

        result = _render_template_snapshot(tpl, payload, fallback)
        assert "$unknown_var" in result["title"]

    def test_render_none_link_template_uses_fallback(self):
        from app.services.notification_dispatcher import _render_template_snapshot

        tpl = self._make_template(link_template=None)
        payload = {"lead_name": "Test"}
        fallback = {"title": "x", "message": "x", "link": "/fallback/link", "type": "info"}

        result = _render_template_snapshot(tpl, payload, fallback)
        assert result["link"] == "/fallback/link"

    def test_render_empty_title_template_uses_fallback(self):
        from app.services.notification_dispatcher import _render_template_snapshot

        tpl = self._make_template(title_template="")
        payload = {"lead_name": "Test"}
        fallback = {"title": "Fallback Title", "message": "x", "link": None, "type": "info"}

        result = _render_template_snapshot(tpl, payload, fallback)
        assert result["title"] == "Fallback Title"


# ---------------------------------------------------------------------------
# E2-2: _resolve_action_templates helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestResolveActionTemplates:
    """Test pre-fetching templates for actions with template_code."""

    def _make_action(self, **overrides):
        a = MagicMock()
        a.step = overrides.get("step", 1)
        a.channel = overrides.get("channel", "browser")
        a.template_code = overrides.get("template_code", None)
        a.delay_minutes = overrides.get("delay_minutes", 0)
        a.config = overrides.get("config", None)
        return a

    def _make_template(self, code="TPL_TEST"):
        tpl = MagicMock()
        tpl.template_code = code
        tpl.title_template = f"Title from {code}"
        tpl.message_template = f"Message from {code}"
        tpl.link_template = f"/link/{code}"
        tpl.supported_channels = ["browser", "email"]
        return tpl

    async def test_no_template_codes_returns_empty(self):
        from app.services.notification_dispatcher import _resolve_action_templates

        actions = [self._make_action(template_code=None)]
        db = AsyncMock()

        result = await _resolve_action_templates(db, actions)
        assert result == {}

    async def test_valid_template_code_returns_template(self):
        from app.services.notification_dispatcher import _resolve_action_templates

        tpl = self._make_template("TPL_EMAIL")
        actions = [self._make_action(template_code="TPL_EMAIL", channel="email")]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=tpl)

        with patch(
            "app.services.notification_dispatcher.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            result = await _resolve_action_templates(AsyncMock(), actions)

        assert "TPL_EMAIL" in result
        assert result["TPL_EMAIL"] == tpl

    async def test_missing_template_code_returns_empty(self):
        from app.services.notification_dispatcher import _resolve_action_templates

        actions = [self._make_action(template_code="DOES_NOT_EXIST", channel="email")]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=None)

        with patch(
            "app.services.notification_dispatcher.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            result = await _resolve_action_templates(AsyncMock(), actions)

        assert result == {}

    async def test_multiple_actions_same_code_fetched_once(self):
        """Distinct codes should each be fetched once."""
        from app.services.notification_dispatcher import _resolve_action_templates

        tpl = self._make_template("TPL_SHARED")
        actions = [
            self._make_action(template_code="TPL_SHARED", channel="browser", step=1),
            self._make_action(template_code="TPL_SHARED", channel="email", step=2),
        ]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=tpl)

        with patch(
            "app.services.notification_dispatcher.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            result = await _resolve_action_templates(AsyncMock(), actions)

        # Only one unique code -> one fetch
        assert mock_repo.get_by_template_code.call_count == 1
        assert "TPL_SHARED" in result

    async def test_db_error_returns_empty_for_that_code(self):
        from app.services.notification_dispatcher import _resolve_action_templates

        actions = [self._make_action(template_code="TPL_FAIL", channel="email")]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(side_effect=Exception("DB error"))

        with patch(
            "app.services.notification_dispatcher.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            result = await _resolve_action_templates(AsyncMock(), actions)

        assert result == {}


# ---------------------------------------------------------------------------
# E2-3: CRUD validation — _validate_action_template_codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestValidateActionTemplateCodes:
    """Test async template_code validation in CRUD service."""

    def _make_action(self, **overrides):
        a = MagicMock()
        a.step = overrides.get("step", 1)
        a.channel = overrides.get("channel", "browser")
        a.template_code = overrides.get("template_code", None)
        a.delay_minutes = overrides.get("delay_minutes", 0)
        a.config = overrides.get("config", None)
        return a

    def _make_template(self, code="TPL_TEST", channels=None):
        tpl = MagicMock()
        tpl.template_code = code
        tpl.supported_channels = channels or ["browser", "email"]
        return tpl

    async def test_no_template_code_passes(self):
        """Actions without template_code should pass validation."""
        from app.services.notification_rule_crud_service import _validate_action_template_codes

        actions = [self._make_action(template_code=None)]
        # Should not raise
        await _validate_action_template_codes(AsyncMock(), actions)

    async def test_valid_template_code_passes(self):
        from app.services.notification_rule_crud_service import _validate_action_template_codes

        tpl = self._make_template("TPL_VALID", channels=["browser", "email"])
        actions = [self._make_action(template_code="TPL_VALID", channel="browser")]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=tpl)

        with patch(
            "app.services.notification_rule_crud_service.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            # Should not raise
            await _validate_action_template_codes(AsyncMock(), actions)

    async def test_nonexistent_template_code_raises(self):
        from app.services.notification_rule_crud_service import _validate_action_template_codes
        from app.utils.exceptions import BadRequest

        actions = [self._make_action(template_code="DOES_NOT_EXIST", channel="browser", step=1)]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=None)

        with patch(
            "app.services.notification_rule_crud_service.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            with pytest.raises(BadRequest, match="does not exist"):
                await _validate_action_template_codes(AsyncMock(), actions)

    async def test_template_unsupported_channel_raises(self):
        from app.services.notification_rule_crud_service import _validate_action_template_codes
        from app.utils.exceptions import BadRequest

        # Template supports only ["email"], but action wants "zalo"
        tpl = self._make_template("TPL_EMAIL_ONLY", channels=["email"])
        actions = [self._make_action(template_code="TPL_EMAIL_ONLY", channel="zalo", step=1)]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=tpl)

        with patch(
            "app.services.notification_rule_crud_service.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            with pytest.raises(BadRequest, match="does not support channel"):
                await _validate_action_template_codes(AsyncMock(), actions)

    async def test_empty_actions_passes(self):
        from app.services.notification_rule_crud_service import _validate_action_template_codes

        await _validate_action_template_codes(AsyncMock(), [])
        await _validate_action_template_codes(AsyncMock(), None)

    async def test_multiple_actions_mixed_template_codes(self):
        """One action with template_code, one without. Only the coded one is validated."""
        from app.services.notification_rule_crud_service import _validate_action_template_codes

        tpl = self._make_template("TPL_BROWSER", channels=["browser"])
        actions = [
            self._make_action(template_code="TPL_BROWSER", channel="browser", step=1),
            self._make_action(template_code=None, channel="email", step=2),
        ]

        mock_repo = MagicMock()
        mock_repo.get_by_template_code = AsyncMock(return_value=tpl)

        with patch(
            "app.services.notification_rule_crud_service.NotificationTemplateRepository",
            return_value=mock_repo,
        ):
            # Should not raise — email action has no template_code
            await _validate_action_template_codes(AsyncMock(), actions)

        # Only called once (for the browser action)
        mock_repo.get_by_template_code.assert_called_once_with("TPL_BROWSER")


# ---------------------------------------------------------------------------
# E2-4: CRUD create/update calls template validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCRUDIntegration:
    """Verify create_rule and update_rule invoke template_code validation."""

    async def test_create_rule_with_invalid_template_code_raises(self):
        """create_rule should reject actions with nonexistent template_code."""
        from app.services.notification_rule_crud_service import create_rule
        from app.utils.exceptions import BadRequest

        rule_data = MagicMock()
        rule_data.event = "LEAD_ASSIGNED"
        rule_data.actions = [MagicMock(
            step=1, channel="browser", template_code="INVALID_CODE",
            delay_minutes=0, config=None,
        )]
        rule_data.template_id = None
        rule_data.model_dump = MagicMock(return_value={})

        mock_rule_repo = MagicMock()
        mock_rule_repo.get_by_event = AsyncMock(return_value=None)

        mock_tpl_repo = MagicMock()
        mock_tpl_repo.get_by_template_code = AsyncMock(return_value=None)

        with patch(
            "app.services.notification_rule_crud_service.NotificationRuleRepository",
            return_value=mock_rule_repo,
        ), patch(
            "app.services.notification_rule_crud_service.NotificationTemplateRepository",
            return_value=mock_tpl_repo,
        ):
            with pytest.raises(BadRequest, match="does not exist"):
                await create_rule(AsyncMock(), rule_data)

    async def test_create_rule_without_template_code_passes_validation(self):
        """create_rule with actions that have no template_code should pass."""
        from app.services.notification_rule_crud_service import create_rule

        rule_data = MagicMock()
        rule_data.event = "LEAD_ASSIGNED"
        rule_data.actions = [MagicMock(
            step=1, channel="browser", template_code=None,
            delay_minutes=0, config=None,
        )]
        rule_data.template_id = None
        rule_data.channels = []
        rule_data.model_dump = MagicMock(return_value={})

        new_rule = MagicMock()
        new_rule.id = 1
        new_rule.event = "LEAD_ASSIGNED"

        mock_rule_repo = MagicMock()
        mock_rule_repo.get_by_event = AsyncMock(return_value=None)
        mock_rule_repo.create_with_actions = AsyncMock(return_value=new_rule)

        with patch(
            "app.services.notification_rule_crud_service.NotificationRuleRepository",
            return_value=mock_rule_repo,
        ), patch(
            "app.services.notification_rule_crud_service.invalidate_rule_cache",
            new_callable=AsyncMock,
        ):
            result, callback = await create_rule(AsyncMock(), rule_data)

        assert result.id == 1


# ---------------------------------------------------------------------------
# E2-5: _validate_actions sync checks still work (no regression)
# ---------------------------------------------------------------------------

class TestValidateActionsSyncNoRegression:
    """Ensure sync validation still catches step/channel duplicates."""

    def test_duplicate_step_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.utils.exceptions import BadRequest

        actions = [
            MagicMock(step=1, channel="browser", delay_minutes=0, template_code=None, config=None),
            MagicMock(step=1, channel="email", delay_minutes=0, template_code=None, config=None),
        ]
        with pytest.raises(BadRequest, match="Duplicate step"):
            _validate_actions(actions)

    def test_duplicate_channel_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.utils.exceptions import BadRequest

        actions = [
            MagicMock(step=1, channel="browser", delay_minutes=0, template_code=None, config=None),
            MagicMock(step=2, channel="browser", delay_minutes=0, template_code=None, config=None),
        ]
        with pytest.raises(BadRequest, match="Duplicate channel"):
            _validate_actions(actions)

    def test_negative_delay_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.utils.exceptions import BadRequest

        actions = [
            MagicMock(step=1, channel="browser", delay_minutes=-5, template_code=None, config=None),
        ]
        with pytest.raises(BadRequest, match="delay_minutes must be >= 0"):
            _validate_actions(actions)

    def test_noncontiguous_steps_rejected(self):
        from app.services.notification_rule_crud_service import _validate_actions
        from app.utils.exceptions import BadRequest

        actions = [
            MagicMock(step=1, channel="browser", delay_minutes=0, template_code=None, config=None),
            MagicMock(step=3, channel="email", delay_minutes=0, template_code=None, config=None),
        ]
        with pytest.raises(BadRequest, match="contiguous"):
            _validate_actions(actions)

    def test_template_code_no_longer_rejected_in_sync_validation(self):
        """Phase E2: template_code is now allowed (validated async)."""
        from app.services.notification_rule_crud_service import _validate_actions

        actions = [
            MagicMock(step=1, channel="browser", delay_minutes=0, template_code="TPL_TEST", config=None),
        ]
        # Should NOT raise (was previously rejected as "deferred to D8")
        _validate_actions(actions)
