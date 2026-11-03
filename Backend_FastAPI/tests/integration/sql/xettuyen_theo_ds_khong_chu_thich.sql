-- Bản GHIM của truy vấn bộ xuất `xettuyen_theo_ds.sql` dùng cho test khoá hai nguồn bằng
-- nhau (CLAUDE.md §7) — KHÔNG phải mã chạy production.
-- sha256 nguồn (bản đã che mã): e67606812fba0895ed96b62dfb37ec04ffaf384f40325ac7c80723600cb4c94e
-- Biến đổi cơ học (ma-gd1/cong-cu/bo_chu_thich_sql_e1.py): (1) bỏ mọi chú thích `--…`
-- ngoài chuỗi, dòng chỉ có chú thích bị bỏ (80 dòng); (2) bỏ vỏ COPY … TO STDOUT;
-- (3) thay điều kiện lọc trình độ bằng lọc theo danh sách id (tham số ids).
-- Literal còn lại chỉ là mã hệ thống / nhãn / mẫu regex (đã rà, không tên người, không mã
-- hồ sơ, không số thật). Không sửa tay tệp này: sha của nó ghim trong test.
WITH tuition AS (
  SELECT DISTINCT ON (f.admission_profile_id) f.admission_profile_id AS pid,
         f.final_amount, f.paid_amount, f.waived_amount, f.resolved_major_id,
         f.resolved_degree_level
  FROM fee f WHERE f.fee_type = 'tuition' AND f.status <> 'cancelled' AND f.semester_no = 1
  ORDER BY f.admission_profile_id, f.id DESC),
nv1 AS (
  SELECT DISTINCT ON (c.admission_profile_id) c.admission_profile_id AS pid,
         mp.name AS mname, mp.degree_level AS dl, sg.code AS to_hop,
         am.name AS phuong_thuc, ac.scoring_method::text AS cach_tinh,
         c.id AS choice_id, psg.subject_group_id AS sg_id, cot.code AS loai_hinh
  FROM admission_profile_choice c
  JOIN admission_path ap ON ap.id = c.admission_path_id
  JOIN admission_method am ON am.id = ap.admission_method_id
  LEFT JOIN admission_criteria ac ON ac.id = ap.criteria_id
  JOIN path_subject_group_config psg ON psg.id = c.path_subject_group_config_id
  JOIN subject_group sg ON sg.id = psg.subject_group_id
  JOIN offering_academic_info oai ON oai.id = ap.academic_info_id
  JOIN program_offering po ON po.id = oai.offering_id
  JOIN major_program mp ON mp.id = po.program_id
  LEFT JOIN config_offering_type cot ON cot.id = po.offering_type_id
  ORDER BY c.admission_profile_id, c.display_order, c.id),
diem AS (
  SELECT nv1.pid,
    max(CASE WHEN x.thu_tu = 1 THEN x.score END) AS m1,
    max(CASE WHEN x.thu_tu = 2 THEN x.score END) AS m2,
    max(CASE WHEN x.thu_tu = 3 THEN x.score END) AS m3,
    sum(x.score) AS tong, avg(x.score) AS tb, count(*) AS so_mon_co,
    string_agg(x.ten_mon, ', ' ORDER BY x.thu_tu) AS mon_to_hop
  FROM nv1 JOIN LATERAL (
    SELECT pcs.score, s.name_vi AS ten_mon,
           row_number() OVER (ORDER BY sgs.position NULLS LAST, s.display_order) AS thu_tu
    FROM profile_choice_score pcs
    JOIN subject s ON s.id = pcs.subject_id
    JOIN subject_group_subject sgs ON sgs.subject_group_id = nv1.sg_id AND sgs.subject_id = s.id
    WHERE pcs.admission_profile_choice_id = nv1.choice_id) x ON TRUE
  GROUP BY nv1.pid),
gt AS (
  SELECT pd.profile_id AS pid,
    max(CASE WHEN dt.code = 'phieu_dang_ky_xet_tuyen' THEN pd.status::text END) AS s_phieu,
    max(CASE WHEN dt.code = 'so_yeu_ly_lich'          THEN pd.status::text END) AS s_soyeu,
    max(CASE WHEN dt.code = 'hoc_ba_thpt'             THEN pd.status::text END) AS s_hocba,
    max(CASE WHEN dt.code = 'hoc_ba_thpt'             THEN pd.actual_submission_format::text END) AS f_hocba,
    max(CASE WHEN dt.code = 'bang_tot_nghiep_thpt'    THEN pd.status::text END) AS s_bang,
    max(CASE WHEN dt.code = 'bang_tot_nghiep_thpt'    THEN pd.actual_submission_format::text END) AS f_bang,
    max(CASE WHEN dt.code = 'bang_tot_nghiep_thpt'    THEN pd.graduation_proof_kind END) AS k_bang,
    max(CASE WHEN dt.code = 'bang_tot_nghiep_thpt'    THEN pd.supplement_due_date::text END) AS h_bang,
    max(CASE WHEN dt.code = 'hoc_ba_thcs'             THEN pd.status::text END) AS s_hocba_thcs,
    max(CASE WHEN dt.code = 'bang_tot_nghiep_thcs'    THEN pd.status::text END) AS s_bang_thcs,
    max(CASE WHEN dt.code = 'giay_cn_hoan_thanh_gdpt' THEN pd.status::text END) AS s_cngdpt,
    max(CASE WHEN dt.code = 'giay_cn_hoan_thanh_gdpt' THEN pd.actual_submission_format::text END) AS f_cngdpt,
    max(CASE WHEN dt.code = 'giay_khai_sinh'          THEN pd.status::text END) AS s_ks,
    max(CASE WHEN dt.code = 'giay_khai_sinh'          THEN pd.actual_submission_format::text END) AS f_ks,
    max(CASE WHEN dt.code = 'cccd'                    THEN pd.status::text END) AS s_cccd,
    max(CASE WHEN dt.code = 'cccd'                    THEN pd.actual_submission_format::text END) AS f_cccd,
    max(CASE WHEN dt.code = 'anh_3x4'                 THEN pd.status::text END) AS s_anh,
    max(CASE WHEN dt.code = 'anh_3x4'                 THEN pd.actual_submission_format::text END) AS f_anh
  FROM profile_document pd JOIN config_document_type dt ON dt.id = pd.document_type_id
  GROUP BY 1)
SELECT
  p.id                                                            AS "pid",
  COALESCE(p.citizen_id, '')                                      AS "ma_ho_so",
  CASE WHEN btrim(regexp_replace(p.full_name, '\s+', ' ', 'g')) ~ ' '
       THEN regexp_replace(btrim(regexp_replace(p.full_name, '\s+', ' ', 'g')), '\s+\S+$', '')
       ELSE '' END                                                   AS "ho",
  COALESCE((regexp_match(btrim(regexp_replace(p.full_name, '\s+', ' ', 'g')), '(\S+)$'))[1], '') AS "ten",
  COALESCE(p.gender, '')                                          AS "gioi_tinh",
  to_char(p.dob, 'DD/MM/YYYY')                          AS "ngay_sinh",
  COALESCE(p.place_of_birth, '')                                  AS "noi_sinh",
  COALESCE(cs.name, p.ethnicity, '')                              AS "dan_toc",
  COALESCE(an_tinh.name, NULLIF(p.permanent_province, ''), '')    AS "tinh_chuan",
  COALESCE(NULLIF(btrim(concat_ws(', ', NULLIF(p.permanent_residential_group, ''),
           NULLIF(COALESCE(mcur.ward, p.permanent_ward), ''),
           NULLIF(COALESCE(an_tinh.name, p.permanent_province), ''))), ''), '')
                                                                  AS "dia_chi",
  CASE p.cultural_education_level::text
    WHEN 'graduated_thpt' THEN 'THPT'
    WHEN 'graduated_gdtx' THEN 'GDTX'
    WHEN 'completed_thpt' THEN 'Hoàn thành THPT'
    WHEN 'graduated_thcs' THEN 'THCS'
    WHEN 'completed_thcs' THEN 'Hoàn thành THCS'
    ELSE COALESCE(p.cultural_education_level::text, '') END       AS "van_hoa",
  p.status::text                                                  AS "trang_thai",
  COALESCE(mp.name, nv1.mname, '')                                AS "nganh",
  COALESCE(mp.code, '')                                           AS "ma_nganh",
  COALESCE(t.resolved_degree_level::text, nv1.dl::text, '')       AS "trinh_do",
  COALESCE(nv1.to_hop, '')                                        AS "to_hop",
  COALESCE(nv1.phuong_thuc, '')                                   AS "phuong_thuc",
  COALESCE(nv1.cach_tinh, '')                                     AS "cach_tinh",
  COALESCE(diem.m1::text, '')                                     AS "m1",
  COALESCE(diem.m2::text, '')                                     AS "m2",
  COALESCE(diem.m3::text, '')                                     AS "m3",
  COALESCE(round(diem.tb, 2)::text, '')                           AS "diem_tb",
  COALESCE(diem.tong::text, '')                                   AS "tong_diem",
  COALESCE(diem.so_mon_co::text, '0')                             AS "so_mon_co",
  COALESCE(diem.mon_to_hop, '')                                   AS "mon_to_hop",
  COALESCE(p.priority_resolution_snapshot::jsonb->>'kv_resolved', '') AS "kv",
  COALESCE((SELECT pac.bonus_points::text FROM priority_area_config pac
            WHERE pac.area_code = p.priority_resolution_snapshot::jsonb->>'kv_resolved'
            ORDER BY pac.effective_from DESC NULLS LAST LIMIT 1), '0') AS "diem_kv",
  COALESCE(mcur.area_code, '')                                    AS "kv_ho_khau",
  CASE WHEN COALESCE(cs.name, p.ethnicity, '') IN ('Kinh', '') THEN ''
       WHEN mcur.area_code = 'KV1' THEN '01'
       ELSE '06' END                                              AS "ut_ma",
  CASE WHEN COALESCE(cs.name, p.ethnicity, '') IN ('Kinh', '') THEN '0'
       WHEN mcur.area_code = 'KV1' THEN '2.00'
       ELSE '1.00' END                                            AS "diem_ut",
  (COALESCE(t.final_amount, 0) - COALESCE(t.paid_amount, 0)
   - COALESCE(t.waived_amount, 0))::text                          AS "con_lai",
  CASE WHEN t.pid IS NULL THEN '0' ELSE '1' END                   AS "co_hoc_phi",
  COALESCE(gt.s_phieu, 'missing')   AS "s_phieu",
  COALESCE(gt.s_soyeu, 'missing')   AS "s_soyeu",
  COALESCE(gt.s_hocba_thcs, 'missing') AS "s_hocba_thcs",
  COALESCE(gt.s_bang_thcs, 'missing')  AS "s_bang_thcs",
  COALESCE((SELECT max((e.v->>'year_to')::int) FROM jsonb_array_elements(p.academic_history) e(v)
            WHERE (e.v->>'grade_to')::int = 9)::text, '')          AS "lop9_nam",
  COALESCE(gt.s_hocba, 'missing')   AS "s_hocba",  COALESCE(gt.f_hocba, '')  AS "f_hocba",
  COALESCE(gt.s_bang, 'missing')    AS "s_bang",   COALESCE(gt.f_bang, '')   AS "f_bang",
  COALESCE(gt.k_bang, '')           AS "k_bang",   COALESCE(gt.h_bang, '')   AS "h_bang",
  COALESCE(gt.s_cngdpt, 'missing')  AS "s_cngdpt", COALESCE(gt.f_cngdpt, '') AS "f_cngdpt",
  COALESCE(gt.s_ks, 'missing')      AS "s_ks",     COALESCE(gt.f_ks, '')     AS "f_ks",
  COALESCE(gt.s_cccd, 'missing')    AS "s_cccd",   COALESCE(gt.f_cccd, '')   AS "f_cccd",
  COALESCE(gt.s_anh, 'missing')     AS "s_anh",    COALESCE(gt.f_anh, '')    AS "f_anh",
  p.vocational_qualification::text                                AS "chuyen_mon",
  COALESCE(nv1.loai_hinh, '')                                     AS "loai_hinh"
FROM admission_profile p
LEFT JOIN tuition t   ON t.pid = p.id
LEFT JOIN major_program mp ON mp.id = t.resolved_major_id
LEFT JOIN nv1         ON nv1.pid = p.id
LEFT JOIN diem        ON diem.pid = p.id
LEFT JOIN gt          ON gt.pid = p.id
LEFT JOIN config_system_category cs ON cs.type = 'ethnicity' AND cs.code = p.ethnicity
LEFT JOIN vn_commune_area_map mcur
       ON mcur.commune_code = p.permanent_commune_code AND mcur.effective_to IS NULL
LEFT JOIN administrative_nodes an_xa
       ON an_xa.code = p.permanent_commune_code AND an_xa.level = 'WARD'
      AND an_xa.is_active AND an_xa.valid_to IS NULL
LEFT JOIN administrative_nodes an_tinh
       ON an_tinh.code = an_xa.province_code AND an_tinh.level = 'PROVINCE'
      AND an_tinh.is_active AND an_tinh.valid_to IS NULL
WHERE p.id = ANY(CAST(:ids AS integer[]))
ORDER BY COALESCE(mp.name, nv1.mname), p.id
