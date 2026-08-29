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

    def _dong_lenh(self):
        """Các dòng LỆNH của entrypoint, đã bỏ chú thích và dòng trống.

        `content.index("sync_notification_rules")` trên NGUYÊN văn bản bắt
        trúng dòng chú thích ở đầu tệp (`# manual run alembic + backfill +
        sync_notification_rules + Casbin reload ngoài`), nằm TRƯỚC lệnh
        `alembic upgrade head` thật — nên phép kiểm đỏ trong khi thứ tự chạy
        hoàn toàn đúng. Đây là lớp lỗi "biểu thức khớp trúng dòng thông báo
        thay vì dòng lệnh": nó vừa báo động giả, vừa có thể im lặng khi thứ
        tự lệnh thật sự sai mà chú thích lại đúng thứ tự.

        Trả về danh sách dòng lệnh để so THEO VỊ TRÍ DÒNG, không theo offset
        ký tự trong nguyên văn bản.
        """
        return [
            l for l in self.ENTRYPOINT.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]

    def _vi_tri_lenh(self, manh: str) -> int:
        dong = self._dong_lenh()
        hop = [i for i, l in enumerate(dong) if manh in l]
        assert hop, f"khong tim thay dong LENH nao chua {manh!r}"
        return hop[0]

    def test_alembic_before_sync(self):
        """alembic upgrade head must appear before sync_notification_rules."""
        assert self._vi_tri_lenh("alembic upgrade head") < self._vi_tri_lenh(
            "sync_notification_rules"
        ), "alembic must run before sync"

    def test_sync_before_exec(self):
        """sync must appear before exec (app start)."""
        assert self._vi_tri_lenh("sync_notification_rules") < self._vi_tri_lenh(
            'exec "$@"'
        ), "sync must run before exec (app start)"

    def test_exec_is_last_command(self):
        """exec "$@" should be the last meaningful command."""
        lines = [
            l.strip() for l in self.ENTRYPOINT.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("echo")
        ]
        assert lines[-1] == 'exec "$@"', f"Last command should be exec, got: {lines[-1]}"
