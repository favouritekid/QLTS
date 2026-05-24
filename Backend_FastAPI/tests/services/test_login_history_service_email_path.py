"""Option-B Commit 5 — email path is single-sourced through the dispatcher.

Pre-PR, ``record_login._post_commit`` fired ``send_login_alert_email_task``
.delay() DIRECTLY whenever a login was suspicious, regardless of the
user's notification_preference. The notification dispatcher (called
from auth.py:_dispatch_suspicious_login) ALSO sends email for the same
event, but DOES respect preference. The two paths produced duplicate
emails for opted-in users and bypass-style email for opted-out users.

The 2026-05-23 prod log on user 16 was the smoking gun:
  channel_counts.email=0 (dispatcher filter said "skip email")
  but inbox got the alert anyway (direct path bypassed).

Commit 5 deletes the direct path. Dispatcher is now the single source.

These tests are pure source-inspection unit tests — no DB, no Celery,
no Redis. They lock the "the dead path stays dead" contract so any
future PR that re-introduces ``send_login_alert_email_task.delay()``
inside ``record_login`` (or its post-commit closure) breaks loudly.
"""
from __future__ import annotations

import inspect
import re

from app.services import login_history_service


def _strip_docstrings_and_comments(src: str) -> str:
    """Remove triple-quoted docstrings + ``#`` comments so the remaining
    text is pure executable Python. Migration / service docstrings
    document the very symbols this file's assertions forbid in
    executable code — they're documentation, not the bypass itself.
    """
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    return "\n".join(
        re.sub(r"\s*#.*$", "", line) for line in src.splitlines()
    )


def test_record_login_does_not_call_send_login_alert_delay():
    """``record_login`` body — including the nested ``_post_commit`` closure
    that runs after ``db.commit()`` — MUST NOT call
    ``send_login_alert_email_task.delay`` anywhere.
    """
    src = _strip_docstrings_and_comments(
        inspect.getsource(login_history_service.record_login)
    )
    assert "send_login_alert_email_task.delay" not in src, (
        "record_login is calling send_login_alert_email_task.delay directly. "
        "Option-B Commit 5 removed this — the dispatcher path in auth.py is "
        "the single source of email. Direct calls bypass user notification "
        "preference (proven on prod 2026-05-23 user 16: channel_counts."
        "email=0 from dispatcher filter but inbox got the alert)."
    )


def test_record_login_does_not_import_celery_email_task():
    """Defence-in-depth: the import itself should be gone too. A future
    refactor that adds back the import is a strong signal someone is
    about to re-introduce the bypass.
    """
    src = _strip_docstrings_and_comments(
        inspect.getsource(login_history_service.record_login)
    )
    assert "from app.celery_utils import send_login_alert_email_task" not in src
    assert "send_login_alert_email_task" not in src, (
        "Stale reference to send_login_alert_email_task lingers in record_login. "
        "Remove the import + the .delay() call together."
    )


def test_record_login_keeps_redis_pending_notification_path():
    """The R1+R2 reliability fix (Redis pending notification stored for
    socket-on-connect replay) is NOT removed by Commit 5 — only the
    email bypass is. Keep an assertion that this path is preserved so
    future cleanup doesn't accidentally drop both.
    """
    src = inspect.getsource(login_history_service.record_login)
    assert "pending_login_notif" in src, (
        "Redis pending_login_notif path was removed; this is a R1+R2 "
        "reliability fix that must stay independent of email path cleanup."
    )
    assert "safe_redis_lpush" in src


def test_celery_task_definition_kept_for_dispatcher():
    """``send_login_alert_email_task`` itself MUST still exist — the
    dispatcher invokes it through the SUSPICIOUS_LOGIN notification
    rule's email action. We only removed the DIRECT .delay() call from
    the service; the task definition is a dispatcher dependency.
    """
    from app.celery_utils import send_login_alert_email_task
    assert send_login_alert_email_task is not None
    assert callable(send_login_alert_email_task)


def test_record_login_signature_keeps_email_kwargs_for_back_compat():
    """Plan v10 kept ``email_to`` / ``username`` in the signature so the
    auth caller doesn't need an in-flight signature change in the same
    PR. They're now unused inside the body but the kwargs survive — a
    silent removal would be a breaking change to any external caller.
    """
    sig = inspect.signature(login_history_service.record_login)
    assert "email_to" in sig.parameters
    assert "username" in sig.parameters
    assert sig.parameters["email_to"].default is None
    assert sig.parameters["username"].default is None
