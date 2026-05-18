"""Build KV ưu tiên table for Đắk Lắk province — proof of concept.

Pipeline:
1. Load master Excel (MOET 7,453 KK/ĐBKK pre-2025) → filter Đắk Lắk + Phú Yên (cũ)
2. Load ward_mappings.sql → 393 Đắk Lắk + Phú Yên old→new entries
3. Load wards.sql → 102 Đắk Lắk mới (post-sáp nhập 2025) post-2025 wards
4. Crosswalk: for each old xã in master, match to new_ward_code via name → KV1
5. MAX-rank merge: if ANY old xã of a new ward is KK/ĐBKK → new ward = KV1
6. Apply default rule cho remaining (TỈNH Đắk Lắk):
   - Phường → KV2 (thị xã/TP thuộc tỉnh)
   - Xã → KV2-NT (rural default)
7. Output table: ward_code, province, ward_name, area_code, sources

Đắk Lắk mới post-2025 = sáp nhập Đắk Lắk (cũ) + Phú Yên → 102 wards
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd


MASTER_EXCEL = Path("/tmp/master_xa_kk.xls")
WARD_MAPPINGS_SQL = Path("/tmp/ward_mappings.sql")
WARDS_SQL = Path("/tmp/wards.sql")
PROVINCES_SQL = Path("/tmp/provinces.sql")
OUTPUT_JSON = Path("/tmp/dak_lak_kv_table.json")
OUTPUT_CSV = Path("/tmp/dak_lak_kv_table.csv")


def _strip_diacritics(s: str) -> str:
    """Remove Vietnamese diacritics for diacritic-insensitive matching.

    Critical: Master Excel + ward_mappings.sql có 2 cách viết khác nhau cho
    cùng âm tiếng Việt (vd "Hoà" vs "Hòa", "thuý" vs "thúy"). 2 chuỗi
    Unicode khác nhau nhưng same phonetic. Strip diacritics để match.
    """
    nfkd = unicodedata.normalize("NFKD", s)
    # Special: đ → d (not handled by combining char removal)
    out = "".join(c for c in nfkd if not unicodedata.combining(c))
    return out.replace("đ", "d").replace("Đ", "D")


def normalize_vn(s: str) -> str:
    """Normalize Vietnamese name for matching (diacritic-insensitive)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = s.strip()
    # Drop "(trước DATE)" / "(từ DATE)" suffix (incl. multi-date variants)
    while True:
        new_s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
        if new_s == s:
            break
        s = new_s
    # Strip prefix: Xã/Phường/Thị trấn
    s = re.sub(r"^(Xã|Th[ịi]\s*tr[ấâ]n|Ph[ưu][ờơ]ng)\s+", "", s, flags=re.IGNORECASE)
    # Strip district prefix
    s = re.sub(r"^(Huy[ệe]n|Th[ịi]\s*x[ãa]|Th[àa]nh\s*ph[ốo]|Qu[ậa]n)\s+", "", s, flags=re.IGNORECASE)
    # Strip province prefix
    s = re.sub(r"^T[ỉi]nh\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Diacritic-insensitive: "hòa" và "hoà" cùng map về "hoa"
    s = _strip_diacritics(s)
    return s


WARD_PREFIX_RE = re.compile(r"^(Xã|Th[ịi]\s*tr[ấâ]n|Ph[ưu][ờơ]ng)\s+", re.IGNORECASE)


def get_ward_kind(name: str) -> str:
    """Return PHUONG|XA|DAC_KHU based on name prefix."""
    if name.startswith("Đặc khu"):
        return "DAC_KHU"
    if name.startswith("Phường"):
        return "PHUONG"
    return "XA"


def load_master_dak_lak() -> pd.DataFrame:
    """Load master Excel, filter Đắk Lắk + Phú Yên (cũ) rows."""
    df = pd.read_excel(MASTER_EXCEL, sheet_name="Sheet1", header=5)
    df.columns = ["stt", "ma_tinh", "ten_tinh", "ma_huyen", "ten_huyen", "ma_xa", "ten_xa", "loai"]
    dl_py = df[df["ten_tinh"].isin(["Đắk Lắk", "Phú Yên"])].copy()
    dl_py["ten_xa_norm"] = dl_py["ten_xa"].apply(normalize_vn)
    dl_py["ten_huyen_norm"] = dl_py["ten_huyen"].apply(normalize_vn)
    return dl_py


# MySQL INSERT regex for ward_mappings
_MAPPING_ROW = re.compile(
    r"VALUES\s*\(\s*\d+\s*,\s*"
    r"'(?P<old_code>[^']+)'\s*,\s*"
    r"'(?P<old_ward>(?:[^']|\\')+)'\s*,\s*"
    r"'(?P<old_district>(?:[^']|\\')+)'\s*,\s*"
    r"'(?P<old_province>(?:[^']|\\')+)'\s*,\s*"
    r"'(?P<new_code>[^']+)'\s*,\s*"
    r"'(?P<new_ward>(?:[^']|\\')+)'\s*,\s*"
    r"'(?P<new_province>(?:[^']|\\')+)'"
)


def load_ward_mappings_dak_lak() -> pd.DataFrame:
    """Load Đắk Lắk + Phú Yên (cũ) → Đắk Lắk (mới) ward_mappings."""
    text = WARD_MAPPINGS_SQL.read_text(encoding="utf-8")
    rows = []
    for m in _MAPPING_ROW.finditer(text):
        old_prov = m.group("old_province")
        new_prov = m.group("new_province")
        # Filter: old in Đắk Lắk cũ or Phú Yên; new = Đắk Lắk
        if "Đắk Lắk" in old_prov or "Phú Yên" in old_prov:
            if "Đắk Lắk" in new_prov:
                rows.append({
                    "old_ward_code": m.group("old_code"),
                    "old_ward_name": m.group("old_ward").replace("\\'", "'"),
                    "old_district_name": m.group("old_district").replace("\\'", "'"),
                    "old_province_name": old_prov,
                    "new_ward_code": m.group("new_code"),
                    "new_ward_name": m.group("new_ward").replace("\\'", "'"),
                })
    df = pd.DataFrame(rows)
    df["old_ward_norm"] = df["old_ward_name"].apply(normalize_vn)
    df["old_district_norm"] = df["old_district_name"].apply(normalize_vn)
    return df


_WARD_ROW = re.compile(
    r"VALUES\s*\(\s*\d+\s*,\s*"
    r"'(?P<code>[0-9]+)'\s*,\s*"
    r"'(?P<name>(?:[^']|'')+)'\s*,\s*"
    r"'(?P<province>[0-9]+)'\s*\)"
)


def load_wards_dak_lak() -> pd.DataFrame:
    """Load wards.sql, filter province_code = 66 (Đắk Lắk mới)."""
    text = WARDS_SQL.read_text(encoding="utf-8")
    rows = []
    for m in _WARD_ROW.finditer(text):
        if m.group("province") == "66":
            name = m.group("name").replace("''", "'")
            rows.append({
                "ward_code": m.group("code"),
                "ward_name": name,
                "kind": get_ward_kind(name),
            })
    df = pd.DataFrame(rows)
    df["ward_norm"] = df["ward_name"].apply(normalize_vn)
    return df


def main():
    print("=== Đắk Lắk KV Table Build ===")
    print()

    # 1. Load master Excel (pre-2025 KK/ĐBKK)
    master = load_master_dak_lak()
    print(f"Master Excel — Đắk Lắk + Phú Yên KK/ĐBKK rows: {len(master)}")
    print(f"  Loại: {dict(master['loai'].value_counts())}")
    print()

    # 2. Load ward_mappings (Đắk Lắk + Phú Yên cũ → Đắk Lắk mới)
    mappings = load_ward_mappings_dak_lak()
    print(f"ward_mappings — Đắk Lắk + Phú Yên cũ → Đắk Lắk mới: {len(mappings)}")
    print(f"  Unique new wards: {mappings['new_ward_code'].nunique()}")
    print()

    # 3. Load wards.sql (Đắk Lắk mới post-2025)
    wards = load_wards_dak_lak()
    print(f"wards.sql — Đắk Lắk mới wards: {len(wards)}")
    print(f"  Kinds: {dict(wards['kind'].value_counts())}")
    print()

    # 4. Build crosswalk: match each master row to mapping by (ten_huyen, ten_xa normalized)
    #    Then group by new_ward_code → set of loai
    new_ward_kv1_sources = defaultdict(list)  # new_ward_code → list of (master_ten_xa, loai)
    matched_master = 0
    unmatched_master = []

    # Build mapping lookup by old district + old ward normalized
    mapping_lookup = defaultdict(list)  # (old_district_norm, old_ward_norm) → list of mapping rows
    for _, row in mappings.iterrows():
        key = (row["old_district_norm"], row["old_ward_norm"])
        mapping_lookup[key].append(row)

    for _, mrow in master.iterrows():
        key = (mrow["ten_huyen_norm"], mrow["ten_xa_norm"])
        if key in mapping_lookup:
            for map_row in mapping_lookup[key]:
                new_ward_kv1_sources[map_row["new_ward_code"]].append({
                    "old_ten_xa": mrow["ten_xa"],
                    "old_ten_huyen": mrow["ten_huyen"],
                    "old_ten_tinh": mrow["ten_tinh"],
                    "loai": mrow["loai"],
                    "new_ward_name": map_row["new_ward_name"],
                })
            matched_master += 1
        else:
            unmatched_master.append((mrow["ten_tinh"], mrow["ten_huyen"], mrow["ten_xa"], mrow["loai"]))

    print(f"Crosswalk: {matched_master}/{len(master)} master rows matched")
    print(f"  KV1 wards mapped: {len(new_ward_kv1_sources)}")
    print(f"  Unmatched master rows: {len(unmatched_master)}")
    if unmatched_master:
        print("  Sample unmatched (first 5):")
        for u in unmatched_master[:5]:
            print(f"    {u}")
    print()

    # 5. Build final table: 102 Đắk Lắk mới wards × KV
    # province_code 66 = Đắk Lắk → TỈNH (not TP TƯ)
    # Default rule for TỈNH: Phường → KV2, Xã → KV2-NT, Đặc khu → check master
    results = []
    for _, w in wards.iterrows():
        code = w["ward_code"]
        kv1_src = new_ward_kv1_sources.get(code)
        if kv1_src:
            area_code = "KV1"
            sources = [f"{s['old_ten_huyen']}/{s['old_ten_xa']}={s['loai']}" for s in kv1_src]
            source_summary = f"KK/ĐBKK ({len(kv1_src)} old xã)"
        else:
            # Default rule for TỈNH Đắk Lắk
            if w["kind"] == "PHUONG":
                area_code = "KV2"
                source_summary = "Default: Phường tỉnh"
            elif w["kind"] == "DAC_KHU":
                area_code = "KV2-NT"  # Đắk Lắk có đặc khu? — unlikely
                source_summary = "Default: Đặc khu non-KV1"
            else:
                area_code = "KV2-NT"
                source_summary = "Default: Xã tỉnh"
            sources = []
        results.append({
            "ward_code": code,
            "ward_name": w["ward_name"],
            "kind": w["kind"],
            "area_code": area_code,
            "source_summary": source_summary,
            "kv1_old_sources": sources,
        })

    # Output
    OUTPUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(results).drop(columns=["kv1_old_sources"]).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    # Stats
    from collections import Counter
    dist = Counter(r["area_code"] for r in results)
    print(f"=== Final Đắk Lắk KV Table ===")
    print(f"Total wards post-2025: {len(results)}")
    for kv in ("KV1", "KV2", "KV2-NT", "KV3"):
        print(f"  {kv:7s} {dist.get(kv, 0)}")
    print()
    print(f"Sample KV1 wards (first 5):")
    for r in [r for r in results if r["area_code"] == "KV1"][:5]:
        print(f"  {r['ward_code']} {r['ward_name']:<30} {r['area_code']}  ({r['source_summary']})")
    print()
    print(f"Sample KV2 wards (first 5):")
    for r in [r for r in results if r["area_code"] == "KV2"][:5]:
        print(f"  {r['ward_code']} {r['ward_name']:<30} {r['area_code']}  ({r['source_summary']})")
    print()
    print(f"Sample KV2-NT wards (first 5):")
    for r in [r for r in results if r["area_code"] == "KV2-NT"][:5]:
        print(f"  {r['ward_code']} {r['ward_name']:<30} {r['area_code']}  ({r['source_summary']})")
    print()
    print(f"Output: {OUTPUT_JSON}, {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
