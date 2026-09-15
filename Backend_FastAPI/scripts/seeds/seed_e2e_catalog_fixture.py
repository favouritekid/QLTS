#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixture DANH MỤC tối thiểu cho E2E — địa giới + KV xã + trường + KV trường.

VÌ SAO TỆP NÀY TỒN TẠI
======================

Trên một CSDL vừa ``alembic upgrade head`` + ``scripts.seed_from_xlsx`` (đúng
chuỗi mà ``nightly-regression.yml`` chạy), bốn bảng danh mục dưới đây ĐỀU RỖNG::

    administrative_nodes = 0     vn_school               = 0
    vn_commune_area_map  = 0     vn_school_kv_assignment = 0

Không migration nào INSERT vào chúng, và không bước workflow nào gọi seed danh
mục. Hệ quả đo được: MỌI hồ sơ E2E nộp qua ``POST /api/admissions/{id}/submit``
đều fail-closed ở hai cổng độc lập trong ``admission_service.submit_and_evaluate``:

* ``_kv_unresolved_error_message`` — engine KV trả ``insufficient_data`` /
  ``catalog_gap_school`` / ``catalog_gap_commune`` vì không tra được bảng nào.
* ``_is_current_era_ward`` — ``permanent_commune_code`` phải là một WARD
  **đương thời** (``valid_to IS NULL`` + ``is_active``) trong
  ``administrative_nodes``; bảng rỗng ⇒ luôn False.

Đây là fixture để E2E vượt hai cổng ấy bằng **dữ liệu thật của sản phẩm**, KHÔNG
phải bằng cách nới validator.

KHÔNG PHỤ THUỘC HAI ĐƯỜNG ĐÃ HỎNG
=================================

``scripts/seeds/seed_administrative_nodes.py`` đọc
``Documents/Seeding data/data province/ward_mappings.sql`` — tệp ấy **CHƯA TỪNG
có trong git**. ``app/scripts/build_kv_table_dak_lak.py`` đọc
``/tmp/ward_mappings.sql``. Cả hai đường đều không tái lập được trên một clean
checkout, nên tệp này KHÔNG dùng chúng.

Nguồn của fixture là ``Documents/reports/dak_lak_kv_table.csv`` — có sẵn trong
git. Các hàng đã chọn được chép NGUYÊN VĂN vào ``FIXTURE_WARDS`` bên dưới (hằng
số, không đọc tệp lúc chạy) vì ``Documents/`` nằm NGOÀI build context của ảnh
backend (``context: ./Backend_FastAPI``) nên không bao giờ có trong container.
Quan hệ hằng-số ↔ CSV gốc được khoá bằng ``tests/unit/test_e2e_catalog_fixture.py``.

GUARD — HAI TẦNG, FAIL-CLOSED
=============================

Tầng 1  ``APP_ENV`` phải nằm trong allowlist (mặc định: chỉ ``test``).
Tầng 2  TÊN CSDL phải nằm trong allowlist (mặc định: chỉ ``qlts_test``) — kiểm
        HAI LẦN: trên ``DATABASE_URL`` trước khi kết nối, và trên
        ``SELECT current_database()`` sau khi kết nối (đo trạng thái thật, không
        tin chuỗi cấu hình), cộng thêm một phép so hai giá trị ấy phải trùng.

``--allow-dev`` nới cả hai allowlist sang ``development`` / ``qlts_dev``. Không
có cờ nào nới sang production: ``production`` và ``qlts_production`` bị chặn
cứng trong ``_ALWAYS_FORBIDDEN_*``.

Mặc định của CLI là **dry-run**; phải nêu ``--apply`` mới ghi.

IDEMPOTENT
==========

Mọi hàng đều get-or-create theo khoá tự nhiên. Chạy lại lượt hai chèn 0 hàng.
``administrative_nodes`` KHÔNG có UNIQUE nào trên ``code`` (đã đo bằng ``\\d``)
nên tính idempotent ở đó là do script bảo đảm, không do CSDL — vì vậy phần
``_verify`` đếm lại từng mã và ĐỎ nếu có mã nào xuất hiện >1 lần.

HẬU ĐIỀU KIỆN
=============

``_verify`` chạy HAI lần: một lần TRƯỚC ``commit`` (lỗi ⇒ rollback, không ghi
gì) và một lần trên PHIÊN MỚI sau commit (identity map rỗng ⇒ buộc SELECT thật).
Nó không đếm "có hàng nào không" mà gọi thẳng hai hàm sản phẩm
``priority_service._lookup_commune_kv`` và ``lookup_kv_for_school_year`` để
chứng minh engine tra RA ĐÚNG KV đã khai.

CÁCH CHẠY
=========

    # trong container backend (fixture nằm trong ảnh, chạy được bằng -m)
    docker compose exec -T backend \\
        python -m scripts.seeds.seed_e2e_catalog_fixture --apply

    # xem trước, không chạm CSDL
    docker compose exec -T backend \\
        python -m scripts.seeds.seed_e2e_catalog_fixture
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import sys
from datetime import date
from typing import Any, Iterable, Optional

# =============================================================================
# NGUỒN — Documents/reports/dak_lak_kv_table.csv (PA-A)
# =============================================================================
# Đo trên blob đang có trong git (xem test khoá quan hệ):
#   * UTF-8 CÓ BOM, kết dòng CRLF
#   * header 5 cột: ward_code,ward_name,kind,area_code,source_summary
#     (mô tả "4 cột" lưu hành trước đây là THIẾU cột source_summary)
#   * 102 hàng dữ liệu, ward_code KHÔNG trùng lặp
#   * phân bố area_code: KV1=90 · KV2=4 · KV2-NT=8 (không có KV3 — KV3 là giá
#     trị MẶC ĐỊNH KHI VẮNG MẶT theo TT 05/2021, cố ý không lưu)
#   * phân bố kind: PHUONG=14 · XA=88
PA_A_CSV_REPO_PATH = "Documents/reports/dak_lak_kv_table.csv"
PA_A_ROW_COUNT = 102
PA_A_AREA_CODE_DISTRIBUTION = {"KV1": 90, "KV2": 4, "KV2-NT": 8}

# Quy tắc chọn: HÀNG ĐẦU TIÊN của mỗi area_code theo ĐÚNG thứ tự xuất hiện
# trong tệp. Tất định, không phụ thuộc sort, tái lập được bằng
# ``select_minimal_wards()`` bên dưới.
PA_A_SELECTION_RULE = "first row per distinct area_code, in file order"

# Tỉnh của 102 xã này: Đắk Lắk (mới) = Đắk Lắk (cũ) + Phú Yên, theo
# ``app/scripts/build_kv_table_dak_lak.py``. Mã tỉnh 66 lấy từ bảng TCTK trong
# ``scripts/seeds/seed_administrative_nodes.py:91``.
FIXTURE_PROVINCE_CODE = "66"
FIXTURE_PROVINCE_NAME = "Tỉnh Đắk Lắk"

# Mốc địa giới 2 cấp (QĐ 19/2025) — cùng giá trị mà
# ``seed_administrative_nodes.py`` dùng cho nhánh "current".
CURRENT_ERA_VALID_FROM = date(2025, 7, 1)

# 3 xã, chép NGUYÊN VĂN từ PA-A (ward_code, ward_name, kind, area_code).
FIXTURE_WARDS: tuple[dict[str, str], ...] = (
    {
        "ward_code": "22015",
        "ward_name": "Phường Tuy Hòa",
        "kind": "PHUONG",
        "area_code": "KV2",
    },
    {
        "ward_code": "22045",
        "ward_name": "Phường Bình Kiến",
        "kind": "PHUONG",
        "area_code": "KV1",
    },
    {
        "ward_code": "22114",
        "ward_name": "Xã Tuy An Bắc",
        "kind": "XA",
        "area_code": "KV2-NT",
    },
)

# Trường THPT — nguồn RIÊNG, KHÔNG mượn từ PA-A.
#
# ``app/scripts/seed_commune_kv.py`` nói thẳng: KV-trường và KV-thường-trú là
# HAI NGUỒN TÁCH RỜI, không mượn chéo. PA-A là bảng KV **thường trú**; nó không
# phát biểu gì về KV của trường. Nên KV dưới đây là giá trị DO FIXTURE ẤN ĐỊNH.
#
# Ba trường đầu ăn theo KV xã nơi trường đóng (hợp lý về nghiệp vụ, và cho E2E
# đủ cả KV1/KV2/KV2-NT). Trường thứ tư CỐ Ý lệch: nó đóng ở xã KV2 nhưng mang
# KV3 — nhờ vậy một khẳng định E2E trên ``kv_resolved`` phân biệt được NGÃ NÀO
# đã resolve (LICH_SU_THPT qua trường → KV3, hay THUONG_TRU qua xã → KV2).
#
# Dải mã 9xx được giữ riêng cho fixture để không đụng dữ liệu MOET thật mà
# ``app/scripts/import_moet_schools_3_provinces.py`` nạp.
FIXTURE_SCHOOLS: tuple[dict[str, Any], ...] = (
    {
        "moet_school_code": "901",
        "name": "THPT E2E Bình Kiến",
        "commune_code": "22045",
        "kv_code": "KV1",
    },
    {
        "moet_school_code": "902",
        "name": "THPT E2E Tuy Hòa",
        "commune_code": "22015",
        "kv_code": "KV2",
    },
    {
        "moet_school_code": "903",
        "name": "THPT E2E Tuy An Bắc",
        "commune_code": "22114",
        "kv_code": "KV2-NT",
    },
    {
        "moet_school_code": "904",
        "name": "THPT E2E Tuy Hòa (KV3)",
        "commune_code": "22015",
        "kv_code": "KV3",
    },
)

# Dải năm của ``vn_school_kv_assignment``.
#
# ``lookup_kv_for_school_year`` tra theo TỪNG NĂM trong ``[year_from, year_to]``
# của mỗi mục ``academic_history``. Một dải hẹp làm hồ sơ có năm học cũ rơi vào
# ``catalog_gap_school`` — đúng lớp lỗi fixture này sinh ra để đóng. 2000→NULL
# phủ mọi năm E2E có thể dựng mà vẫn thoả CHECK ``effective_to_year >=
# effective_from_year``.
SCHOOL_KV_FROM_YEAR = 2000
SCHOOL_KV_TO_YEAR: Optional[int] = None
SCHOOL_KV_SOURCE = "manual_admin"
FIXTURE_NOTE = "E2E catalog fixture — scripts/seeds/seed_e2e_catalog_fixture.py"

# ⚠️ HAI QUY ƯỚC ĐANG LỆCH NHAU TRONG CHÍNH KHO NÀY:
#   * ``app/scripts/import_moet_schools_3_provinces.py:93`` ghi
#     ``moet_province_code = ma_tinh.zfill(3)``  → "066"
#   * ``app/scripts/rebuild_school_kv_from_xls.py:183`` ghi
#     ``moet_province_code = gso`` (thô)          → "66"
# Fixture theo bản zfill(3) vì đó là bản DUY NHẤT dùng được với endpoint sản
# phẩm: ``GET /api/v2/vn-school/search`` khai ``province`` là
# ``Query(min_length=3, max_length=3)`` — mã 2 ký tự không bao giờ khớp.
MOET_PROVINCE_CODE = FIXTURE_PROVINCE_CODE.zfill(3)
# ``moet_code`` = mã tỉnh 2 số + mã trường 3 số (rebuild_school_kv_from_xls:232).
MOET_CODE_PROVINCE_PREFIX = FIXTURE_PROVINCE_CODE.zfill(2)
SCHOOL_LEVEL = "THPT"


# =============================================================================
# GUARD — hai tầng, fail-closed
# =============================================================================

class GuardError(RuntimeError):
    """Guard môi trường từ chối chạy. KHÔNG bắt rồi đi tiếp."""


_DEFAULT_ALLOWED_APP_ENV = frozenset({"test"})
_DEV_ALLOWED_APP_ENV = frozenset({"test", "development"})
_DEFAULT_ALLOWED_DB = frozenset({"qlts_test"})
_DEV_ALLOWED_DB = frozenset({"qlts_test", "qlts_dev"})

# Chặn cứng, KHÔNG cờ nào nới được.
_ALWAYS_FORBIDDEN_APP_ENV = frozenset({"production", "prod", "staging"})
_ALWAYS_FORBIDDEN_DB = frozenset({"qlts_production", "qlts_prod", "qlts"})


def allowed_app_envs(allow_dev: bool) -> frozenset[str]:
    return _DEV_ALLOWED_APP_ENV if allow_dev else _DEFAULT_ALLOWED_APP_ENV


def allowed_db_names(allow_dev: bool) -> frozenset[str]:
    return _DEV_ALLOWED_DB if allow_dev else _DEFAULT_ALLOWED_DB


def assert_app_env_allowed(app_env: Optional[str], *, allow_dev: bool = False) -> str:
    """TẦNG 1. Trả về APP_ENV đã chuẩn hoá; ném ``GuardError`` nếu không hợp lệ."""
    value = (app_env or "").strip()
    if not value:
        raise GuardError(
            "TẦNG 1 TỪ CHỐI: APP_ENV rỗng/không đặt. Fixture danh mục chỉ được "
            f"chạy khi APP_ENV ∈ {sorted(allowed_app_envs(allow_dev))}."
        )
    lowered = value.lower()
    if lowered in _ALWAYS_FORBIDDEN_APP_ENV:
        raise GuardError(
            f"TẦNG 1 TỪ CHỐI: APP_ENV={value!r} nằm trong danh sách CHẶN CỨNG "
            f"{sorted(_ALWAYS_FORBIDDEN_APP_ENV)}. Không cờ nào nới được."
        )
    if lowered not in allowed_app_envs(allow_dev):
        raise GuardError(
            f"TẦNG 1 TỪ CHỐI: APP_ENV={value!r} không thuộc "
            f"{sorted(allowed_app_envs(allow_dev))}"
            + ("" if allow_dev else " (thêm --allow-dev để nới sang development).")
        )
    return lowered


def assert_db_name_allowed(
    db_name: Optional[str], *, allow_dev: bool = False, nguon: str = "DATABASE_URL"
) -> str:
    """TẦNG 2. Trả về tên CSDL; ném ``GuardError`` nếu không hợp lệ."""
    value = (db_name or "").strip()
    if not value:
        raise GuardError(
            f"TẦNG 2 TỪ CHỐI: không đọc được tên CSDL từ {nguon}. "
            f"Chỉ chạy trên {sorted(allowed_db_names(allow_dev))}."
        )
    lowered = value.lower()
    if lowered in _ALWAYS_FORBIDDEN_DB:
        raise GuardError(
            f"TẦNG 2 TỪ CHỐI ({nguon}): CSDL {value!r} nằm trong danh sách CHẶN "
            f"CỨNG {sorted(_ALWAYS_FORBIDDEN_DB)}. Không cờ nào nới được."
        )
    if lowered not in allowed_db_names(allow_dev):
        raise GuardError(
            f"TẦNG 2 TỪ CHỐI ({nguon}): CSDL {value!r} không thuộc "
            f"{sorted(allowed_db_names(allow_dev))}"
            + ("" if allow_dev else " (thêm --allow-dev để nới sang qlts_dev).")
        )
    return lowered


# =============================================================================
# PA-A — quy tắc chọn (dùng lại bởi test khoá quan hệ)
# =============================================================================

PA_A_REQUIRED_COLUMNS = ("ward_code", "ward_name", "kind", "area_code")


def read_pa_a_rows(text: str) -> list[dict[str, str]]:
    """Đọc PA-A từ NỘI DUNG (không phải đường dẫn) — BOM + CRLF an toàn."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿"), newline=""))
    missing = [c for c in PA_A_REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"PA-A thiếu cột: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not (raw.get("ward_code") or "").strip():
            continue
        rows.append({c: (raw.get(c) or "").strip() for c in PA_A_REQUIRED_COLUMNS})
    return rows


def select_minimal_wards(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Quy tắc ``PA_A_SELECTION_RULE``: hàng ĐẦU TIÊN của mỗi area_code, thứ tự tệp."""
    seen: set[str] = set()
    picked: list[dict[str, str]] = []
    for row in rows:
        area = row["area_code"]
        if area in seen:
            continue
        seen.add(area)
        picked.append({c: row[c] for c in PA_A_REQUIRED_COLUMNS})
    return picked


# =============================================================================
# SEED
# =============================================================================

def _ward_path(ward_code: str) -> str:
    return f"{FIXTURE_PROVINCE_CODE}/{ward_code}"


def _school_moet_code(moet_school_code: str) -> str:
    return f"{MOET_CODE_PROVINCE_PREFIX}{moet_school_code}"


def _ward_by_code(ward_code: str) -> dict[str, str]:
    for w in FIXTURE_WARDS:
        if w["ward_code"] == ward_code:
            return w
    raise KeyError(
        f"FIXTURE_SCHOOLS trỏ tới xã {ward_code!r} không có trong FIXTURE_WARDS"
    )


async def _seed(session, *, ket_qua: dict[str, list[int]]) -> None:
    """Get-or-create toàn bộ fixture trên ``session``. Chỉ flush, KHÔNG commit."""
    from sqlalchemy import select

    from app.models.administrative_node import AdministrativeLevel, AdministrativeNode
    from app.models.vn_locality import VnCommuneAreaMap
    from app.models.vn_school import VnSchool, VnSchoolKvAssignment

    def ghi(bang: str, da_co: bool) -> None:
        ket_qua.setdefault(bang, [0, 0])
        ket_qua[bang][1 if da_co else 0] += 1

    # --- administrative_nodes: 1 PROVINCE ---------------------------------
    province = (
        await session.execute(
            select(AdministrativeNode).where(
                AdministrativeNode.code == FIXTURE_PROVINCE_CODE,
                AdministrativeNode.level == AdministrativeLevel.PROVINCE,
                AdministrativeNode.valid_to.is_(None),
            )
        )
    ).scalar_one_or_none()
    if province is None:
        province = AdministrativeNode(
            code=FIXTURE_PROVINCE_CODE,
            name=FIXTURE_PROVINCE_NAME,
            level=AdministrativeLevel.PROVINCE,
            parent_id=None,
            path=FIXTURE_PROVINCE_CODE,
            province_code=FIXTURE_PROVINCE_CODE,
            district_code=None,
            ward_code=None,
            valid_from=CURRENT_ERA_VALID_FROM,
            valid_to=None,
            is_active=True,
        )
        session.add(province)
        await session.flush()
        ghi("administrative_nodes.PROVINCE", False)
    else:
        ghi("administrative_nodes.PROVINCE", True)

    # --- administrative_nodes: 3 WARD đương thời ---------------------------
    for w in FIXTURE_WARDS:
        node = (
            await session.execute(
                select(AdministrativeNode).where(
                    AdministrativeNode.code == w["ward_code"],
                    AdministrativeNode.level == AdministrativeLevel.WARD,
                    AdministrativeNode.valid_to.is_(None),
                )
            )
        ).scalar_one_or_none()
        if node is None:
            session.add(
                AdministrativeNode(
                    code=w["ward_code"],
                    name=w["ward_name"],
                    level=AdministrativeLevel.WARD,
                    parent_id=province.id,
                    path=_ward_path(w["ward_code"]),
                    province_code=FIXTURE_PROVINCE_CODE,
                    # 2 cấp: xã treo THẲNG dưới tỉnh. ``get_wards_by_province``
                    # lọc ``district_code IS NULL`` nên giá trị khác sẽ làm
                    # endpoint /administrative/wards trả rỗng.
                    district_code=None,
                    ward_code=w["ward_code"],
                    valid_from=CURRENT_ERA_VALID_FROM,
                    valid_to=None,
                    is_active=True,
                    # PR-2 lineage: xã còn sống trỏ về CHÍNH NÓ, nếu không
                    # ``/administrative/resolve-ward`` trả resolved=false.
                    successor_ward_code=w["ward_code"],
                )
            )
            ghi("administrative_nodes.WARD", False)
        else:
            ghi("administrative_nodes.WARD", True)
    await session.flush()

    # --- vn_commune_area_map: KV THƯỜNG TRÚ (ngã THUONG_TRU) ---------------
    for w in FIXTURE_WARDS:
        row = (
            await session.execute(
                select(VnCommuneAreaMap).where(
                    VnCommuneAreaMap.commune_code == w["ward_code"],
                    VnCommuneAreaMap.effective_to.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(
                VnCommuneAreaMap(
                    commune_code=w["ward_code"],
                    province=FIXTURE_PROVINCE_NAME,
                    # ``seed_commune_kv.py`` cũng để rỗng: địa giới 2 cấp không
                    # còn cấp huyện, mà cột NOT NULL.
                    district="",
                    ward=w["ward_name"],
                    area_code=w["area_code"],
                    effective_from=CURRENT_ERA_VALID_FROM,
                    effective_to=None,
                )
            )
            ghi("vn_commune_area_map", False)
        else:
            ghi("vn_commune_area_map", True)
    await session.flush()

    # --- vn_school + vn_school_kv_assignment (ngã LICH_SU_THPT) ------------
    for s in FIXTURE_SCHOOLS:
        ward = _ward_by_code(s["commune_code"])
        school = (
            await session.execute(
                select(VnSchool).where(
                    VnSchool.moet_province_code == MOET_PROVINCE_CODE,
                    VnSchool.moet_school_code == s["moet_school_code"],
                    VnSchool.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if school is None:
            school = VnSchool(
                moet_school_code=s["moet_school_code"],
                moet_province_code=MOET_PROVINCE_CODE,
                moet_district_code=None,
                moet_code=_school_moet_code(s["moet_school_code"]),
                commune_code=s["commune_code"],
                name=s["name"],
                province=FIXTURE_PROVINCE_NAME,
                district=None,
                ward=ward["ward_name"],
                level=SCHOOL_LEVEL,
                is_dtnt=False,
                is_active=True,
            )
            session.add(school)
            await session.flush()
            ghi("vn_school", False)
        else:
            ghi("vn_school", True)

        assignment = (
            await session.execute(
                select(VnSchoolKvAssignment).where(
                    VnSchoolKvAssignment.school_id == school.id,
                    VnSchoolKvAssignment.effective_from_year == SCHOOL_KV_FROM_YEAR,
                )
            )
        ).scalar_one_or_none()
        if assignment is None:
            session.add(
                VnSchoolKvAssignment(
                    school_id=school.id,
                    kv_code=s["kv_code"],
                    effective_from_year=SCHOOL_KV_FROM_YEAR,
                    effective_to_year=SCHOOL_KV_TO_YEAR,
                    source=SCHOOL_KV_SOURCE,
                    notes=FIXTURE_NOTE,
                )
            )
            ghi("vn_school_kv_assignment", False)
        else:
            ghi("vn_school_kv_assignment", True)
    await session.flush()


async def _verify(session, *, kv_year: int, nhan: str) -> dict[str, Any]:
    """Hậu điều kiện. Ném ``GuardError`` ở khẳng định ĐẦU TIÊN không đạt.

    Không đếm "có hàng nào không" — gọi THẲNG hai hàm engine
    (``_lookup_commune_kv``, ``lookup_kv_for_school_year``) để chứng minh việc
    tra cứu mà submit thật sự đi qua CHO RA ĐÚNG KV đã khai.
    """
    from sqlalchemy import func, select

    from app.models.administrative_node import AdministrativeLevel, AdministrativeNode
    from app.models.vn_locality import VnCommuneAreaMap
    from app.models.vn_school import VnSchool, VnSchoolKvAssignment
    from app.services.priority_service import (
        _lookup_commune_kv,
        lookup_kv_for_school_year,
    )

    loi: list[str] = []

    def doi(dieu_kien: bool, thong_diep: str) -> None:
        if not dieu_kien:
            loi.append(thong_diep)

    # 1. Tỉnh đương thời, đúng 1 hàng.
    so_tinh = await session.scalar(
        select(func.count())
        .select_from(AdministrativeNode)
        .where(
            AdministrativeNode.code == FIXTURE_PROVINCE_CODE,
            AdministrativeNode.level == AdministrativeLevel.PROVINCE,
            AdministrativeNode.valid_to.is_(None),
        )
    )
    doi(so_tinh == 1, f"PROVINCE {FIXTURE_PROVINCE_CODE}: mong 1 hàng, đo {so_tinh}")

    for w in FIXTURE_WARDS:
        # 2. Xã đương thời, ĐÚNG 1 hàng (không có UNIQUE ở CSDL ⇒ tự đếm).
        so_xa = await session.scalar(
            select(func.count())
            .select_from(AdministrativeNode)
            .where(
                AdministrativeNode.code == w["ward_code"],
                AdministrativeNode.level == AdministrativeLevel.WARD,
                AdministrativeNode.valid_to.is_(None),
                AdministrativeNode.is_active.is_(True),
            )
        )
        doi(so_xa == 1, f"WARD {w['ward_code']}: mong 1 hàng đương thời, đo {so_xa}")

        # 3. Đúng hình dạng mà repository/endpoint địa giới đòi.
        # ``.first()``, KHÔNG ``.scalar_one_or_none()``: khi có hàng TRÙNG,
        # ``scalar_one_or_none`` ném ``MultipleResultsFound`` ngay tại đây và
        # nuốt mất thông điệp gộp ở cuối — người đọc chỉ thấy traceback
        # SQLAlchemy thay vì "mong 1 hàng đương thời, đo 2". Đã đo bằng đột
        # biến M8 (lookup WARD tra nhầm sang kỷ nguyên cũ).
        node = (
            await session.execute(
                select(AdministrativeNode)
                .where(
                    AdministrativeNode.code == w["ward_code"],
                    AdministrativeNode.level == AdministrativeLevel.WARD,
                    AdministrativeNode.valid_to.is_(None),
                )
                .order_by(AdministrativeNode.id)
                .limit(1)
            )
        ).scalars().first()
        if node is None:
            doi(False, f"WARD {w['ward_code']}: không đọc lại được")
        else:
            doi(
                node.district_code is None,
                f"WARD {w['ward_code']}: district_code phải NULL (2 cấp), đo "
                f"{node.district_code!r}",
            )
            doi(
                node.province_code == FIXTURE_PROVINCE_CODE,
                f"WARD {w['ward_code']}: province_code phải {FIXTURE_PROVINCE_CODE}",
            )
            doi(
                node.successor_ward_code == w["ward_code"],
                f"WARD {w['ward_code']}: successor_ward_code phải trỏ chính nó",
            )

        # 4. vn_commune_area_map: đúng 1 hàng còn hiệu lực, KV đúng.
        so_map = await session.scalar(
            select(func.count())
            .select_from(VnCommuneAreaMap)
            .where(
                VnCommuneAreaMap.commune_code == w["ward_code"],
                VnCommuneAreaMap.effective_to.is_(None),
            )
        )
        doi(so_map == 1, f"commune_area_map {w['ward_code']}: mong 1, đo {so_map}")

        # 5. ENGINE THẬT tra ra đúng KV thường trú.
        kv = await _lookup_commune_kv(session, w["ward_code"], kv_year)
        doi(
            kv == w["area_code"],
            f"_lookup_commune_kv({w['ward_code']}, {kv_year}) = {kv!r}, "
            f"mong {w['area_code']!r}",
        )

    for s in FIXTURE_SCHOOLS:
        so_truong = await session.scalar(
            select(func.count())
            .select_from(VnSchool)
            .where(
                VnSchool.moet_province_code == MOET_PROVINCE_CODE,
                VnSchool.moet_school_code == s["moet_school_code"],
                VnSchool.is_active.is_(True),
            )
        )
        doi(
            so_truong == 1,
            f"vn_school {MOET_PROVINCE_CODE}/{s['moet_school_code']}: mong 1, "
            f"đo {so_truong}",
        )
        school_id = await session.scalar(
            select(VnSchool.id).where(
                VnSchool.moet_province_code == MOET_PROVINCE_CODE,
                VnSchool.moet_school_code == s["moet_school_code"],
                VnSchool.is_active.is_(True),
            )
        )
        if school_id is None:
            doi(False, f"vn_school {s['moet_school_code']}: không đọc lại được id")
            continue
        so_gan = await session.scalar(
            select(func.count())
            .select_from(VnSchoolKvAssignment)
            .where(VnSchoolKvAssignment.school_id == school_id)
        )
        doi(so_gan == 1, f"kv_assignment school_id={school_id}: mong 1, đo {so_gan}")

        # 6. ENGINE THẬT tra ra đúng KV trường, ở cả hai đầu dải năm.
        for year in (SCHOOL_KV_FROM_YEAR, kv_year):
            kv = await lookup_kv_for_school_year(session, school_id, year)
            doi(
                kv == s["kv_code"],
                f"lookup_kv_for_school_year({school_id}, {year}) = {kv!r}, "
                f"mong {s['kv_code']!r}",
            )

    if loi:
        raise GuardError(
            f"HẬU ĐIỀU KIỆN KHÔNG ĐẠT ({nhan}) — {len(loi)} khẳng định:\n  - "
            + "\n  - ".join(loi)
        )
    return {
        "wards": len(FIXTURE_WARDS),
        "schools": len(FIXTURE_SCHOOLS),
        "kv_year": kv_year,
    }


async def apply(*, allow_dev: bool, kv_year: int) -> int:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from app.config import settings
    from app.database import AsyncSessionLocal

    # --- TẦNG 1 -----------------------------------------------------------
    app_env = assert_app_env_allowed(settings.APP_ENV, allow_dev=allow_dev)

    # --- TẦNG 2a: tên CSDL trên chuỗi cấu hình (trước khi kết nối) ---------
    db_tu_url = assert_db_name_allowed(
        make_url(str(settings.DATABASE_URL)).database,
        allow_dev=allow_dev,
        nguon="DATABASE_URL",
    )

    async with AsyncSessionLocal() as session:
        # --- TẦNG 2b: ĐO TRẠNG THÁI THẬT trên kết nối đang mở -------------
        db_thuc = assert_db_name_allowed(
            await session.scalar(text("SELECT current_database()")),
            allow_dev=allow_dev,
            nguon="current_database()",
        )
        if db_thuc != db_tu_url:
            raise GuardError(
                f"TẦNG 2 TỪ CHỐI: DATABASE_URL nói {db_tu_url!r} nhưng kết nối "
                f"thật đang ở {db_thuc!r}."
            )
        print(f"[guard] APP_ENV={app_env} · current_database()={db_thuc} · OK")

        ket_qua: dict[str, list[int]] = {}
        try:
            await _seed(session, ket_qua=ket_qua)
            # Hậu điều kiện TRƯỚC commit — hỏng thì không ghi gì.
            await _verify(session, kv_year=kv_year, nhan="trước commit")
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Phiên MỚI: identity map rỗng ⇒ buộc SELECT thật, không đọc lại bộ nhớ.
    async with AsyncSessionLocal() as kiem:
        tom_tat = await _verify(kiem, kv_year=kv_year, nhan="sau commit, phiên mới")

    print("[apply] chèn / đã-có theo bảng:")
    for bang in sorted(ket_qua):
        chen, da_co = ket_qua[bang]
        print(f"  {bang:<34} chèn={chen} đã-có={da_co}")
    print(f"[verify] ĐẠT — {tom_tat}")
    return 0


def dry_run(*, allow_dev: bool, kv_year: int) -> int:
    print("=" * 72)
    print("FIXTURE DANH MỤC E2E — DRY-RUN (KHÔNG chạm CSDL)")
    print(f"  nguồn PA-A          : {PA_A_CSV_REPO_PATH}")
    print(f"  quy tắc chọn        : {PA_A_SELECTION_RULE}")
    print(f"  tỉnh                : {FIXTURE_PROVINCE_CODE} {FIXTURE_PROVINCE_NAME}")
    print(f"  administrative_nodes: 1 PROVINCE + {len(FIXTURE_WARDS)} WARD")
    print(f"  vn_commune_area_map : {len(FIXTURE_WARDS)}")
    print(f"  vn_school           : {len(FIXTURE_SCHOOLS)}")
    print(f"  kv_assignment       : {len(FIXTURE_SCHOOLS)} "
          f"(năm {SCHOOL_KV_FROM_YEAR}→{SCHOOL_KV_TO_YEAR or 'nay'})")
    print(f"  kv_year kiểm        : {kv_year}")
    print(f"  APP_ENV cho phép    : {sorted(allowed_app_envs(allow_dev))}")
    print(f"  CSDL cho phép       : {sorted(allowed_db_names(allow_dev))}")
    for w in FIXTURE_WARDS:
        print(f"    xã  {w['ward_code']} {w['ward_name']:<20} {w['area_code']}")
    for s in FIXTURE_SCHOOLS:
        print(
            f"    trg {_school_moet_code(s['moet_school_code'])} "
            f"{s['name']:<26} {s['kv_code']:<6} @xã {s['commune_code']}"
        )
    print("  (chạy lại --apply KHÔNG nhân bản: get-or-create theo khoá tự nhiên)")
    print("=" * 72)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed fixture danh mục tối thiểu cho E2E (test-only, fail-closed)."
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Thực sự ghi CSDL. Không có cờ này = dry-run.",
    )
    ap.add_argument(
        "--allow-dev",
        action="store_true",
        help="Nới allowlist sang development / qlts_dev (KHÔNG nới sang production).",
    )
    ap.add_argument(
        "--kv-year",
        type=int,
        default=date.today().year,
        help="Năm dùng để kiểm hậu điều kiện tra KV (mặc định: năm hiện tại).",
    )
    args = ap.parse_args(argv)

    if not args.apply:
        return dry_run(allow_dev=args.allow_dev, kv_year=args.kv_year)
    try:
        return asyncio.run(apply(allow_dev=args.allow_dev, kv_year=args.kv_year))
    except GuardError as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
