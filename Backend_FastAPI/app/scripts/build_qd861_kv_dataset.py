"""Phase B.2 Q9 #07 — Build vn_commune_area_map seed CSV from local SQL.

Stage 1A: Default KV classification per (province type, ward type), no
external data. Stage 1B (KV1 override from QĐ 861/QĐ-TTg DTTS list) is a
separate sub-PR that needs offline DOC download from luatvietnam.vn
(paywall blocks WebFetch).

Inputs (committed to repo):
- Documents/Seeding data/data province/provinces.sql  (34 rows post-2025)
- Documents/Seeding data/data province/wards.sql      (3,321 rows post-2025)

Output:
- Backend_FastAPI/app/seed/vn_commune_kv_stage1a.csv

CSV columns match vn_locality_service.import_commune_csv:
    commune_code, province, district, ward, area_code

Convention (revised 2026-05-26 — see commune_code note):
- commune_code = ward.code (raw, e.g. "00025"). administrative_nodes.code is
  nationally-unique for current-era wards, and the FE stores that raw code in
  profile.permanent_commune_code. The earlier "{province_code}_{ward_code}"
  composed form was dropped because the province prefix only desynced the KV
  catalog key from the FE-stored code (commune KV never resolved). Engine
  lookup is opaque equality, so raw is safe everywhere.
- district = ""  (post-sáp nhập 2025 không còn cấp huyện)
- area_code regex `^KV[1-9](-NT)?$` (CHECK constraint phase1_08b)

Default KV rule (per TT 06/2026 + research_qd861_data_source.md):
- Đặc khu (đảo)            → KV1   (hải đảo/đặc khu union per design doc)
- TP TƯ + Phường           → KV3   (inner-city)
- TP TƯ + Xã               → KV2   (outer-city)
- Tỉnh + Phường            → KV2   (provincial urban)
- Tỉnh + Xã                → KV2-NT (rural default — most populous bucket)

Stage 1B will OVERRIDE these defaults with KV1 cho DTTS communes (QĐ 861)
+ bãi ngang (QĐ 353) via temporal expire-and-insert pattern.

Usage (run inside backend container; Documents/ NOT in image, bind-mount):

    docker compose run --rm --no-deps \\
        -v "$(pwd)/Documents:/repo-docs" backend \\
        python -m app.scripts.build_qd861_kv_dataset \\
            --provinces-sql /repo-docs/Seeding\\ data/data\\ province/provinces.sql \\
            --wards-sql     /repo-docs/Seeding\\ data/data\\ province/wards.sql

    # Default paths assume Documents/ is mounted at /repo-docs:
    docker compose run --rm --no-deps \\
        -v "$(pwd)/Documents:/repo-docs" backend \\
        python -m app.scripts.build_qd861_kv_dataset

Ship sequence:
    1. Run locally → produces app/seed/vn_commune_kv_stage1a.csv
    2. Commit CSV to repo (audit trail + Docker COPY ships into image)
    3. Post-deploy: admin POST CSV to /api/v2/admin/vn-locality/communes/import
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class Province:
    code: str
    name: str
    place_type: str

    @property
    def is_tp_tu(self) -> bool:
        return self.place_type == "Thành phố Trung Ương"


@dataclass(frozen=True)
class Ward:
    code: str
    name: str
    province_code: str

    @property
    def kind(self) -> str:
        """One of: PHUONG | XA | DAC_KHU."""
        if self.name.startswith("Đặc khu"):
            return "DAC_KHU"
        if self.name.startswith("Phường"):
            return "PHUONG"
        return "XA"


# Paths — default to docker bind-mount location `/repo-docs` when Documents/
# is mounted in, fallback to host repo layout for unit-test runs.
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR.parent
HOST_REPO_ROOT = BACKEND_DIR.parent  # parent of Backend_FastAPI/

_BIND_DIR = Path("/repo-docs/Seeding data/data province")
_HOST_DIR = HOST_REPO_ROOT / "Documents" / "Seeding data" / "data province"
DEFAULT_SEED_DIR = _BIND_DIR if _BIND_DIR.exists() else _HOST_DIR

OUTPUT_DIR = APP_DIR / "seed"
OUTPUT_FILE = OUTPUT_DIR / "vn_commune_kv_stage1a.csv"

# Postgres multi-row VALUES: (id, 'code', 'name', 'short', 'code5', 'place_type', 'VN'),
_PROVINCE_ROW = re.compile(
    r"\(\s*\d+\s*,\s*'(?P<code>[0-9]+)'\s*,\s*"
    r"'(?P<name>(?:[^']|'')+)'\s*,\s*"
    r"'(?:[^']|'')+'\s*,\s*"
    r"'(?:[^']|'')+'\s*,\s*"
    r"'(?P<place_type>(?:[^']|'')+)'\s*,\s*"
    r"'VN'\s*\)"
)

# Postgres single-row INSERT per line:
# INSERT INTO wards (id, ward_code, name, province_code) VALUES (1, '00004', 'Phường Ba Đình', '01');
# Name allows SQL-escaped apostrophe ('' → ') — e.g. "Phường B''Lao" in Lâm Đồng.
_WARD_ROW = re.compile(
    r"VALUES\s*\(\s*\d+\s*,\s*"
    r"'(?P<ward_code>[0-9]+)'\s*,\s*"
    r"'(?P<name>(?:[^']|'')+)'\s*,\s*"
    r"'(?P<province_code>[0-9]+)'\s*\)\s*;"
)


def _unescape_sql(s: str) -> str:
    """Reverse SQL double-apostrophe escape: ''  →  '."""
    return s.replace("''", "'")


def parse_provinces(path: Path) -> Dict[str, Province]:
    text = path.read_text(encoding="utf-8")
    out: Dict[str, Province] = {}
    for m in _PROVINCE_ROW.finditer(text):
        p = Province(
            code=m.group("code"),
            name=_unescape_sql(m.group("name")),
            place_type=_unescape_sql(m.group("place_type")),
        )
        if p.code in out:
            raise ValueError(f"Duplicate province code {p.code} in {path}")
        out[p.code] = p
    if not out:
        raise ValueError(f"No provinces parsed from {path}")
    return out


def parse_wards(path: Path) -> List[Ward]:
    text = path.read_text(encoding="utf-8")
    wards: List[Ward] = []
    seen: set[str] = set()
    for m in _WARD_ROW.finditer(text):
        w = Ward(
            code=m.group("ward_code"),
            name=_unescape_sql(m.group("name")),
            province_code=m.group("province_code"),
        )
        if w.code in seen:
            raise ValueError(f"Duplicate ward_code {w.code} in {path}")
        seen.add(w.code)
        wards.append(w)
    if not wards:
        raise ValueError(f"No wards parsed from {path}")
    return wards


def classify_kv(ward: Ward, province: Province) -> str:
    if ward.kind == "DAC_KHU":
        return "KV1"
    if province.is_tp_tu:
        return "KV3" if ward.kind == "PHUONG" else "KV2"
    return "KV2" if ward.kind == "PHUONG" else "KV2-NT"


def build_rows(
    provinces: Dict[str, Province], wards: List[Ward]
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for w in wards:
        p = provinces.get(w.province_code)
        if p is None:
            raise ValueError(
                f"Ward {w.code} {w.name!r} references unknown province "
                f"{w.province_code!r}"
            )
        rows.append(
            {
                "commune_code": w.code,  # raw ward.code (matches FE permanent_commune_code)
                "province": p.name,
                "district": "",
                "ward": w.name,
                "area_code": classify_kv(w, p),
            }
        )
    return rows


def write_csv(rows: List[Dict[str, str]], path: Path = OUTPUT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig adds BOM → Excel/Notepad on Windows opens it as UTF-8
    # (without BOM, Excel falls back to ANSI/CP-1258 → garbled diacritics).
    # The import service already strips BOM via utf-8-sig decode, so this
    # is fully round-trip safe.
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["commune_code", "province", "district", "ward", "area_code"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--provinces-sql",
        type=Path,
        default=DEFAULT_SEED_DIR / "provinces.sql",
        help="Path to provinces.sql (default: bind-mount /repo-docs or host repo)",
    )
    parser.add_argument(
        "--wards-sql",
        type=Path,
        default=DEFAULT_SEED_DIR / "wards.sql",
        help="Path to wards.sql (default: bind-mount /repo-docs or host repo)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="Output CSV path (default: app/seed/vn_commune_kv_stage1a.csv)",
    )
    args = parser.parse_args(argv)

    provinces = parse_provinces(args.provinces_sql)
    wards = parse_wards(args.wards_sql)
    rows = build_rows(provinces, wards)
    write_csv(rows, args.output)

    dist = Counter(r["area_code"] for r in rows)
    tp_tu_codes = {c for c, p in provinces.items() if p.is_tp_tu}
    print(f"Provinces parsed: {len(provinces)} ({len(tp_tu_codes)} TP TƯ)")
    print(f"Wards parsed:     {len(wards)}")
    print(f"CSV written:      {args.output}")
    print("KV distribution:")
    for kv in ("KV1", "KV2", "KV2-NT", "KV3"):
        print(f"  {kv:7s} {dist.get(kv, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
