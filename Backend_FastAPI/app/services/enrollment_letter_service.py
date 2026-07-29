# app/services/enrollment_letter_service.py
"""
Service for issuing the official "Giấy báo nhập học" PDF.

Flow: gather + VALIDATE the data (gate trạng thái + required fields + the
profile's active HK1 tuition Fee), render the PDF off the event loop, persist
the bytes to disk (atomic + sha256 + retention) and record an ``EnrollmentLetter``
issuance row. The router commits; this service only flushes (arch rule).

SỐ TIỀN in trên giấy lấy từ BẢNG THU của Nhà trường
(``constants.enrollment_letter.TUITION_SCHEDULE``, tra theo mã ngành), KHÔNG
dẫn xuất từ Fee và **KHÔNG trừ phần thí sinh đã nộp trước** (quyết định nghiệp
vụ 20-07: mọi giấy cùng ngành in cùng một bảng thu, việc đối trừ tiền giữ chỗ
làm tại quầy). Fee vẫn BẮT BUỘC phải có và tổng của nó phải KHỚP bảng thu —
lệch thì không phát giấy, vì khi đó hai nguồn đang nói hai số khác nhau.

NGÀNH + TRÌNH ĐỘ resolve theo NGUYỆN VỌNG rồi ĐỐI CHIẾU với ngành mà tiền đã
tính theo (xem ``_resolve_admitted_major``): giấy ghi "Đã trúng tuyển ngành X"
nên X phải là nguyện vọng, và lệch giữa hai nguồn thì KHÔNG phát giấy. Thiếu
Fee (hoặc bất kỳ trường bắt buộc nào) → lỗi "thiếu dữ liệu" thay vì phát ra một
tờ giấy khuyết.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import structlog
from anyio import to_thread
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.constants import enrollment_letter as C
from app.models.finance.fee import FeeStatusEnum, FeeTypeEnum
from app.services.admission_pdf_service import render_enrollment_letter
from app.utils.address_format import format_permanent_address
from app.utils.admission_status import is_enrollment_letter_eligible
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.sms_export import STAGING_PREFIX, sha256_file

log = structlog.get_logger(__name__)


async def _get_active_hk1_tuition_fee(db, profile_id: int):
    """Return the profile's single ACTIVE HK1 tuition Fee (or None).

    Active = ``status != cancelled`` (a unique partial index guarantees at most
    one such fee per profile for tuition — see ``Fee.__table_args__``). Eager
    loads ``resolved_major`` so the ngành name is available without a lazy load.

    ``populate_existing=True`` là BẮT BUỘC, không phải tối ưu. Hàm này được gọi
    HAI lần trong cùng một session: lần đầu ở ``build_letter_data``, lần sau ở
    ``issue_enrollment_letter`` để kiểm lại số tiền sau khi đã có khoá. Mặc định
    SQLAlchemy trả lại chính instance trong identity map và GIỮ NGUYÊN các thuộc
    tính đã nạp — nên lần gọi thứ hai đọc lại đúng giá trị cũ và phép so
    "tiền bây giờ vs tiền lúc render" thành so một giá trị với chính nó: guard
    không bao giờ kích hoạt được. (Ca Fee bị huỷ vẫn bắt được vì SQL lọc
    ``status != cancelled`` nên trả None/row khác — chỉ ca SỬA final_amount tại
    chỗ là lọt, và đó đúng là ca giấy in sai số tiền.) Cùng lớp lỗi với
    ``get_for_update`` không re-read khi instance đã nằm trong session.
    """
    stmt = (
        select(models.Fee)
        .where(
            models.Fee.admission_profile_id == profile_id,
            models.Fee.fee_type == FeeTypeEnum.tuition.value,
            models.Fee.semester_no == 1,
            models.Fee.status != FeeStatusEnum.cancelled.value,
        )
        .options(selectinload(models.Fee.resolved_major))
        .order_by(models.Fee.created_at.desc())
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def supersede_current_letter(
    db, profile_id: int, *, reason: str
) -> int:
    """Đóng dấu ``superseded_at`` cho bản giấy báo HIỆN HÀNH của hồ sơ (nếu có).

    Dùng khi ĐỔI NGÀNH (``reprice_for_major_change``): giấy cũ ghi ngành + số
    tiền CŨ, không còn hiệu lực. Chỉ GIẢI PHÓNG slot "bản hiện hành" (partial
    unique index ``ix_enrollment_letter_current`` trên ``profile_id WHERE
    superseded_at IS NULL``) — KHÔNG chèn bản mới (bản mới phát lại sau khi kế
    toán confirm, qua ``issue_enrollment_letter``). File PDF cũ KHÔNG bị xoá:
    route download cố ý không lọc ``superseded_at`` (đường phục hồi/đối chiếu).

    Reuse ĐÚNG câu UPDATE mold của ``issue_enrollment_letter`` block (a). Trả về
    số bản vừa đóng dấu (0 = hồ sơ chưa từng phát giấy → no-op, không lỗi).
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(models.EnrollmentLetter)
        .where(
            models.EnrollmentLetter.profile_id == profile_id,
            models.EnrollmentLetter.superseded_at.is_(None),
        )
        .values(superseded_at=now)
    )
    n = result.rowcount or 0
    if n:
        log.info(
            "enrollment_letter_superseded",
            profile_id=profile_id,
            superseded_count=n,
            reason=reason,
        )
    return n


async def _resolve_admitted_major(db, profile, fee):
    """Ngành + trình độ IN LÊN GIẤY, lấy theo NGUYỆN VỌNG (không phải cột
    snapshot trên Fee).

    Giấy in nguyên văn "Đã trúng tuyển ngành: X" nên X phải là nguyện vọng, và
    học phí phải được tính theo ĐÚNG nguyện vọng đó. ``resolve_fee_academic_info``
    là single-source-of-truth cho luật này (dùng chung với fees/invoices):

      * đã công bố kết quả ⇒ NV có ``decision='admitted'`` — có thể KHÔNG phải
        NV1, và in NV1 lúc đó là sai sự thật;
      * chưa công bố + đúng 1 NV ⇒ chính NV đó (= NV1, đường prepay/giữ chỗ ở
        ``submitted`` mà gate phát giấy đang mở);
      * ≥2 NV còn pending, hoặc 0 NV ⇒ fail-closed.

    Vì sao KHÔNG đọc thẳng ``fee.resolved_major``: cột đó chỉ được ghi lại khi
    resnapshot chạy, nên có thể trỏ ngành CŨ nếu cấu hình đổi sau lúc tính phí —
    repo đã biết trước rủi ro này và log ``fee_resolved_major_drift``
    (``fee_calculation_service.py``). Ở đây ta resolve LẠI từ nguyện vọng rồi
    ĐỐI CHIẾU với ngành mà tiền đã tính theo; lệch nhau thì KHÔNG phát giấy, vì
    một tờ giấy ghi ngành A kèm học phí của ngành B là văn bản tự mâu thuẫn.

    Trả về ``(major_name, degree_level, offering_type|None, major_code|None)``.
    ``major_code`` là khoá tra ``TUITION_SCHEDULE`` (bảng thu học phí). Ném
    ``ValidationError`` với lý do đọc được nếu không xác định được ngành, Fee
    chưa gắn ngành, hoặc hai nguồn lệch nhau.
    """
    from app.services.fee_calculation_service import resolve_fee_academic_info
    from app.utils.exceptions import BadRequest

    # --- Nguồn 1 (ưu tiên): nguyện vọng ---
    live = None
    try:
        academic_info = await resolve_fee_academic_info(db, profile)
    except BadRequest as exc:
        # Hồ sơ legacy thiếu offering_admission_config / applied_rules, hoặc
        # multi-NV chưa công bố kết quả: KHÔNG chặn ngay ở đây — còn snapshot
        # trên Fee (nguồn 2) là ngành mà TIỀN thực sự đã tính theo.
        #
        # PHẢI LOG: resolve_fee_academic_info ném BadRequest ở đúng những ca nó
        # cố ý FAIL-CLOSED ("≥2 NV chưa công bố", "nhiều hơn 1 NV trúng tuyển" =
        # dữ liệu lỗi). Nuốt im lặng nghĩa là ta phát giấy "Đã trúng tuyển ngành
        # X" theo snapshot cũ cho một hồ sơ mà hệ thống vừa nói là chưa xác định
        # được ngành — không dấu vết nào để hậu kiểm.
        academic_info = None
        log.warning(
            "enrollment_letter.major_resolve_fell_back_to_fee_snapshot",
            profile_id=getattr(profile, "id", None),
            reason=str(exc),
        )

    if academic_info is not None:
        row = (
            await db.execute(
                select(
                    models.MajorProgram.id,
                    models.MajorProgram.name,
                    models.MajorProgram.degree_level,
                    # Hệ đào tạo nằm ngay trong chuỗi join này — trước đây bị
                    # hard-code hằng "Chính quy" với lý do hoãn sang v2, khiến
                    # thí sinh hệ Liên thông / Vừa làm vừa học nhận giấy chính
                    # thức ghi sai hệ.
                    models.ProgramOffering.offering_type,
                    # Mã ngành = khoá tra bảng thu học phí (TUITION_SCHEDULE).
                    models.MajorProgram.code,
                )
                .select_from(models.OfferingAcademicInfo)
                .join(
                    models.ProgramOffering,
                    models.ProgramOffering.id
                    == models.OfferingAcademicInfo.offering_id,
                )
                .join(
                    models.MajorProgram,
                    models.MajorProgram.id == models.ProgramOffering.program_id,
                )
                .where(models.OfferingAcademicInfo.id == academic_info.id)
            )
        ).first()
        if row is not None and row[1]:
            live = row

    # --- Nguồn 2 (đối chứng / dự phòng): snapshot đã đóng băng trên Fee ---
    snap_major = fee.resolved_major if fee is not None else None
    snap = (
        (
            snap_major.id,
            snap_major.name,
            fee.resolved_degree_level,
            None,
            snap_major.code,
        )
        if snap_major and snap_major.name
        else None
    )

    if live is None and snap is None:
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — chưa xác định được ngành trúng "
            "tuyển (hồ sơ chưa chọn nguyện vọng, hoặc học phí chưa gắn ngành). "
            "Hãy tính lại học phí trước khi phát giấy."
        )

    # Fee CÓ nhưng chưa gắn ngành ⇒ không đối chiếu được tiền↔ngành. Đây từng
    # là lỗi "thiếu dữ liệu" chặn cứng; bỏ đi thì giấy in ngành resolve được
    # kèm số tiền của một Fee KHÔNG BIẾT tính theo ngành nào — đúng thứ hàm này
    # tồn tại để chặn. Giữ fail-closed.
    if snap is None:
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — khoản học phí chưa gắn ngành nên "
            "không đối chiếu được với nguyện vọng trúng tuyển. Hãy tính lại học "
            "phí trước khi phát giấy."
        )

    # Cả hai cùng có nhưng LỆCH ⇒ tiền và ngành đang nói hai chuyện khác nhau.
    # Một tờ giấy ghi ngành A kèm học phí của ngành B là văn bản tự mâu thuẫn,
    # nên fail-closed thay vì chọn bừa một bên.
    if live and live[0] != snap[0]:
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — nguyện vọng trúng tuyển là "
            f"'{live[1]}' nhưng học phí đang tính theo ngành '{snap[1]}'. "
            f"Hãy tính lại học phí cho đúng ngành trước khi phát giấy."
        )

    chosen = live or snap
    return chosen[1], chosen[2], chosen[3], chosen[4]


async def _resolve_officer(db, profile) -> tuple[str, str]:
    """(tên, số điện thoại) officer đang phụ trách — cho dòng "Điện thoại hỗ
    trợ" trên giấy.

    Đi qua ``lead.assigned_officer_id`` chứ không qua trường denormalize
    ``assigned_officer_name``: trường đó chỉ được populate ở tầng response, nên
    rỗng khi service chạy độc lập (Celery, script).

    KHÔNG chặn phát giấy khi thiếu — đây là thông tin liên hệ THÊM và hotline
    chung vẫn được in. Trả chuỗi rỗng để renderer tự bỏ phần đó.
    """
    row = (
        await db.execute(
            select(models.User.full_name, models.User.phone_number)
            .select_from(models.Lead)
            .join(models.User, models.User.id == models.Lead.assigned_officer_id)
            .where(models.Lead.id == profile.lead_id)
        )
    ).first()
    if row is None:
        return "", ""
    return (row[0] or "").strip(), (row[1] or "").strip()


def _vnd(amount) -> str:
    """9200000 → "9.200.000". Dấu chấm phân nhóm như cách viết tiền của VN —
    ``f"{n:,}"`` cho ra "9,200,000", đọc như số kiểu Anh ngay trong một thông
    báo tiếng Việt mà officer phải đối chiếu với màn Học phí."""
    return f"{int(amount):,}".replace(",", ".")


def _resolve_tuition_schedule(
    major_code, major_name, degree_level, fee, base_total: int, payable_total: int
) -> dict:
    """Tra bảng thu học phí kỳ I theo MÃ NGÀNH và đối chiếu với Fee.

    FAIL-CLOSED ở cả bốn cửa (quyết định 19-07). Giấy báo là văn bản chính thức
    có chữ ký Hiệu trưởng, nên "không phát được, báo lỗi rõ" luôn tốt hơn "phát
    ra một tờ ghi sai số tiền":

    1. Ngành chưa có trong bảng thu (ngành mới mở, hoặc mã lệch) — không có mức
       đợt nào để in.
    2. Fee thuộc năm học khác năm của bảng thu — bảng thu chỉ đúng cho MỘT mùa,
       in mức của mùa này lên hồ sơ mùa khác là sai.
    3. Học phí GỐC trong hệ thống lệch ``hk1`` của bảng thu.
    4. Số PHẢI NỘP lệch mức của bảng thu.

    🔴 Vì sao phải tách 3 và 4 (sửa 29-07). Bản cũ so ``hk1`` với **một** con số
    là ``fee.final_amount``, tức ngầm giả định *"phải nộp = học phí gốc"*. Giả
    định đó đúng cho tới khi hệ thống có hồ sơ ĐẦU TIÊN được áp chính sách giảm:
    khi ấy ``final_amount`` tụt xuống còn phần phải nộp, lệch ``hk1``, và cửa 3
    chặn sạch mọi hồ sơ của ngành có ưu đãi — dù bảng thu đã khai chính ưu đãi
    đó (``discount_percent: 30`` ở sáu ngành cao đẳng) và số phải nộp KHỚP đúng
    ``first``. Ngày 29-07 điều này xảy ra thật trên prod với 74 hồ sơ.

    Bảng thu mô hình hoá ưu đãi bằng cách GIỮ giá gốc rồi hạ mức đợt:
    ``hk1`` là giá gốc · ``first`` = phải nộp (``hk1 × (100−discount_percent)%``
    khi có ưu đãi) · ``second`` = 0. Nên đối chiếu đúng phải là **hai** phép:
    gốc↔gốc và phải-nộp↔mức-đợt. Cách này còn CHẶT HƠN bản cũ: nó bắt được cả
    ca giá gốc sai lẫn ca mức giảm sai, thay vì chỉ so được một con số.

    Hồ sơ được giảm/chỉnh TAY riêng vẫn bị chặn ở cửa 4 (số phải nộp không rơi
    vào mức nào của bảng thu) — đúng như trước, vì giấy in bảng thu CHUNG thì
    không phản ánh được khoản chỉnh riêng của một người.

    Trả về dict dòng bảng thu (``hk1``/``discount_percent``/``first``/``second``).
    """
    row = C.TUITION_SCHEDULE.get((major_code or "").strip())
    if row is None:
        log.warning(
            "enrollment_letter.tuition_schedule_missing",
            major_code=major_code,
            major_name=major_name,
            degree_level=degree_level,
        )
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — ngành '{major_name}' "
            f"({degree_level}, mã {major_code or 'chưa có'}) chưa có trong bảng "
            f"thu học phí của giấy báo. Hãy báo bộ phận kỹ thuật bổ sung bảng "
            f"thu trước khi phát giấy."
        )

    year = getattr(fee, "academic_year", None)
    if year != C.TUITION_SCHEDULE_ACADEMIC_YEAR:
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — học phí của hồ sơ thuộc năm học "
            f"{year or 'không xác định'}, trong khi bảng thu trên giấy báo là "
            f"của mùa tuyển sinh {C.TUITION_SCHEDULE_ACADEMIC_YEAR}. Hãy báo bộ "
            f"phận kỹ thuật cập nhật bảng thu."
        )

    if base_total != row["hk1"]:
        log.warning(
            "enrollment_letter.tuition_amount_drift",
            major_code=major_code,
            fee_base_total=base_total,
            schedule_total=row["hk1"],
        )
        # ⚠️ KHÔNG khuyên "hãy tính lại học phí" ở đây. Lệch số rất có thể là do
        # hồ sơ được giảm/chỉnh học phí THỦ CÔNG (applied_discount
        # source='manual_discount') — bấm tính lại sẽ XOÁ MẤT chính khoản chỉnh
        # tay đó. Lệch ở đây là việc của người, không phải việc của một nút bấm.
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — học phí gốc kỳ I của hồ sơ là "
            f"{_vnd(base_total)} đồng nhưng bảng thu ngành '{major_name}' ghi "
            f"{_vnd(row['hk1'])} đồng. Hai nguồn đang nói hai số khác nhau — hãy "
            f"liên hệ kế toán để đối chiếu. ĐỪNG bấm tính lại học phí: thao tác "
            f"đó xoá khoản chỉnh tay."
        )

    # Mức PHẢI NỘP theo bảng thu: ngành ưu đãi nộp một lần thì là ``first``
    # (``second`` = 0); ngành thu hai đợt thì là trọn ``hk1`` (= first + second,
    # bất biến đã khoá bằng ``test_tuition_schedule_is_consistent``).
    expected_payable = row["first"] if row["discount_percent"] > 0 else row["hk1"]
    if payable_total != expected_payable:
        log.warning(
            "enrollment_letter.payable_amount_drift",
            major_code=major_code,
            fee_payable_total=payable_total,
            schedule_payable=expected_payable,
            schedule_discount_percent=row["discount_percent"],
        )
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — số phải nộp kỳ I của hồ sơ là "
            f"{_vnd(payable_total)} đồng nhưng theo bảng thu ngành '{major_name}' "
            f"phải là {_vnd(expected_payable)} đồng"
            + (
                f" (học phí {_vnd(row['hk1'])} đã trừ ưu đãi "
                f"{row['discount_percent']}%)"
                if row["discount_percent"] > 0
                else ""
            )
            + ". Nếu hồ sơ này được giảm/chỉnh học phí riêng thì giấy báo (in "
            "theo bảng thu chung) không phản ánh đúng số phải nộp — hãy liên hệ "
            "kế toán để đối chiếu. ĐỪNG bấm tính lại học phí: thao tác đó xoá "
            "khoản chỉnh tay."
        )

    return row


def _school_year_label(fee) -> str:
    """Nhãn năm học "2026-2027" dẫn xuất từ ``fee.academic_year``.

    Cùng công thức với fees.py / invoices.py để giấy báo, màn học phí và hoá
    đơn không bao giờ nói hai năm khác nhau cho cùng một Fee. Fee thiếu
    academic_year (dữ liệu cũ) mới rơi về hằng số.
    """
    year = getattr(fee, "academic_year", None)
    if isinstance(year, int) and year > 0:
        return f"{year}-{year + 1}"
    return C.SCHOOL_YEAR


async def build_letter_data(db, profile) -> dict:
    """Gather + validate the data snapshot rendered onto the letter.

    Raises ``BusinessRuleViolation`` if the profile is not letter-eligible, or
    ``ValidationError`` listing every missing required field. The returned dict
    is BOTH the render input and the persisted ``data_snapshot`` (JSON-safe:
    dates as ISO strings, amounts as int).
    """
    if not is_enrollment_letter_eligible(profile):
        raise BusinessRuleViolation(
            "Chỉ phát giấy báo nhập học cho hồ sơ đã nộp trở đi "
            "(đã nộp / đã duyệt / xác nhận / nhập học) và chưa thôi học."
        )

    missing: list[str] = []

    full_name = (profile.full_name or "").strip()
    if not full_name:
        missing.append("họ tên")

    dob = profile.dob
    if not dob:
        missing.append("ngày sinh")

    address = format_permanent_address(profile)
    if not address:
        missing.append("địa chỉ thường trú")

    fee = await _get_active_hk1_tuition_fee(db, profile.id)
    if fee is None:
        missing.append("phí học kỳ 1 (HK1) — hãy tính học phí trước")

    # Đổi ngành: CHẶN xuất giấy khi đang trong chu kỳ đổi ngành (chờ officer sửa
    # + nộp lại HOẶC chờ kế toán xác nhận) — giấy sẽ ghi ngành/số tiền sai. Gate
    # feature-flag-aware (flag OFF → False). Kiểm ở CẢ đây LẪN re-check dưới khoá
    # (issue_enrollment_letter) chống TOCTOU cửa sổ render.
    from app.services.fee_calculation_service import (
        assert_major_change_cycle_closed,
    )
    await assert_major_change_cycle_closed(  # F13
        db,
        profile,
        message="Không thể xuất giấy báo nhập học: hồ sơ đang trong quá trình "
        "đổi ngành, chờ kế toán xác nhận học phí.",
        exc_type=ValidationError,
    )

    if missing:
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — thiếu dữ liệu: "
            + ", ".join(missing)
            + "."
        )

    # Ngành + trình độ resolve LẠI từ nguyện vọng và đối chiếu với ngành mà học
    # phí đã tính theo (xem ``_resolve_admitted_major``). Chạy SAU khối
    # ``missing`` vì nó cần fee, và nó tự ném ValidationError với lý do riêng
    # thay vì gộp vào danh sách "thiếu dữ liệu".
    (
        major_name,
        degree_level,
        offering_type,
        major_code,
    ) = await _resolve_admitted_major(db, profile, fee)
    if not degree_level:
        # Trình độ KHÔNG được để trống: dữ liệu thật có ngành trùng tên giữa
        # Cao đẳng và Trung cấp, nên "Đã trúng tuyển ngành: Kế toán" một mình
        # là câu chưa xác định. Thà không phát còn hơn phát một tờ giấy mơ hồ.
        raise ValidationError(
            "Không thể tạo giấy báo nhập học — chưa xác định được TRÌNH ĐỘ của "
            "ngành trúng tuyển. Hãy tính lại học phí trước khi phát giấy."
        )

    # Danh mục hồ sơ mang theo khác nhau giữa Cao đẳng và Trung cấp. Không tra
    # được ⇒ KHÔNG phát: một tờ giấy ghi sai danh mục khiến thí sinh đi cả trăm
    # cây số tới trường rồi phải quay về lấy giấy tờ.
    required_documents = C.documents_for_degree(degree_level)
    if required_documents is None:
        log.warning(
            "enrollment_letter.documents_missing_for_degree",
            profile_id=profile.id,
            degree_level=degree_level,
        )
        raise ValidationError(
            f"Không thể tạo giấy báo nhập học — chưa có danh mục hồ sơ nhập học "
            f"cho trình độ '{degree_level}'. Hãy báo bộ phận kỹ thuật bổ sung "
            f"trước khi phát giấy."
        )

    # --- Khối tiền: tra BẢNG THU của Nhà trường theo mã ngành ---------------
    # Các mức đợt là mức CHUẨN của bảng thu, KHÔNG trừ phần đã nộp trước (quyết
    # định nghiệp vụ 19-07): phần lớn hồ sơ đã nộp giữ chỗ 2,5tr và việc đối trừ
    # được thực hiện tại quầy khi thí sinh đến đóng, không thể hiện trên giấy.
    # Giấy in HỌC PHÍ GỐC (khớp ``hk1`` bảng thu), ưu đãi thể hiện ở mức đợt —
    # nên số lên giấy lấy từ ``base_amount``, KHÔNG phải ``final_amount``.
    # ``final_amount`` là số phải nộp sau ưu đãi, dùng để đối chiếu với mức đợt.
    _base_total = max(0, int(round(fee.base_amount or 0)))
    _payable_total = max(0, int(round(fee.final_amount or 0)))
    schedule = _resolve_tuition_schedule(
        major_code, major_name, degree_level, fee, _base_total, _payable_total
    )
    officer_name, officer_phone = await _resolve_officer(db, profile)

    return {
        "full_name": full_name,
        "dob": dob.isoformat(),
        "permanent_address": address,
        # Ngành + trình độ theo nguyện vọng. TRÌNH ĐỘ LÀ BẮT BUỘC trên giấy:
        # dữ liệu thật có ngành TRÙNG TÊN giữa hai trình độ (Kế toán, Công nghệ
        # ô tô, Y sỹ đa khoa, Chăn nuôi - Thú y, Công nghệ thông tin), nên
        # "Đã trúng tuyển ngành: Kế toán" một mình là câu chưa xác định.
        "major_name": major_name,
        "degree_level": degree_level,
        # Hệ đào tạo lấy từ chính ProgramOffering của nguyện vọng (cùng query
        # với ngành). Chỉ rơi về hằng khi phải dùng snapshot Fee — snapshot
        # không lưu hệ đào tạo.
        "offering_type": offering_type or C.DEFAULT_OFFERING_TYPE,
        # round (not truncate) so a hypothetical fractional discount never
        # under-states the charge on the official letter; VND fees are whole.
        "hk1_fee_amount": _base_total,
        # Số PHẢI NỘP sau ưu đãi (= ``first`` của bảng thu với ngành ưu đãi).
        # Chụp lại để guard trước lúc ghi file so được CẢ HAI con số: ai đó gỡ
        # ưu đãi giữa lúc render thì ``base`` không đổi nhưng ``final`` đổi —
        # chỉ so một mình ``hk1_fee_amount`` sẽ không bắt được.
        "payable_amount": _payable_total,
        # Mã ngành = khoá đã tra bảng thu. Lưu lại để hậu kiểm truy được dòng
        # bảng thu nào đã sinh ra các con số dưới đây.
        "major_code": major_code,
        "fee_id": fee.id,
        # Nhãn năm học DẪN XUẤT từ chính Fee đang render (quy ước dùng khắp
        # repo: fees.py / invoices.py), KHÔNG lấy hằng process-wide — nếu không
        # màn Học phí hiện "2026-2027" còn giấy báo in một năm khác.
        "school_year": _school_year_label(fee),
        # Literal ĐÃ IN lên giấy được chụp lại cùng: đây là official record,
        # mà mọi hằng dưới đây đều có thể đổi giữa các mùa tuyển sinh. Không
        # lưu thì sau retention không còn gì đối chiếu "giấy đã nói gì".
        # Bảng thu có thể được sửa cho mùa sau, nên các mức đợt + hạn nộp phải
        # nằm trong snapshot chứ không tra lại lúc đọc.
        "required_documents": required_documents,
        # LỜI HỨA VẬT CHẤT phải nằm trong snapshot, không chỉ phần tiền: giấy
        # hứa ba lô + áo thun + hỗ trợ học lái xe A1 + 3 tháng ký túc xá, dưới
        # chữ ký Hiệu trưởng. Mùa sau đổi quà, retention xoá PDF — không lưu ở
        # đây thì khi thí sinh cầm giấy tới đòi, không còn gì đối chiếu "giấy
        # đã hứa những gì". Cùng lý do đã áp cho ngân hàng/người ký.
        "early_enrollment_bonus": C.EARLY_ENROLLMENT_BONUS.format(
            due=C.INSTALLMENT_1_DUE.strftime("%d/%m/%Y")
        ),
        "benefits": list(C.BENEFITS),
        "closing_note": C.CLOSING_NOTE,
        "tuition_discount_percent": schedule["discount_percent"],
        "first_installment": schedule["first"],
        "second_installment": schedule["second"],
        "first_installment_due": C.INSTALLMENT_1_DUE.isoformat(),
        "second_installment_due": C.INSTALLMENT_2_DUE.isoformat(),
        "bank_account_number": C.BANK_ACCOUNT_NUMBER,
        "bank_account_name": C.BANK_ACCOUNT_NAME,
        "bank_name": C.BANK_NAME,
        "signatory_title": C.SIGNATORY_TITLE,
        "signatory_name": C.SIGNATORY_NAME,
        "phone": (profile.phone or "").strip(),
        # Cán bộ phụ trách in kèm hotline chung. Chụp vào snapshot vì officer
        # có thể đổi sau khi giấy đã trao tay — bản in nói ai thì hồ sơ phải
        # còn ghi đúng người đó.
        "officer_name": officer_name,
        "officer_phone": officer_phone,
        # Mã hồ sơ dùng cho nội dung chuyển khoản. Đây là số định danh hồ sơ mà
        # giao diện hiển thị dạng "#334" và finance tra ngược qua
        # ``admission_profile_id``; tiền tố "HS" chỉ để con số không bị đọc
        # nhầm trên sao kê ngân hàng.
        "profile_code": f"HS{profile.id}",
    }


def _write_pdf_atomic(content: bytes, final_path: str) -> tuple[str, int]:
    """Write ``content`` atomically (staging → fsync → os.replace). Returns
    (sha256_hex, size). SYNC/blocking → call via ``to_thread.run_sync``."""
    sha = hashlib.sha256(content).hexdigest()
    # 0o700 / 0o600: PDF chứa họ tên + ngày sinh + địa chỉ + điện thoại + học
    # phí. Mode mặc định cho ra 0o755/0o644, tức mọi uid khác đọc được thẳng
    # trên volume (volume này còn mount vào cả celery-worker và beat) — vòng
    # qua toàn bộ CasbinAuth + IDOR + audit ở tầng API mà không để lại dấu vết.
    _dir = os.path.dirname(final_path)
    os.makedirs(_dir, mode=0o700, exist_ok=True)
    # ``mode=`` của makedirs chỉ áp cho thư mục LÁ, và chỉ khi nó vừa được tạo:
    # các thư mục TRUNG GIAN (<STORAGE_DIR> lần đầu chạy) ra đời với 0o755, còn
    # thư mục lá của hồ sơ đã từng phát giấy thì giữ nguyên mode cũ. Phải siết
    # tường minh cả hai — 0o755 trên volume dùng chung (mount vào cả
    # celery-worker lẫn beat) cho uid khác `ls` được, tức đọc ra profile id nào
    # đã được phát giấy báo trúng tuyển. Best-effort: quyền thư mục không được
    # phép chặn việc phát giấy.
    for _d in (settings.ENROLLMENT_LETTER_STORAGE_DIR, _dir):
        try:
            if (os.stat(_d).st_mode & 0o777) != 0o700:
                os.chmod(_d, 0o700)
        except OSError:
            pass
    staging = os.path.join(
        os.path.dirname(final_path), f"{STAGING_PREFIX}{uuid4().hex[:12]}.pdf"
    )
    try:
        with open(staging, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(staging, 0o600)  # trước os.replace: file cuối kế thừa mode này
        os.replace(staging, final_path)
    except Exception:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass
        raise
    # Best-effort parent-dir fsync (durability on Linux; no-op on Windows).
    try:
        dir_fd = os.open(os.path.dirname(final_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, AttributeError):
        pass
    return sha, len(content)


def _best_effort_delete(path: str) -> None:
    """Delete a file, swallowing I/O errors. Used to clean up the just-written
    PDF when the issuance transaction fails so it does not orphan on disk.
    SYNC → call via to_thread."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def issue_enrollment_letter(
    db,
    profile,
    start_date,
    end_date,
    current_user,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple["models.EnrollmentLetter", bytes]:
    """Render + persist an official letter. Returns (row, pdf_bytes).

    Caller (router) commits. Date validation (end >= start) is done at the API
    schema layer; this trusts the validated inputs.
    """
    data = await build_letter_data(db, profile)
    render_data = {
        **data,
        "enrollment_start_date": start_date.isoformat(),
        "enrollment_end_date": end_date.isoformat(),
    }

    # ReportLab is synchronous + CPU-bound → keep it off the event loop.
    pdf_bytes = await to_thread.run_sync(render_enrollment_letter, render_data)

    final_path = os.path.join(
        settings.ENROLLMENT_LETTER_STORAGE_DIR, str(profile.id), f"{uuid4().hex}.pdf"
    )
    sha, size = await to_thread.run_sync(_write_pdf_atomic, pdf_bytes, final_path)

    # KHOÁ MUỘN: chỉ giữ SELECT FOR UPDATE từ đây tới lúc router commit, thay vì
    # từ đầu request. Lấy khoá ở dependency (như bản trước) nghĩa là giữ khoá
    # ghi trên hồ sơ suốt cả quá trình render ReportLab + fsync — mọi thao tác
    # song song trên đúng hồ sơ đó (duyệt, ghi nhận thanh toán, rút hồ sơ) phải
    # xếp hàng sau, và trên volume mạng chậm thì đủ lâu để chúng timeout.
    #
    # Đổi lại phải KIỂM TRA LẠI gate sau khi có khoá: trong lúc render, hồ sơ có
    # thể đã bị rollback về draft / rút / thôi học. Không kiểm lại thì ta vừa
    # đánh mất đúng thứ mà cái khoá sinh ra để bảo vệ.
    # Chỉ SELECT 2 cột cần cho gate: ``select(models.AdmissionProfile)`` sẽ kéo
    # theo eager-join sang ``lead`` và Postgres từ chối FOR UPDATE trên nhánh
    # nullable của outer join (đúng cảnh báo trong deps.py). Khoá theo cột vẫn
    # khoá đúng row.
    locked = (
        await db.execute(
            select(
                models.AdmissionProfile.status,
                models.AdmissionProfile.is_dropped,
                # Đọc TƯƠI trong CHÍNH query đã khoá — instance ``profile`` là bản
                # trước render, ``major_change_requested`` trên đó có thể stale
                # False sau khi admin mở chu kỳ giữa lúc render. Re-check ở dưới
                # phải dùng giá trị này, không dùng thuộc tính của instance cũ.
                models.AdmissionProfile.major_change_requested,
            )
            .where(models.AdmissionProfile.id == profile.id)
            .with_for_update()
        )
    ).first()
    if locked is None or not is_enrollment_letter_eligible(
        SimpleNamespace(status=locked[0], is_dropped=locked[1])
    ):
        await to_thread.run_sync(_best_effort_delete, final_path)
        raise BusinessRuleViolation(
            "Hồ sơ đã đổi trạng thái trong lúc tạo giấy báo — không phát hành. "
            "Hãy tải lại trang và kiểm tra trạng thái hồ sơ."
        )

    # ...và kiểm lại cả SỐ TIỀN. Cửa sổ render (~350ms, dài hơn trên volume
    # mạng) không giữ khoá, mà ``calculate_fee`` khoá cùng row hồ sơ nên TRƯỚC
    # đây nó bị xếp hàng sau ta. Nay kế toán có thể huỷ Fee + tính lại ngay
    # giữa lúc ta đang render, và giấy sẽ mang số tiền của một Fee đã cancelled
    # với ``data_snapshot.fee_id`` trỏ vào đó. Chỉ kiểm status là bỏ sót đúng
    # thứ tờ giấy nói ra.
    # Chỉ kiểm ĐÚNG những gì tờ giấy nói: id Fee + TỔNG học phí (các mức đợt là
    # hằng của bảng thu, tra từ tổng này). Phần đã nộp / được miễn KHÔNG còn in
    # trên giấy nữa nên một khoản thu vừa vào trong lúc render không được phép
    # làm hỏng lần phát hành — kiểm cả hai như trước sẽ chặn oan đúng nhóm hồ sơ
    # prepay vốn đang đóng tiền liên tục.
    fee_now = await _get_active_hk1_tuition_fee(db, profile.id)
    if (
        fee_now is None
        or fee_now.id != data.get("fee_id")
        or int(round(fee_now.base_amount or 0)) != data.get("hk1_fee_amount")
        or int(round(fee_now.final_amount or 0)) != data.get("payable_amount")
    ):
        await to_thread.run_sync(_best_effort_delete, final_path)
        log.warning(
            "enrollment_letter.fee_changed_during_render",
            profile_id=profile.id,
            snapshot_fee_id=data.get("fee_id"),
            current_fee_id=getattr(fee_now, "id", None),
        )
        raise BusinessRuleViolation(
            "Học phí của hồ sơ vừa thay đổi trong lúc tạo giấy báo — không phát "
            "hành để tránh in sai số tiền. Hãy thử lại."
        )

    # Đổi ngành: re-check dưới khoá (TOCTOU) — chu kỳ đổi ngành có thể mở TRONG
    # lúc render (cửa sổ ~350ms không giữ khoá). Xoá file tạm + fail như nhánh
    # fee-changed. Flag OFF → False → no-op.
    # F13 NGOẠI LỆ: KHÔNG dùng assert_major_change_cycle_closed vì phải DỌN file
    # PDF tạm (_best_effort_delete) TRƯỚC khi raise — helper raise thẳng không cho
    # chèn cleanup. Giữ check tường minh.
    # Truyền cờ TƯƠI (đọc trong query đã khoá ở trên) qua một view nhẹ thay vì
    # ``profile`` — instance cũ có thể còn ``major_change_requested=False`` trong
    # khi admin vừa mở chu kỳ; phần ``awaiting`` của predicate là query riêng nên
    # đã tươi sẵn.
    from app.services.fee_calculation_service import is_major_change_cycle_open
    _locked_view = SimpleNamespace(id=profile.id, major_change_requested=locked[2])
    if await is_major_change_cycle_open(db, _locked_view):
        await to_thread.run_sync(_best_effort_delete, final_path)
        raise BusinessRuleViolation(
            "Hồ sơ vừa vào quá trình đổi ngành trong lúc tạo giấy báo — không "
            "phát hành. Hãy chờ kế toán xác nhận học phí rồi thử lại."
        )

    _now = datetime.now(timezone.utc)
    expires_at = _now + timedelta(days=settings.ENROLLMENT_LETTER_RETENTION_DAYS)
    letter = models.EnrollmentLetter(
        profile_id=profile.id,
        enrollment_start_date=start_date,
        enrollment_end_date=end_date,
        data_snapshot=data,
        file_path=final_path,
        sha256=sha,
        file_size=size,
        generated_by_id=current_user.id if current_user else None,
        expires_at=expires_at,
    )
    try:
        # ⚠️ THỨ TỰ QUAN TRỌNG: đóng dấu bản cũ TRƯỚC, chèn bản mới SAU.
        #
        # Bản trước làm ngược lại (flush bản mới rồi mới UPDATE), nên trong
        # khoảnh khắc giữa hai bước hồ sơ có HAI row ``superseded_at IS NULL``.
        # Không ai thấy vì cùng một transaction — cho tới khi index
        # ``ix_enrollment_letter_current`` thành UNIQUE thì chính bước flush đó
        # ném IntegrityError và không hồ sơ nào phát được bản thứ hai. Index chỉ
        # phơi ra thứ tự vốn đã sai, không tạo ra lỗi mới.
        #
        # Vì sao đồng bộ expires_at: hạn tính riêng từng bản kể từ lúc phát,
        # nên bản 1 — bản nhiều khả năng ĐÃ TRAO TAY thí sinh — hết hạn và bị
        # xoá PII TRƯỚC bản 2 mà chưa ai cầm. Khi có tranh chấp "giấy tôi cầm
        # ghi gì", bằng chứng còn sống lại là bản sai. Cho cả nhóm chết cùng
        # lúc theo bản mới nhất.
        # (a) Đánh dấu "đã thay thế": CHỈ bản đang hiện hành. Không cần loại
        # trừ bản mới — nó chưa tồn tại ở thời điểm này.
        await db.execute(
            update(models.EnrollmentLetter)
            .where(
                models.EnrollmentLetter.profile_id == profile.id,
                models.EnrollmentLetter.superseded_at.is_(None),
            )
            .values(superseded_at=_now)
        )
        # (b) Gia hạn lưu trữ: MỌI bản của hồ sơ, KHÔNG lọc superseded_at.
        # Lọc theo `superseded_at IS NULL` (như bản trước) chỉ chạm đúng bản
        # ngay trước, nên từ lần phát thứ BA trở đi bản đầu tiên giữ hạn cũ và
        # chết sớm hơn — đo trên dev: lệch 24 giờ. Bản đầu chính là bản nhiều
        # khả năng đã trao tay thí sinh, tức bằng chứng bị huỷ trước lại đúng là
        # bản đang tranh chấp.
        # ...TRỪ những bản đã bị retention xoá file + scrub PII. Đẩy hạn cho
        # chúng làm sống lại một row tự mâu thuẫn: "còn hạn tới 90 ngày nữa"
        # trong khi file đã biến mất và snapshot đã mất PII. Officer nhìn danh
        # sách tưởng tải lại được, bấm vào thì 404.
        await db.execute(
            update(models.EnrollmentLetter)
            .where(
                models.EnrollmentLetter.profile_id == profile.id,
                models.EnrollmentLetter.data_snapshot["_purged"].astext.is_(None),
            )
            .values(expires_at=expires_at)
        )
        # Bản mới chèn SAU cùng: lúc này không còn row nào của hồ sơ mang
        # superseded_at NULL, nên nó vào đúng vị trí "bản hiện hành" duy nhất.
        db.add(letter)
        await db.flush()
    except Exception:
        # Flush failed → the PDF we just wrote would orphan on disk with no
        # row referencing it. Delete it before propagating. (A router commit
        # failure AFTER this is cleaned up by the router; the periodic cleanup
        # task is the final backstop.)
        await to_thread.run_sync(_best_effort_delete, final_path)
        raise
    # Audit the issuance (symmetry with the 'downloaded' event) so the
    # EntityAuditLog access stream also captures the initial PII-PDF delivery,
    # not just re-downloads. Committed by the router.
    db.add(
        models.EntityAuditLog(
            entity_type="EnrollmentLetter",
            entity_id=letter.id,
            action="issued",
            actor_user_id=current_user.id if current_user else None,
            source="api",
            ip_address=(ip_address or None),
            user_agent=(user_agent[:500] if user_agent else None),
            reason=f"Phát giấy báo nhập học hồ sơ #{profile.id}",
        )
    )
    log.info(
        "enrollment_letter.issued",
        letter_id=letter.id,
        profile_id=profile.id,
        generated_by=current_user.id if current_user else None,
    )
    return letter, pdf_bytes


async def get_letter_record(db, profile_id: int, letter_id: int):
    """Fetch an issuance row scoped to ``profile_id`` (IDOR handled upstream by
    the profile dependency). Returns None if not found / not this profile's."""
    stmt = select(models.EnrollmentLetter).where(
        models.EnrollmentLetter.id == letter_id,
        models.EnrollmentLetter.profile_id == profile_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def discard_letter_file(letter) -> None:
    """Best-effort delete the letter's PDF from disk — called by the router if
    the commit fails AFTER issuance flushed, so a rolled-back letter does not
    orphan its file. Safe post-rollback: file_path is a loaded scalar
    (expire_on_commit=False)."""
    await to_thread.run_sync(_best_effort_delete, letter.file_path)


async def list_letters_for_profile(db, profile_id: int):
    """Issued letters for a profile, newest first (for the re-download UI).

    Kept in the service so the router stays a dumb translator (no db.execute /
    raw SQL in the HTTP layer)."""
    stmt = (
        select(models.EnrollmentLetter)
        .where(models.EnrollmentLetter.profile_id == profile_id)
        .order_by(models.EnrollmentLetter.generated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_letter_for_download(
    db,
    profile_id: int,
    letter_id: int,
    actor_user_id: int | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """Resolve a letter for re-download (IDOR-scoped to profile) AND record a
    'downloaded' access-audit row (A09 — mirrors document download).

    Raises ResourceNotFoundError (→ 404, no existence leak) if the letter is not
    this profile's or the file has been purged by retention. Flushes the audit;
    the router commits before streaming the file.
    """
    letter = await get_letter_record(db, profile_id, letter_id)
    # 404 (no existence leak) for: not this profile's · hết hạn / đã purge
    # (``is_downloadable`` — CÙNG thuộc tính danh sách dùng để bật/tắt nút, nên
    # nút và cổng không thể nói hai chuyện khác nhau) · file không còn trên đĩa.
    # Mirrors the SMS export "expired → not served" gate so an expired official
    # document is never downloadable even if the daily cleanup task has not yet
    # removed the file.
    if (
        letter is None
        or not letter.is_downloadable
        or not os.path.exists(letter.file_path)
    ):
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )

    # THU HỒI THEO TRẠNG THÁI HIỆN TẠI của hồ sơ. Không luồng nào (rút hồ sơ /
    # từ chối / thôi học / rollback về nháp) đụng tới bảng enrollment_letter,
    # nên nếu chỉ kiểm row thì giấy "Đã trúng tuyển" của một thí sinh đã rút hồ
    # sơ vẫn tải về được suốt cả thời hạn lưu trữ. Kiểm tại thời điểm tải là
    # cách rẻ nhất mà luôn đúng: không cần cột revoked_at, không cần hook vào
    # mọi luồng workflow, và tự đúng lại nếu hồ sơ được khôi phục.
    profile_state = (
        await db.execute(
            select(
                models.AdmissionProfile.status,
                models.AdmissionProfile.is_dropped,
            ).where(models.AdmissionProfile.id == profile_id)
        )
    ).first()
    if profile_state is None or not is_enrollment_letter_eligible(
        SimpleNamespace(status=profile_state[0], is_dropped=profile_state[1])
    ):
        log.info(
            "enrollment_letter.download_blocked_ineligible_profile",
            letter_id=letter_id,
            profile_id=profile_id,
            status=None if profile_state is None else profile_state[0],
        )
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )
    # Integrity (A08): recompute the sha256 and refuse to stream a
    # tampered/corrupt official PDF. Chunked read off the event loop.
    actual_sha = await to_thread.run_sync(sha256_file, letter.file_path)
    if actual_sha != letter.sha256:
        log.error(
            "enrollment_letter.integrity_mismatch",
            letter_id=letter.id,
            profile_id=profile_id,
            expected_sha256=letter.sha256,
            actual_sha256=actual_sha,
        )
        raise ResourceNotFoundError(
            detail=f"Enrollment letter {letter_id} not found"
        )
    db.add(
        models.EntityAuditLog(
            entity_type="EnrollmentLetter",
            entity_id=letter.id,
            action="downloaded",
            actor_user_id=actor_user_id,
            source="api",
            ip_address=(ip_address or None),
            user_agent=(user_agent[:500] if user_agent else None),
            reason=f"Tải giấy báo nhập học hồ sơ #{profile_id}",
        )
    )
    await db.flush()
    return letter
