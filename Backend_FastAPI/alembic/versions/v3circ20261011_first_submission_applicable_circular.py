"""V3 — lần nộp đầu + thông tư áp dụng theo từng hồ sơ (M1).

Revision ID: v3circ20261011
Revises: e1safety20260912
Create Date: 2026-10-11

VÌ SAO
------
Từ 03-11-2026 TT 76/2026/TT-BGDĐT thay TT 05/2021/TT-BLĐTBXH. Owner chốt (11-10-2026): mỗi hồ sơ mang MỘT
thông tư, mặc định theo ngày lịch giờ Việt Nam của LẦN NỘP ĐẦU. Hằng và luật ở
``app/constants/admission_circular.py``; tầng chủ sở hữu việc đóng dấu lúc chạy là
``admission_state_service.transition()``. Migration này thêm cột và gán giá trị cho dữ liệu đã có.

BACKFILL THEO LỊCH SỬ, KHÔNG THEO TRẠNG THÁI HIỆN TẠI
-----------------------------------------------------
Mọi trạng thái chưa kết thúc đều về được ``draft``. Một hồ sơ đang ``draft`` lúc chạy migration có thể ĐÃ
nộp trước đó; xếp nó vào "chưa nộp" thì lần nộp lại sau 03-11 biến nó thành TT 76 — trái quyết định "lần
nộp đầu". Vì vậy phân loại đọc ``admission_profile_status_history``:

1. ``status_history`` — có hàng ``draft → submitted`` VÀ không có dấu hiệu sau-nộp nào SỚM HƠN hàng ấy.
   Ngày = ``MIN(occurred_at)`` của hàng nộp.
2. ``missing_evidence`` — đã qua bước nộp (trạng thái hiện tại thuộc POST_SUBMIT, hoặc có hàng lịch sử đi
   từ/tới một trạng thái POST_SUBMIT) mà không đủ điều kiện mục 1. Ngày để TRỐNG. Gồm cả hồ sơ có hàng
   khởi tạo ``phase1_10`` (``NULL → submitted`` tại ``created_at``) sớm hơn hàng nộp đầu tiên: khi ấy MIN
   của hàng nộp KHÔNG phải lần nộp đầu, và ngày thật không còn chứng cứ.
3. Còn lại — chưa từng nộp ⇒ cả hai cột NULL (draft, rút thẳng từ nháp, ``draft → withdrawal_pending →
   draft``).

Thông tư: mục 1 theo công thức ngày VN; mục 2 = TT 05 — chỉ đúng khi migration chạy TRƯỚC mốc, nên khối
kiểm chặn trường hợp ngược lại.

MỘT CÂU ``DO`` DUY NHẤT — vì ``alembic/env.py`` chạy ở AUTOCOMMIT
-----------------------------------------------------------------
``env.py`` đặt ``isolation_level=AUTOCOMMIT`` và không mở ``begin_transaction()``: MỖI ``op.execute`` tự commit.
Nếu backfill và khối kiểm là hai lệnh, khối kiểm RAISE khi backfill ĐÃ commit — đúng dạng "báo lỗi mà việc
hỏng vẫn nằm lại". Vì vậy ``upgrade()`` gửi đúng MỘT câu ``DO`` chứa: thêm cột + CK1–CK3 → backfill →
khối kiểm → CK4/CK5. Một câu là một giao dịch ngầm: RAISE ở bất kỳ đâu ⇒ lùi TOÀN BỘ, kể cả cột mới, và
``alembic_version`` không bị đóng dấu ⇒ chạy lại sạch. ``test_admission_circular_constants.py`` khoá
``upgrade()`` chỉ gọi ``op.execute`` đúng một lần; test Tier 4i chứng minh RAISE lùi cả backfill.

Không dùng ký tự phần trăm trong SQL (``RAISE … USING MESSAGE`` + nối chuỗi): driver nào thoát ký tự ấy
thế nào thì câu vẫn y nguyên.

FAIL-CLOSED
-----------
``GUARD_SQL`` tạo hàm tạm ``pg_temp.v3_m1_guard(run_at)``; migration gọi với ``now()``, test gọi với mốc cố
định — cùng một mã, không núm vặn bỏ qua. Hàm đếm vi phạm từng điều và RAISE (liệt kê mã) TRƯỚC khi
migration thêm CK4/CK5 và commit. Downgrade RAISE khi còn hàng ``manual``: bỏ cột là mất thay đổi tay.

CK5 CHỈ Ở ĐÂY, KHÔNG Ở MODEL
----------------------------
"Trạng thái sau nộp phải có dấu ngày nộp" là lưới ở tầng CSDL production cho SQL tay. Không khai ở model vì
CSDL test dựng bằng ``create_all()`` và hàng trăm fixture tạo hồ sơ thẳng ở ``submitted``. Cửa sổ deploy:
mã cũ nộp hồ sơ trong vài phút giữa migration và backend mới sẽ bị CK5 chặn — owner chấp nhận (Q14 = W1,
deploy giờ vắng).

Test: ``tests/api/test_v3_first_submission_backfill_migration.py`` (Tier 4i) import các hằng SQL của tệp
này, không chép. ``tests/unit/test_admission_circular_constants.py`` (Tier 5) khoá các bản chép đông cứng
dưới đây bằng hằng của ứng dụng và bằng ràng buộc của model.
"""

from alembic import op

revision = "v3circ20261011"
down_revision = "e1safety20260912"
branch_labels = None
depends_on = None

# --- Bản chép ĐÔNG CỨNG (migration không import mã ứng dụng) ---------------------------------------
CUTOVER_DATE_FROZEN = "2026-11-03"
VN_TZ_FROZEN = "Asia/Ho_Chi_Minh"
TT05_FROZEN = "TT05_2021"
TT76_FROZEN = "TT76_2026"
CIRCULARS_FROZEN = (TT05_FROZEN, TT76_FROZEN)
POST_SUBMIT_FROZEN = (
    "submitted",
    "resubmitted",
    "approved",
    "rejected",
    "revision_requested",
    "confirmed",
    "overridden",
    "enrolled",
    "reviewing",
    "result_published",
    "admitted",
    "waitlisted",
)
PRE_SUBMIT_FROZEN = ("draft", "withdrawn", "withdrawal_pending")
FIRST_SUBMITTED_SOURCES_FROZEN = ("submit_transition", "status_history", "missing_evidence", "manual")
FIRST_SUBMITTED_SOURCES_WITH_DATE_FROZEN = ("submit_transition", "status_history", "manual")
CIRCULAR_SOURCES_FROZEN = (
    "default_first_submit",
    "backfill_first_submit",
    "backfill_missing_evidence",
    "manual",
)


def _ds(values) -> str:
    return ", ".join("'%s'" % v for v in values)


def circular_formula_sql(col: str) -> str:
    """Thông tư theo NGÀY LỊCH VN của một cột ``timestamptz``.

    ``timestamptz AT TIME ZONE '<vùng>'`` cho giờ địa phương của vùng ấy, KHÔNG phụ thuộc ``TimeZone`` của
    phiên. Viết ``col::date`` trần thì phiên ở UTC tính sai đúng 7 giờ quanh nửa đêm.
    """
    return (
        "CASE WHEN (%s AT TIME ZONE '%s')::date >= DATE '%s' THEN '%s' ELSE '%s' END"
        % (col, VN_TZ_FROZEN, CUTOVER_DATE_FROZEN, TT76_FROZEN, TT05_FROZEN)
    )


# --- Ràng buộc (tên → biểu thức). Bốn cái đầu khai giống hệt ở model. -------------------------------
CHECKS_TRUOC_BACKFILL = {
    "ck_admission_profile_first_submitted_source": (
        "first_submitted_source IS NULL OR first_submitted_source IN (%s)"
        % _ds(FIRST_SUBMITTED_SOURCES_FROZEN)
    ),
    "ck_admission_profile_applicable_circular": (
        "applicable_circular IS NULL OR applicable_circular IN (%s)" % _ds(CIRCULARS_FROZEN)
    ),
    "ck_admission_profile_applicable_circular_source": (
        "applicable_circular_source IS NULL OR applicable_circular_source IN (%s)"
        % _ds(CIRCULAR_SOURCES_FROZEN)
    ),
    "ck_admission_profile_first_submitted_pair": (
        "(first_submitted_at IS NOT NULL) = (first_submitted_source IS NOT NULL "
        "AND first_submitted_source IN (%s))" % _ds(FIRST_SUBMITTED_SOURCES_WITH_DATE_FROZEN)
    ),
    "ck_admission_profile_applicable_circular_pair": (
        "(applicable_circular IS NULL) = (applicable_circular_source IS NULL)"
    ),
}
CK4_NAME = "ck_admission_profile_submitted_has_circular"
CK4_SQL = "first_submitted_source IS NULL OR applicable_circular IS NOT NULL"
CK5_NAME = "ck_admission_profile_post_submit_stamped"
CK5_SQL = "status IN (%s) OR first_submitted_source IS NOT NULL" % _ds(PRE_SUBMIT_FROZEN)

# --- Phân loại theo lịch sử: MỘT định nghĩa, dùng chung cho backfill và khối kiểm ---------------------
#: Mỗi hồ sơ: lần nộp đầu (``nop``) và dấu hiệu sau-nộp sớm nhất (``dau_hieu``). Hàng ``draft → submitted``
#: tự nó là một dấu hiệu sau-nộp, nên ``dau_hieu <= nop`` luôn đúng; ``dau_hieu < nop`` nghĩa là hồ sơ đã ở
#: trạng thái sau nộp TRƯỚC hàng nộp đầu tiên còn lưu.
PHAN_LOAI_SQL = """
SELECT p.id AS profile_id,
       n.nop,
       d.dau_hieu,
       CASE
         WHEN n.nop IS NOT NULL AND d.dau_hieu >= n.nop THEN 'status_history'
         WHEN p.status IN ({post}) OR d.dau_hieu IS NOT NULL THEN 'missing_evidence'
         ELSE NULL
       END AS phan_loai
FROM admission_profile p
LEFT JOIN (
    SELECT profile_id, MIN(occurred_at) AS nop
    FROM admission_profile_status_history
    WHERE from_status = 'draft' AND to_status = 'submitted'
    GROUP BY profile_id
) n ON n.profile_id = p.id
LEFT JOIN (
    SELECT profile_id, MIN(occurred_at) AS dau_hieu
    FROM admission_profile_status_history
    WHERE from_status IN ({post}) OR to_status IN ({post})
    GROUP BY profile_id
) d ON d.profile_id = p.id
""".format(post=_ds(POST_SUBMIT_FROZEN))

#: Các câu backfill — MỖI PHẦN TỬ MỘT CÂU (driver không nhận nhiều lệnh trong một câu chuẩn bị).
#: Chỉ chạm hồ sơ ``first_submitted_source IS NULL`` và không ghi đè thông tư đã có ⇒ chạy lại vô hại.
BACKFILL_SQL = (
    # Mục 1 — status_history.
    """
    UPDATE admission_profile p
       SET first_submitted_at = c.nop,
           first_submitted_source = 'status_history',
           applicable_circular = COALESCE(p.applicable_circular, {formula}),
           applicable_circular_source = COALESCE(p.applicable_circular_source, 'backfill_first_submit'),
           applicable_circular_set_at = COALESCE(p.applicable_circular_set_at, now())
      FROM ({phan_loai}) c
     WHERE c.profile_id = p.id
       AND c.phan_loai = 'status_history'
       AND p.first_submitted_source IS NULL
    """.format(formula=circular_formula_sql("c.nop"), phan_loai=PHAN_LOAI_SQL),
    # Mục 2 — missing_evidence: ngày TRỐNG, thông tư TT 05.
    """
    UPDATE admission_profile p
       SET first_submitted_source = 'missing_evidence',
           applicable_circular = COALESCE(p.applicable_circular, '{tt05}'),
           applicable_circular_source = COALESCE(p.applicable_circular_source, 'backfill_missing_evidence'),
           applicable_circular_set_at = COALESCE(p.applicable_circular_set_at, now())
      FROM ({phan_loai}) c
     WHERE c.profile_id = p.id
       AND c.phan_loai = 'missing_evidence'
       AND p.first_submitted_source IS NULL
    """.format(tt05=TT05_FROZEN, phan_loai=PHAN_LOAI_SQL),
)

#: Khối kiểm. Mỗi mã một bất biến; hàm đếm TẤT CẢ rồi RAISE một lần, liệt kê mã vi phạm (``a1=3 g=1``).
GUARD_SQL = """
CREATE OR REPLACE FUNCTION pg_temp.v3_m1_guard(run_at timestamptz) RETURNS void
LANGUAGE plpgsql AS $guard$
DECLARE
    v_a1 bigint; v_a2 bigint; v_b bigint; v_c bigint; v_e bigint; v_f bigint; v_g bigint;
    n_hist bigint; n_missing bigint; n_null bigint;
    loi text := '';
BEGIN
    -- (a1) phân loại nói status_history mà nguồn không mang ngày từ lịch sử/đường chạy.
    SELECT COUNT(*) INTO v_a1
      FROM ({phan_loai}) c JOIN admission_profile p ON p.id = c.profile_id
     WHERE c.phan_loai = 'status_history'
       AND p.first_submitted_source IS DISTINCT FROM 'status_history'
       AND p.first_submitted_source IS DISTINCT FROM 'submit_transition'
       AND p.first_submitted_source IS DISTINCT FROM 'manual';
    -- (a2) nguồn status_history mà ngày khác lần nộp đầu, hoặc phân loại không phải status_history.
    SELECT COUNT(*) INTO v_a2
      FROM admission_profile p JOIN ({phan_loai}) c ON c.profile_id = p.id
     WHERE p.first_submitted_source = 'status_history'
       AND (c.phan_loai IS DISTINCT FROM 'status_history' OR p.first_submitted_at IS DISTINCT FROM c.nop);
    -- (b) có missing_evidence mà migration chạy từ mốc trở đi: TT 05 không còn chứng minh được.
    SELECT COUNT(*) INTO v_b
      FROM admission_profile p
     WHERE p.first_submitted_source = 'missing_evidence'
       AND (run_at AT TIME ZONE '{vn_tz}')::date >= DATE '{cutover}';
    -- (c) trạng thái sau nộp mà nguồn NULL.
    SELECT COUNT(*) INTO v_c
      FROM admission_profile p
     WHERE p.status IN ({post}) AND p.first_submitted_source IS NULL;
    -- (e) thông tư do backfill gán khác công thức ngày VN.
    SELECT COUNT(*) INTO v_e
      FROM admission_profile p
     WHERE p.applicable_circular_source = 'backfill_first_submit'
       AND p.applicable_circular IS DISTINCT FROM ({formula});
    -- (f) hồ sơ chưa từng nộp mà bị backfill gán thông tư (chỉ đặt tay mới được).
    SELECT COUNT(*) INTO v_f
      FROM admission_profile p
     WHERE p.first_submitted_source IS NULL
       AND p.applicable_circular IS NOT NULL
       AND p.applicable_circular_source IS DISTINCT FROM 'manual';
    -- (g) lịch sử có dấu hiệu sau-nộp mà nguồn NULL (hồ sơ đang nháp từng bị trả về).
    SELECT COUNT(*) INTO v_g
      FROM admission_profile p JOIN ({phan_loai}) c ON c.profile_id = p.id
     WHERE p.first_submitted_source IS NULL AND c.dau_hieu IS NOT NULL;

    SELECT COUNT(*) FILTER (WHERE first_submitted_source = 'status_history'),
           COUNT(*) FILTER (WHERE first_submitted_source = 'missing_evidence'),
           COUNT(*) FILTER (WHERE first_submitted_source IS NULL)
      INTO n_hist, n_missing, n_null
      FROM admission_profile;
    RAISE NOTICE USING MESSAGE = 'V3M1 dem: status_history=' || n_hist || ', missing_evidence=' || n_missing
        || ', null=' || n_null;

    IF v_a1 > 0 THEN loi := loi || 'a1=' || v_a1 || ' '; END IF;
    IF v_a2 > 0 THEN loi := loi || 'a2=' || v_a2 || ' '; END IF;
    IF v_b  > 0 THEN loi := loi || 'b='  || v_b  || ' '; END IF;
    IF v_c  > 0 THEN loi := loi || 'c='  || v_c  || ' '; END IF;
    IF v_e  > 0 THEN loi := loi || 'e='  || v_e  || ' '; END IF;
    IF v_f  > 0 THEN loi := loi || 'f='  || v_f  || ' '; END IF;
    IF v_g  > 0 THEN loi := loi || 'g='  || v_g  || ' '; END IF;
    IF loi <> '' THEN
        RAISE EXCEPTION USING MESSAGE = 'V3M1 khoi kiem DO: ' || btrim(loi);
    END IF;
END
$guard$
""".format(
    phan_loai=PHAN_LOAI_SQL,
    vn_tz=VN_TZ_FROZEN,
    cutover=CUTOVER_DATE_FROZEN,
    post=_ds(POST_SUBMIT_FROZEN),
    formula=circular_formula_sql("p.first_submitted_at"),
)

#: Lời gọi khối kiểm bên trong khối PL/pgSQL. ``run_at_sql`` là BIỂU THỨC SQL (migration: ``now()``; test:
#: một mốc cố định dựng bằng ``make_timestamptz``).
def guard_perform_sql(run_at_sql: str = "now()") -> str:
    return "PERFORM pg_temp.v3_m1_guard(%s)" % run_at_sql


DDL_TRUOC_SQL = (
    "ALTER TABLE admission_profile ADD COLUMN first_submitted_at timestamptz",
    "ALTER TABLE admission_profile ADD COLUMN first_submitted_source varchar(24)",
    "ALTER TABLE admission_profile ADD COLUMN applicable_circular varchar(16)",
    "ALTER TABLE admission_profile ADD COLUMN applicable_circular_source varchar(32)",
    "ALTER TABLE admission_profile ADD COLUMN applicable_circular_set_at timestamptz",
    "ALTER TABLE admission_profile ADD COLUMN applicable_circular_set_by_id integer",
    "ALTER TABLE admission_profile ADD CONSTRAINT fk_admission_profile_circular_set_by "
    'FOREIGN KEY (applicable_circular_set_by_id) REFERENCES "user"(id) ON DELETE SET NULL',
) + tuple(
    "ALTER TABLE admission_profile ADD CONSTRAINT %s CHECK (%s)" % (ten, bt)
    for ten, bt in CHECKS_TRUOC_BACKFILL.items()
)
DDL_SAU_SQL = (
    "ALTER TABLE admission_profile ADD CONSTRAINT %s CHECK (%s)" % (CK4_NAME, CK4_SQL),
    "ALTER TABLE admission_profile ADD CONSTRAINT %s CHECK (%s)" % (CK5_NAME, CK5_SQL),
)


def build_upgrade_do(*, ddl_truoc, backfill, ddl_sau, run_at_sql: str = "now()") -> str:
    """Ghép MỘT câu ``DO``: DDL trước → backfill → tạo + gọi khối kiểm → DDL sau.

    Test dựng lại câu này với ``ddl_truoc=()`` (CSDL test đã có cột qua ``create_all()``) để chứng minh
    RAISE lùi cả backfill.
    """
    than = list(ddl_truoc) + list(backfill) + [GUARD_SQL, guard_perform_sql(run_at_sql)] + list(ddl_sau)
    return "DO $m1$\nBEGIN\n" + ";\n".join(c.strip() for c in than) + ";\nEND\n$m1$"


UPGRADE_DO_SQL = build_upgrade_do(ddl_truoc=DDL_TRUOC_SQL, backfill=BACKFILL_SQL, ddl_sau=DDL_SAU_SQL)

#: Downgrade chặn khi còn thay đổi tay — các giá trị khác dựng lại được từ lịch sử, giá trị tay thì không.
#: Kiểm và bỏ cột trong CÙNG một câu ``DO`` (AUTOCOMMIT — xem đầu tệp).
DOWNGRADE_DO_SQL = """
DO $dg$
DECLARE n bigint;
BEGIN
    SELECT COUNT(*) INTO n FROM admission_profile
     WHERE first_submitted_source = 'manual' OR applicable_circular_source = 'manual';
    IF n > 0 THEN
        RAISE EXCEPTION USING MESSAGE = 'V3M1 downgrade bi chan: ' || n
            || ' ho so co gia tri manual — bo cot se mat thay doi tay';
    END IF;
    ALTER TABLE admission_profile DROP CONSTRAINT {ck5};
    ALTER TABLE admission_profile DROP CONSTRAINT {ck4};
{drop_ck}
    ALTER TABLE admission_profile DROP CONSTRAINT fk_admission_profile_circular_set_by;
    ALTER TABLE admission_profile DROP COLUMN applicable_circular_set_by_id;
    ALTER TABLE admission_profile DROP COLUMN applicable_circular_set_at;
    ALTER TABLE admission_profile DROP COLUMN applicable_circular_source;
    ALTER TABLE admission_profile DROP COLUMN applicable_circular;
    ALTER TABLE admission_profile DROP COLUMN first_submitted_source;
    ALTER TABLE admission_profile DROP COLUMN first_submitted_at;
END
$dg$
""".format(
    ck5=CK5_NAME,
    ck4=CK4_NAME,
    drop_ck="\n".join(
        "    ALTER TABLE admission_profile DROP CONSTRAINT %s;" % ten for ten in reversed(list(CHECKS_TRUOC_BACKFILL))
    ),
)


def upgrade() -> None:
    # MỘT lệnh duy nhất — xem "MỘT CÂU DO DUY NHẤT" ở đầu tệp.
    op.execute(UPGRADE_DO_SQL)


def downgrade() -> None:
    # Kiểm hàng ``manual`` và bỏ cột trong CÙNG một câu ``DO``.
    op.execute(DOWNGRADE_DO_SQL)
