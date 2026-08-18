"""Nguồn định danh duy nhất cho fixture test — KHÔNG dùng đồng hồ.

Vì sao tệp này tồn tại
======================

Nhiều fixture từng sinh định danh bằng::

    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000

Biểu thức đó **quay vòng mỗi 1.000 giây**. Một lượt pytest dài hơn 1.000 giây thì
hai fixture chạy cách nhau đúng một chu kỳ sẽ nhận **cùng một** ``ts``, và mọi cột
``unique`` dẫn xuất từ nó đụng nhau.

Đã xảy ra thật trên CI (PR #564, attempt 1)::

    FAILED tests/api/test_phase3_pr3c_routers_integration.py
           ::test_capacity_check_null_admit_quota_pass_through
    UniqueViolationError: duplicate key value violates unique constraint
    "uq_citizen_academic_year"
    =========== 1 failed, 908 passed in 2184.44s (0:36:24) ===========

Lượt đó dài 2.184s ⇒ quay **2,18 vòng**. Chạy lại y nguyên commit thì xanh
(909 passed) — đặc trưng của flake phụ thuộc thời điểm.

Bốn cột ``unique`` cùng chịu rủi ro này, không chỉ một:

===============================  ============================================
Cột                              Ràng buộc
===============================  ============================================
``admission_profile.citizen_id`` ``uq_citizen_academic_year`` (+ academic_year)
``admission_method.code``        ``unique=True``
``subject.code``                 ``unique=True``
``subject_group.code``           ``unique=True`` · ``String(10)``
===============================  ============================================

Ba cách KHÔNG dùng
==================

* **``random``** — giảm xác suất, không loại bỏ. Một guard chỉ "thường đúng" là
  một guard sẽ đỏ vào ngày xấu nhất.
* **``sleep``** — làm chậm bộ test để né một lỗi thiết kế; và vẫn hỏng khi hai
  tiến trình chạy song song.
* **thêm chữ số vào ``ts``** — vẫn là đồng hồ, chỉ đẩy chu kỳ ra xa hơn.

Cách dùng
=========

Nguồn duy nhất là **sequence của PostgreSQL** — nó không bao giờ trả lại cùng
một giá trị, kể cả khi giao dịch bị rollback, kể cả khi chạy song song::

    khoa = await khoa_duy_nhat(s)          # trước khi tạo hàng nào
    method = models.AdmissionMethod(code=ma_tu_khoa("M3C", khoa, 50), ...)

Khi hàng đã ``flush()`` thì dùng thẳng khóa chính của nó — cùng nguồn, khỏi tốn
một vòng truy vấn::

    s.add(lead); await s.flush()
    profile = models.AdmissionProfile(citizen_id=citizen_id_tu_khoa(lead.id), ...)
"""
from __future__ import annotations

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "khoa_duy_nhat",
    "citizen_id_tu_khoa",
    "ma_tu_khoa",
    "sdt_tu_khoa",
    "CITIZEN_ID_DO_DAI",
]

#: ``admission_profile.citizen_id`` là ``String(12)``.
CITIZEN_ID_DO_DAI = 12

_SEQ = "SELECT nextval(pg_get_serial_sequence('lead', 'id'))"


async def khoa_duy_nhat(s: AsyncSession) -> int:
    """Một số nguyên **duy nhất tuyệt đối**, lấy từ sequence của PostgreSQL.

    Dùng khi cần định danh **trước** lúc có hàng nào được ``flush()``.

    Vì sao là sequence chứ không phải đồng hồ: ``nextval`` không bao giờ trả lại
    cùng một giá trị trong vòng đời một cơ sở dữ liệu — không phụ thuộc lượt chạy
    dài bao lâu, không phụ thuộc hai tiến trình chạy song song, và không quay vòng.

    Sequence của ``lead.id`` được mượn làm nguồn đếm chung. Tiêu tốn vài id lead là
    vô hại trong test, và giữ mọi định danh trong **một** không gian số.
    """
    return int((await s.execute(sa_text(_SEQ))).scalar_one())


def citizen_id_tu_khoa(khoa: int, nhom: str = "0") -> str:
    """``citizen_id`` 12 chữ số, suy ra một-một từ ``khoa``.

    :param khoa: khóa duy nhất — ``lead.id`` đã flush, hoặc `khoa_duy_nhat`.
    :param nhom: một chữ số phân nhóm, chỉ để đọc log cho dễ; **không** phải
        nguồn duy nhất. Hai fixture cùng ``nhom`` mà khác ``khoa`` vẫn khác nhau.

    Bố cục: ``<nhom:1><khoa:11>`` = đúng 12 chữ số, khớp ``String(12)``.
    """
    if not (len(nhom) == 1 and nhom.isdigit()):
        raise ValueError("nhom phải là đúng MỘT chữ số, nhận: %r" % (nhom,))
    if khoa < 0:
        raise ValueError("khoa phải không âm, nhận: %r" % (khoa,))
    ra = f"{nhom}{khoa:011d}"
    if len(ra) != CITIZEN_ID_DO_DAI:
        # khoa vượt 11 chữ số — không xảy ra với sequence int4/int8 trong test,
        # nhưng cắt ngắn ở đây sẽ phá tính duy nhất nên phải nổ thay vì im lặng.
        raise ValueError(
            "khoa=%d quá lớn: citizen_id dài %d ký tự, cần đúng %d"
            % (khoa, len(ra), CITIZEN_ID_DO_DAI)
        )
    return ra


def ma_tu_khoa(tien_to: str, khoa: int, do_dai_toi_da: int) -> str:
    """Mã (``code``) duy nhất, dạng ``<tien_to><khoa>``, không vượt độ dài cột.

    Cắt ngắn sẽ phá tính duy nhất nên hàm **nổ** thay vì cắt — đó là điểm khác
    với ``f"...{ts}"[:20]`` cũ, vốn im lặng vứt bớt chữ số.
    """
    ra = f"{tien_to}{khoa}"
    if len(ra) > do_dai_toi_da:
        raise ValueError(
            "mã %r dài %d ký tự, vượt giới hạn %d — rút ngắn tien_to thay vì cắt "
            "đuôi (cắt đuôi làm mất tính duy nhất)" % (ra, len(ra), do_dai_toi_da)
        )
    return ra


def sdt_tu_khoa(dau_so: str, khoa: int) -> str:
    """Số điện thoại 10 chữ số: ``<dau_so:3><khoa:7>``.

    ``lead.phone`` không có ràng buộc unique, nhưng vẫn suy từ cùng một nguồn để
    log đọc được và để không còn chỗ nào trong tệp phụ thuộc đồng hồ.
    """
    if not (len(dau_so) == 3 and dau_so.isdigit()):
        raise ValueError("dau_so phải là đúng BA chữ số, nhận: %r" % (dau_so,))
    return f"{dau_so}{khoa % 10_000_000:07d}"
