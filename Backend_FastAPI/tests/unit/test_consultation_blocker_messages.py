"""Unit tests — review lần 2 (cleanup): mọi blocker code mà
``_consultation_mutation_verdict`` trả về (và ĐI TỚI lookup message) PHẢI có
message riêng trong ``_UPDATE_BLOCKER_MESSAGES`` / ``_DELETE_BLOCKER_MESSAGES``.

Nếu ai thêm blocker mới vào verdict mà quên message → nó rơi vào fallback generic
(mất text guard cũ). Test này chốt hợp đồng đó (query-free, pure predicate).
"""
from types import SimpleNamespace

import pytest

from app.core.constants import UserRole, SYSTEM_CONSULTATION_METHOD
from app.services.lead_service import (
    _consultation_mutation_verdict,
    _DELETE_BLOCKER_MESSAGES,
    _UPDATE_BLOCKER_MESSAGES,
)

pytestmark = pytest.mark.unit


def _consult(method="phone", officer_id=1):
    return SimpleNamespace(method=method, officer_id=officer_id)


def _lead(assigned_officer_id=1):
    return SimpleNamespace(assigned_officer_id=assigned_officer_id)


def _user(role=UserRole.OFFICER, uid=1):
    return SimpleNamespace(role=role, id=uid)


def _verdict(consult, lead, user, *, is_latest, within_24h, check_24h, is_hard_terminal):
    return _consultation_mutation_verdict(
        consult, lead, user,
        is_latest=is_latest, within_24h=within_24h,
        check_24h=check_24h, is_hard_terminal=is_hard_terminal,
    )


# ---------------------------------------------------------------------------
# Từng blocker code verdict CÓ THỂ trả — xác nhận đúng code (không đổi thầm).
# ---------------------------------------------------------------------------

def test_verdict_blocker_codes():
    # system (row bất biến) — thực tế chặn bởi _assert_consultation_mutable TRƯỚC,
    # nhưng verdict vẫn trả code này (defense-in-depth).
    allowed, code = _verdict(
        _consult(method=SYSTEM_CONSULTATION_METHOD), _lead(), _user(),
        is_latest=True, within_24h=True, check_24h=False, is_hard_terminal=False,
    )
    assert (allowed, code) == (False, "system")

    # hard_terminal (enrolled) — thực tế raise BusinessRuleViolation riêng.
    assert _verdict(
        _consult(), _lead(), _user(),
        is_latest=True, within_24h=True, check_24h=False, is_hard_terminal=True,
    ) == (False, "hard_terminal")

    # not_latest / not_assigned / not_author / expired_24h (ladder officer).
    assert _verdict(
        _consult(), _lead(), _user(),
        is_latest=False, within_24h=True, check_24h=True, is_hard_terminal=False,
    ) == (False, "not_latest")
    assert _verdict(
        _consult(officer_id=1), _lead(assigned_officer_id=999), _user(uid=1),
        is_latest=True, within_24h=True, check_24h=True, is_hard_terminal=False,
    ) == (False, "not_assigned")
    assert _verdict(
        _consult(officer_id=999), _lead(assigned_officer_id=1), _user(uid=1),
        is_latest=True, within_24h=True, check_24h=True, is_hard_terminal=False,
    ) == (False, "not_author")
    assert _verdict(
        _consult(officer_id=1), _lead(assigned_officer_id=1), _user(uid=1),
        is_latest=True, within_24h=False, check_24h=True, is_hard_terminal=False,
    ) == (False, "expired_24h")

    # no_role (vai trò khác officer/manager/admin).
    assert _verdict(
        _consult(), _lead(), _user(role=UserRole.ACCOUNTANT),
        is_latest=True, within_24h=True, check_24h=False, is_hard_terminal=False,
    ) == (False, "no_role")

    # manager/admin luôn allowed (không blocker).
    assert _verdict(
        _consult(), _lead(), _user(role=UserRole.ADMIN),
        is_latest=False, within_24h=False, check_24h=True, is_hard_terminal=False,
    ) == (True, None)


# ---------------------------------------------------------------------------
# Mọi blocker ĐI TỚI lookup message phải có key riêng (không rơi fallback).
# system → _assert_consultation_mutable; hard_terminal → BusinessRuleViolation:
# 2 code này KHÔNG qua .get() nên không bắt buộc có trong dict.
# ---------------------------------------------------------------------------

# update áp cửa sổ 24h cho officer → có expired_24h.
_UPDATE_REACHABLE = {"not_latest", "not_assigned", "not_author", "expired_24h", "no_role"}
# delete check_24h=False → KHÔNG có expired_24h.
_DELETE_REACHABLE = {"not_latest", "not_assigned", "not_author", "no_role"}


def test_update_blocker_messages_cover_all_reachable():
    missing = _UPDATE_REACHABLE - set(_UPDATE_BLOCKER_MESSAGES)
    assert not missing, f"_UPDATE_BLOCKER_MESSAGES thiếu message cho: {missing}"
    for code in _UPDATE_REACHABLE:
        assert _UPDATE_BLOCKER_MESSAGES[code].strip()


def test_delete_blocker_messages_cover_all_reachable():
    missing = _DELETE_REACHABLE - set(_DELETE_BLOCKER_MESSAGES)
    assert not missing, f"_DELETE_BLOCKER_MESSAGES thiếu message cho: {missing}"
    for code in _DELETE_REACHABLE:
        assert _DELETE_BLOCKER_MESSAGES[code].strip()
