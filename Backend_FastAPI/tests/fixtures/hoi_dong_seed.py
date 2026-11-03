# tests/fixtures/hoi_dong_seed.py
"""Dữ liệu GIẢ cho test hàm đọc hồ sơ + bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển").

Chèn bằng SQL thô (không qua ORM: không sự kiện / giá trị mặc định phía Python nào chen vào)
lên CSDL test đã dựng bằng ``create_all``. Mọi tên, mã, số ở đây là GIẢ (tiền tố ``GIA``).

``seed_hoi_dong(conn)`` dựng danh mục + các hồ sơ phủ những nhánh khó của truy vấn bộ xuất:
tên một chữ / khoảng trắng thừa, nhiều nguyện vọng (``display_order`` ngược thứ tự ``id``),
thiếu / huỷ / học kỳ 2 học phí, có / không giấy + hình thức giấy + bằng tạm thời, giấy minh
chứng ưu tiên trùng loại, Kinh / DTTS / mã dân tộc lạ / rỗng, xã KV1 / không KV1, hàng
``vn_commune_area_map`` đã hết hiệu lực (kèm / không kèm hàng hiện hành), xã có tên rỗng,
``administrative_nodes`` không còn hiệu lực / không hoạt động (xã lẫn tỉnh), thiếu ngày sinh,
đủ 5 nhãn văn hoá + rỗng, 4 giá trị chuyên môn, hai loại hình khác nhau cùng chuyên môn,
nguyện vọng đầu không có điểm, không có nguyện vọng, khu vực ưu tiên có hai mức theo ngày.
Trạng thái hồ sơ cố ý trộn (nộp, nháp, đã duyệt, chờ hoàn để rút, nộp lại — hàm đọc KHÔNG lọc
trạng thái). Trả ``{nhãn ca: (cccd, id hồ sơ)}``.
"""
import json
from datetime import date, datetime, timezone

from sqlalchemy import text

LUC = datetime(2026, 10, 1, tzinfo=timezone.utc)

LOAI_GIAY = (
    "phieu_dang_ky_xet_tuyen",
    "so_yeu_ly_lich",
    "hoc_ba_thpt",
    "bang_tot_nghiep_thpt",
    "hoc_ba_thcs",
    "bang_tot_nghiep_thcs",
    "giay_cn_hoan_thanh_gdpt",
    "giay_khai_sinh",
    "cccd",
    "anh_3x4",
    "giay_khac_gia",
)


async def chen(conn, bang: str, **cot) -> int:
    """INSERT một hàng, trả id. dict / list ⇒ jsonb."""
    ten, gia = [], {}
    for k, v in cot.items():
        if isinstance(v, (dict, list)):
            ten.append((k, "CAST(:%s AS jsonb)" % k))
            gia[k] = json.dumps(v, ensure_ascii=False)
        else:
            ten.append((k, ":%s" % k))
            gia[k] = v
    sql = 'INSERT INTO "%s" (%s) VALUES (%s) RETURNING id' % (
        bang,
        ", ".join('"%s"' % k for k, _ in ten),
        ", ".join(v for _, v in ten),
    )
    return (await conn.execute(text(sql), gia)).scalar_one()


async def danh_muc(conn) -> dict:
    """Danh mục dùng chung; trả các id cần cho hồ sơ."""
    d = {}
    d["u1"] = await chen(
        conn, "organization_unit", name="Đơn vị giả 1", type="department"
    )
    d["u2"] = await chen(
        conn, "organization_unit", name="Đơn vị giả 2", type="department"
    )
    d["nguoi"] = await chen(
        conn,
        "user",
        username="gia_admin_hd",
        email="gia_admin_hd@example.invalid",
        password_hash="x",
        role="admin",
        total_lead_score=0,
    )
    d["ot_cq"] = await chen(
        conn,
        "config_offering_type",
        code="chinh_quy",
        name="Chính quy giả",
        display_order=1,
        is_active=True,
    )
    d["ot_lt"] = await chen(
        conn,
        "config_offering_type",
        code="lien_thong",
        name="Liên thông giả",
        display_order=2,
        is_active=True,
    )
    nganh = {
        "oto_cd": ("Công nghệ ô tô", "Cao đẳng", "GIA-CD-OTO"),
        "oto_tc": ("Công nghệ ô tô", "Trung cấp", "GIA-TC-OTO"),
        "duoc_cd": ("Dược", "Cao đẳng", "GIA-CD-DUOC"),
        "kt_tc": ("Kế toán", "Trung cấp", "GIA-TC-KT"),
    }
    d["mp"] = {}
    for k, (ten, td, ma) in nganh.items():
        d["mp"][k] = await chen(
            conn,
            "major_program",
            name=ten,
            degree_level=td,
            code=ma,
            is_active=True,
            unit_id=d["u1"],
        )
    d["vong"] = await chen(
        conn,
        "offering_admission_round",
        academic_year=2026,
        round_code="GIA-V1",
        round_name="Vòng giả 1",
    )
    d["pt"] = await chen(
        conn,
        "admission_method",
        code="gia_hoc_ba",
        name="Xét học bạ (giả)",
        requires_gpa=False,
        requires_subject_scores=True,
        display_order=1,
        is_active=True,
    )
    # Môn: thứ tự hiển thị ≠ thứ tự id ≠ vị trí trong tổ hợp.
    d["mon"] = {}
    for k, ten, thu_tu in (
        ("ly", "Vật lý giả", 4),
        ("toan", "Toán giả", 1),
        ("hoa", "Hóa học giả", 3),
        ("van", "Ngữ văn giả", 2),
    ):
        d["mon"][k] = await chen(
            conn,
            "subject",
            code="GIA-" + k,
            name_vi=ten,
            display_order=thu_tu,
            is_active=True,
        )
    d["to_hop"] = {}
    # G1: Hóa(vị trí 1) · Toán(2) · Lý(3) — khác display_order (Toán 1, Hóa 3, Lý 4) và id.
    # G2: Văn(1) · Toán(2) · Lý(3).
    for k, ma, mon in (
        ("g1", "GIA-A", (("hoa", 1), ("toan", 2), ("ly", 3))),
        ("g2", "GIA-C", (("van", 1), ("toan", 2), ("ly", 3))),
    ):
        d["to_hop"][k] = await chen(
            conn,
            "subject_group",
            code=ma,
            name="Tổ hợp giả " + k,
            display_order=1,
            is_active=True,
        )
        for m, vt in mon:
            await chen(
                conn,
                "subject_group_subject",
                subject_group_id=d["to_hop"][k],
                subject_id=d["mon"][m],
                position=vt,
            )
    # Ngành × loại hình → offering → academic info → path → cấu hình tổ hợp (G1 + G2).
    d["psg"] = {}
    for k, mp_id in d["mp"].items():
        for lh, ot in (("cq", d["ot_cq"]), ("lt", d["ot_lt"])):
            po = await chen(
                conn,
                "program_offering",
                offering_type="gia_" + lh,
                is_active=True,
                program_id=mp_id,
                offering_type_id=ot,
            )
            oai = await chen(
                conn,
                "offering_academic_info",
                academic_year=2026,
                is_published=True,
                offering_id=po,
            )
            ap = await chen(
                conn,
                "admission_path",
                academic_info_id=oai,
                admission_method_id=d["pt"],
                status="active",
                display_order=1,
                visibility="public",
                admission_round_id=d["vong"],
                created_at=LUC,
                updated_at=LUC,
            )
            for g, sg in d["to_hop"].items():
                d["psg"][(k, lh, g)] = (
                    ap,
                    await chen(
                        conn,
                        "path_subject_group_config",
                        admission_path_id=ap,
                        subject_group_id=sg,
                    ),
                )
    d["giay"] = {}
    for i, ma in enumerate(LOAI_GIAY, 1):
        d["giay"][ma] = await chen(
            conn,
            "config_document_type",
            code=ma,
            name="Giấy giả " + ma,
            display_order=i,
            is_active=True,
        )
    for ma, ten in (("01", "Kinh"), ("02", "Dân tộc giả A"), ("03", "Dân tộc giả B")):
        await chen(conn, "config_system_category", type="ethnicity", code=ma, name=ten)
    await chen(
        conn, "config_system_category", type="religion", code="02", name="Tôn giáo giả"
    )
    # Khu vực theo xã: GX1 KV1 · GX2 KV2 · GX3 hết hiệu lực KV1 + HIỆN HÀNH KV2-NT (tên xã
    # khác) · GX4 CHỈ còn hàng hết hiệu lực (KV1) · GX5 hiện hành, tên xã RỖNG.
    for ma, kv, xa, den in (
        ("GX1", "KV1", "Xã Giả Một", None),
        ("GX2", "KV2", "Xã Giả Hai", None),
        ("GX3", "KV1", "Xã Giả Ba Cũ", date(2025, 6, 30)),
        ("GX3", "KV2-NT", "Xã Giả Ba Mới", None),
        ("GX4", "KV1", "Xã Giả Bốn Cũ", date(2025, 6, 30)),
        ("GX5", "KV2", "", None),
    ):
        await chen(
            conn,
            "vn_commune_area_map",
            commune_code=ma,
            province="Tỉnh giả",
            district="Huyện giả",
            ward=xa,
            area_code=kv,
            effective_from=date(2020, 1, 1),
            effective_to=den,
        )
    # Danh mục hành chính: tỉnh GT1 hiện hành · GT2 KHÔNG hoạt động · GT3 hết hiệu lực;
    # xã GX1→GT1 · GX2→GT2 · GX6 hết hiệu lực (→GT1) · GX7→GT3 · GX3, GX4→GT1.
    for ma, ten, hd, den in (
        ("GT1", "Tỉnh Giả Một", True, None),
        ("GT2", "Tỉnh Giả Hai", False, None),
        ("GT3", "Tỉnh Giả Ba", True, date(2025, 6, 30)),
    ):
        await chen(
            conn,
            "administrative_nodes",
            code=ma,
            name=ten,
            level="PROVINCE",
            path=ma,
            province_code=ma,
            valid_from=date(2020, 1, 1),
            valid_to=den,
            is_active=hd,
        )
    for ma, tinh, den in (
        ("GX1", "GT1", None),
        ("GX2", "GT2", None),
        ("GX3", "GT1", None),
        ("GX4", "GT1", None),
        ("GX6", "GT1", date(2025, 6, 30)),
        ("GX7", "GT3", None),
    ):
        await chen(
            conn,
            "administrative_nodes",
            code=ma,
            name="Phường giả " + ma,
            level="WARD",
            path=tinh + "/" + ma,
            province_code=tinh,
            ward_code=ma,
            valid_from=date(2020, 1, 1),
            valid_to=den,
            is_active=True,
        )
    # Mức điểm khu vực: KV1 có HAI mức — mới nhất theo effective_from thắng.
    for kv, diem, tu in (
        ("KV1", "0.50", date(2024, 1, 1)),
        ("KV1", "0.75", date(2026, 1, 1)),
        ("KV2", "0.25", date(2026, 1, 1)),
        ("KV2-NT", "0.50", date(2026, 1, 1)),
        ("KV3", "0.00", date(2026, 1, 1)),
    ):
        await chen(
            conn,
            "priority_area_config",
            academic_year=2026,
            area_code=kv,
            area_name="Khu vực giả " + kv,
            bonus_points=diem,
            effective_from=tu,
        )
    return d


async def ho_so(
    conn,
    d,
    *,
    cccd,
    unit="u1",
    nam=2026,
    nv=(),
    hoc_phi=(),
    giay=(),
    diem=None,
    status="submitted",
    **cot
) -> int:
    """Một hồ sơ + lead + nguyện vọng + học phí + giấy + điểm.

    ``nv``: [(display_order, khoá ngành, loại hình, tổ hợp)] theo thứ tự CHÈN (id tăng dần).
    ``diem``: {chỉ số nv: {môn: điểm}}. ``hoc_phi``: [dict cột của fee]. ``giay``: [dict].
    ``status`` luôn ghi tường minh (giá trị mặc định phía CSDL của CSDL test không dùng được).
    """
    cot["status"] = status
    lead = await chen(
        conn,
        "lead",
        full_name="Lead giả",
        phone="0000000000",
        source="gia",
        status="new",
        assignment_status="pending",
        lead_score=0,
        location_proximity=0,
        occupation_relevance=0,
        academic_performance=0,
        created_at=LUC,
        updated_at=LUC,
        version=1,
        consultation_count=0,
        cached_urgency_score=0,
        is_hot_lead=False,
        is_overdue=False,
        unit_id=d[unit],
    )
    pid = await chen(
        conn,
        "admission_profile",
        lead_id=lead,
        academic_year=nam,
        citizen_id=cccd,
        applied_rules={},
        created_at=LUC,
        updated_at=LUC,
        **cot
    )
    choice_ids = []
    for do, ng, lh, g in nv:
        ap, psg = d["psg"][(ng, lh, g)]
        choice_ids.append(
            await chen(
                conn,
                "admission_profile_choice",
                admission_profile_id=pid,
                admission_path_id=ap,
                path_subject_group_config_id=psg,
                display_order=do,
            )
        )
    for i, bang_diem in (diem or {}).items():
        for m, sc in bang_diem.items():
            await chen(
                conn,
                "profile_choice_score",
                admission_profile_choice_id=choice_ids[i],
                subject_id=d["mon"][m],
                score=sc,
                max_score_snapshot="10",
            )
    for f in hoc_phi:
        f = dict(f)
        k = f.pop("resolved_major", None)
        f["resolved_major_id"] = d["mp"][k] if k else None
        await chen(
            conn,
            "fee",
            admission_profile_id=pid,
            academic_year=nam,
            base_amount="1000",
            final_amount="1000",
            calculated_at=LUC,
            created_at=LUC,
            updated_at=LUC,
            **f
        )
    for g in giay:
        g = dict(g)
        g["document_type_id"] = d["giay"][g.pop("loai")]
        await chen(
            conn,
            "profile_document",
            profile_id=pid,
            created_at=LUC,
            updated_at=LUC,
            **g
        )
    return pid


DU_GIAY = [
    dict(
        loai="phieu_dang_ky_xet_tuyen",
        status="verified",
        actual_submission_format="original",
    ),
    dict(
        loai="so_yeu_ly_lich",
        status="paper_submitted",
        actual_submission_format="photo",
    ),
    dict(
        loai="hoc_ba_thpt", status="verified", actual_submission_format="certified_copy"
    ),
    dict(
        loai="bang_tot_nghiep_thpt",
        status="paper_submitted",
        actual_submission_format="photo",
        graduation_proof_kind="official_diploma",
    ),
    dict(
        loai="giay_khai_sinh",
        status="rejected",
        actual_submission_format="certified_copy",
    ),
    dict(loai="cccd", status="uploaded"),
    dict(loai="anh_3x4", status="paper_submitted", actual_submission_format="original"),
    dict(loai="hoc_ba_thcs", status="verified"),
    dict(loai="giay_khac_gia", status="verified", actual_submission_format="original"),
]
HP_CD = dict(
    fee_type="tuition",
    semester_no=1,
    status="pending",
    resolved_major="oto_cd",
    resolved_degree_level="Cao đẳng",
)


async def seed_hoi_dong(conn) -> dict:
    d = await danh_muc(conn)
    hs = {}

    async def them(nhan, cccd, **kw):
        hs[nhan] = (cccd, await ho_so(conn, d, cccd=cccd, **kw))

    # Hai NV: NV có display_order 1 được chèn SAU (id lớn hơn) ⇒ NV1 theo display_order ≠ theo id.
    await them(
        "nhieu_nv_khoang_trang",
        "GIA000000001",
        full_name="  Họ   Giả  Một ",
        dob=date(2008, 1, 2),
        gender="Nam",
        place_of_birth="Nơi sinh giả",
        ethnicity="01",
        permanent_residential_group="Thôn giả 1",
        permanent_ward="Phường trên hồ sơ",
        permanent_province="Tỉnh trên hồ sơ",
        permanent_commune_code="GX1",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot={"kv_resolved": "KV1"},
        nv=[(2, "duoc_cd", "cq", "g2"), (1, "oto_cd", "cq", "g1")],
        diem={
            0: {"van": "9.00", "toan": "9.00", "ly": "9.00"},
            1: {"toan": "7.25", "ly": "6.50", "hoa": "8.00"},
        },
        hoc_phi=[
            HP_CD,
            dict(HP_CD, status="cancelled", resolved_major="duoc_cd"),
            dict(
                HP_CD,
                semester_no=2,
                resolved_major="kt_tc",
                resolved_degree_level="Trung cấp",
            ),
        ],
        giay=DU_GIAY,
    )
    # Tên MỘT chữ có dấu nháy; DTTS, xã KV2 (tỉnh của xã KHÔNG hoạt động); không học phí;
    # thiếu ngày sinh; Hoàn thành THPT; Trung cấp; liên thông.
    await them(
        "ten_mot_chu_khong_hoc_phi",
        "GIA000000002",
        full_name="H'Giả",
        gender="Nữ",
        ethnicity="02",
        permanent_residential_group="Buôn giả",
        permanent_ward="Xã trên hồ sơ 2",
        permanent_province="Tỉnh trên hồ sơ 2",
        permanent_commune_code="GX2",
        cultural_education_level="completed_thpt",
        vocational_qualification="trung_cap",
        priority_resolution_snapshot={"kv_resolved": "KV2"},
        nv=[(1, "oto_tc", "lt", "g1")],
        diem={0: {"toan": "5.00", "ly": "5.50", "hoa": "6.00"}},
    )
    # DTTS ở xã KV1; học phí có trình độ nhưng KHÔNG có ngành; bằng tạm thời; giấy minh chứng
    # ưu tiên cùng loại giấy với một giấy đường thường (max() gộp cả hai); GDTX + Cao đẳng.
    await them(
        "dtts_kv1_hoc_phi_khong_nganh",
        "GIA000000003",
        status="withdrawal_pending",
        full_name="Họ Giả Ba",
        dob=date(2007, 12, 31),
        gender="Nữ",
        ethnicity="02",
        permanent_commune_code="GX1",
        permanent_ward="Xã trên hồ sơ 3",
        cultural_education_level="graduated_gdtx",
        vocational_qualification="cao_dang",
        priority_resolution_snapshot={"kv_resolved": "KV1"},
        nv=[(1, "duoc_cd", "cq", "g2")],
        diem={0: {"van": "8.00", "toan": "7.00", "ly": "6.00"}},
        hoc_phi=[dict(HP_CD, resolved_major=None, resolved_degree_level="Cao đẳng")],
        giay=[
            dict(
                loai="bang_tot_nghiep_thpt",
                status="paper_submitted",
                actual_submission_format="certified_copy",
                graduation_proof_kind="provisional_cert",
                supplement_due_date=date(2026, 12, 31),
            ),
            dict(
                loai="cccd", status="paper_submitted", actual_submission_format="photo"
            ),
            dict(
                loai="cccd",
                category="priority_evidence",
                priority_sub_code="01",
                status="verified",
                actual_submission_format="original",
            ),
        ],
    )
    # Xã có hàng khu vực HẾT HIỆU LỰC + hàng HIỆN HÀNH (tên xã khác).
    await them(
        "xa_het_hieu_luc_co_hien_hanh",
        "GIA000000004",
        full_name="Họ Giả Bốn",
        dob=date(2008, 5, 6),
        gender="Nam",
        ethnicity="01",
        permanent_commune_code="GX3",
        permanent_ward="Xã trên hồ sơ 4",
        permanent_province="Tỉnh trên hồ sơ 4",
        cultural_education_level="graduated_thcs",
        vocational_qualification="so_cap",
        priority_resolution_snapshot={"kv_resolved": "KV2-NT"},
        nv=[(1, "oto_tc", "cq", "g1")],
        diem={0: {"toan": "6.00", "ly": "6.00", "hoa": "6.00"}},
        hoc_phi=[
            dict(HP_CD, resolved_major="oto_tc", resolved_degree_level="Trung cấp")
        ],
    )
    # Xã CHỈ còn hàng khu vực hết hiệu lực (KV1) ⇒ coi như không có KV; DTTS ⇒ 06.
    await them(
        "xa_chi_con_het_hieu_luc",
        "GIA000000005",
        status="resubmitted",
        full_name="Họ Giả Năm",
        dob=date(2008, 7, 8),
        gender="Nữ",
        ethnicity="03",
        permanent_residential_group="Thôn giả 5",
        permanent_commune_code="GX4",
        permanent_ward="Xã trên hồ sơ 5",
        permanent_province="Tỉnh trên hồ sơ 5",
        cultural_education_level="completed_thcs",
        vocational_qualification="none",
        priority_resolution_snapshot={"kv_resolved": "KV1"},
        nv=[(1, "kt_tc", "cq", "g2")],
        diem={0: {"van": "5.25", "toan": "5.75", "ly": "4.00"}},
        hoc_phi=[
            dict(HP_CD, resolved_major="kt_tc", resolved_degree_level="Trung cấp")
        ],
    )
    # Xã hiện hành có tên RỖNG ⇒ không rơi về tên trên hồ sơ; mọi phần địa chỉ còn lại rỗng.
    await them(
        "dia_chi_rong",
        "GIA000000006",
        status="approved",
        full_name="Họ Giả Sáu",
        dob=date(2008, 9, 10),
        gender="Nam",
        ethnicity="01",
        permanent_commune_code="GX5",
        permanent_ward="Xã trên hồ sơ 6",
        permanent_residential_group="",
        permanent_province="",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot={},
        nv=[(1, "oto_cd", "cq", "g1")],
        diem={0: {"toan": "8.00", "ly": "8.00", "hoa": "8.00"}},
        hoc_phi=[HP_CD],
    )
    # Xã có nút hành chính HẾT HIỆU LỰC ⇒ tỉnh rơi về chữ trên hồ sơ; mã dân tộc lạ.
    await them(
        "nut_xa_het_hieu_luc_dan_toc_la",
        "GIA000000007",
        full_name="Họ Giả Bảy",
        dob=date(2008, 11, 12),
        gender="Nam",
        ethnicity="99",
        permanent_commune_code="GX6",
        permanent_ward="Xã trên hồ sơ 7",
        permanent_province="Tỉnh trên hồ sơ 7",
        cultural_education_level="graduated_thpt",
        vocational_qualification="trung_cap",
        priority_resolution_snapshot={"kv_resolved": "KV3"},
        nv=[(1, "oto_tc", "cq", "g1")],
        diem={0: {"toan": "7.00", "ly": "7.00", "hoa": "7.00"}},
        hoc_phi=[
            dict(HP_CD, resolved_major="oto_tc", resolved_degree_level="Trung cấp")
        ],
    )
    # Tỉnh của xã HẾT HIỆU LỰC; dân tộc rỗng; văn hoá rỗng; NV1 KHÔNG có điểm (NV2 có).
    await them(
        "nut_tinh_het_hieu_luc_nv1_khong_diem",
        "GIA000000008",
        full_name="Họ Giả Tám",
        dob=date(2009, 1, 1),
        gender="Nữ",
        permanent_commune_code="GX7",
        permanent_ward="Xã trên hồ sơ 8",
        permanent_province="Tỉnh trên hồ sơ 8",
        vocational_qualification="none",
        nv=[(1, "duoc_cd", "cq", "g2"), (2, "oto_cd", "cq", "g1")],
        diem={1: {"toan": "9.00", "ly": "9.00", "hoa": "9.00"}},
        hoc_phi=[dict(HP_CD, resolved_major="duoc_cd")],
    )
    # Không có nguyện vọng nào; học phí có ngành ⇒ ngành theo học phí.
    await them(
        "khong_nguyen_vong",
        "GIA000000009",
        status="draft",
        full_name="Họ Giả Chín",
        dob=date(2008, 2, 3),
        gender="Nam",
        ethnicity="01",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        hoc_phi=[
            dict(HP_CD, resolved_major="kt_tc", resolved_degree_level="Trung cấp")
        ],
    )
    # Hai loại hình KHÁC nhau, CÙNG chuyên môn (trung cấp), cùng ngành ⇒ cùng số đếm Biên bản.
    for nhan, cccd, lh in (
        ("loai_hinh_chinh_quy", "GIA000000010", "cq"),
        ("loai_hinh_lien_thong", "GIA000000011", "lt"),
    ):
        await them(
            nhan,
            cccd,
            full_name="Họ Giả Loại Hình",
            dob=date(2006, 3, 4),
            gender="Nam",
            ethnicity="01",
            permanent_commune_code="GX2",
            cultural_education_level="graduated_thpt",
            vocational_qualification="trung_cap",
            priority_resolution_snapshot={"kv_resolved": "KV2"},
            nv=[(1, "oto_cd", lh, "g1")],
            diem={0: {"toan": "6.50", "ly": "6.50", "hoa": "6.50"}},
            hoc_phi=[HP_CD],
        )
    # Đơn vị KHÁC (cho phép đo đơn vị của bộ).
    await them(
        "don_vi_khac",
        "GIA000000012",
        unit="u2",
        full_name="Họ Giả Mười Hai",
        dob=date(2008, 4, 5),
        gender="Nam",
        ethnicity="01",
        permanent_commune_code="GX1",
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        priority_resolution_snapshot={"kv_resolved": "KV1"},
        nv=[(1, "oto_cd", "cq", "g1")],
        diem={0: {"toan": "5.00", "ly": "5.00", "hoa": "5.00"}},
        hoc_phi=[HP_CD],
    )
    hs["_danh_muc"] = d
    return hs
