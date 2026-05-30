"""feat/document-group-audience-merge — ĐỢT B: backfill split lớp audience

Revision ID: docgrp_audience_bf_20260530
Revises: docgrp_audience_20260529
Create Date: 2026-05-30

ĐỢT B (data migration, owner-gated) — tách bộ hồ sơ NỀN thành các lớp theo
``applicable_audience`` để TS tốt nghiệp THCS / THPT nhận đúng bộ giấy tờ.

Bối cảnh (plan §8): group shared (``admission_method_id`` + ``admission_path_id``
NULL, ``applicable_audience`` NULL = lớp NỀN) hiện gộp HỌC BẠ + BẰNG TN THPT cho
MỌI hồ sơ — kể cả TS chỉ tốt nghiệp THCS (32 path trung cấp chính quy). Đây là
bug gốc owner báo.

Migration làm 2 việc, GENERIC + DATA-DRIVEN (match theo CODE, KHÔNG hard-code
id — prod id 9/10 ≠ seed 1/2; §8.1 dry-run xác nhận drift) cho TỪNG group NỀN:

§8.2 — SPLIT POST_THPT (MOVE):
  Item có doc code ∈ {hoc_ba_thpt, bang_tot_nghiep_thpt, bang_diem_thpt}
  → CHUYỂN sang group anh em ``{code}_POST_THPT`` (applicable_audience=[POST_THPT]).
  Resolve gộp NỀN + lớp khớp audience → TS THPT vẫn nhận đủ; TS THCS KHÔNG bị ép.

§8.0 — WIRE POST_THCS (INSERT, CHỈ offering type ``chinh_quy``):
  Tạo group ``{code}_POST_THCS`` (applicable_audience=[POST_THCS]) +
  thêm item hoc_ba_thcs + bang_tot_nghiep_thcs (doc type ĐÃ TỒN TẠI prod —
  §8.1 round-8; KHÔNG tạo doc type). Phục vụ 32 path trung cấp chính quy
  tuyển từ THCS. CĐ chính quy vô hại (eligibility chặn graduated_thcs khỏi CĐ).

KHÔNG đụng (chủ đích):
- Group method/path-override (audience chỉ có nghĩa ở tier shared). §8.1 prod = 0
  override group → §8.3 "rebuild path" MOOT (không có gì để xóa).
- LIEN_THONG_*/VLVH: seed không có doc nguồn ("bằng TC/CĐ" = vocational_qualification,
  KHÔNG phải document) → known-limitation §5; admin upsert qua panel nếu cần.
- POST_THCS cho offering type ≠ chinh_quy (lien_thong ot22 unused 0 path).
- Snapshot ``applied_rules`` của hồ sơ cũ (bất biến — chỉ re-fire khi PATCH
  cultural/vocational qua update_profile, đã ship ĐỢT A).

Idempotent (N4): rerun bỏ qua CẢ tạo group LẪN move (item đã rời NỀN → query
rỗng; group audience đã tồn tại → reuse theo code). An toàn chạy lại nhiều lần.

Downgrade (H3): HOÀN NGUYÊN split THẬT — move item POST_THPT VỀ NỀN + xóa group
POST_THPT (rỗng) + xóa group POST_THCS (cascade item). KHÔNG drop doc type
(non-destructive). Bắt buộc reverse thật: nếu chỉ drop cột (ĐỢT A) mà để group
tách đứng yên → code resolve cũ post-rollback merge TẤT CẢ shared group/ot →
hồ sơ mới over-require cả THPT lẫn THCS.
"""
from typing import Optional, Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "docgrp_audience_bf_20260530"
down_revision: Union[str, None] = "docgrp_audience_20260529"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Phân loại doc code → lớp audience (quyết định backfill, §8.0/§8.2/H2) ---
# THPT-level (học bạ / bằng TN / bảng điểm THPT). bang_diem_thpt vào POST_THPT
# (H2): KHÔNG để NỀN, tránh ép TC-liên-thông-từ-THCS nộp bảng điểm THPT.
POST_THPT_DOC_CODES = ("hoc_ba_thpt", "bang_tot_nghiep_thpt", "bang_diem_thpt")
# THCS-level — INSERT cho lớp POST_THCS (doc type có sẵn prod §8.1).
POST_THCS_DOC_CODES = ("hoc_ba_thcs", "bang_tot_nghiep_thcs")
# Lớp POST_THCS CHỈ wire cho offering type chính quy (§8.0 owner scope).
CHINH_QUY_OT_CODE = "chinh_quy"

# Nhãn group (mirror document_resolution_service.AUDIENCE_LABELS — migration
# tự chứa, KHÔNG import app code).
_AUDIENCE_LABELS = {
    "POST_THPT": "Tốt nghiệp THPT",
    "POST_THCS": "Tốt nghiệp THCS",
}

# Mặc định item THCS mới — mirror item THPT hiện hữu (is_mandatory=t,
# requires_upload=t, submission_format=certified_copy — verify dev 2026-05-30).
_THCS_ITEM_SUBMISSION_FORMAT = "certified_copy"


def _audience_group_code(nen_code: str, audience: str) -> str:
    """Code group lớp = ``{nen_code}_{audience}`` (deterministic → idempotent +
    downgrade khớp đúng group migration tạo, KHÔNG đụng group admin upsert qua
    panel — panel sinh ``SHARED_DOC_OT_{id}*`` khác scheme)."""
    code = f"{nen_code}_{audience}"
    # §3/P2: code UNIQUE VARCHAR(50). Fail-loud nếu vượt (seed thực ~23 ký tự).
    assert len(code) <= 50, (
        f"audience group code '{code}' ({len(code)} ký tự) > 50 — "
        f"đổi scheme hậu tố cho group NỀN code dài '{nen_code}'"
    )
    return code


def _ensure_audience_group(
    bind, nen_id: int, nen_code: str, nen_name: str, offering_type_id: int,
    audience: str,
) -> int:
    """Tạo (hoặc reuse nếu đã có — idempotent) group shared lớp ``audience``.

    Group anh em cùng offering_type, method+path NULL, applicable_audience=[audience].
    """
    code = _audience_group_code(nen_code, audience)
    existing = bind.execute(
        text("SELECT id FROM document_group WHERE code = :code"),
        {"code": code},
    ).scalar()
    if existing is not None:
        return existing

    label = _AUDIENCE_LABELS[audience]
    new_id = bind.execute(
        text(
            """
            INSERT INTO document_group (
                offering_type_id, admission_method_id, admission_path_id,
                code, name, description, is_active, applicable_audience
            )
            VALUES (
                :ot, NULL, NULL,
                :code, :name, :descr, TRUE,
                ARRAY[:aud]::admission_audience[]
            )
            RETURNING id
            """
        ),
        {
            "ot": offering_type_id,
            "code": code,
            "name": f"{nen_name} — {label}",
            "descr": f"Lớp giấy tờ theo đối tượng: {label} (tách từ {nen_code}).",
            "aud": audience,
        },
    ).scalar()
    return new_id


def upgrade() -> None:
    bind = op.get_bind()

    # Mọi group NỀN tier shared (method+path NULL, audience NULL).
    nen_groups = bind.execute(
        text(
            """
            SELECT dg.id, dg.code, dg.name, dg.offering_type_id, ot.code AS ot_code
            FROM document_group dg
            JOIN config_offering_type ot ON ot.id = dg.offering_type_id
            WHERE dg.admission_method_id IS NULL
              AND dg.admission_path_id IS NULL
              AND dg.applicable_audience IS NULL
            ORDER BY dg.id
            """
        )
    ).fetchall()

    for grp in nen_groups:
        # ---- §8.2 — MOVE item THPT-level sang lớp POST_THPT ----
        thpt_items = bind.execute(
            text(
                """
                SELECT dgi.id
                FROM document_group_item dgi
                JOIN config_document_type dt ON dt.id = dgi.document_type_id
                WHERE dgi.group_id = :gid
                  AND dt.code = ANY(:codes)
                """
            ),
            {"gid": grp.id, "codes": list(POST_THPT_DOC_CODES)},
        ).fetchall()

        if thpt_items:  # KHÔNG tạo group rỗng (§8.2)
            thpt_gid = _ensure_audience_group(
                bind, grp.id, grp.code, grp.name, grp.offering_type_id, "POST_THPT"
            )
            for (item_id,) in thpt_items:
                # MOVE: group anh em mới → KHÔNG đụng uq_document_group_item
                # (group_id, document_type_id) vì target group khác.
                bind.execute(
                    text(
                        "UPDATE document_group_item SET group_id = :ng WHERE id = :iid"
                    ),
                    {"ng": thpt_gid, "iid": item_id},
                )

        # ---- §8.0 — INSERT lớp POST_THCS (chỉ chinh_quy) ----
        if grp.ot_code == CHINH_QUY_OT_CODE:
            # Doc type THCS phải tồn tại (§8.1: có sẵn prod). Trên DB thiếu
            # (test/fresh) → bỏ qua, KHÔNG tạo group rỗng.
            thcs_types = bind.execute(
                text(
                    """
                    SELECT id, code FROM config_document_type
                    WHERE code = ANY(:codes)
                    ORDER BY array_position(:codes, code)
                    """
                ),
                {"codes": list(POST_THCS_DOC_CODES)},
            ).fetchall()

            if thcs_types:
                thcs_gid = _ensure_audience_group(
                    bind, grp.id, grp.code, grp.name, grp.offering_type_id,
                    "POST_THCS",
                )
                for order, (dt_id, _code) in enumerate(thcs_types, start=1):
                    # Idempotent: chỉ INSERT nếu (group, doc_type) chưa có.
                    exists = bind.execute(
                        text(
                            """
                            SELECT 1 FROM document_group_item
                            WHERE group_id = :g AND document_type_id = :d
                            """
                        ),
                        {"g": thcs_gid, "d": dt_id},
                    ).scalar()
                    if exists:
                        continue
                    bind.execute(
                        text(
                            """
                            INSERT INTO document_group_item (
                                group_id, document_type_id, is_mandatory,
                                requires_upload, submission_format, display_order
                            )
                            VALUES (:g, :d, TRUE, TRUE, :fmt, :ord)
                            """
                        ),
                        {
                            "g": thcs_gid,
                            "d": dt_id,
                            "fmt": _THCS_ITEM_SUBMISSION_FORMAT,
                            "ord": order,
                        },
                    )


def downgrade() -> None:
    bind = op.get_bind()

    # Reverse THẬT cho từng group NỀN (H3). Match group lớp theo code
    # deterministic ``{nen_code}_POST_*`` → chỉ đụng group migration tạo.
    nen_groups = bind.execute(
        text(
            """
            SELECT id, code FROM document_group
            WHERE admission_method_id IS NULL
              AND admission_path_id IS NULL
              AND applicable_audience IS NULL
            ORDER BY id
            """
        )
    ).fetchall()

    for grp in nen_groups:
        # POST_THPT: MOVE item VỀ NỀN rồi xóa group (rỗng).
        thpt_code = f"{grp.code}_POST_THPT"
        thpt_gid: Optional[int] = bind.execute(
            text("SELECT id FROM document_group WHERE code = :c"),
            {"c": thpt_code},
        ).scalar()
        if thpt_gid is not None:
            bind.execute(
                text(
                    "UPDATE document_group_item SET group_id = :nen WHERE group_id = :thpt"
                ),
                {"nen": grp.id, "thpt": thpt_gid},
            )
            bind.execute(
                text("DELETE FROM document_group WHERE id = :id"),
                {"id": thpt_gid},
            )

        # POST_THCS: xóa group → item cascade (item THCS được INSERT, KHÔNG
        # có ở NỀN trước đó nên KHÔNG move về).
        thcs_code = f"{grp.code}_POST_THCS"
        thcs_gid: Optional[int] = bind.execute(
            text("SELECT id FROM document_group WHERE code = :c"),
            {"c": thcs_code},
        ).scalar()
        if thcs_gid is not None:
            bind.execute(
                text("DELETE FROM document_group WHERE id = :id"),
                {"id": thcs_gid},
            )
    # KHÔNG drop doc type hoc_ba_thcs/bang_tot_nghiep_thcs (non-destructive).
