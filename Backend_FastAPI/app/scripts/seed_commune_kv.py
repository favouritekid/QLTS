"""Seed/bổ sung KV cấp xã (nơi THƯỜNG TRÚ) vào vn_commune_area_map từ CSV.

Nguồn KV thường trú = QĐ 60 (xã khu vực I/II/III → KV1) + phân loại đơn vị
hành chính (Phường đô thị → KV2; Xã nông thôn → KV2-NT; KV3 = mặc định vắng
mặt, KHÔNG lưu). TÁCH NGUỒN: KHÔNG dùng KV-trường (xem
rebuild_school_kv_from_xls.py) — KV-trường vs KV-thường-trú không mượn chéo.

CSV cột bắt buộc: commune_code, province, ward, area_code (KV1|KV2|KV2-NT).

CHẾ ĐỘ:
  --dry-run (mặc định): đọc CSV + validate, in phân bố. KHÔNG chạm DB.
  --apply: 1 transaction; IDEMPOTENT — BỎ QUA commune_code đã có dòng active
           (effective_to IS NULL, theo partial-UNIQUE), chỉ INSERT dòng mới.
           district="" ; effective_from=CURRENT_DATE (server_default);
           effective_to=NULL. Chạy sau khi review CSV.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter

VALID_KV = re.compile(r"^KV[1-9](-NT)?$")
REQUIRED = {"commune_code", "province", "ward", "area_code"}


def load(path):
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"CSV thiếu cột: {', '.join(sorted(missing))}")
        return list(reader)


def validate(rows):
    bad = [r for r in rows if not VALID_KV.match(r["area_code"].strip())]
    if bad:
        raise SystemExit(
            f"{len(bad)} dòng area_code sai định dạng " f"(vd {bad[0]['area_code']!r})"
        )


def dry_run(args) -> int:
    rows = load(args.source)
    validate(rows)
    print("=" * 60)
    print(f"SEED commune KV — DRY-RUN | nguồn={args.source}")
    print(f"  dòng        : {len(rows)}")
    print(f"  phân bố KV  : {dict(Counter(r['area_code'] for r in rows))}")
    print(f"  tỉnh        : {dict(Counter(r['province'] for r in rows))}")
    print("  (apply: BỎ QUA commune_code đã có dòng active; chỉ insert mới)")
    print("=" * 60)
    return 0


async def apply(args) -> int:
    from app.database import AsyncSessionLocal
    from app.models.vn_locality import VnCommuneAreaMap
    from sqlalchemy import select

    rows = load(args.source)
    validate(rows)
    ins = skip = 0
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for r in rows:
                cc = r["commune_code"].strip()
                exists = await db.scalar(
                    select(VnCommuneAreaMap.id)
                    .where(
                        VnCommuneAreaMap.commune_code == cc,
                        VnCommuneAreaMap.effective_to.is_(None),
                    )
                    .limit(1)
                )
                if exists:
                    skip += 1
                    continue
                db.add(
                    VnCommuneAreaMap(
                        commune_code=cc,
                        province=r["province"].strip(),
                        district="",
                        ward=r["ward"].strip(),
                        area_code=r["area_code"].strip(),
                    )
                )
                ins += 1
    print(f"[apply] insert={ins} skip(đã có active)={skip} tổng={len(rows)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="CSV commune KV")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.source):
        print(f"Không thấy file: {args.source}", file=sys.stderr)
        return 2
    if args.apply:
        import asyncio

        return asyncio.run(apply(args))
    return dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
