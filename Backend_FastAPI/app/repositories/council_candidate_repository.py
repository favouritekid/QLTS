# app/repositories/council_candidate_repository.py
"""Đọc số liệu hồ sơ cho bộ văn bản Hội đồng — MỘT giao dịch ``REPEATABLE READ READ ONLY``
trên kết nối RIÊNG (không dùng giao dịch của request), không ghi gì trong đó.

Mỗi cột trả về tính ĐÚNG như cột cùng tên của truy vấn bộ xuất ``xettuyen_theo_ds.sql``
(nguồn tham chiếu của luật v1; bản ghim không chú thích ở
``tests/integration/sql/xettuyen_theo_ds_khong_chu_thich.sql``). Hai nguồn được khoá bằng
nhau bởi ``tests/integration/test_council_candidate_snapshot.py`` trên dữ liệu giả
(CLAUDE.md §7): sửa một bên mà không sửa bên kia ⇒ test đỏ. Viết bằng SQL tham số hoá
(``text()``) để định dạng số (``numeric::text``, ``round(avg, 2)``) và chữ (``to_char``,
``regexp_replace``) do CHÍNH PostgreSQL làm, như bộ xuất — không chép lại bằng Python.

Khác bộ xuất (có chủ ý, không đổi giá trị nào của một hồ sơ):

* Đầu vào là danh sách id hồ sơ đã phân giải từ mã (CCCD); KHÔNG lọc trạng thái, KHÔNG lọc
  trình độ (danh sách do Quyết định quyết; trình độ lạ do bộ dựng chặn). Kết quả theo ĐÚNG
  thứ tự đầu vào.
* Không nối ``admission_criteria`` / ``config_offering_type``: nối trái theo khoá chính nên
  không đổi số hàng, và không cột nào của DTO đọc chúng (loại hình không ảnh hưởng cách đếm
  của Biên bản — luật v1.1).
* Hai phép sắp có thể HOÀ trong bộ xuất được thêm khoá phụ tất định (``id``): mức điểm khu
  vực theo ``effective_from`` và thứ tự môn theo ``position, display_order``. Khi không hoà
  thì kết quả trùng bộ xuất; khi hoà thì bộ xuất không xác định.
* Thêm ``lead.unit_id`` (đơn vị của hồ sơ — đúng cột kiểm quyền Quản lý của
  ``admission_service._check_idor_access`` dùng) để tính đơn vị của bộ văn bản.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.utils.exceptions import ServiceError

MUC_CO_LAP = "repeatable read"


@dataclass(frozen=True)
class ThongTinGiaoDich:
    """Đo NGAY TRONG giao dịch đọc (không suy từ cấu hình)."""

    transaction_isolation: str
    transaction_read_only: str
    moc_chup: datetime  # transaction_timestamp() — mốc chụp của bộ
    backend_pid: int


@asynccontextmanager
async def giao_dich_chi_doc(
    engine: AsyncEngine,
) -> AsyncIterator["tuple[AsyncConnection, ThongTinGiaoDich]"]:
    """Mở MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối riêng của ``engine``.

    Mức cô lập + chỉ đọc đặt bằng tuỳ chọn của KẾT NỐI ⇒ asyncpg mở giao dịch bằng đúng MỘT
    lệnh ``BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`` (không có truy vấn nào chen
    trước). Sau đó ĐO lại trong giao dịch; lệch ⇒ ``ServiceError`` (fail-closed, không đọc).
    Thoát khối (kể cả khi lỗi) ⇒ giao dịch kết thúc bằng ROLLBACK — không có gì để commit —
    và kết nối trả pool (SQLAlchemy trả mức cô lập / chỉ đọc về mặc định khi trả kết nối;
    test khoá điều này trên pool một kết nối)."""
    async with engine.connect() as conn:
        await conn.execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        )
        gd = await conn.begin()
        try:
            do = (
                await conn.execute(
                    text(
                        "SELECT current_setting('transaction_isolation') AS iso, "
                        "current_setting('transaction_read_only') AS ro, "
                        "transaction_timestamp() AS moc, pg_backend_pid() AS pid"
                    )
                )
            ).one()
            tt = ThongTinGiaoDich(do.iso, do.ro, do.moc, do.pid)
            if (
                tt.transaction_isolation != MUC_CO_LAP
                or tt.transaction_read_only != "on"
            ):
                raise ServiceError(
                    "Giao dịch đọc hồ sơ không ở REPEATABLE READ READ ONLY — không đọc."
                )
            yield conn, tt
        finally:
            await gd.rollback()


# Mỗi dòng đầu vào khớp bao nhiêu hồ sơ (CCCD = ``admission_profile.citizen_id``) TRONG
# NĂM HỌC đã cho. CCCD chỉ UNIQUE theo năm học (``uq_citizen_academic_year``) ⇒ không lọc
# năm thì một người có hồ sơ ở hai năm "khớp NHIỀU"; người gọi vẫn đòi ĐÚNG MỘT (lớp phụ).
SQL_PHAN_GIAI_MA = text(
    """
SELECT d.stt::int AS stt, count(p.id)::int AS so_khop, min(p.id) AS pid
FROM unnest(CAST(:ma AS text[])) WITH ORDINALITY AS d(ma, stt)
LEFT JOIN admission_profile p
       ON p.citizen_id = d.ma AND p.academic_year = CAST(:nam AS integer)
GROUP BY d.stt
ORDER BY d.stt
"""
)

# Số liệu của các hồ sơ ``:pids`` theo ĐÚNG thứ tự mảng. Tên cột = tên trường DTO.
SQL_SO_LIEU = text(
    r"""
WITH chon AS (
    SELECT x.pid, x.stt
    FROM unnest(CAST(:pids AS integer[])) WITH ORDINALITY AS x(pid, stt)
),
hoc_phi AS (
    -- khoản học phí học kỳ 1 chưa huỷ, id lớn nhất
    SELECT DISTINCT ON (f.admission_profile_id)
           f.admission_profile_id AS pid, f.resolved_major_id, f.resolved_degree_level
    FROM fee f
    JOIN chon ON chon.pid = f.admission_profile_id
    WHERE f.fee_type = 'tuition' AND f.status <> 'cancelled' AND f.semester_no = 1
    ORDER BY f.admission_profile_id, f.id DESC
),
nv1 AS (
    -- nguyện vọng đầu: display_order rồi id, CHỈ trong các nguyện vọng có đủ chuỗi
    -- phương thức -> tổ hợp -> ngành (nối trong, như bộ xuất)
    SELECT DISTINCT ON (c.admission_profile_id)
           c.admission_profile_id AS pid, c.id AS choice_id,
           mp.name AS ten_nganh, mp.degree_level AS trinh_do_nganh,
           sg.code AS to_hop, am.name AS phuong_thuc, psg.subject_group_id AS sg_id
    FROM admission_profile_choice c
    JOIN chon ON chon.pid = c.admission_profile_id
    JOIN admission_path ap ON ap.id = c.admission_path_id
    JOIN admission_method am ON am.id = ap.admission_method_id
    JOIN path_subject_group_config psg ON psg.id = c.path_subject_group_config_id
    JOIN subject_group sg ON sg.id = psg.subject_group_id
    JOIN offering_academic_info oai ON oai.id = ap.academic_info_id
    JOIN program_offering po ON po.id = oai.offering_id
    JOIN major_program mp ON mp.id = po.program_id
    ORDER BY c.admission_profile_id, c.display_order, c.id
),
mon AS (
    -- điểm từng môn của NGUYỆN VỌNG ĐẦU, thứ tự môn theo vị trí trong tổ hợp đã chọn
    SELECT nv1.pid, pcs.score, s.name_vi,
           row_number() OVER (PARTITION BY nv1.pid
                              ORDER BY sgs.position NULLS LAST, s.display_order, s.id) AS vt
    FROM nv1
    JOIN profile_choice_score pcs ON pcs.admission_profile_choice_id = nv1.choice_id
    JOIN subject s ON s.id = pcs.subject_id
    JOIN subject_group_subject sgs
         ON sgs.subject_group_id = nv1.sg_id AND sgs.subject_id = s.id
),
diem AS (
    SELECT pid,
           max(score) FILTER (WHERE vt = 1) AS m1,
           max(score) FILTER (WHERE vt = 2) AS m2,
           max(score) FILTER (WHERE vt = 3) AS m3,
           sum(score) AS tong, avg(score) AS tb,
           string_agg(name_vi, ', ' ORDER BY vt) AS mon_to_hop
    FROM mon
    GROUP BY pid
),
giay AS (
    -- trạng thái + hình thức từng loại giấy (không có giấy -> mặc định ở SELECT)
    SELECT pd.profile_id AS pid,
      max(pd.status::text) FILTER (WHERE dt.code = 'phieu_dang_ky_xet_tuyen') AS s_phieu,
      max(pd.status::text) FILTER (WHERE dt.code = 'so_yeu_ly_lich') AS s_soyeu,
      max(pd.status::text) FILTER (WHERE dt.code = 'hoc_ba_thpt') AS s_hocba,
      max(pd.actual_submission_format::text) FILTER (WHERE dt.code = 'hoc_ba_thpt') AS f_hocba,
      max(pd.status::text) FILTER (WHERE dt.code = 'bang_tot_nghiep_thpt') AS s_bang,
      max(pd.actual_submission_format::text)
          FILTER (WHERE dt.code = 'bang_tot_nghiep_thpt') AS f_bang,
      max(pd.graduation_proof_kind) FILTER (WHERE dt.code = 'bang_tot_nghiep_thpt') AS k_bang,
      max(pd.status::text) FILTER (WHERE dt.code = 'giay_cn_hoan_thanh_gdpt') AS s_cngdpt,
      max(pd.actual_submission_format::text)
          FILTER (WHERE dt.code = 'giay_cn_hoan_thanh_gdpt') AS f_cngdpt,
      max(pd.status::text) FILTER (WHERE dt.code = 'giay_khai_sinh') AS s_ks,
      max(pd.actual_submission_format::text) FILTER (WHERE dt.code = 'giay_khai_sinh') AS f_ks,
      max(pd.status::text) FILTER (WHERE dt.code = 'cccd') AS s_cccd,
      max(pd.actual_submission_format::text) FILTER (WHERE dt.code = 'cccd') AS f_cccd,
      max(pd.status::text) FILTER (WHERE dt.code = 'anh_3x4') AS s_anh,
      max(pd.actual_submission_format::text) FILTER (WHERE dt.code = 'anh_3x4') AS f_anh
    FROM profile_document pd
    JOIN chon ON chon.pid = pd.profile_id
    JOIN config_document_type dt ON dt.id = pd.document_type_id
    GROUP BY pd.profile_id
)
SELECT
  chon.stt::int AS stt,
  p.id AS pid,
  l.unit_id AS unit_id,
  COALESCE(p.citizen_id, '') AS ma_ho_so,
  -- họ = mọi từ trừ từ cuối; tên một chữ thì họ RỖNG (không lặp tên vào họ)
  CASE WHEN h.ten_gon ~ ' ' THEN regexp_replace(h.ten_gon, '\s+\S+$', '') ELSE '' END AS ho,
  COALESCE((regexp_match(h.ten_gon, '(\S+)$'))[1], '') AS ten,
  COALESCE(p.gender, '') AS gioi_tinh,
  COALESCE(to_char(p.dob, 'DD/MM/YYYY'), '') AS ngay_sinh,
  COALESCE(p.place_of_birth, '') AS noi_sinh,
  COALESCE(dtoc.name, p.ethnicity, '') AS dan_toc,
  -- tên xã lấy bản ghi khu vực HIỆN HÀNH (tên sau sắp xếp), tên tỉnh từ danh mục hành chính
  -- hiện hành; thiếu thì rơi về chữ trên hồ sơ
  COALESCE(NULLIF(btrim(concat_ws(', ',
      NULLIF(p.permanent_residential_group, ''),
      NULLIF(COALESCE(kvx.ward, p.permanent_ward), ''),
      NULLIF(COALESCE(tinh.name, p.permanent_province), ''))), ''), '') AS dia_chi,
  CASE p.cultural_education_level::text
      WHEN 'graduated_thpt' THEN 'THPT'
      WHEN 'graduated_gdtx' THEN 'GDTX'
      WHEN 'completed_thpt' THEN 'Hoàn thành THPT'
      WHEN 'graduated_thcs' THEN 'THCS'
      WHEN 'completed_thcs' THEN 'Hoàn thành THCS'
      ELSE COALESCE(p.cultural_education_level::text, '') END AS van_hoa,
  -- ngành + mã ngành theo khoản học phí (ngành đã định giá), không có thì theo nguyện vọng
  -- đầu (mã ngành chỉ lấy từ khoản học phí)
  COALESCE(mpt.name, nv1.ten_nganh, '') AS nganh,
  COALESCE(mpt.code, '') AS ma_nganh,
  COALESCE(t.resolved_degree_level::text, nv1.trinh_do_nganh::text, '') AS trinh_do,
  COALESCE(nv1.to_hop, '') AS to_hop,
  COALESCE(nv1.phuong_thuc, '') AS phuong_thuc,
  COALESCE(diem.mon_to_hop, '') AS mon_to_hop,
  COALESCE(diem.m1::text, '') AS m1,
  COALESCE(diem.m2::text, '') AS m2,
  COALESCE(diem.m3::text, '') AS m3,
  COALESCE(round(diem.tb, 2)::text, '') AS diem_tb,
  COALESCE(diem.tong::text, '') AS tong_diem,
  -- khu vực ưu tiên theo nơi học THPT (ảnh chụp phân giải trên hồ sơ)
  COALESCE(p.priority_resolution_snapshot->>'kv_resolved', '') AS kv,
  COALESCE((SELECT pac.bonus_points::text FROM priority_area_config pac
            WHERE pac.area_code = p.priority_resolution_snapshot->>'kv_resolved'
            ORDER BY pac.effective_from DESC NULLS LAST, pac.id DESC LIMIT 1), '0') AS diem_kv,
  -- đối tượng ưu tiên của em dân tộc thiểu số theo HỘ KHẨU (xã thường trú KV1 hay không)
  CASE WHEN COALESCE(dtoc.name, p.ethnicity, '') IN ('Kinh', '') THEN ''
       WHEN kvx.area_code = 'KV1' THEN '01'
       ELSE '06' END AS ut_ma,
  CASE WHEN COALESCE(dtoc.name, p.ethnicity, '') IN ('Kinh', '') THEN '0'
       WHEN kvx.area_code = 'KV1' THEN '2.00'
       ELSE '1.00' END AS diem_ut,
  COALESCE(giay.s_phieu, 'missing') AS s_phieu,
  COALESCE(giay.s_soyeu, 'missing') AS s_soyeu,
  COALESCE(giay.s_hocba, 'missing') AS s_hocba,
  COALESCE(giay.f_hocba, '') AS f_hocba,
  COALESCE(giay.s_bang, 'missing') AS s_bang,
  COALESCE(giay.f_bang, '') AS f_bang,
  COALESCE(giay.k_bang, '') AS k_bang,
  COALESCE(giay.s_cngdpt, 'missing') AS s_cngdpt,
  COALESCE(giay.f_cngdpt, '') AS f_cngdpt,
  COALESCE(giay.s_ks, 'missing') AS s_ks,
  COALESCE(giay.f_ks, '') AS f_ks,
  COALESCE(giay.s_cccd, 'missing') AS s_cccd,
  COALESCE(giay.f_cccd, '') AS f_cccd,
  COALESCE(giay.s_anh, 'missing') AS s_anh,
  COALESCE(giay.f_anh, '') AS f_anh,
  p.vocational_qualification::text AS chuyen_mon
FROM chon
JOIN admission_profile p ON p.id = chon.pid
JOIN lead l ON l.id = p.lead_id
CROSS JOIN LATERAL (
    SELECT btrim(regexp_replace(p.full_name, '\s+', ' ', 'g')) AS ten_gon
) h
LEFT JOIN hoc_phi t ON t.pid = p.id
LEFT JOIN major_program mpt ON mpt.id = t.resolved_major_id
LEFT JOIN nv1 ON nv1.pid = p.id
LEFT JOIN diem ON diem.pid = p.id
LEFT JOIN giay ON giay.pid = p.id
LEFT JOIN config_system_category dtoc
       ON dtoc.type = 'ethnicity' AND dtoc.code = p.ethnicity
LEFT JOIN vn_commune_area_map kvx
       ON kvx.commune_code = p.permanent_commune_code AND kvx.effective_to IS NULL
LEFT JOIN administrative_nodes xa
       ON xa.code = p.permanent_commune_code AND xa.level = 'WARD'
      AND xa.is_active AND xa.valid_to IS NULL
LEFT JOIN administrative_nodes tinh
       ON tinh.code = xa.province_code AND tinh.level = 'PROVINCE'
      AND tinh.is_active AND tinh.valid_to IS NULL
ORDER BY chon.stt
"""
)


async def phan_giai_ma(
    conn: AsyncConnection, ma: Sequence[str], academic_year: int
) -> List[tuple]:
    """[(stt, số hồ sơ khớp trong năm học ``academic_year``, id nhỏ nhất)] theo thứ tự đầu
    vào."""
    return [
        tuple(r)
        for r in (
            await conn.execute(SQL_PHAN_GIAI_MA, {"ma": list(ma), "nam": academic_year})
        ).all()
    ]


async def doc_so_lieu(conn: AsyncConnection, pids: Sequence[int]) -> List[dict]:
    """Mỗi hàng = dict cột → giá trị, theo thứ tự ``pids``."""
    return [
        dict(r._mapping)
        for r in (await conn.execute(SQL_SO_LIEU, {"pids": list(pids)})).all()
    ]
