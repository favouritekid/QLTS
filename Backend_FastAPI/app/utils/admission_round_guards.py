"""Shared admission round guard helpers.

Extracted from `admission_service.py` + `admission_choice_service.py` to
eliminate the 2-copy drift risk flagged in PR #346 review (2026-05-28).

Both services need to enforce ``OfferingAdmissionRound`` SPEC §2.1.a
Rule 1 (round.end_date cutoff → 410 Gone), but historical co-evolution
left them with slightly different error messages and risked drift on
future i18n / grace-period / timezone changes.

This module:
* Contains the canonical ``_assert_round_open`` implementation.
* Imports ONLY from `app.utils.*` + `app.models.*` to avoid circular
  imports with either service.
* Keeps message contracts in one place so caller-specific wording
  (e.g. "Liên hệ admin" vs "rút NV vẫn cho phép") layers on top via
  optional `context_hint` parameter.

Reference: PR #346 review follow-up nit #1 (plan v4 2026-05-28 sprint).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.utils.datetime_helpers import today_vn
from app.utils.exceptions import RoundClosedError

if TYPE_CHECKING:  # pragma: no cover — import only for type hints
    from app.models import OfferingAdmissionRound


def assert_round_open(
    round_obj: "OfferingAdmissionRound",
    *,
    context_hint: Optional[str] = None,
) -> None:
    """Raise RoundClosedError nếu round.end_date < today_vn().

    PR-2 (2026-05-28) — strict cutoff enforcement của
    OfferingAdmissionRound SPEC §2.1.a Rule 1.

    NULL end_date → open-ended round, pass-through (admin có thể set
    explicit end_date sau). Strict semantic — KHÔNG có grace period,
    KHÔNG admin override ngầm (plan v4 locked decision: admin extends
    qua POST /rounds/{id}/extend, KHÔNG bypass gate này).

    Args:
        round_obj: OfferingAdmissionRound đã load (callers thường đã có
            qua eager-load của allow_multi_nv check hoặc explicit query).
        context_hint: Optional Vietnamese clause append vào error message
            để caller-side gợi ý hành động cho candidate/officer:
            * Service create/submit: "Liên hệ admin nếu cần extend đợt."
            * Service choice CRUD: "Không thể thêm/sửa nguyện vọng
              (rút NV vẫn cho phép)."
            Default None → message chỉ chứa round_code + end_date.

    Raises:
        RoundClosedError: end_date < today_vn(). HTTP 410 Gone tự pickup
            via BaseAppException handler (main.py:398).
    """
    if round_obj.end_date is None or round_obj.end_date >= today_vn():
        return

    detail = (
        f"Đợt tuyển sinh '{round_obj.round_code}' đã đóng "
        f"(hạn cuối: {round_obj.end_date})."
    )
    if context_hint:
        detail = f"{detail} {context_hint}"
    raise RoundClosedError(detail)
