# app/scripts/audit_permanent_commune_codes.py
"""Audit tính toàn vẹn của địa chỉ thường trú (permanent_commune_code) trên hồ sơ
tuyển sinh — dữ liệu quyết định KV → chính sách ưu tiên / miễn-giảm học phí
(Nghị định 238/NĐ-CP). KHÔNG được để sai lệch.

Read-only. Cờ các hồ sơ mà ``permanent_commune_code`` không dùng được cho KV:

1. ward_set_but_code_missing — có tên xã (``permanent_ward``) nhưng THIẾU mã
   (``permanent_commune_code`` NULL/rỗng) → engine không resolve được KV.
2. code_not_current_era — có mã nhưng mã KHÔNG phải xã hiện hành (valid_to IS NULL)
   → mã legacy/stale, KV resolve sai hoặc fail.
3. code_orphan — mã không tồn tại như bất kỳ ward nào (administrative_nodes).

Chạy:
    docker compose exec backend python -m app.scripts.audit_permanent_commune_codes
    # one-off: docker compose run --rm --no-deps backend \
    #     python -m app.scripts.audit_permanent_commune_codes

Exit code: 0 nếu sạch, 1 nếu có hồ sơ lỗi (dùng được làm cổng pre/post data-import,
vd sau khi import MOET các tỉnh sáp nhập 2025 thay đổi administrative_nodes).
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import AsyncSessionLocal


# Một câu SELECT tổng hợp đếm + gom id để vừa báo số liệu vừa chỉ rõ hồ sơ lỗi.
_AUDIT_SQL = text(
    """
    WITH flagged AS (
        SELECT
            ap.id,
            (ap.permanent_ward IS NOT NULL AND ap.permanent_ward <> ''
             AND (ap.permanent_commune_code IS NULL OR ap.permanent_commune_code = '')
            ) AS ward_set_but_code_missing,
            (ap.permanent_commune_code IS NOT NULL AND ap.permanent_commune_code <> ''
             AND NOT EXISTS (
                SELECT 1 FROM administrative_nodes an
                WHERE an.code = ap.permanent_commune_code
                  AND an.level = 'WARD' AND an.valid_to IS NULL AND an.is_active = true)
            ) AS code_not_current_era,
            (ap.permanent_commune_code IS NOT NULL AND ap.permanent_commune_code <> ''
             AND NOT EXISTS (
                SELECT 1 FROM administrative_nodes an
                WHERE an.code = ap.permanent_commune_code AND an.level = 'WARD')
            ) AS code_orphan
        FROM admission_profile ap
    )
    SELECT
        (SELECT count(*) FROM admission_profile) AS total_profiles,
        array_remove(array_agg(id) FILTER (WHERE ward_set_but_code_missing), NULL)
            AS ward_set_but_code_missing,
        array_remove(array_agg(id) FILTER (WHERE code_not_current_era), NULL)
            AS code_not_current_era,
        array_remove(array_agg(id) FILTER (WHERE code_orphan), NULL)
            AS code_orphan
    FROM flagged
    """
)


async def audit() -> int:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(_AUDIT_SQL)).mappings().one()

    total = row["total_profiles"]
    missing = list(row["ward_set_but_code_missing"] or [])
    not_current = list(row["code_not_current_era"] or [])
    orphan = list(row["code_orphan"] or [])
    bad_total = len(set(missing) | set(not_current) | set(orphan))

    print(f"[audit] permanent_commune_code — {total} hồ sơ")
    print(f"  - ward_set_but_code_missing : {len(missing)} {missing}")
    print(f"  - code_not_current_era      : {len(not_current)} {not_current}")
    print(f"  - code_orphan               : {len(orphan)} {orphan}")

    if bad_total == 0:
        print("[audit] OK — 0 hồ sơ sai lệch địa chỉ thường trú.")
        return 0
    print(
        f"[audit] FAIL — {bad_total} hồ sơ cần xử lý (KV/miễn-giảm có thể sai). "
        "Yêu cầu officer chọn lại Phường/Xã hiện hành hoặc backfill có kiểm soát."
    )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(audit()))
