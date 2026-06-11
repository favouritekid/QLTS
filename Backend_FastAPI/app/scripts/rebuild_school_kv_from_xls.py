"""PHỦ DATA MỚI: nạp toàn bộ catalog trường THPT từ XLS chính thức MOET (QĐ 60 + TT05).

Quyết định (vì trường có ĐỔI TÊN → match-tên không tin cậy):
  ĐỢT 1 (script này):
    1) INSERT toàn bộ trường vùng target từ XLS — catalog SẠCH mới (moet_code +
       commune_code + KV chuẩn, source=moet_thpt_2026_qd60).
    2) XÓA CỨNG (DELETE) TOÀN BỘ bản ghi cũ vùng target (CASCADE kéo theo
       kv_assignment + name_history) → dropdown chỉ còn catalog sạch; hồ sơ MỚI
       chọn = đúng ngay. (academic_history JSONB của hồ sơ cũ KHÔNG có FK cứng →
       school_id dangling, resolve graceful + officer chọn lại.)
    3) FIX dòng ACTIVE + ADD commune mới vn_commune_area_map theo KV suy từ XLS
       (khóa = mã xã; CHỈ đụng dòng effective_to IS NULL; ADD lấy ward/tỉnh từ
       administrative_nodes hiện hành — không resolve được thì CẢNH BÁO + bỏ
       qua để thêm tay qua /admin/commune-kv). KV3 không lưu (= default vắng mặt).
  ĐỢT 2 (backfill — script riêng, làm SAU):
    Re-link academic_history của các hồ sơ ĐÃ chọn (school_id cũ → bản ghi mới),
    khớp theo commune_code + fuzzy/tay (vì đổi tên). Script này CHỈ liệt kê
    danh sách cần backfill, KHÔNG đụng.

KV mới: effective_from_year=2000 (sentinel; KV trường hằng số; resolve được cả
engine năm-học lẫn năm-tuyển-sinh), effective_to_year=NULL.

CHẾ ĐỘ:
  --dry-run (mặc định): đọc --source + --state-dir (dump prod), KHÔNG DB, KHÔNG ghi.
  --apply: kết nối DB, 1 transaction, idempotent theo moet_code. Chạy sau backup+duyệt.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

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
    "gso", "moet_code", "commune_code", "kv", "name", "province",
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
    (mọi downstream — dry_run/apply/commune — thấy KV canonical 'KV2-NT')."""
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


def commune_plan(src_t, map_now):
    """Trả (fix, add): sửa/thêm vn_commune_area_map theo KV suy từ XLS."""
    sck = defaultdict(Counter)
    for s in src_t:
        if s["commune_code"]:
            sck[s["commune_code"]][s["kv"]] += 1
    fix, add = [], []
    for cc, ctr in sck.items():
        want = ctr.most_common(1)[0][0]
        cur = map_now.get(cc)
        if cur is None:
            if want in ("KV1", "KV2", "KV2-NT"):
                add.append((cc, want))
        elif cur != want:
            fix.append((cc, cur, want))
    return fix, add


def dry_run(args) -> int:
    src = load_source(args.source)
    provinces = set(p.strip() for p in args.provinces.split(","))
    src_t = [s for s in src if s["gso"] in provinces]

    schools = read_csv(os.path.join(args.state_dir, "schools.csv"))
    cmap = read_csv(os.path.join(args.state_dir, "commune_map.csv"))
    prof = read_csv(os.path.join(args.state_dir, "profile_schools.csv"))

    db_region = [
        (r + [""] * 7)[:7]
        for r in schools
        if (r + [""] * 7)[6].lower() in ("t", "true", "1")
        and OLD_TO_GSO.get((r + [""] * 7)[2].strip()) in provinces
    ]
    map_now = {r[0]: nkv(r[3]) for r in cmap}
    cfix, cadd = commune_plan(src_t, map_now)

    sel_ids = set(r[2] for r in prof if len(r) >= 3 and r[2])
    sch_by_id = {r[0]: r for r in db_region}
    backfill = [sch_by_id[sid] for sid in sel_ids if sid in sch_by_id]

    print("=" * 70)
    print(f"PHỦ DATA MỚI (blanket) — DRY-RUN | GSO={sorted(provinces)}")
    print("=" * 70)
    print(
        f"[1] INSERT trường mới từ XLS     : {len(src_t)}  "
        f"(KV {dict(Counter(s['kv'] for s in src_t))})"
    )
    print(
        f"      effective_from={KV_EFFECTIVE_FROM}, effective_to=NULL, "
        f"source={SOURCE_OF}"
    )
    print(
        f"[2] XÓA CỨNG bản ghi cũ          : {len(db_region)} "
        f"(toàn bộ vùng target; CASCADE kv+name_history)"
    )
    print(f"[3] commune_area_map  SỬA={len(cfix)} | THÊM={len(cadd)}")
    print(
        f"[4] HỒ SƠ DANGLING (officer chọn lại): {len(backfill)} "
        f"trường đã chọn sẽ mất link"
    )
    for r in backfill:
        print(f"        school_id={r[0]:>4} | {r[1][:40]:42} | {r[2]}")
    print("-" * 70)
    print(f"=> active sau ĐỢT 1 = {len(src_t)} (catalog XLS sạch)")
    print("=" * 70)

    out = os.path.join(args.state_dir, "phu_data_plan.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["action", "key", "name", "detail"])
        for s in src_t:
            w.writerow(["INSERT", s["moet_code"], s["name"], s["kv"]])
        for r in db_region:
            w.writerow(["DELETE", r[0], r[1], ""])
        for cc, a, b in cfix:
            w.writerow(["COMMUNE_FIX", cc, a, b])
        for cc, b in cadd:
            w.writerow(["COMMUNE_ADD", cc, "", b])
        for r in backfill:
            w.writerow(["BACKFILL_DEFER", r[0], r[1], r[2]])
    print(f"Kế hoạch -> {out}")
    return 0


async def apply(args) -> int:
    from app.database import AsyncSessionLocal
    from app.models.vn_school import VnSchool, VnSchoolKvAssignment
    from app.models.vn_locality import VnCommuneAreaMap
    from sqlalchemy import select, update

    src = load_source(args.source)
    provinces = set(p.strip() for p in args.provinces.split(","))
    src_t = [s for s in src if s["gso"] in provinces]

    from sqlalchemy import delete as sa_delete

    old_names = [n for n, g in OLD_TO_GSO.items() if g in provinces]
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # (2) XÓA CỨNG toàn bộ cũ vùng target.
            # FK: vn_school_kv_assignment + vn_school_name_history = CASCADE (tự xóa).
            # merged_into_id (self-ref, NO ACTION): set NULL trước để không vỡ.
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
            # (3) commune_area_map: FIX dòng ACTIVE (effective_to IS NULL) + ADD
            # commune mới (lấy ward/tỉnh hiện hành từ administrative_nodes).
            from app.repositories.administrative_repository import (
                AdministrativeRepository,
            )

            admin_repo = AdministrativeRepository(db)
            cfix = 0
            cadd = 0
            cadd_skip = 0
            sck = defaultdict(Counter)
            for s in src_t:
                if s["commune_code"]:
                    sck[s["commune_code"]][s["kv"]] += 1
            for cc, ctr in sck.items():
                want = ctr.most_common(1)[0][0]
                # KV3 = default (vắng mặt trong map) → KHÔNG add/fix về KV3.
                if want not in ("KV1", "KV2", "KV2-NT"):
                    continue
                # CHỈ dòng ACTIVE (effective_to IS NULL) — KHÔNG đụng dòng retire.
                row = await db.scalar(
                    select(VnCommuneAreaMap)
                    .where(
                        VnCommuneAreaMap.commune_code == cc,
                        VnCommuneAreaMap.effective_to.is_(None),
                    )
                    .limit(1)
                )
                if row is not None:
                    if row.area_code != want:
                        row.area_code = want
                        cfix += 1
                    continue
                # Commune chưa có trong map → ADD (resolve ward/tỉnh hiện hành).
                ward_name, province_name = (
                    await admin_repo.get_current_commune_display(cc)
                )
                if not (ward_name and province_name):
                    cadd_skip += 1  # không resolve → KHÔNG bỏ âm thầm, đếm + cảnh báo
                    continue
                db.add(
                    VnCommuneAreaMap(
                        commune_code=cc,
                        province=province_name,
                        district="",
                        ward=ward_name,
                        area_code=want,
                    )
                )
                cadd += 1
    print(
        f"[apply] insert={ins} deleted={react} commune_fix={cfix} "
        f"commune_add={cadd} commune_add_skip={cadd_skip}"
    )
    if cadd_skip:
        print(
            f"[apply] CẢNH BÁO: {cadd_skip} commune mới KHÔNG resolve được "
            f"ward/tỉnh hiện hành → CHƯA thêm vào map; thêm tay qua "
            f"/admin/commune-kv."
        )
    print(
        "[apply] Hồ sơ đã chọn trường cũ -> dangling; officer chọn lại từ catalog mới."
    )
    return 0


def export_source(xls_path: str, out_path: str, provinces: set[str]) -> int:
    """XLS chính thức MOET -> source.csv (cột chuẩn cho --apply). Cần pandas+xlrd.
    Đọc Mã Xã/Mã Tỉnh/Mã Trường dạng CHUỖI (giữ số 0 đầu)."""
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
        rows.append(
            {
                "moet_code": mt.zfill(2) + mtr.zfill(3),
                "commune_code": mx[:5] if mx and mx.lower() != "nan" else "",
                "gso": mt,
                "province": str(r["Tên Tỉnh/TP"]).strip(),
                "name": name,
                "address": (
                    str(r["Địa Chỉ"]).strip() if str(r["Địa Chỉ"]) != "nan" else ""
                ),
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
