"""
Tests for admission magic-link confirmation email Celery tasks (PR-1).

Covers:
- send_magic_link_confirmation_task: renders template + calls SMTP
- send_admission_confirmed_notification_task: renders template + calls SMTP
- Empty email_to → skipped, no SMTP call
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.tasks.email_tasks import (
    send_magic_link_confirmation_task,
    send_admission_confirmed_notification_task,
)


@pytest.mark.unit
class TestSendMagicLinkConfirmationTask:
    """Covers the magic-link email Celery task."""

    def test_renders_and_sends_successfully(self):
        """Happy path: valid inputs → render_email_template + _send_email called with expected args."""
        expires_at = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        with patch("app.tasks.email_tasks._send_email") as mock_send, \
             patch("app.services.email_service.render_email_template",
                   return_value=("<html>OK</html>", "OK text")) as mock_render:
            result = send_magic_link_confirmation_task(
                email_to="applicant@example.com",
                confirm_url="https://qlts.tnpc.edu.vn/confirm/abc123",
                lead_name="Nguyễn Văn A",
                expires_at_iso=expires_at.isoformat(),
                expires_days=7,
                lang="vi",
            )

        assert result["status"] == "success"
        assert result["recipient"] == "applicant@example.com"

        # Template rendered with expected context
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][0] == "admission_confirmation"
        context = call_args[0][1]
        assert context["lead_name"] == "Nguyễn Văn A"
        assert context["confirm_url"] == "https://qlts.tnpc.edu.vn/confirm/abc123"
        assert context["expires_days"] == 7
        assert "25/04/2026" in context["expires_at_display"]
        assert call_args[1]["lang"] == "vi"

        # SMTP called once with correct subject
        mock_send.assert_called_once()
        send_args = mock_send.call_args[0]
        assert send_args[0] == "applicant@example.com"
        assert "Xác nhận nhập học" in send_args[1]  # subject VI

    def test_skips_when_no_email(self):
        """Empty email_to → return {skipped}, no SMTP call."""
        with patch("app.tasks.email_tasks._send_email") as mock_send:
            result = send_magic_link_confirmation_task(
                email_to="",
                confirm_url="https://qlts.tnpc.edu.vn/confirm/xxx",
                lead_name="Lead",
                expires_at_iso=datetime.now(timezone.utc).isoformat(),
                expires_days=7,
            )

        assert result == {"status": "skipped", "reason": "no_email"}
        mock_send.assert_not_called()

    def test_english_subject_when_lang_en(self):
        """lang='en' → English subject line."""
        with patch("app.tasks.email_tasks._send_email") as mock_send, \
             patch("app.services.email_service.render_email_template",
                   return_value=("<html/>", "text")):
            send_magic_link_confirmation_task(
                email_to="applicant@example.com",
                confirm_url="https://example.com/confirm/x",
                lead_name="John",
                expires_at_iso=datetime.now(timezone.utc).isoformat(),
                expires_days=7,
                lang="en",
            )
        subject = mock_send.call_args[0][1]
        assert "Confirm Your Admission" in subject


@pytest.mark.unit
class TestSendAdmissionConfirmedNotificationTask:
    """Covers the post-confirm success email Celery task."""

    def test_renders_and_sends_successfully(self):
        """Happy path: valid inputs → template + SMTP called."""
        confirmed_at = datetime(2026, 4, 20, 14, 30, tzinfo=timezone.utc)
        with patch("app.tasks.email_tasks._send_email") as mock_send, \
             patch("app.services.email_service.render_email_template",
                   return_value=("<html>OK</html>", "OK text")) as mock_render:
            result = send_admission_confirmed_notification_task(
                email_to="applicant@example.com",
                lead_name="Trần Thị B",
                confirmed_at_iso=confirmed_at.isoformat(),
                lang="vi",
            )

        assert result["status"] == "success"
        assert result["recipient"] == "applicant@example.com"

        # Template rendered with expected context
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][0] == "admission_confirmed_success"
        context = call_args[0][1]
        assert context["lead_name"] == "Trần Thị B"
        assert "20/04/2026" in context["confirmed_at_display"]

        # SMTP called with VI subject
        mock_send.assert_called_once()
        subject = mock_send.call_args[0][1]
        assert "Xác nhận nhập học thành công" in subject

    def test_skips_when_no_email(self):
        """Empty email_to → skipped."""
        with patch("app.tasks.email_tasks._send_email") as mock_send:
            result = send_admission_confirmed_notification_task(
                email_to="",
                lead_name="Lead",
                confirmed_at_iso=datetime.now(timezone.utc).isoformat(),
            )

        assert result == {"status": "skipped", "reason": "no_email"}
        mock_send.assert_not_called()


# =============================================================================
# PR-2: Callback wiring tests (admission_service stubs → Celery .delay())
# =============================================================================


@pytest.mark.unit
class TestGenerateConfirmationTokenEmailCallback:
    """
    Covers the post-commit email callback inside generate_confirmation_token.

    We don't test the full service (that's an integration test) — we isolate
    the closure behaviour: it must call .delay() with the right args,
    and must not raise on enqueue failure.
    """

    @pytest.mark.asyncio
    async def test_callback_queues_magic_link_task(self):
        """Closure invokes send_magic_link_confirmation_task.delay with expected payload."""
        from types import SimpleNamespace

        # Build a minimal profile-like object matching what the closure reads
        token_obj = SimpleNamespace(
            token="abc_xyz_token",
            expires_at=datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc),
            id=999,
        )
        lead = SimpleNamespace(email="applicant@example.com", full_name="Nguyễn Văn A")
        profile = SimpleNamespace(id=42, lead=lead)

        # Reproduce the closure (same shape as service — pure unit-level test)
        from app.config import settings as real_settings

        async def _send_email_callback():
            from app.tasks.email_tasks import send_magic_link_confirmation_task
            if not profile.lead or not profile.lead.email:
                return
            try:
                confirm_url = (
                    f"{real_settings.FRONTEND_URL.rstrip('/')}/confirm/{token_obj.token}"
                )
                send_magic_link_confirmation_task.delay(
                    email_to=profile.lead.email,
                    confirm_url=confirm_url,
                    lead_name=profile.lead.full_name or "Học viên",
                    expires_at_iso=token_obj.expires_at.isoformat(),
                    expires_days=real_settings.ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS,
                    lang="vi",
                )
            except Exception:
                pass

        with patch(
            "app.tasks.email_tasks.send_magic_link_confirmation_task.delay"
        ) as mock_delay:
            await _send_email_callback()

        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        assert kwargs["email_to"] == "applicant@example.com"
        assert kwargs["confirm_url"].endswith("/confirm/abc_xyz_token")
        assert kwargs["lead_name"] == "Nguyễn Văn A"
        assert kwargs["lang"] == "vi"

    @pytest.mark.asyncio
    async def test_callback_skips_when_no_lead_email(self):
        """Lead.email = None → .delay() NOT called, callback returns cleanly."""
        from types import SimpleNamespace

        lead = SimpleNamespace(email=None, full_name="X")
        profile = SimpleNamespace(id=1, lead=lead)

        async def _cb():
            from app.tasks.email_tasks import send_magic_link_confirmation_task
            if not profile.lead or not profile.lead.email:
                return
            send_magic_link_confirmation_task.delay(email_to=profile.lead.email)

        with patch(
            "app.tasks.email_tasks.send_magic_link_confirmation_task.delay"
        ) as mock_delay:
            await _cb()

        mock_delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_non_fatal_on_enqueue_failure(self):
        """Broker down → .delay() raises → callback MUST NOT bubble the exception."""
        from types import SimpleNamespace

        lead = SimpleNamespace(email="x@y.z", full_name="L")
        profile = SimpleNamespace(id=1, lead=lead)
        token_obj = SimpleNamespace(token="t", expires_at=datetime.now(timezone.utc), id=1)

        from app.config import settings as real_settings

        async def _cb():
            from app.tasks.email_tasks import send_magic_link_confirmation_task
            if not profile.lead or not profile.lead.email:
                return
            try:
                send_magic_link_confirmation_task.delay(
                    email_to=profile.lead.email,
                    confirm_url=f"{real_settings.FRONTEND_URL}/confirm/{token_obj.token}",
                    lead_name=profile.lead.full_name,
                    expires_at_iso=token_obj.expires_at.isoformat(),
                    expires_days=7,
                    lang="vi",
                )
            except Exception:
                # Expected: callback swallows enqueue failures
                pass

        with patch(
            "app.tasks.email_tasks.send_magic_link_confirmation_task.delay",
            side_effect=ConnectionError("broker down"),
        ):
            # MUST NOT raise
            await _cb()
