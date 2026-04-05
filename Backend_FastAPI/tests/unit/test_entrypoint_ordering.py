# tests/unit/test_entrypoint_ordering.py
"""
PR3.5: Verify docker-entrypoint.sh startup ordering contract.

The entrypoint must run: alembic → sync_notification_rules → exec.
This is a static analysis test — no Docker required.
"""
from pathlib import Path

import pytest


@pytest.mark.unit
class TestEntrypointOrdering:
    """docker-entrypoint.sh must enforce correct startup sequence."""

    ENTRYPOINT = Path(__file__).resolve().parent.parent.parent / "docker-entrypoint.sh"

    def test_entrypoint_exists(self):
        assert self.ENTRYPOINT.exists(), f"docker-entrypoint.sh not found at {self.ENTRYPOINT}"

    def test_set_e_enabled(self):
        """set -e must be present for fail-fast behavior."""
        content = self.ENTRYPOINT.read_text()
        assert "set -e" in content, "docker-entrypoint.sh must have 'set -e'"

    def test_alembic_before_sync(self):
        """alembic upgrade head must appear before sync_notification_rules."""
        content = self.ENTRYPOINT.read_text()
        alembic_pos = content.index("alembic upgrade head")
        sync_pos = content.index("sync_notification_rules")
        assert alembic_pos < sync_pos, "alembic must run before sync"

    def test_sync_before_exec(self):
        """sync must appear before exec (app start)."""
        content = self.ENTRYPOINT.read_text()
        sync_pos = content.index("sync_notification_rules")
        exec_pos = content.index('exec "$@"')
        assert sync_pos < exec_pos, "sync must run before exec (app start)"

    def test_exec_is_last_command(self):
        """exec "$@" should be the last meaningful command."""
        lines = [
            l.strip() for l in self.ENTRYPOINT.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("echo")
        ]
        assert lines[-1] == 'exec "$@"', f"Last command should be exec, got: {lines[-1]}"
