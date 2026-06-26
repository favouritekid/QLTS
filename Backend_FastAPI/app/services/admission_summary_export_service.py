"""Xuất báo cáo tuyển sinh (snapshot) ra Excel — orchestration only, no FastAPI.

Báo cáo "ảnh chụp" phân bố TẠI THỜI ĐIỂM xuất, KHÁC cockpit tuần (funnel theo
thời gian). Đếm:
- Phễu LEAD exclusive (mỗi lead 1 ô — cộng = tổng lead): Chưa tư vấn | Đang tư vấn
  | Chỉ đóng lệ phí | Đã đóng học phí | Đã dừng. Ưu tiên theo TIỀN thật (đóng cả
  lệ phí + học phí → CHỈ tính học phí); phần chưa đóng tiền phân theo
  consultation_status.
- HỒ SƠ đếm riêng theo ``admission_profile.status``: Nháp (draft) | Đã nộp (submitted).
- Nguồn tuyển nhập học = breakdown nhóm "đã đóng học phí": Liên hệ/Giới thiệu
  (referral / có referrer) vs Hệ thống phân phối (còn lại).

Scope: admin = toàn trường (hoặc đơn vị chọn); manager = ép đơn vị của mình.
Read-only → service không commit. Raises domain exceptions, never HTTPException.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.admission_report_service import AdmissionReportService
from app.utils.csv_helpers import sanitize_csv_cell

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# ---- Quy ước phân nhóm (xem docstring) --------------------------------------
LEAD_BUCKETS = [
    ("chua", "Chưa tư vấn"),
    ("dang", "Đang tư vấn"),
    ("lephi", "Chỉ đóng lệ phí"),
    ("hocphi", "Đã đóng học phí"),
    ("dung", "Đã dừng"),
]
LB_KEYS = [b[0] for b in LEAD_BUCKETS]
LB_LABEL = dict(LEAD_BUCKETS)
HS_BUCKETS = [("nhap", "Nháp (draft)"), ("danop", "Đã nộp (submitted)")]
HS_KEYS = [b[0] for b in HS_BUCKETS]
HS_LABEL = dict(HS_BUCKETS)
SRC_BUCKETS = [("lienhe", "Liên hệ/Giới thiệu"), ("hethong", "Hệ thống phân phối")]
SRC_KEYS = [b[0] for b in SRC_BUCKETS]
SRC_LABEL = dict(SRC_BUCKETS)

_DUNG_CS = {"sts20", "sts16", "sts08", "sts18", "sts12"}
_CHUA_CS = {"sts00", "sts02", "sts01", "sts15", "sts19"}
_UNASSIGNED = 0  # sentinel cột "Chưa PC" cho lead không có nhân viên phụ trách

# ---- Styling ----------------------------------------------------------------
_THIN = Side(style="thin", color="B0B0B0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="4472C4")
_HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
_GRPA_FILL = PatternFill("solid", fgColor="D9E1F2")
_GRPB_FILL = PatternFill("solid", fgColor="E2EFDA")
_GRPC_FILL = PatternFill("solid", fgColor="FCE4D6")
_SUB_FONT = Font(bold=True, color="1F3864", size=9)
_TOTAL_FILL = PatternFill("solid", fgColor="FFF2CC")
_TOTAL_FONT = Font(bold=True, size=10)
_TITLE_FONT = Font(bold=True, size=14, color="1F3864")
_CTR = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

# Lead is year-scoped via its offering's academic year (lead has no year column);
# leads without an offering are kept (year unknown → '(Chưa xác định ngành)').
# Major attribution: nguyện vọng 1 of the year's profile (display_order=1) if any,
# else the lead's intent offering. "đã đóng" = paid_amount>0 OR waived (miễn).
_YEAR_SCOPE = """
      AND (
          po.id IS NULL
          OR EXISTS (
              SELECT 1 FROM offering_academic_info oai
              WHERE oai.offering_id = po.id AND oai.academic_year = :year
          )
      )"""
_LEAD_SQL = text(
    """
    SELECT l.id,
           COALESCE(max(nv1_po.program_id), max(po.program_id)) AS pid,
           l.consultation_status_id AS cs,
           l.assigned_officer_id AS off, l.source, l.referrer_id,
           max(ap.status) AS pstatus,
           bool_or(f.fee_type='application'
                   AND (f.paid_amount > 0 OR f.status = 'waived')) AS has_app,
           bool_or(f.fee_type='tuition'
                   AND (f.paid_amount > 0 OR f.status = 'waived')) AS has_tui
    FROM lead l
    LEFT JOIN program_offering po ON l.offering_id = po.id
    LEFT JOIN admission_profile ap ON ap.lead_id = l.id AND ap.academic_year = :year
    LEFT JOIN admission_profile_choice nv1
           ON nv1.admission_profile_id = ap.id AND nv1.display_order = 1
    LEFT JOIN admission_path nv1_path ON nv1.admission_path_id = nv1_path.id
    LEFT JOIN offering_academic_info nv1_oai
           ON nv1_path.academic_info_id = nv1_oai.id
    LEFT JOIN program_offering nv1_po ON nv1_oai.offering_id = nv1_po.id
    LEFT JOIN fee f ON f.admission_profile_id = ap.id
    WHERE l.deleted_at IS NULL
      AND (CAST(:unit AS INTEGER) IS NULL OR l.unit_id = CAST(:unit AS INTEGER))"""
    + _YEAR_SCOPE
    + """
    GROUP BY l.id, l.consultation_status_id,
             l.assigned_officer_id, l.source, l.referrer_id
    """
)
_OFFICER_SQL = text(
    """
    SELECT u.id, COALESCE(u.full_name, u.username) AS nm, count(l.id) AS c
    FROM lead l
    JOIN "user" u ON l.assigned_officer_id = u.id
    LEFT JOIN program_offering po ON l.offering_id = po.id
    WHERE l.deleted_at IS NULL
      AND (CAST(:unit AS INTEGER) IS NULL OR l.unit_id = CAST(:unit AS INTEGER))"""
    + _YEAR_SCOPE
    + """
    GROUP BY 1, 2 ORDER BY c DESC, u.id
    """
)
_MAJOR_SQL = text(
    """
    SELECT id, code, name, degree_level FROM major_program WHERE is_active
    ORDER BY name, CASE degree_level WHEN 'Cao đẳng' THEN 0 ELSE 1 END, code
    """
)


def _lead_bucket(has_tui, has_app, cs) -> str:
    if has_tui:
        return "hocphi"
    if has_app:
        return "lephi"
    if cs in _DUNG_CS:
        return "dung"
    if cs is None or cs in _CHUA_CS:
        return "chua"
    return "dang"


def _H(cell, fill=_HEAD_FILL, font=_HEAD_FONT):
    cell.fill = fill
    cell.font = font
    cell.alignment = _CTR
    cell.border = _BORDER


def _officer_short_names(oname: dict, officer_ids: list) -> dict:
    """Short header label (last name token) per officer.

    Whitespace-safe ('   '.split() → [] → '#id', avoids IndexError),
    CSV-injection-safe (sanitize_csv_cell), and disambiguated so two officers
    sharing a last name fall back to the full name instead of colliding.
    """
    base = {}
    for oid in officer_ids:
        parts = (oname.get(oid) or "").split()
        base[oid] = parts[-1] if parts else f"#{oid}"
    counts: dict = {}
    for v in base.values():
        counts[v] = counts.get(v, 0) + 1
    out = {}
    for oid in officer_ids:
        label = base[oid]
        if counts[label] > 1:  # collision → fuller name to keep columns distinct
            label = (oname.get(oid) or "").strip() or f"#{oid}"
        out[oid] = sanitize_csv_cell(label)
    return out


class AdmissionSummaryExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_xlsx(
        self,
        current_user: models.User,
        academic_year: int,
        unit_id: Optional[int] = None,
    ) -> tuple[bytes, str]:
        # Reuse the weekly report's scope rule (admin all/chosen unit, manager
        # forced own unit) so viewing and exporting enforce IDOR identically.
        scope_unit = AdmissionReportService._resolve_scope(current_user, unit_id)
        params = {"year": academic_year, "unit": scope_unit}
        leads = (await self.db.execute(_LEAD_SQL, params)).mappings().all()
        officers = (await self.db.execute(_OFFICER_SQL, params)).mappings().all()
        majors = (await self.db.execute(_MAJOR_SQL)).mappings().all()

        wb = self._build_workbook(academic_year, leads, officers, majors)
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        ts = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
        filename = f"bao_cao_tuyen_sinh_{academic_year}_{ts}.xlsx"
        return bio.getvalue(), filename

    # ----------------------------------------------------------- workbook build
    def _build_workbook(self, year, leads, officers, majors) -> Workbook:
        officer_ids = [r["id"] for r in officers]
        officer_id_set = set(officer_ids)
        oname = {r["id"]: r["nm"] for r in officers}
        oshort = _officer_short_names(oname, officer_ids)
        n_unassigned = sum(1 for r in leads if r["off"] not in officer_id_set)
        # Sheet-2 columns = officers (+ "Chưa PC" if any lead has no officer) so
        # EVERY lead is attributed → sheet 2 reconciles exactly with sheet 1.
        officer_cols = list(officer_ids)
        if n_unassigned:
            officer_cols.append(_UNASSIGNED)
            oshort[_UNASSIGNED] = "Chưa PC"

        major_ids = [m["id"] for m in majors]
        minfo = {m["id"]: m for m in majors}
        NONE = -1
        all_keys = major_ids + [NONE]

        s1 = {p: {k: 0 for k in LB_KEYS} for p in all_keys}
        s1hs = {p: {k: 0 for k in HS_KEYS} for p in all_keys}
        s2 = {p: {k: {o: 0 for o in officer_cols} for k in LB_KEYS} for p in all_keys}
        s2hs = {p: {k: {o: 0 for o in officer_cols} for k in HS_KEYS} for p in all_keys}
        src = {p: {g: {o: 0 for o in officer_cols} for g in SRC_KEYS} for p in all_keys}

        for r in leads:
            pid = r["pid"] if r["pid"] in s1 else NONE
            b = _lead_bucket(r["has_tui"], r["has_app"], r["cs"])
            s1[pid][b] += 1
            off = r["off"]
            # col is always a valid key: an unassigned lead implies _UNASSIGNED ∈ cols
            col = off if off in officer_id_set else _UNASSIGNED
            s2[pid][b][col] += 1
            ps = r["pstatus"]
            # draft → Nháp; bất kỳ trạng thái khác (đã nộp trở lên: submitted/
            # approved/enrolled/…) → Đã nộp (mốc lũy kế); không hồ sơ → bỏ qua.
            hk = "nhap" if ps == "draft" else ("danop" if ps is not None else None)
            if hk:
                s1hs[pid][hk] += 1
                s2hs[pid][hk][col] += 1
            if b == "hocphi":
                g = (
                    "lienhe"
                    if (r["source"] == "referral" or r["referrer_id"] is not None)
                    else "hethong"
                )
                src[pid][g][col] += 1

        ordered = [
            p for p in major_ids if sum(s1[p].values()) + sum(s1hs[p].values()) > 0
        ]
        if sum(s1[NONE].values()) + sum(s1hs[NONE].values()) > 0:
            ordered.append(NONE)

        def desc_of(pid):
            if pid == NONE:
                return "", "(Chưa xác định ngành)", ""
            m = minfo[pid]
            return (
                sanitize_csv_cell(m["code"]),
                sanitize_csv_cell(m["name"]),
                sanitize_csv_cell(m["degree_level"]),
            )

        ts_label = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
        wb = Workbook()
        DESC = ["TT", "Mã ngành", "Ngành, nghề", "Trình độ", "Liên thông/VB2"]
        ND = len(DESC)

        self._sheet_summary(wb, year, ts_label, DESC, ND, ordered, desc_of, s1, s1hs)
        self._sheet_by_officer(
            wb,
            year,
            ts_label,
            DESC,
            ND,
            ordered,
            desc_of,
            officer_cols,
            oshort,
            n_unassigned,
            s2,
            s2hs,
            src,
        )
        self._sheet_notes(wb, year, n_unassigned, len(leads))
        return wb

    # --------------------------------------------------------- sheet 1: chung
    def _sheet_summary(self, wb, year, ts_label, DESC, ND, ordered, desc_of, s1, s1hs):
        ws = wb.active
        ws.title = "Số liệu chung"
        c_tong = ND + 1
        c_lead = c_tong + 1
        c_hs = c_lead + len(LB_KEYS)
        total = ND + 1 + len(LB_KEYS) + len(HS_KEYS)

        ws.cell(1, 1, f"SỐ LIỆU TUYỂN SINH NĂM {year}").font = _TITLE_FONT
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total)
        ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(2, 1, "Thời điểm báo cáo:").font = Font(italic=True, size=9)
        ws.cell(2, 2, ts_label).font = Font(italic=True, size=9)

        for i, h in enumerate(DESC, 1):
            ws.merge_cells(start_row=4, start_column=i, end_row=5, end_column=i)
            _H(ws.cell(4, i, h))
        ws.merge_cells(start_row=4, start_column=c_tong, end_row=5, end_column=c_tong)
        _H(ws.cell(4, c_tong, "Tổng lead"))
        ws.merge_cells(
            start_row=4,
            start_column=c_lead,
            end_row=4,
            end_column=c_lead + len(LB_KEYS) - 1,
        )
        _H(
            ws.cell(
                4,
                c_lead,
                "PHÂN LOẠI LEAD THEO TRẠNG THÁI  (mỗi lead 1 ô — cộng = Tổng lead)",
            )
        )
        ws.merge_cells(
            start_row=4,
            start_column=c_hs,
            end_row=4,
            end_column=c_hs + len(HS_KEYS) - 1,
        )
        _H(ws.cell(4, c_hs, "HỒ SƠ (đếm theo hồ sơ)"))
        for j, k in enumerate(LB_KEYS):
            _H(ws.cell(5, c_lead + j, LB_LABEL[k]), fill=_GRPA_FILL, font=_SUB_FONT)
        for j, k in enumerate(HS_KEYS):
            _H(ws.cell(5, c_hs + j, HS_LABEL[k]), fill=_GRPB_FILL, font=_SUB_FONT)

        # TỔNG (row 6)
        ws.cell(6, 1, "TỔNG CỘNG")
        ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=ND)
        ws.cell(6, 1).font = _TOTAL_FONT
        ws.cell(6, 1).alignment = _CTR
        for i in range(1, ND + 1):
            ws.cell(6, i).fill = _TOTAL_FILL
            ws.cell(6, i).border = _BORDER
        tot = sum(sum(s1[p].values()) for p in ordered)
        vals = (
            [tot]
            + [sum(s1[p][k] for p in ordered) for k in LB_KEYS]
            + [sum(s1hs[p][k] for p in ordered) for k in HS_KEYS]
        )
        for j, v in enumerate(vals):
            c = ws.cell(6, c_tong + j, v)
            c.fill = _TOTAL_FILL
            c.font = _TOTAL_FONT
            c.alignment = _CTR
            c.border = _BORDER

        r = 7
        for n, pid in enumerate(ordered, 1):
            code, name, deg = desc_of(pid)
            ws.cell(r, 1, n).alignment = _CTR
            ws.cell(r, 2, code).alignment = _CTR
            ws.cell(r, 3, name).alignment = _LEFT
            ws.cell(r, 4, deg).alignment = _CTR
            ws.cell(r, 5, "Không").alignment = _CTR
            row_vals = (
                [sum(s1[pid].values())]
                + [s1[pid][k] for k in LB_KEYS]
                + [s1hs[pid][k] for k in HS_KEYS]
            )
            for j, v in enumerate(row_vals):
                c = ws.cell(r, c_tong + j, v)
                c.alignment = _CTR
                if j == 0:
                    c.font = Font(bold=True)
            for i in range(1, total + 1):
                ws.cell(r, i).border = _BORDER
            r += 1

        for col, w in zip("ABCDE", (4.5, 11, 34, 10, 9)):
            ws.column_dimensions[col].width = w
        ws.column_dimensions[get_column_letter(c_tong)].width = 8
        for j in range(len(LB_KEYS)):
            ws.column_dimensions[get_column_letter(c_lead + j)].width = 11
        for j in range(len(HS_KEYS)):
            ws.column_dimensions[get_column_letter(c_hs + j)].width = 12
        # Freeze rows 1-6 (header + TỔNG) and the A-E descriptor cols, like sheet 2.
        ws.freeze_panes = ws.cell(7, c_tong).coordinate

    # ----------------------------------------------------- sheet 2: nhân viên
    def _sheet_by_officer(
        self,
        wb,
        year,
        ts_label,
        DESC,
        ND,
        ordered,
        desc_of,
        officer_cols,
        oshort,
        n_unassigned,
        s2,
        s2hs,
        src,
    ):
        ws = wb.create_sheet("Chia theo nhân viên")
        noff = len(officer_cols)
        block_w = 1 + noff  # cột "Tổng" + mỗi nhân viên (+ "Chưa PC" nếu có)
        aA = ND + 1
        aB = aA + len(LB_KEYS) * block_w
        aC = aB + len(HS_KEYS) * block_w
        total2 = ND + (len(LB_KEYS) + len(HS_KEYS) + len(SRC_KEYS)) * block_w

        ws.cell(1, 1, f"SỐ LIỆU TUYỂN SINH NĂM {year} — CHIA THEO NHÂN VIÊN").font = (
            _TITLE_FONT
        )
        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=max(total2, 1)
        )
        ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(2, 1, "Thời điểm báo cáo:").font = Font(italic=True, size=9)
        ws.cell(2, 2, ts_label).font = Font(italic=True, size=9)
        if n_unassigned:
            ws.cell(
                2,
                6,
                f"{n_unassigned} lead chưa phân công nằm ở cột 'Chưa PC' (mỗi "
                "khối) → cột 'Tổng' khớp sheet 'Số liệu chung'.",
            ).font = Font(italic=True, color="C00000", size=9)

        if not officer_cols:
            return  # không có lead trong phạm vi → sheet chỉ có tiêu đề

        for i, h in enumerate(DESC, 1):
            ws.merge_cells(start_row=3, start_column=i, end_row=5, end_column=i)
            _H(ws.cell(3, i, h))
        ws.merge_cells(start_row=3, start_column=aA, end_row=3, end_column=aB - 1)
        _H(ws.cell(3, aA, "PHÂN LOẠI LEAD THEO TRẠNG THÁI"))
        ws.merge_cells(start_row=3, start_column=aB, end_row=3, end_column=aC - 1)
        _H(ws.cell(3, aB, "HỒ SƠ (đếm theo hồ sơ)"))
        ws.merge_cells(start_row=3, start_column=aC, end_row=3, end_column=total2)
        _H(ws.cell(3, aC, "Nguồn tuyển nhập học (nhóm đã đóng học phí)"))

        # mỗi khối: cột "Tổng" + 1 cột / nhân viên (+ "Chưa PC")
        def grp(col, keys, label, fill):
            for k in keys:
                ws.merge_cells(
                    start_row=4,
                    start_column=col,
                    end_row=4,
                    end_column=col + block_w - 1,
                )
                _H(ws.cell(4, col, label[k]), fill=fill, font=_SUB_FONT)
                _H(ws.cell(5, col, "Tổng"), fill=fill, font=_SUB_FONT)
                for t, oid in enumerate(officer_cols):
                    _H(ws.cell(5, col + 1 + t, oshort[oid]), fill=fill, font=_SUB_FONT)
                col += block_w

        grp(aA, LB_KEYS, LB_LABEL, _GRPA_FILL)
        grp(aB, HS_KEYS, HS_LABEL, _GRPB_FILL)
        grp(aC, SRC_KEYS, SRC_LABEL, _GRPC_FILL)

        # TỔNG CỘNG row 6
        ws.cell(6, 1, "TỔNG CỘNG")
        ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=ND)
        ws.cell(6, 1).font = _TOTAL_FONT
        ws.cell(6, 1).alignment = _CTR
        for i in range(1, ND + 1):
            ws.cell(6, i).fill = _TOTAL_FILL
            ws.cell(6, i).border = _BORDER

        def emit(row, col, store, keys, pid, is_total):
            for k in keys:
                vals = [
                    (
                        sum(store[p][k][oid] for p in ordered)
                        if is_total
                        else store[pid][k][oid]
                    )
                    for oid in officer_cols
                ]
                # cột "Tổng" của khối = cộng các nhân viên (khớp sheet Số liệu chung)
                cells = [(col, sum(vals), True)]
                cells += [(col + 1 + t, v, False) for t, v in enumerate(vals)]
                for cc, v, is_block_total in cells:
                    c = ws.cell(row, cc, v)
                    c.alignment = _CTR
                    c.border = _BORDER
                    if is_total:
                        c.fill = _TOTAL_FILL
                        c.font = _TOTAL_FONT
                    elif is_block_total:
                        c.font = Font(bold=True)
                col += block_w
            return col

        emit(6, aA, s2, LB_KEYS, None, True)
        emit(6, aB, s2hs, HS_KEYS, None, True)
        emit(6, aC, src, SRC_KEYS, None, True)

        r = 7
        for n, pid in enumerate(ordered, 1):
            code, name, deg = desc_of(pid)
            ws.cell(r, 1, n).alignment = _CTR
            ws.cell(r, 2, code).alignment = _CTR
            ws.cell(r, 3, name).alignment = _LEFT
            ws.cell(r, 4, deg).alignment = _CTR
            ws.cell(r, 5, "Không").alignment = _CTR
            emit(r, aA, s2, LB_KEYS, pid, False)
            emit(r, aB, s2hs, HS_KEYS, pid, False)
            emit(r, aC, src, SRC_KEYS, pid, False)
            for i in range(1, ND + 1):
                ws.cell(r, i).border = _BORDER
            r += 1

        for col, w in zip("ABCDE", (4.5, 11, 28, 9, 8)):
            ws.column_dimensions[col].width = w
        for cc in range(aA, total2 + 1):
            ws.column_dimensions[get_column_letter(cc)].width = 6.5
        ws.freeze_panes = ws.cell(7, aA).coordinate

    # ----------------------------------------------------- sheet 3: quy ước
    def _sheet_notes(self, wb, year, n_unassigned, n_leads):
        ws = wb.create_sheet("Quy ước & ghi chú")
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 78
        ws.cell(1, 1, "QUY ƯỚC ĐẾM & GHI CHÚ").font = _TITLE_FONT
        ws.merge_cells("A1:B1")
        rows = [
            (
                "Tổng lead",
                "Tổng số lead theo ngành = nguyện vọng 1 của hồ sơ; nếu chưa "
                "có hồ sơ thì theo ngành quan tâm (offering). Đếm theo LEAD.",
            ),
            (
                "Chưa tư vấn",
                "Lead chưa tiếp cận: sts00, sts02, các trạng thái phổ quát "
                "sts01/sts15/sts19, hoặc chưa có trạng thái. Đếm theo LEAD.",
            ),
            (
                "Đang tư vấn",
                "Lead còn trong quy trình, chưa đóng phí và chưa dừng "
                "(sts03–sts06 và các trạng thái khác). Đếm theo LEAD.",
            ),
            (
                "Chỉ đóng lệ phí",
                "Đã đóng/được miễn lệ phí xét tuyển NHƯNG chưa đóng học phí. "
                "Đếm theo TIỀN thật (paid_amount>0 hoặc miễn).",
            ),
            (
                "Đã đóng học phí",
                "Đã đóng/được miễn học phí (đã gồm lệ phí). Đóng cả 2 → CHỈ "
                "tính ở đây. Đếm theo TIỀN thật (paid_amount>0 hoặc miễn).",
            ),
            (
                "Đã dừng",
                "Lead ngừng/loại: sts20 (ngừng tư vấn), sts16/sts08 (hồ sơ "
                "rớt/rút), sts18 (hoàn HP), sts12 (nghỉ học). Đếm theo LEAD.",
            ),
            (
                "Nháp (draft)",
                "Số HỒ SƠ đang nháp, chưa nộp (admission_profile = draft). "
                "Đếm theo HỒ SƠ.",
            ),
            (
                "Đã nộp (submitted)",
                "Số HỒ SƠ đã nộp chính thức (submitted trở lên — gồm đã "
                "duyệt/nhập học, KHÔNG gồm nháp). Đếm theo HỒ SƠ.",
            ),
            (
                "Liên hệ/Giới thiệu",
                "Trong nhóm đã đóng học phí: lead có source='referral' hoặc "
                "có người giới thiệu.",
            ),
            (
                "Hệ thống phân phối",
                "Trong nhóm đã đóng học phí: các lead còn lại "
                "(website/social/phone/walk-in/event/other).",
            ),
        ]
        _H(ws.cell(3, 1, "Cột"))
        _H(ws.cell(3, 2, "Cách đếm"))
        r = 4
        for a, b in rows:
            ws.cell(r, 1, a).font = Font(bold=True)
            ws.cell(r, 1).alignment = _LEFT
            ws.cell(r, 2, b).alignment = _LEFT
            for i in (1, 2):
                ws.cell(r, i).border = _BORDER
            r += 1
        r += 1
        notes = [
            "GHI CHÚ:",
            "• 5 cột phân loại lead (Chưa TV + Đang TV + Chỉ lệ phí + Học "
            "phí + Đã dừng) LOẠI TRỪ nhau → cộng đúng = Tổng lead. Mỗi lead "
            "chỉ nằm 1 ô (theo nấc cao nhất).",
            "• Cột Nháp & Đã nộp đếm theo HỒ SƠ (chiều khác) — đặt riêng, "
            "KHÔNG cộng vào Tổng lead. Nháp và Đã nộp rời nhau (mỗi hồ sơ 1 "
            "trạng thái, mỗi lead tối đa 1 hồ sơ).",
            "• 'Đã đóng học phí' nằm trong 'đã đóng lệ phí' về bản chất, "
            "nhưng theo quy ước: đóng cả 2 CHỈ tính học phí → 2 cột rời "
            "nhau, cộng = tổng đã đóng tiền.",
            "• Nguồn tuyển nhập học chỉ tính cho nhóm 'đã đóng học phí'.",
            "• Sheet 'Chia theo nhân viên': mỗi khối có cột 'Tổng' (= cộng các "
            "nhân viên, KHỚP sheet 'Số liệu chung') và cột 'Chưa PC' (lead chưa "
            "phân công nhân viên) nên sheet 2 đối chiếu khớp sheet 1.",
        ]
        if n_unassigned:
            notes.append(
                f"• Có {n_unassigned} lead chưa phân công nhân viên (cột " "'Chưa PC')."
            )
        for t in notes:
            ws.cell(r, 1, t).alignment = _LEFT
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
            if t.endswith(":"):
                ws.cell(r, 1).font = Font(bold=True, size=11)
            r += 1
