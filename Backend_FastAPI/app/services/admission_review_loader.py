# app/services/admission_review_loader.py
"""GĐ2-B đợt 2 — BỘ NẠP THEO LÔ của run "Kiểm hồ sơ": đọc mọi dữ kiện của MỘT lần xét trong MỘT ảnh chụp ``REPEATABLE READ READ
ONLY`` rồi dựng ``admission_review_rules.RunFacts`` + ``ProfileFacts`` (đầu vào của luật thuần L2).

Hợp đồng: ``logs-P5/cong-bo-ket-qua/gd2/gd2b/dot2/HOP-DONG-BO-NAP-THEO-LO-2026-11-22.md`` — danh sách câu, tham số là mảng id,
TỔNG số câu cố định (không theo số hồ sơ — BT35, owner K1 21-11: đếm CẢ bước tính lại KV F231). Bất biến:

* KHÔNG chép luật: mọi quyết định đi qua hàm có sẵn — dữ kiện E6 của bản in GĐ1 (``read_print_figures`` /
  ``read_check_source`` / ``_score_add_rules`` / ``from_row``), cổng nguyện vọng của T6 (``choice_gate_facts`` trên đồ thị nạp
  theo ĐÚNG các đường ``t6_profile_load_paths`` — mỗi cạnh một câu tham số mảng, KHÔNG ``selectinload`` (chia khúc 500 khoá — owner
  Q3 22-11)), F231 qua ``area_check_rules.area_check`` (gọi bộ quyết định thuần của ``priority_service``),
  bộ đếm chỉ tiêu (``quota_occupancy_service``), dấu chỉ tiêu (``quota_fingerprint_of``). Chỗ nào buộc có bản thứ hai thì test khoá
  bằng nhau (``tests/integration/test_gd2b_bt35_toan_luot_db.py``).
* KHÔNG đọc từng hồ sơ: không ``session.get`` / không gọi hàm đọc một hồ sơ trong vòng lặp. Vòng lặp chỉ DỰNG dữ kiện từ kết quả
  đã nạp.
* Dữ kiện tự mâu thuẫn (hai câu chọn khoản HK1 lệch nhau, thiếu hàng, trùng dòng giấy…) ⇒ ``ReviewInputError`` (cả run dừng, không
  đoán).

Không ghi gì; không khoá dòng nào; không import FastAPI.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import lazyload

from app import models
from app.repositories import admission_review_load_repository as load_repo
from app.repositories import admission_review_repository as review_repo
from app.repositories.council_candidate_repository import read_check_source, read_print_figures
from app.services import admission_review_errors as errors
from app.services import admission_review_rules as rules
from app.services import area_check_rules
from app.services import council_set_gate_service as set_gate
from app.services import quota_occupancy_service as qos
from app.services.admission_choice_engine_service import t6_profile_load_paths
from app.services.admission_quota_table_service import quota_fingerprint_of
from app.services.admission_review_service import ACTION_RUN_EVALUATE, require_session_action
from app.services.council_candidate_service import _merge_duplicate_rows, _score_add_rules
from app.services.council_decision_status_service import from_row
from app.services.priority_service import (
    RATE_TABLE_OBJECT,
    kv_lookup_keys,
    latest_manual_override_audit_rows,
    pick_open_priority_rates,
    verified_object_codes,
)


@dataclass(frozen=True)
class LoadedRun:
    """Kết quả bộ nạp: dữ kiện cho ``evaluate_run`` + phần ``inputs`` của run đọc trong CÙNG ảnh chụp."""

    session_id: int
    session_version: int
    academic_year: int
    run: rules.RunFacts
    profiles: Tuple[rules.ProfileFacts, ...]
    quota_table: Dict[str, Any]


def _ordered(choices: Sequence[Any]) -> List[Any]:
    """Nguyện vọng theo ``display_order`` rồi ``id`` — thứ tự của luật (``admission_review_rules._ordered_choices``)."""
    return sorted(choices, key=lambda c: (c.display_order, c.id))


def _decimal(value: Any) -> Optional[Decimal]:
    return None if value is None else Decimal(value)


def _merged_figures(figures: Sequence[dict], pids: Sequence[int]) -> Tuple[Dict[int, dict], Set[int]]:
    """Số liệu in theo vị trí (``stt``), gộp hàng trùng do bảng tham chiếu như bản in GĐ1 (``_build_snapshot`` — Codex 42 F334:
    giữ trường giống nhau, trường chữ khác nhau ⇒ rỗng; dòng mang cờ ``tham_chieu_trung``)."""
    by_pos: Dict[int, List[dict]] = {}
    for h in figures:
        by_pos.setdefault(int(h["stt"]), []).append(h)
    if sorted(by_pos) != list(range(1, len(pids) + 1)):
        raise rules.ReviewInputError("Đọc số liệu hồ sơ thiếu hàng.")
    duplicate = {stt for stt, rows in by_pos.items() if len(rows) > 1}
    merged = {stt: (_merge_duplicate_rows(rows) if stt in duplicate else rows[0]) for stt, rows in by_pos.items()}
    if [merged[i]["pid"] for i in range(1, len(pids) + 1)] != list(pids):
        raise rules.ReviewInputError("Số liệu hồ sơ sai thứ tự.")
    return merged, duplicate


def _by_stt(rows: Sequence[dict], pids: Sequence[int]) -> Dict[int, dict]:
    if [int(h["stt"]) for h in rows] != list(range(1, len(pids) + 1)) or [h["pid"] for h in rows] != list(pids):
        raise rules.ReviewInputError("Đọc dữ liệu kiểm hồ sơ sai thứ tự / thiếu hàng.")
    return {int(h["pid"]): h for h in rows}


def _profile_check(k: dict, fig: dict, *, duplicate: bool, area: Tuple[Optional[str], Optional[str]],
                   rule: Tuple[Optional[str], Optional[str]]) -> set_gate.CheckData:
    """Dữ kiện E6 MỨC HỒ SƠ = ĐÚNG ``CheckData`` của bản in GĐ1 (cùng cột, cùng nguồn — ``_build_snapshot``); test khoá bằng nhau
    với ``council_candidate_service.read_profiles_by_id(...).check_data``."""
    state = from_row(k)
    return set_gate.CheckData(
        stt=k["stt"],
        status=k["status"],
        uses_choice_engine=k["uses_choice_engine"],
        so_nv=k["so_nv"],
        nv1_id=k["nv1_id"],
        nv_in_id=fig.get("nv_in_id"),
        so_nv_trung=k["so_nv_trung"],
        nv_trung_id=k["nv_trung_id"],
        hp_co=bool(fig.get("hp_co")),
        hp_nganh_id=fig.get("hp_nganh_id"),
        nv_in_nganh_id=k["nv_in_nganh_id"],
        nv_in_path_id=k["nv_in_path_id"],
        nv_in_sg_id=k["nv_in_sg_id"],
        lg_nganh_id=k["lg_nganh_id"],
        lg_path_id=k["lg_path_id"],
        lg_sg_id=k["lg_sg_id"],
        diem_ca_hai_khac=k["diem_ca_hai_khac"],
        diem_chi_nv=k["diem_chi_nv"],
        diem_chi_hs=k["diem_chi_hs"],
        kv_ly_do=area[0],
        kv_muc=area[1],
        luat_kv=rule[0],
        luat_ut=rule[1],
        nv_in_ai_id=k["nv_in_ai_id"],
        nv_in_offering_id=k["nv_in_offering_id"],
        qd_hieu_luc_id=state.qd_hieu_luc_id,
        qd_chuoi_id=state.qd_chuoi_id,
        cho_quyet_id=state.cho_quyet_id,
        dau_appsheet=state.dau_appsheet,
        thieu_ma_ho_so=isinstance(fig.get("ma_ho_so"), str) and not fig["ma_ho_so"].strip(),
        duplicate_reference=duplicate,
    )


# ── dữ kiện học vụ / sàn / bảng chỉ tiêu — DÙNG CHUNG cho run (:func:`load_run_facts`) và E10 (:func:`load_floor_candidate_facts`) ──
#: Bộ đếm rỗng — học vụ không có trong kết quả đếm (và E10, vốn không đếm).
NO_USAGE: Mapping[str, int] = {"publish_count": 0, "approved_count": 0, "used": 0}


async def read_floors(conn: AsyncConnection, session_id: int) -> Dict[int, Decimal]:
    """Điểm sàn ĐANG lưu của lần xét: {id học vụ: mức}."""
    return {int(r.offering_academic_info_id): Decimal(r.floor_score) for r in await review_repo.list_floors(conn, session_id)}


async def read_group_of(conn: AsyncConnection, academic_year: int) -> Dict[int, int]:
    """{id học vụ: id nhóm} của bảng chỉ tiêu năm; một học vụ thuộc hai nhóm ⇒ ``ReviewInputError`` (dữ kiện tự mâu thuẫn)."""
    group_of: Dict[int, int] = {}
    for gid, ai_id in await load_repo.read_group_members(conn, academic_year):
        if ai_id in group_of and group_of[ai_id] != gid:
            raise rules.ReviewInputError("Học vụ %s thuộc hai nhóm." % ai_id)
        group_of[ai_id] = gid
    return group_of


def academic_info_facts(
    r: Any, *, group_of: Mapping[int, int], counts: Mapping[int, Mapping[str, int]]
) -> rules.AcademicInfoFacts:
    """MỘT hàng của ``load_repo.read_academic_infos`` ⇒ ``AcademicInfoFacts`` (cờ Ngừng của loại hình / ngành: ``False`` từ CSDL ⇒
    Ngừng; nối trái vắng ⇒ không Ngừng). ``counts`` vắng học vụ ⇒ :data:`NO_USAGE`."""
    used = counts.get(int(r.id), NO_USAGE)
    return rules.AcademicInfoFacts(
        offering_academic_info_id=int(r.id),
        academic_year=int(r.academic_year),
        offering_id=r.offering_id,
        annual_quota=r.annual_admission_quota,
        group_id=group_of.get(int(r.id)),
        is_deleted=bool(r.is_deleted),
        offering_inactive=r.offering_active is False,
        major_inactive=r.major_active is False,
        used_publish=used["publish_count"],
        used_approved=used["approved_count"],
        used=used["used"],
        major_code=r.major_code,
        major_name=r.major_name,
        offering_type=r.offering_type,
    )


def quota_table_input(table: Any, ai_rows: Sequence[Any], academic_year: int) -> Dict[str, Any]:
    """``{status, version, quota_fingerprint}`` của bảng chỉ tiêu năm — dấu băm từ CHÍNH các hàng học vụ ĐÚNG năm đã đọc trong ảnh
    chụp (``quota_fingerprint_of`` — một hàm băm với GET bảng chỉ tiêu)."""
    return {
        "status": table.status,
        "version": int(table.version),
        "quota_fingerprint": quota_fingerprint_of(
            (int(r.id), r.annual_admission_quota, bool(r.is_deleted))
            for r in ai_rows
            if int(r.academic_year) == int(academic_year)
        ),
    }


async def load_run_facts(
    conn: AsyncConnection,
    *,
    session_id: int,
    session_version: int,
    fee_gate_mode: str,
) -> LoadedRun:
    """Nạp mọi dữ kiện của run trên ``conn`` (kết nối ĐANG ở giao dịch ``REPEATABLE READ READ ONLY`` — nơi gọi mở). Lần xét
    không có ⇒ 404; không ``draft`` ⇒ 409; ``version`` lệch ⇒ 409 stale; năm chưa có bảng chỉ tiêu ⇒ 409 (lỗi miền
    ``admission_review_errors``)."""
    s = await load_repo.read_session(conn, session_id)
    if s is None:
        raise errors.review_session_not_found()
    require_session_action(s.status, ACTION_RUN_EVALUATE)  # MỘT cổng với ``available_actions`` (hợp đồng §3.1)
    if int(s.version) != int(session_version):
        raise errors.review_session_stale(int(s.version))
    year = int(s.academic_year)

    floors = await read_floors(conn, session_id)
    table = await load_repo.read_quota_table(conn, year)
    if table is None:
        raise errors.review_quota_table_missing(year)
    group_rows = await load_repo.read_groups(conn, year)
    group_of = await read_group_of(conn, year)

    orm = AsyncSession(bind=conn)
    try:
        p_model = models.AdmissionProfile
        profiles = list(
            (
                await orm.execute(
                    select(p_model)
                    .where(
                        p_model.academic_year == year,
                        cast(p_model.status, String).notin_(rules.NO_ROW_STATUSES),
                    )
                    # Không kéo quan hệ MẶC ĐỊNH của hồ sơ (``lead`` joined, giấy / phí / người duyệt selectin — chia khúc 500).
                    .options(lazyload("*"))
                    .order_by(p_model.id)
                )
            ).scalars()
        )
        await load_repo.load_relationship_paths(orm, profiles, t6_profile_load_paths())
        pids = [int(p.id) for p in profiles]
        ordered = {int(p.id): _ordered(list(p.choices)) for p in profiles}
        choice_ai_ids = {
            int(c.admission_path.academic_info_id)
            for cs in ordered.values()
            for c in cs
            if c.admission_path is not None and c.admission_path.academic_info_id is not None
        }

        # Học vụ + bộ đếm (một câu cho mọi học vụ) + bộ đếm nhóm.
        ai_rows = await load_repo.read_academic_infos(conn, year, choice_ai_ids)
        counts = await qos.count_by_academic_infos(orm, academic_info_ids=[int(r.id) for r in ai_rows])
        group_counts = {int(g.id): await qos.count_by_group(orm, group_id=int(g.id)) for g in group_rows}

        # Dữ kiện E6 của bản in GĐ1 (NV in) + từng vòng NV thứ k (điểm hai nguồn của CHÍNH NV ấy).
        figures, duplicate = _merged_figures(await read_print_figures(conn, pids), pids)
        printed = [figures[i].get("nv_in_id") for i in range(1, len(pids) + 1)]
        check_rows = _by_stt(await read_check_source(conn, pids, printed), pids)
        depth = max((len(cs) for cs in ordered.values()), default=0)
        choice_rows: Dict[int, dict] = {}
        for k in range(depth):
            nv_in = [ordered[pid][k].id if k < len(ordered[pid]) else None for pid in pids]
            for pid, h in _by_stt(await read_check_source(conn, pids, nv_in), pids).items():
                if k < len(ordered[pid]):
                    choice_rows[int(ordered[pid][k].id)] = h

        tuition = {int(r.pid): r for r in await load_repo.read_tuition_hk1(conn, pids)}
        application: Dict[int, List[Any]] = {}
        for r in await load_repo.read_application_fees(conn, pids):
            application.setdefault(int(r.pid), []).append(r)
        documents: Dict[int, Dict[str, rules.DocumentRowFacts]] = {}
        for r in await load_repo.read_path_documents(conn, pids):
            per = documents.setdefault(int(r.pid), {})
            if r.code in per:
                raise rules.ReviewInputError("Hồ sơ %s có hai dòng giấy thường cùng loại." % r.pid)
            per[r.code] = rules.DocumentRowFacts(int(r.document_id), r.status, r.row_version, r.verified_format)
        all_choice_ids = [int(c.id) for cs in ordered.values() for c in cs]
        totals = await load_repo.read_choice_subject_totals(conn, all_choice_ids)
        path_ids = sorted(
            {int(c.admission_path_id) for cs in ordered.values() for c in cs if c.admission_path_id is not None}
            | {int(h["nv_in_path_id"]) for h in check_rows.values() if isinstance(h["nv_in_path_id"], int)}
        )
        rule_of = dict(zip(path_ids, await _score_add_rules(conn, path_ids)))
        audits = await latest_manual_override_audit_rows(orm, pids)

        # F231 + ưu tiên dân tộc: mọi khoá tra KV của mọi hồ sơ ⇒ HAI câu.
        commune_keys: Set[Tuple[str, int]] = set()
        school_keys: Set[Tuple[int, int]] = set()
        for p in profiles:
            snap = area_check_rules.parse_kv_snapshot(check_rows[int(p.id)]["kv_snapshot"])
            if isinstance(snap, dict):
                c_keys, s_keys = kv_lookup_keys(
                    p, target_level=snap.get("target_level"), admission_type=snap.get("admission_type")
                )
                commune_keys |= c_keys
                school_keys |= s_keys
            code = p.permanent_commune_code
            if isinstance(code, str) and code:
                commune_keys.add((code, year))
        commune_kv = await load_repo.read_commune_kv(conn, commune_keys)
        school_kv = await load_repo.read_school_kv(conn, school_keys)
        area_rates = await load_repo.read_open_area_rates(conn, year)
        object_rows = await load_repo.read_open_object_rates(conn, year)
        match_key = {int(p.id): rules.citizen_id_match_key(p.citizen_id) for p in profiles}
        prior_by_key: Dict[str, List[rules.PriorYearProfileFacts]] = {}
        for r in await load_repo.read_prior_year_profiles(
            conn,
            academic_year=year,
            match_keys=[k for k in match_key.values() if k],
            whitespace_pattern=rules.CITIZEN_ID_WHITESPACE_PATTERN,
        ):
            prior_by_key.setdefault(r.match_key, []).append(
                rules.PriorYearProfileFacts(int(r.academic_year), r.status, bool(r.has_effective_decision))
            )
        prior = {pid: prior_by_key.get(k, []) if k else [] for pid, k in match_key.items()}
        other_auto = frozenset(await load_repo.read_other_draft_auto_profile_ids(conn, session_id, year))

        # ── dựng dữ kiện (KHÔNG đọc CSDL từ đây) ──
        facts: List[rules.ProfileFacts] = []
        for stt, p in enumerate(profiles, 1):
            pid = int(p.id)
            k = check_rows[pid]
            fig = figures[stt]
            area = area_check_rules.area_check(
                kv_snapshot=k["kv_snapshot"],
                area_resolution_basis=k["area_resolution_basis"],
                profile=p,
                manual_audit_row=audits.get(pid),
                commune_kv=commune_kv,
                school_kv=school_kv,
                open_area_rate_rows=area_rates,
            )
            printed_path = k["nv_in_path_id"]
            rule = rule_of.get(printed_path, (None, None)) if isinstance(printed_path, int) else (None, None)
            check = _profile_check(k, fig, duplicate=stt in duplicate, area=area, rule=rule)
            t = tuition.get(pid)
            if (t is not None) != check.hp_co or (t is not None and t.resolved_major_id != check.hp_nganh_id):
                raise rules.ReviewInputError("Hồ sơ %s: hai câu chọn khoản học phí HK1 lệch nhau." % pid)
            choices: List[rules.ChoiceFacts] = []
            for c in ordered[pid]:
                h = choice_rows[int(c.id)]
                c_rule = rule_of.get(int(c.admission_path_id), (None, None)) if c.admission_path_id is not None else (None, None)
                path = c.admission_path
                choices.append(
                    rules.ChoiceFacts(
                        choice_id=int(c.id),
                        display_order=c.display_order,
                        admission_path_id=c.admission_path_id,
                        offering_academic_info_id=h["nv_in_ai_id"],
                        major_id=h["nv_in_nganh_id"],
                        gate=rules.choice_gate_facts(p, c),
                        check=rules.choice_check(
                            check,
                            choice_id=int(c.id),
                            major_id=h["nv_in_nganh_id"],
                            admission_path_id=h["nv_in_path_id"],
                            subject_group_id=h["nv_in_sg_id"],
                            offering_academic_info_id=h["nv_in_ai_id"],
                            offering_id=h["nv_in_offering_id"],
                            area_rule=c_rule[0],
                            object_rule=c_rule[1],
                            score_both_differ=h["diem_ca_hai_khac"],
                            score_only_choice=h["diem_chi_nv"],
                            score_only_profile=h["diem_chi_hs"],
                        ),
                        subject_total=_decimal(totals.get(int(c.id))),
                        application_fee_free=path is not None and not path.requires_application_fee,
                    )
                )
            commune = p.permanent_commune_code
            facts.append(
                rules.ProfileFacts(
                    profile_id=pid,
                    status=k["status"],
                    check=check,
                    tuition_fee=None if t is None else rules.FeeFacts(int(t.fee_id), t.status, _decimal(t.paid_amount)),
                    application_fees=tuple(
                        rules.FeeFacts(int(a.fee_id), a.status, _decimal(a.paid_amount)) for a in application.get(pid, [])
                    ),
                    applied_rules=p.applied_rules,
                    path_documents=documents.get(pid, {}),
                    ethnicity_name=fig.get("dan_toc"),
                    permanent_commune_code=commune,
                    commune_area_code=commune_kv.get((commune, year)) if isinstance(commune, str) and commune else None,
                    verified_object_codes=tuple(verified_object_codes(p)),
                    choices=tuple(choices),
                    prior_year_profiles=tuple(prior.get(pid, ())),
                )
            )
    finally:
        await orm.close()

    try:
        object_rates = pick_open_priority_rates(
            object_rows, table=RATE_TABLE_OBJECT, academic_year=year, codes=[r[0] for r in object_rows]
        )
    except RuntimeError as exc:
        # Hai hàng mức đối tượng ĐANG MỞ (``effective_to IS NULL``) cùng mã, cùng năm ⇒ cả run dừng (500). Owner / điều phối Q6
        # 22-11 chấp nhận: production có chỉ mục UNIQUE từng phần ``WHERE effective_to IS NULL`` (``models/priority_config.py``) nên
        # ca này chỉ có khi CSDL bị sửa tay.
        raise rules.ReviewInputError("Mức đối tượng đang mở không nhất quán.") from exc

    academic_infos = {int(r.id): academic_info_facts(r, group_of=group_of, counts=counts) for r in ai_rows}
    groups = tuple(
        rules.GroupFacts(
            group_id=int(g.id),
            code=g.code,
            name=g.name,
            ceiling=int(g.ceiling),
            used_publish=group_counts[int(g.id)]["publish_count"],
            used_approved=group_counts[int(g.id)]["approved_count"],
            used=group_counts[int(g.id)]["used"],
        )
        for g in group_rows
    )
    run = rules.RunFacts(
        academic_year=year,
        fee_gate_mode=fee_gate_mode,
        floors=floors,
        academic_infos=academic_infos,
        groups=groups,
        quota_table_status=table.status,
        object_rates=object_rates,
        other_draft_auto_profile_ids=other_auto,
    )
    quota_table = quota_table_input(table, ai_rows, year)
    return LoadedRun(int(session_id), int(s.version), year, run, tuple(facts), quota_table)


@dataclass(frozen=True)
class LoadedFloorCandidates:
    """Kết quả :func:`load_floor_candidate_facts` — mọi trường đọc trong CÙNG một ảnh chụp."""

    session_id: int
    session_version: int
    session_status: str
    academic_year: int
    floors: Dict[int, Decimal]
    academic_infos: Dict[int, rules.AcademicInfoFacts]
    group_codes: Dict[int, str]
    quota_table: Dict[str, Any]


async def load_floor_candidate_facts(conn: AsyncConnection, *, session_id: int) -> LoadedFloorCandidates:
    """E10 (phụ lục HĐ4 E10; đính chính thiết kế giao diện 24-11 §3) — dữ kiện học vụ cho màn nhập điểm sàn, đọc trên ``conn`` (kết
    nối ĐANG ở giao dịch ``REPEATABLE READ READ ONLY`` — nơi gọi mở). Dùng CHÍNH các câu đọc + hàm dựng của :func:`load_run_facts`:
    ``read_session``, :func:`read_floors`, ``read_quota_table``, ``read_groups``, :func:`read_group_of`, ``read_academic_infos``
    (mọi học vụ của năm, KỂ CẢ đã xoá mềm), :func:`academic_info_facts`, :func:`quota_table_input`. Khác run: không đếm chỗ đã dùng,
    không đọc học vụ năm khác do nguyện vọng trỏ tới (``quota_view`` bỏ chúng), không đòi ``draft`` / ``version`` (chỉ đọc).

    Lần xét không có ⇒ 404 ``review_session_not_found``. Lần xét luôn có bảng chỉ tiêu của năm (khoá ngoại RESTRICT) ⇒ thiếu bảng là
    dữ liệu hỏng ⇒ ``RuntimeError`` (500 — cùng cách ``admission_review_service.quota_table_state`` của E3)."""
    s = await load_repo.read_session(conn, session_id)
    if s is None:
        raise errors.review_session_not_found()
    year = int(s.academic_year)
    floors = await read_floors(conn, session_id)
    table = await load_repo.read_quota_table(conn, year)
    if table is None:
        raise RuntimeError("Năm %d của lần xét không có bảng chỉ tiêu (khoá ngoại bị vượt)." % year)
    group_codes = {int(g.id): g.code for g in await load_repo.read_groups(conn, year)}
    group_of = await read_group_of(conn, year)
    ai_rows = await load_repo.read_academic_infos(conn, year, ())
    return LoadedFloorCandidates(
        session_id=int(s.id),
        session_version=int(s.version),
        session_status=s.status,
        academic_year=year,
        floors=floors,
        academic_infos={int(r.id): academic_info_facts(r, group_of=group_of, counts={}) for r in ai_rows},
        group_codes=group_codes,
        quota_table=quota_table_input(table, ai_rows, year),
    )
