"""CHECK `committed ⟺ có mã phiếu` với `payment_ids` KHÔNG phải mảng.

Ràng buộc hỏi hai câu trong một biểu thức: ``payment_ids`` có phải mảng không,
và nếu phải thì có rỗng không. ``jsonb_array_length`` gặp scalar là **lỗi
runtime** (SQLSTATE 22023), không phải NULL — nên thứ tự hai câu ấy là vấn đề.

⚠️ **Đã đo, và kết quả bác bỏ giả định ban đầu.** Bản đầu của ca này được viết
với niềm tin rằng bản ``AND`` nối tiếp cũng vỡ ở CHECK. Phép kiểm ngược nói
không:

===========================================  ================
ngữ cảnh, bản ``AND``, dữ liệu scalar         kết quả
===========================================  ================
CHECK — ``ADD CONSTRAINT`` trên bảng có sẵn   không vỡ
CHECK — ``INSERT`` dòng mới                   không vỡ
WHERE — 50k hàng, sau ``ANALYZE``             **vỡ (22023)**
===========================================  ================

PostgreSQL short-circuit ``AND`` trái→phải trong một *expression*; chỗ nó không
hứa thứ tự là *qual* — đúng ngữ cảnh mà backfill của ``imp2axis20260807`` đã vỡ
thật. Vậy ``CASE`` ở CHECK là phòng thủ và nhất quán, **không** phải bản vá cho
một lỗi tái hiện được: tài liệu không hứa gì, và biểu thức này bị sao chép sang
qual một lần rồi (chính backfill).

Hệ quả cho việc đọc ca dưới đây: **chúng KHÔNG phân biệt hai bản DDL** — bộ này
xanh đủ 11/11 trên cả bản ``AND``. Thứ phân biệt là ca lock-in văn bản
``test_CHECK_committed_cung_dung_CASE`` ở
``tests/unit/test_imp2axis_backfill_lockin.py``. Ca ở đây khoá HÀNH VI: dòng
hợp lệ có ``payment_ids`` scalar phải đi qua, dòng ``committed`` không có mã
phiếu phải bị chặn — và ca cuối khoá chính tiền đề trên bằng số đo.

Phân biệt LOẠI lỗi là nội dung, không phải trang trí: cả hai đường đều làm
``INSERT`` hỏng, nên ``pytest.raises(Exception)`` sẽ xanh kể cả khi ràng buộc
sai. Chỉ SQLSTATE mới tách "bị từ chối vì đúng luật" (23514) khỏi "vỡ vì đọc
kiểu sai" (22023).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database import engine

pytestmark = pytest.mark.asyncio

#: Ràng buộc bị vi phạm — dòng bị từ chối vì ĐÚNG luật nghiệp vụ.
CHECK_VIOLATION = "23514"
#: ``cannot get array length of a scalar`` — ràng buộc đọc kiểu sai.
INVALID_PARAMETER_VALUE = "22023"


def _sqlstate(exc: BaseException) -> str | None:
    """Moi SQLSTATE ra khỏi lớp bọc của SQLAlchemy/asyncpg."""
    goc = getattr(exc, "orig", exc)
    ma = getattr(goc, "sqlstate", None) or getattr(goc, "pgcode", None)
    if ma is None:
        ma = getattr(getattr(goc, "__cause__", None), "sqlstate", None)
    return ma


@pytest_asyncio.fixture
async def lo(setup_test_database):
    """Một lô rỗng trong transaction sẽ bị cuộn lại — không để lại gì."""
    async with engine.connect() as conn:
        tx = await conn.begin()
        try:
            batch_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO payment_import_batch
                            (academic_year, semester_no, file_name, file_sha256)
                        VALUES (2026, 1, 'check-jsonb.xlsx', :sha)
                        RETURNING id
                        """
                    ),
                    {"sha": uuid.uuid4().hex + uuid.uuid4().hex[:32]},
                )
            ).scalar_one()
            yield conn, batch_id
        finally:
            await tx.rollback()


async def _chen(conn, batch_id: int, row_no: int, commit_status: str, payment_ids):
    """Chèn một dòng trong savepoint riêng để lỗi không giết transaction ngoài."""
    sp = await conn.begin_nested()
    try:
        await conn.execute(
            text(
                """
                INSERT INTO payment_import_row
                    (batch_id, row_no, raw, validation_status, commit_status,
                     payment_ids)
                VALUES (:b, :r, '{}'::jsonb, 'matched', :cs,
                        CAST(:pi AS jsonb))
                """
            ),
            {"b": batch_id, "r": row_no, "cs": commit_status, "pi": payment_ids},
        )
        await sp.commit()
    except Exception:
        await sp.rollback()
        raise


# ── Dòng HỢP LỆ có `payment_ids` không phải mảng: phải ĐI QUA ───────────────
# Đây là ca duy nhất phân biệt được hai bản DDL. Ba dạng dưới đây đều là
# "không có mã phiếu nào" nên `commit_status='pending'` là nhất quán, và ràng
# buộc không có lý do gì để chặn.
@pytest.mark.parametrize(
    "nhan, gia_tri",
    [
        ("object rỗng", "{}"),
        ("object có khoá", '{"ids": [1]}'),
        ("scalar số", "5"),
        ("scalar chuỗi", '"abc"'),
        ("scalar bool", "true"),
        ("null JSON", "null"),
    ],
)
async def test_pending_voi_payment_ids_khong_phai_mang_van_chen_duoc(
    lo, nhan: str, gia_tri: str
):
    conn, batch_id = lo
    await _chen(conn, batch_id, row_no=1, commit_status="pending", payment_ids=gia_tri)

    con_lai = (
        await conn.execute(
            text(
                "SELECT jsonb_typeof(payment_ids) FROM payment_import_row "
                "WHERE batch_id = :b AND row_no = 1"
            ),
            {"b": batch_id},
        )
    ).scalar_one()
    assert con_lai is not None, f"dòng {nhan} không được ghi"


# ── Cùng dữ liệu ấy nhưng khai `committed`: phải bị chặn VÌ ĐÚNG LUẬT ───────
@pytest.mark.parametrize(
    "nhan, gia_tri",
    [
        ("object rỗng", "{}"),
        ("scalar số", "5"),
        ("mảng rỗng", "[]"),
        ("NULL", None),
    ],
)
async def test_committed_khong_co_ma_phieu_bi_chan_dung_bang_check(
    lo, nhan: str, gia_tri
):
    conn, batch_id = lo
    with pytest.raises(Exception) as loi:
        await _chen(
            conn, batch_id, row_no=2, commit_status="committed", payment_ids=gia_tri
        )

    ma = _sqlstate(loi.value)
    assert ma == CHECK_VIOLATION, (
        f"dòng 'committed' với payment_ids={nhan} phải bị CHECK từ chối "
        f"({CHECK_VIOLATION}), nhưng nhận SQLSTATE {ma}. "
        f"{INVALID_PARAMETER_VALUE} nghĩa là ràng buộc đang gọi "
        "`jsonb_array_length` trước khi kiểm kiểu — cùng dòng dữ liệu ấy ở "
        "trạng thái `pending` sẽ bị từ chối oan."
    )


async def test_committed_co_ma_phieu_that_van_di_qua(lo):
    """Ca dương — giữ cho hai ca trên không xanh nhờ chặn mọi thứ."""
    conn, batch_id = lo
    await _chen(
        conn, batch_id, row_no=3, commit_status="committed", payment_ids="[1, 2]"
    )
    so = (
        await conn.execute(
            text(
                "SELECT jsonb_array_length(payment_ids) FROM payment_import_row "
                "WHERE batch_id = :b AND row_no = 3"
            ),
            {"b": batch_id},
        )
    ).scalar_one()
    assert so == 2


# ── Tiền đề của quyết định dùng CASE, đo trực tiếp ──────────────────────────
# Hai ca dưới không chạm bảng thật. Chúng khoá thứ mà mọi ca trên đứng lên:
# ngữ cảnh nào làm `AND` nối tiếp vỡ, và `CASE` có sống ở ngữ cảnh ấy không.
# Không có chúng thì "dùng CASE" chỉ là một niềm tin được chép lại qua các
# comment, và biểu thức này ĐÃ bị sao chép sang ngữ cảnh nguy hiểm một lần rồi.
_SQL_DUNG_BANG_THU = """
CREATE TEMP TABLE thu_jsonb AS
SELECT CASE
         WHEN g % 3 = 0 THEN '{}'::jsonb
         WHEN g % 3 = 1 THEN to_jsonb(g)
         ELSE jsonb_build_array(g)
       END AS pi
FROM generate_series(1, 50000) g
"""


@pytest_asyncio.fixture
async def bang_thu(setup_test_database):
    """50k hàng trộn ba dạng jsonb, đã ANALYZE — đủ để planner tự chọn thứ tự."""
    async with engine.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(text(_SQL_DUNG_BANG_THU))
            await conn.execute(text("ANALYZE thu_jsonb"))
            yield conn
        finally:
            await tx.rollback()


async def test_AND_noi_tiep_VO_khi_bieu_thuc_nam_o_qual(bang_thu):
    """Đây là ngữ cảnh đã vỡ thật — và là lý do quy tắc tồn tại.

    Ở *qual* (WHERE), planner tách các vế `AND` thành danh sách và sắp lại theo
    chi phí ước lượng, nên `jsonb_array_length` chạy được trước phép kiểm kiểu.

    Ca này đỏ nghĩa là tiền đề đã đổi (PostgreSQL thôi sắp lại, hoặc thống kê
    khác đi) — **đọc lại quyết định, đừng gỡ ca**. Quy tắc "luôn dùng CASE với
    `payment_ids`" mất căn cứ thực nghiệm ngay khi ca này thôi đỏ được.
    """
    sp = await bang_thu.begin_nested()
    try:
        with pytest.raises(Exception) as loi:
            await bang_thu.execute(
                text(
                    "SELECT count(*) FROM thu_jsonb "
                    "WHERE pi IS NOT NULL AND jsonb_typeof(pi) = 'array' "
                    "AND jsonb_array_length(pi) > 0"
                )
            )
    finally:
        await sp.rollback()

    assert _sqlstate(loi.value) == INVALID_PARAMETER_VALUE, (
        "bản `AND` nối tiếp không còn vỡ ở qual (SQLSTATE "
        f"{_sqlstate(loi.value)}). Tiền đề của quy tắc dùng CASE đã đổi."
    )


async def test_CASE_song_o_dung_ngu_canh_da_lam_AND_vo(bang_thu):
    """Và bản đang dùng phải sống ở chính chỗ bản kia chết."""
    so = (
        await bang_thu.execute(
            text(
                "SELECT count(*) FROM thu_jsonb WHERE CASE "
                " WHEN pi IS NULL THEN false "
                " WHEN jsonb_typeof(pi) <> 'array' THEN false "
                " ELSE jsonb_array_length(pi) > 0 "
                "END"
            )
        )
    ).scalar_one()
    # g % 3 = 2 → mảng một phần tử: g = 2, 5, …, 50000 ⇒ 16667 hàng.
    assert so == 16667, f"đếm được {so}, phải là 16667 hàng mảng-không-rỗng"
