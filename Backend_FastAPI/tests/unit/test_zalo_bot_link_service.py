"""Unit tests for ``zalo_bot_link_service``.

Redis interactions are mocked at the ``safe_redis_*`` boundary — the
service is covered, the helpers themselves are exercised by their own
integration tests against a live Redis.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import zalo_bot_link_service as svc
from app.utils.exceptions import BusinessRuleViolation


@pytest.mark.unit
class TestLinkCodeTTL:
    def test_ttl_is_ten_minutes(self):
        """v5/E8: TTL must be 600 seconds — staff need real-world headroom."""
        assert svc.LINK_CODE_TTL == 600


@pytest.mark.unit
@pytest.mark.asyncio
class TestGenerateLinkCode:
    async def test_happy_path_uses_nx(self):
        """First SET NX succeeds → returns the generated code + post_commit cb."""
        with patch("app.database.safe_redis_get", new=AsyncMock(return_value=None)) as m_get, \
             patch("app.database.safe_redis_delete", new=AsyncMock()) as m_del, \
             patch("app.database.safe_redis_set", new=AsyncMock(return_value=True)) as m_set:
            code, cb = await svc.generate_link_code(db=None, user_id=42)

        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isalnum()
        # First SET is the code itself with NX, second is the user pointer.
        nx_calls = [c for c in m_set.call_args_list if c.kwargs.get("nx")]
        assert len(nx_calls) == 1, "exactly one SET NX expected on success"
        assert nx_calls[0].kwargs["ex"] == 600
        # No previous pointer → no delete.
        m_del.assert_not_awaited()
        m_get.assert_awaited_once()
        # Callback callable, no-op.
        assert callable(cb)
        await cb()

    async def test_retries_on_nx_collision(self):
        """Two SET NX collisions, third succeeds — service must keep trying."""
        nx_results = [None, None, True]

        async def fake_set(key, value, ex=None, nx=False):
            if nx:
                return nx_results.pop(0)
            return True  # pointer write

        with patch("app.database.safe_redis_get", new=AsyncMock(return_value=None)), \
             patch("app.database.safe_redis_delete", new=AsyncMock()), \
             patch("app.database.safe_redis_set", new=AsyncMock(side_effect=fake_set)):
            code, _ = await svc.generate_link_code(db=None, user_id=7)

        assert len(code) == 6, "service must surface the code from the third (winning) attempt"

    async def test_exhausts_retries_raises(self):
        """5 collisions → BusinessRuleViolation, never returns a partial code."""
        with patch("app.database.safe_redis_get", new=AsyncMock(return_value=None)), \
             patch("app.database.safe_redis_delete", new=AsyncMock()), \
             patch("app.database.safe_redis_set", new=AsyncMock(return_value=None)) as m_set:
            with pytest.raises(BusinessRuleViolation):
                await svc.generate_link_code(db=None, user_id=99)

        # 5 SET NX attempts, no pointer write.
        nx_calls = [c for c in m_set.call_args_list if c.kwargs.get("nx")]
        assert len(nx_calls) == 5

    async def test_regenerate_deletes_previous_code(self):
        """Existing pointer → service deletes old code key before generating new."""
        with patch("app.database.safe_redis_get", new=AsyncMock(return_value="OLDCOD")) as m_get, \
             patch("app.database.safe_redis_delete", new=AsyncMock()) as m_del, \
             patch("app.database.safe_redis_set", new=AsyncMock(return_value=True)):
            await svc.generate_link_code(db=None, user_id=42)

        m_get.assert_awaited_once()
        m_del.assert_awaited_once()
        deleted_key = m_del.await_args.args[0]
        assert deleted_key == f"{svc.LINK_CODE_PREFIX}OLDCOD", (
            "must delete the *code* key, not the pointer key — pointer is overwritten by SET"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestVerifyAndLink:
    async def test_consume_is_atomic_second_use_fails(self):
        """First verify succeeds, second on the same code returns failure."""
        # Simulate: first GETDEL returns user_id, second returns None.
        getdel_mock = AsyncMock(side_effect=["42", None])
        # Repo writes are stubbed via patching — we don't need a real DB
        # for this contract-level test; the goal is to prove the service
        # hands off to GETDEL exactly once per attempt and treats the
        # absence of a value as a failure.
        repo_mock = AsyncMock()
        repo_mock.get_active_by_chat_id = AsyncMock(return_value=None)
        repo_mock.create_or_reactivate = AsyncMock()

        # Patch audit_service so unit tests don't need a real DB. The
        # full audit semantics are covered in
        # tests/integration/test_zalo_bot_audit_trail.py against a real
        # session — this test only verifies the GETDEL contract.
        with patch("app.database.safe_redis_getdel", new=getdel_mock), \
             patch.object(svc, "StaffZaloBotLinkRepository", return_value=repo_mock), \
             patch.object(svc, "_sync_preference", new=AsyncMock()), \
             patch("app.services.audit_service.log_created", new=AsyncMock()), \
             patch("app.services.audit_service.log_audit", new=AsyncMock()):
            db_mock = AsyncMock()
            ok1, _, _ = await svc.verify_and_link(db_mock, "ABC123", "chat_xyz")
            ok2, msg2, _ = await svc.verify_and_link(db_mock, "ABC123", "chat_xyz")

        assert ok1 is True, "first consume must succeed when GETDEL returns the user_id"
        assert ok2 is False, "second consume on the same code must fail"
        assert "không hợp lệ" in msg2.lower() or "hết hạn" in msg2.lower()
        assert getdel_mock.await_count == 2

    async def test_invalid_code_returns_failure_no_db_writes(self):
        """GETDEL miss → no repository touch."""
        getdel_mock = AsyncMock(return_value=None)
        repo_mock = AsyncMock()

        with patch("app.database.safe_redis_getdel", new=getdel_mock), \
             patch.object(svc, "StaffZaloBotLinkRepository", return_value=repo_mock):
            ok, _, _ = await svc.verify_and_link(AsyncMock(), "BADCOD", "chat_x")

        assert ok is False
        repo_mock.create_or_reactivate.assert_not_awaited()

    async def test_code_is_uppercased_before_lookup(self):
        """User typing ``/lienkiet abc123`` (lowercase) must still hit the key."""
        getdel_mock = AsyncMock(return_value="42")
        repo_mock = AsyncMock()
        repo_mock.get_active_by_chat_id = AsyncMock(return_value=None)
        repo_mock.create_or_reactivate = AsyncMock()

        with patch("app.database.safe_redis_getdel", new=getdel_mock), \
             patch.object(svc, "StaffZaloBotLinkRepository", return_value=repo_mock), \
             patch.object(svc, "_sync_preference", new=AsyncMock()), \
             patch("app.services.audit_service.log_created", new=AsyncMock()), \
             patch("app.services.audit_service.log_audit", new=AsyncMock()):
            await svc.verify_and_link(AsyncMock(), "abc123", "chat_x")

        looked_up_key = getdel_mock.await_args.args[0]
        assert looked_up_key == f"{svc.LINK_CODE_PREFIX}ABC123"
