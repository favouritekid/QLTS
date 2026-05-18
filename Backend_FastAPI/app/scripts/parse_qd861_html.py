"""Parse QĐ 861/QĐ-TTg HTML (thuvienphapluat mirror) → JSON intermediate.

Input: Documents/reports/qd861_raw/qd861_tvpl.html (6.1 MB, downloaded via curl)
Output: Documents/reports/qd861_raw/qd861_parsed.json

State machine:
- Current province tracker (resets when new tỉnh heading detected)
- Current district tracker (resets when new huyện heading detected)
- Each data row = (TT, ten_xa, khu_vuc) → emit (province, district, ward, zone)

Zone normalization: 'I' → 'I', 'II' → 'II', 'III' → 'III' (kept as Roman).
Mapping to tuyển sinh KV1 (all 3 → KV1) happens in downstream step.

Usage (inside container with HTML at /tmp/qd861_tvpl.html):
    docker compose exec backend python -m app.scripts.parse_qd861_html \\
        --html /tmp/qd861_tvpl.html \\
        --output /tmp/qd861_parsed.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


# Province heading patterns. The QĐ 861 appendix uses uppercase province names
# in a section heading like: "Tỉnh AN GIANG" / "TP. HÀ NỘI" / etc.
# In thuvienphapluat HTML, these appear as text inside td.colspan-spanning cells
# preceded by Roman numeral counters (I., II., III., etc.).

PROVINCE_HEADING_RE = re.compile(
    r"^(?:[IVX]+\.|[0-9]+\.)?\s*"
    r"(?:T[ỈI][nN][hH]|TP\.?|Thành ph[ốỐ]|TP\s)\s+"
    r"(?P<name>[A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ\s\-]{3,40}?)\s*$",
    re.IGNORECASE,
)

# Inline "Tỉnh xxx" / "Thành phố xxx" inside heading
PROVINCE_INLINE_RE = re.compile(
    r"\b(?:T[ỉI][nN][hH]|Thành\s+ph[ốỐ]|TP\.?)\s+([A-ZÀ-ỹĐa-z\s\-]+?)(?=\s*$|\s+[IVX])",
    re.IGNORECASE,
)

# Huyện heading: "Huyện X" / "Thị xã Y" / "Thành phố Z" (cấp huyện)
DISTRICT_HEADING_RE = re.compile(
    r"^\s*(?:Huy[ệệ]n|Th[ịị]\s*x[ãã]|Thành\s*ph[ốố]|Qu[ậậ]n)\s+(.+?)\s*$",
    re.IGNORECASE,
)

# Zone cell: contains exactly 'I', 'II', or 'III' (with optional whitespace/dots)
ZONE_RE = re.compile(r"^\s*(I{1,3})\s*$")

# Ward row: starts with "Xã X" / "Thị trấn Y" / "Phường Z"
WARD_PREFIX_RE = re.compile(r"^(?:Xã|Thị\s*trấn|Phường)\s+", re.IGNORECASE)


def normalize_text(s: str) -> str:
    """Collapse whitespace + strip."""
    return re.sub(r"\s+", " ", s).strip()


def detect_province(text: str) -> Optional[str]:
    """Return canonicalized province name if text matches a heading, else None."""
    text = normalize_text(text)
    # Anchor 1: explicit "Tỉnh X" or "Thành phố Y" prefix
    m = re.match(
        r"^(?:T[ỉi]nh|Thành\s*ph[ốo]|TP\.?)\s+(.+?)$",
        text,
        re.IGNORECASE,
    )
    if m:
        name = normalize_text(m.group(1))
        # Filter out obvious non-province text
        if 2 <= len(name) <= 35 and not re.search(r"\d", name):
            return name
    return None


def detect_district(text: str) -> Optional[str]:
    text = normalize_text(text)
    m = re.match(
        r"^(?:Huy[ệe]n|Th[ịi]\s*x[ãa]|Thành\s*ph[ốo]|Qu[ậa]n)\s+(.+?)$",
        text,
        re.IGNORECASE,
    )
    if m:
        return normalize_text(m.group(1))
    return None


def detect_zone(text: str) -> Optional[str]:
    text = normalize_text(text)
    m = ZONE_RE.match(text)
    return m.group(1) if m else None


def detect_ward(text: str) -> Optional[str]:
    text = normalize_text(text)
    if WARD_PREFIX_RE.match(text):
        return text
    return None


def parse(html_path: Path) -> List[Dict[str, str]]:
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    # Find the master table — heuristic: largest table by row count
    tables = soup.find_all("table")
    master = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = master.find_all("tr")
    print(f"[parse] Master table: {len(rows)} rows", file=sys.stderr)

    cur_province: Optional[str] = None
    cur_district: Optional[str] = None
    results: List[Dict[str, str]] = []

    for row in rows:
        cells = [normalize_text(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if not cells:
            continue

        # Skip empty rows
        if all(not c for c in cells):
            continue

        # Pattern recognition strategies:
        # 1) Row with a single (colspan) cell containing "Tỉnh X" / "TP X" → province heading
        # 2) Row with single cell "Huyện X" → district heading
        # 3) Row with 3 cells: [TT, name, zone] where zone matches I/II/III → ward data row
        # 4) Row with name starting with Xã/TT/Phường + a zone elsewhere → ward data row

        joined = " | ".join(cells)
        # Province detection (longer text, contains "Tỉnh" or "Thành phố")
        for c in cells:
            p = detect_province(c)
            if p and len(c) <= 40:
                cur_province = p
                cur_district = None
                break
        else:
            # Not a province row — check district
            for c in cells:
                d = detect_district(c)
                if d and len(c) <= 60:
                    cur_district = d
                    break
            else:
                # Try ward row: look for ward name + zone I/II/III in cells
                ward_name = None
                zone = None
                for c in cells:
                    if ward_name is None:
                        w = detect_ward(c)
                        if w:
                            ward_name = w
                    if zone is None:
                        z = detect_zone(c)
                        if z:
                            zone = z
                if ward_name and zone:
                    results.append({
                        "province": cur_province or "",
                        "district": cur_district or "",
                        "ward": ward_name,
                        "zone": zone,
                    })

    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = parse(args.html)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[done] Parsed {len(rows)} rows → {args.output}", file=sys.stderr)

    # Distribution + missing-province sanity
    from collections import Counter
    zone_dist = Counter(r["zone"] for r in rows)
    print(f"[stats] Zone distribution: {dict(zone_dist)}", file=sys.stderr)

    no_province = [r for r in rows if not r["province"]]
    no_district = [r for r in rows if not r["district"]]
    print(f"[stats] Missing province: {len(no_province)}, missing district: {len(no_district)}", file=sys.stderr)

    provinces = Counter(r["province"] for r in rows if r["province"])
    print(f"[stats] Provinces detected: {len(provinces)}", file=sys.stderr)
    print(f"[stats] Top 5 provinces by ward count:", file=sys.stderr)
    for p, n in provinces.most_common(5):
        print(f"  {p}: {n} xã", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
