"""PHỦ DATA MỚI (nhánh TRƯỜNG): nạp catalog trường THPT từ XLS MOET chính thức.

Quyết định (vì trường có ĐỔI TÊN → match-tên không tin cậy):
  1) INSERT toàn bộ trường vùng target từ XLS — catalog mới (moet_code +
     commune_code + KV chuẩn, source=moet_thpt_2026_qd60).
  2) XÓA CỨNG (DELETE) TOÀN BỘ bản ghi cũ vùng target (CASCADE kéo theo
     kv_assignment + name_history) → dropdown chỉ còn catalog mới; hồ sơ MỚI
     chọn = đúng ngay. (academic_history JSONB của hồ sơ cũ KHÔNG có FK cứng
     → school_id dangling, resolve graceful + officer chọn lại.)

PHẠM VI: CHỈ nhánh TRƯỜNG (vn_school + vn_school_kv_assignment). KHÔNG đụng
vn_commune_area_map — bảng thường trú (nhánh THUONG_TRU) neo nguồn riêng
(QĐ 60 + phân loại đơn vị hành chính); tách nguồn, KV-trường vs KV-thường-trú
không mượn chéo. Chuẩn hóa commune làm việc riêng theo QĐ 60.

KV mới: effective_from_year=2000 (sentinel; KV trường hằng số; resolve được cả
engine năm-học lẫn năm-tuyển-sinh), effective_to_year=NULL.

CHẾ ĐỘ:
  --dry-run (mặc định): đọc --source + --state-dir (dump prod), KHÔNG DB.
  --apply: kết nối DB, 1 transaction, idempotent theo moet_code. Chạy sau
           backup + duyệt.
  --export-source XLS: sinh source.csv từ file XLS MOET (cần pandas+xlrd).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

KV_EFFECTIVE_FROM = 2000
SOURCE_OF = "moet_thpt_2026_qd60"
# Tỉnh cũ (DB) -> GSO hiện hành (XLS)
OLD_TO_GSO = {
    "Đắk Lắk": "66",
    "Phú Yên": "66",
    "Gia Lai": "52",
    "Bình Định": "52",
    "Lâm Đồng": "68",
    "Đắk Nông": "68",
    "Bình Thuận": "68",
}


REQUIRED_SOURCE_COLS = {
    "gso",
    "moet_code",
    "commune_code",
    "kv",
    "name",
    "province",
}


def nkv(k: str) -> str:
    return str(k).strip().upper().replace("_", "-")


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in csv.reader(f) if r]


def load_source(path):
    """Đọc source.csv + validate cột bắt buộc + chuẩn hóa kv NGAY khi nạp
    (mọi downstream — dry_run/apply — thấy KV canonical 'KV2-NT')."""
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_SOURCE_COLS - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"source CSV thiếu cột bắt buộc: {', '.join(sorted(missing))}"
            )
        rows = list(reader)
    for r in rows:
        r["kv"] = nkv(r.get("kv") or "")
    return rows


def dry_run(args) -> int:
    src = load_source(args.source)
    provinces = set(p.strip() for p in args.provinces.split(","))
    src_t = [s for s in src if s["gso"] in provinces]

    schools = read_csv(os.path.join(args.state_dir, "schools.csv"))
    prof = read_csv(os.path.join(args.state_dir, "profile_schools.csv"))

    db_region = [
        (r + [""] * 7)[:7]
        for r in schools
        if (r + [""] * 7)[6].lower() in ("t", "true", "1")
        and OLD_TO_GSO.get((r + [""] * 7)[2].strip()) in provinces
    ]

    sel_ids = set(r[2] for r in prof if len(r) >= 3 and r[2])
    sch_by_id = {r[0]: r for r in db_region}
    backfill = [sch_by_id[sid] for sid in sel_ids if sid in sch_by_id]

    print("=" * 70)
    print(f"PHỦ DATA MỚI (nhánh TRƯỜNG) — DRY-RUN | GSO={sorted(provinces)}")
    print("=" * 70)
    print(
        f"[1] INSERT trường từ XLS : {len(src_t)}  "
        f"(KV {dict(Counter(s['kv'] for s in src_t))})"
    )
    print(
        f"      effective_from={KV_EFFECTIVE_FROM}, "
        f"effective_to=NULL, source={SOURCE_OF}"
    )
    print(
        f"[2] XÓA CỨNG bản ghi cũ  : {len(db_region)} "
        f"(toàn vùng target; CASCADE kv+name_history)"
    )
    print(
        f"[3] HỒ SƠ DANGLING       : {len(backfill)} "
        f"trường đã chọn sẽ mất link (officer chọn lại)"
    )
    for r in backfill:
        print(f"        school_id={r[0]:>4} | {r[1][:46]}")
    print("-" * 70)
    print("[note] vn_commune_area_map KHÔNG đụng (nguồn riêng QĐ 60).")
    print(f"=> active vùng target sau apply = {len(src_t)}")
    print("=" * 70)

    out = os.path.join(args.state_dir, "phu_data_plan.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["action", "key", "name", "detail"])
        for s in src_t:
            w.writerow(["INSERT", s["moet_code"], s["name"], s["kv"]])
        for r in db_region:
            w.writerow(["DELETE", r[0], r[1], ""])
        for r in backfill:
            w.writerow(["BACKFILL_DEFER", r[0], r[1], r[2]])
    print(f"Kế hoạch -> {out}")
    return 0


async def apply(args) -> int:
    from app.database import AsyncSessionLocal
    from app.models.vn_school import VnSchool, VnSchoolKvAssignment
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select, update

    src = load_source(args.source)
    provinces = set(p.strip() for p in args.provinces.split(","))
    src_t = [s for s in src if s["gso"] in provinces]

    old_names = [n for n, g in OLD_TO_GSO.items() if g in provinces]
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # (2) XÓA CỨNG toàn bộ cũ vùng target.
            # FK: kv_assignment + name_history = CASCADE (tự xóa).
            # merged_into_id (self-ref, NO ACTION): set NULL trước.
            await db.execute(
                update(VnSchool)
                .where(VnSchool.province.in_(old_names))
                .values(merged_into_id=None)
            )
            res = await db.execute(
                sa_delete(VnSchool).where(VnSchool.province.in_(old_names))
            )
            react = res.rowcount or 0
            # (1) INSERT catalog mới (idempotent theo moet_code)
            ins = 0
            for s in src_t:
                if await db.scalar(
                    select(VnSchool.id)
                    .where(
                        VnSchool.moet_code == s["moet_code"],
                        VnSchool.is_active.is_(True),
                    )
                    .limit(1)
                ):
                    continue
                sch = VnSchool(
                    moet_school_code=s["moet_code"][2:],
                    moet_province_code=s["gso"],
                    moet_code=s["moet_code"],
                    commune_code=s["commune_code"] or None,
                    name=s["name"],
                    address=s.get("address") or None,
                    province=s["province"],
                    level=s.get("level") or "THPT",
                    is_dtnt=str(s.get("is_dtnt")).lower() in ("1", "true", "t"),
                    is_active=True,
                )
                db.add(sch)
                await db.flush()
                db.add(
                    VnSchoolKvAssignment(
                        school_id=sch.id,
                        kv_code=s["kv"],
                        effective_from_year=KV_EFFECTIVE_FROM,
                        effective_to_year=None,
                        source=SOURCE_OF,
                    )
                )
                ins += 1
    print(f"[apply] insert={ins} deleted={react}")
    print("[apply] vn_commune_area_map KHÔNG đụng (nguồn riêng QĐ 60).")
    print(
        "[apply] Hồ sơ chọn trường cũ -> dangling; " "officer chọn lại từ catalog mới."
    )
    return 0


def export_source(xls_path: str, out_path: str, provinces: set[str]) -> int:
    """XLS chính thức MOET -> source.csv (cột chuẩn cho --apply). Cần
    pandas+xlrd. Đọc Mã Xã/Mã Tỉnh/Mã Trường dạng CHUỖI (giữ số 0 đầu)."""
    import pandas as pd

    conv = {"Mã Xã/ Phường": str, "Mã Tỉnh/TP": str, "Mã Trường": str}
    df = pd.read_excel(xls_path, sheet_name="Sheet1", header=6, converters=conv)
    df.columns = [str(c).strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        mt = str(r["Mã Tỉnh/TP"]).strip()
        if mt not in provinces:
            continue
        mtr = str(r["Mã Trường"]).strip()
        mx = str(r["Mã Xã/ Phường"]).strip()
        name = str(r["Tên Trường"]).strip()
        addr = str(r["Địa Chỉ"]).strip() if str(r["Địa Chỉ"]) != "nan" else ""
        rows.append(
            {
                "moet_code": mt.zfill(2) + mtr.zfill(3),
                "commune_code": mx[:5] if mx and mx.lower() != "nan" else "",
                "gso": mt,
                "province": str(r["Tên Tỉnh/TP"]).strip(),
                "name": name,
                "address": addr,
                "level": "THPT",
                "is_dtnt": "1" if "DTNT" in name.upper() else "0",
                "kv": nkv(r["Khu Vực"]),
            }
        )
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "moet_code",
                "commune_code",
                "gso",
                "province",
                "name",
                "address",
                "level",
                "is_dtnt",
                "kv",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"[export] {len(rows)} trường -> {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="source.csv (cho dry-run/apply)")
    ap.add_argument("--state-dir", default="/tmp/state")
    ap.add_argument("--provinces", default="52,66,68")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--export-source", metavar="XLS", help="sinh source.csv từ XLS MOET"
    )
    ap.add_argument(
        "--out", default="/tmp/source.csv", help="đường ra cho --export-source"
    )
    args = ap.parse_args()
    provinces = set(p.strip() for p in args.provinces.split(","))
    if args.export_source:
        return export_source(args.export_source, args.out, provinces)
    if not args.source:
        print("Cần --source (hoặc --export-source). Dừng.", file=sys.stderr)
        return 2
    if args.apply:
        import asyncio

        return asyncio.run(apply(args))
    return dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
