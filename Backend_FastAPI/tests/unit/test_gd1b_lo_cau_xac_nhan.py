"""GĐ1b — câu của ô xác nhận lô: máy chủ (``confirmation_sentence``) và giao diện (``confirmationSentence`` ở
``frontend/src/lib/document-review/messages.ts``) phải dựng ĐÚNG cùng câu (Codex 71 điểm 4; CLAUDE.md §7 — hai bản thì
phải có test khoá bằng nhau). Máy chủ từ chối mọi câu khác (422 ``CONFIRMATION_MISMATCH``), nên lệch một dấu là lô không
chạy được từ giao diện.
"""
import re
from pathlib import Path

import pytest

from app.services.document_bulk_verify_service import confirmation_sentence

pytestmark = pytest.mark.unit

MESSAGES_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "document-review" / "messages.ts"


def _mau_giao_dien() -> str:
    assert MESSAGES_TS.is_file(), MESSAGES_TS  # thiếu tệp ⇒ ĐỎ, không bỏ qua
    nguon = MESSAGES_TS.read_text(encoding="utf-8")
    m = re.search(
        r"export function confirmationSentence\(n: number\): string \{\s*return `([^`]*)`\s*\}", nguon
    )
    assert m, "không tìm thấy confirmationSentence(n) dạng một template literal"
    mau = m.group(1)
    assert mau.count("${n}") == 1 and "${" not in mau.replace("${n}", ""), mau
    return mau


@pytest.mark.parametrize("n", [0, 1, 4, 37, 1000])
def test_cau_xac_nhan_giao_dien_trung_may_chu(n):
    assert _mau_giao_dien().replace("${n}", str(n)) == confirmation_sentence(n)
