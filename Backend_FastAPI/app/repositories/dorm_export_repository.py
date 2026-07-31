"""Cohort "đã đóng học phí HK1" — nguồn cho export sang ứng dụng KTX.

Đây là nơi duy nhất định nghĩa "học viên nào được đưa sang hệ KTX". Ứng dụng KTX
là hệ tách rời (Supabase) nên nếu vị từ này lệch khỏi QLTS, hai bên sẽ nói hai
danh sách khác nhau mà không có gì nổ ra — vì vậy điều kiện tiền BẮT BUỘC lấy từ
``constants/hk1_fee.confirmed_paid_hk1_conditions`` chứ không viết lại tại chỗ.
Ràng buộc đó được ghim bằng test structural (monkeypatch sentinel), không chỉ
bằng so khớp SQL.

⚠️ ``academic_year`` là THAM SỐ BẮT BUỘC và lọc THẲNG trên
``AdmissionProfile.academic_year``. Cố ý KHÔNG mượn
``assignment_service._current_admission_year_subquery`` (``max(academic_year)``
của lead): mốc đó luôn kéo về mùa mới nhất, nên một lead đã nộp hồ sơ mùa sau sẽ
làm hồ sơ mùa được hỏi biến mất khỏi kết quả.

Không loại hồ sơ có ``resolved_major_id IS NULL``: với hồ sơ nhiều nguyện vọng
chưa chốt ngành, cột này cố ý để trống (fail-soft, xem ``models/finance/fee.py``).
Học viên đó vẫn đã đóng tiền và vẫn cần chỗ ở — ``program_name`` trả ``None`` để
tầng hiển thị ghi "(chưa chốt ngành)".
"""

from typing import Any, List

from sqlalchemy import Select, func, select

from app import models
from app.constants.hk1_fee import confirmed_paid_hk1_conditions
from app.services.admission_state_machine import AdmissionStatus
from app.utils.exceptions import ValidationError

# Trạng thái hồ sơ được đưa sang hệ KTX.
#
# NGUYÊN TẮC: bằng chứng quyết định là TIỀN ĐÃ VÀO, không phải nhãn trạng thái.
# Vì vậy danh sách này CỐ Ý RỘNG — chỉ loại đúng bốn trạng thái mà việc xếp chỗ
# ở là vô nghĩa hoặc sai:
#
#   * ``draft``               — chưa nộp hồ sơ
#   * ``rejected``            — đã bị từ chối
#   * ``withdrawn``           — đã rút hẳn
#   * ``withdrawal_pending``  — ĐANG rút, chờ hoàn tiền. Nhóm này gần như luôn
#     có ``paid_amount > 0`` (chính vì đã đóng tiền mới phải chờ hoàn) nên không
#     loại tường minh thì chắc chắn lọt vào cohort.
#
# Bốn trạng thái ĐANG XÉT (``reviewing``, ``revision_requested``,
# ``result_published``, ``waitlisted``) ĐƯỢC GIỮ: hồ sơ ở đó mà đã đóng học phí
# HK1 là bất thường, nhưng em đó vẫn đã bỏ tiền thật và vẫn cần chỗ ở — loại đi
# là mất người thật khỏi danh sách officer nhìn thấy.
DORM_COHORT_STATUSES: tuple = (
    AdmissionStatus.SUBMITTED.value,
    AdmissionStatus.RESUBMITTED.value,
    AdmissionStatus.REVIEWING.value,
    AdmissionStatus.REVISION_REQUESTED.value,
    AdmissionStatus.RESULT_PUBLISHED.value,
    AdmissionStatus.WAITLISTED.value,
    AdmissionStatus.APPROVED.value,
    AdmissionStatus.OVERRIDDEN.value,
    AdmissionStatus.ADMITTED.value,
    AdmissionStatus.CONFIRMED.value,
    AdmissionStatus.ENROLLED.value,
)

# Tập con của ``DORM_COHORT_STATUSES``: đã đóng học phí HK1 nhưng hồ sơ vẫn ĐANG
# XÉT. Được giữ trong cohort (bằng chứng là tiền, không phải nhãn) nhưng đáng để
# người vận hành nhìn trước khi ghi. Ghim bởi test lock-in với allow-list.
COHORT_ATYPICAL_STATUSES: tuple = (
    AdmissionStatus.REVIEWING.value,
    AdmissionStatus.REVISION_REQUESTED.value,
    AdmissionStatus.RESULT_PUBLISHED.value,
    AdmissionStatus.WAITLISTED.value,
)


def paid_hk1_exists_clause() -> Any:
    """EXISTS: hồ sơ (outer) có dòng phí HK1 kế toán đã xác nhận thu tiền."""
    return (
        select(1)
        .select_from(models.Fee)
        .where(*confirmed_paid_hk1_conditions(models.AdmissionProfile.id))
        .correlate(models.AdmissionProfile)
        .exists()
    )


def _resolved_major_scalar(column: Any, *extra_joins: Any) -> Any:
    """Một giá trị lấy từ ngành TRÚNG TUYỂN (``fee.resolved_major_id``).

    Trả ``NULL`` khi hồ sơ chưa chốt ngành — KHÔNG loại hồ sơ đó khỏi cohort.
    ``limit(1)`` phòng ca dữ liệu có nhiều dòng phí HK1 (ví dụ một dòng đã huỷ
    và một dòng mới): vị từ đã loại ``cancelled`` nên còn lại tối đa một dòng,
    ``limit`` chỉ là chốt an toàn để subquery không bao giờ trả nhiều hàng.

    🔴 Thứ THẬT SỰ giữ cho mọi cột đến từ CÙNG MỘT dòng phí là ràng buộc
    ``uq_fee_profile_type_semester_tuition`` — unique từng phần trên
    ``(admission_profile_id, fee_type, semester_no)`` với điều kiện
    ``fee_type = 'tuition' and status <> 'cancelled'`` — nên vị từ cohort chỉ
    còn tối đa MỘT dòng để chọn. Dùng chung khuôn này KHÔNG bảo đảm điều đó:
    khuôn chung chỉ cho cùng HÌNH DẠNG, không cho cùng HÀNG.

    Hai điều dưới đây là lưới THỨ HAI, cho ngày ràng buộc kia bị nới:

      * ``order_by(Fee.id)`` — ``limit(1)`` không kèm ``order by`` cho phép
        PostgreSQL trả hàng nào tuỳ kế hoạch thực thi. Với hai truy vấn con
        chạy độc lập, hai lần chọn có thể ra hai dòng phí khác nhau.
      * ``outerjoin`` cho các bảng tra — ``join`` trong sẽ LOẠI dòng phí có
        khoá ngoại rỗng, làm truy vấn con này chọn dòng khác hẳn truy vấn kia.
        Ví dụ thật: hồ sơ có hai dòng phí HK1 chưa huỷ (đổi ngành xong tính
        lại), ngành của dòng A không có ``degree_level_id`` còn dòng B có.
        Truy vấn tên trả tên của A, truy vấn trình độ buộc phải trả bậc của B.

    Kết quả của việc thiếu chúng, NẾU ràng buộc kia mất, là "Công nghệ ô tô —
    Cao đẳng" trên một hồ sơ thực ra học Trung cấp, mà không có gì báo. Ràng
    buộc được đo trực tiếp ở
    ``test_at_most_one_paid_hk1_fee_row_can_exist``.

    Args:
        column: cột cần lấy.
        extra_joins: các cặp ``(target, onclause)`` nối thêm sau
            ``major_program``. Luôn nối NGOÀI, xem trên.
    """
    query = (
        select(column)
        .select_from(models.Fee)
        .join(
            models.MajorProgram,
            models.MajorProgram.id == models.Fee.resolved_major_id,
        )
    )
    for target, onclause in extra_joins:
        query = query.outerjoin(target, onclause)

    return (
        query.where(*confirmed_paid_hk1_conditions(models.AdmissionProfile.id))
        .correlate(models.AdmissionProfile)
        .order_by(models.Fee.id)
        .limit(1)
        .scalar_subquery()
    )


def _resolved_major_name_subquery() -> Any:
    """Tên ngành TRÚNG TUYỂN."""
    return _resolved_major_scalar(models.MajorProgram.name)


def _resolved_degree_level_subquery() -> Any:
    """Trình độ của ngành TRÚNG TUYỂN — "Trung cấp", "Cao đẳng"…

    🔴 Vì sao KTX cần cột này thay vì tự suy từ tên ngành: CÙNG MỘT TÊN tồn tại
    ở HAI trình độ. Trên dữ liệu thật, "Công nghệ ô tô", "Chăn nuôi - Thú y" và
    "Kế toán" mỗi cái có cả bản Trung cấp lẫn Cao đẳng, phủ 257/457 hồ sơ của
    khối KTX. Gộp theo tên là gộp hai chương trình khác nhau vào một dòng.

    ⚠️ Đọc qua ``degree_level_id`` → ``config_degree_level``, KHÔNG dùng cột
    ``major_program.degree_level``: chính model khai cột text đó là LEGACY.
    Hôm nay hai nguồn khớp nhau tuyệt đối trên prod (0 hàng lệch), nhưng chọn
    nguồn phụ thuộc vào việc chúng còn khớp là một quả bom hẹn giờ.

    Nối NGOÀI: ngành thiếu FK trình độ vẫn giữ dòng phí lại và cho ``NULL``.
    Nối trong sẽ LOẠI dòng đó, khiến truy vấn con này chọn một dòng phí khác
    với truy vấn tên ngành — xem ``_resolved_major_scalar``. ``NULL`` ở đây
    nghĩa là "không tra được", giống hệt nghĩa của ``NULL`` khi hồ sơ chưa chốt
    ngành; KTX phải hiển thị được cả hai ca đó chứ không lặng lẽ đếm chúng vào
    một trình độ nào.
    """
    return _resolved_major_scalar(
        models.ConfigDegreeLevel.name,
        (
            models.ConfigDegreeLevel,
            models.ConfigDegreeLevel.id == models.MajorProgram.degree_level_id,
        ),
    )


def _blank_to_null(column: Any) -> Any:
    """``NULL`` cho cả giá trị rỗng lẫn chuỗi toàn khoảng trắng.

    ⚠️ Cần thiết vì ``coalesce`` trần KHÔNG lùi về cột sau khi cột trước là
    chuỗi rỗng — mà "ô nhập để trống nhưng có một dấu cách" là ca thường gặp
    nhất ở dữ liệu gõ tay. Không có lớp này, một hồ sơ có sẵn số bên lead vẫn
    sang hệ KTX với ô liên hệ trống.
    """
    return func.nullif(func.trim(column), "")


def _contact_phone_expr() -> Any:
    """Số liên hệ chính: ưu tiên số trên hồ sơ, thiếu thì lấy của lead.

    Đo trên prod 29-07: cả 461 hồ sơ của cohort đều có ``AdmissionProfile.phone``
    nên nhánh lùi hôm nay chưa chạy lần nào. Vẫn viết ra vì cột đó *nullable* —
    một mùa tuyển sinh khác, một luồng nhập khác là nó trống.
    """
    return func.coalesce(
        _blank_to_null(models.AdmissionProfile.phone),
        _blank_to_null(models.Lead.phone),
    )


def _contact_phone2_expr() -> Any:
    """Số liên hệ phụ — chỉ lấy từ lead.

    ⚠️ CỐ Ý không có nhánh lùi: đây là số THỨ HAI, nên nếu nó rỗng thì câu trả
    lời đúng là "không có số phụ", không phải "lấy tạm số nào đó". Việc loại
    trùng với số chính làm ở tầng payload, nơi cả hai giá trị đã nằm cạnh nhau.
    """
    return _blank_to_null(models.Lead.phone2)


def select_paid_hk1_cohort(academic_year: int) -> Select:
    """Câu truy vấn cohort học viên đã đóng học phí HK1 của MỘT năm học.

    Args:
        academic_year: năm học cần lấy. Bắt buộc — xem docstring module.

    Returns:
        ``Select`` trả mỗi hồ sơ đủ điều kiện một hàng, kèm officer phụ trách và
        tên ngành trúng tuyển (có thể ``None``).

    Raises:
        ValidationError: khi ``academic_year`` không được truyền hoặc không phải
            số nguyên — chặn ca gọi nhầm khiến cohort trải khắp mọi năm.

    ⚠️ Dùng ``ValidationError`` (domain exception, ánh xạ 400) chứ KHÔNG phải
    ``ValueError`` trần. Hôm nay caller duy nhất là script CLI nên khác biệt
    không thấy được, nhưng ngày query này lộ qua router thì ``ValueError`` thành
    500 kèm stack trace thay vì 400 — và không có gì báo cho ta biết.
    """
    if academic_year is None or isinstance(academic_year, bool):
        raise ValidationError("academic_year là tham số bắt buộc")
    if not isinstance(academic_year, int):
        raise ValidationError("academic_year phải là số nguyên")

    return (
        select(
            models.AdmissionProfile.id.label("qlts_profile_id"),
            models.AdmissionProfile.full_name.label("full_name"),
            models.AdmissionProfile.gender.label("source_gender_raw"),
            models.AdmissionProfile.academic_year.label("academic_year"),
            models.AdmissionProfile.status.label("profile_status"),
            models.Lead.assigned_officer_id.label("officer_qlts_id"),
            models.Lead.unit_id.label("unit_id"),
            _resolved_major_name_subquery().label("program_name"),
            _resolved_degree_level_subquery().label("degree_level"),
            _contact_phone_expr().label("contact_phone"),
            _contact_phone2_expr().label("contact_phone2"),
        )
        .select_from(models.AdmissionProfile)
        .join(
            models.Lead,
            models.Lead.id == models.AdmissionProfile.lead_id,
        )
        .where(
            models.AdmissionProfile.academic_year == academic_year,
            models.Lead.deleted_at.is_(None),
            # ``is_dropped`` nullable → ``IS NOT TRUE`` bắt cả NULL lẫn False.
            models.AdmissionProfile.is_dropped.is_not(True),
            models.AdmissionProfile.status.in_(DORM_COHORT_STATUSES),
            paid_hk1_exists_clause(),
        )
        .order_by(models.AdmissionProfile.id)
    )


def describe_excluded_statuses() -> List[str]:
    """Trạng thái KHÔNG thuộc cohort — dùng cho log đối soát khi export.

    ``scripts/sync_dorm_students`` ghi danh sách này vào log mỗi lượt. Đó là
    thứ trả lời "vì sao em này không có trong danh sách KTX" mà không phải mở
    code ra đọc.
    """
    allowed = set(DORM_COHORT_STATUSES)
    return sorted(s.value for s in AdmissionStatus if s.value not in allowed)


def count_atypical_statuses(rows: Any) -> int:
    """Số hàng trong cohort đang ở trạng thái ĐANG XÉT.

    Đây là lý do câu truy vấn trả kèm ``profile_status``: bốn trạng thái đó nằm
    trong cohort vì tiền đã vào, nhưng chúng BẤT THƯỜNG — người vận hành cần
    thấy con số trước khi ghi, không phải phát hiện sau.

    Đếm ở đây (chứ không ở script) để danh sách trạng thái bất thường chỉ tồn
    tại một bản, ngay cạnh allow-list mà nó là tập con.
    """
    return sum(1 for r in rows if r.profile_status in COHORT_ATYPICAL_STATUSES)


__all__ = [
    "COHORT_ATYPICAL_STATUSES",
    "DORM_COHORT_STATUSES",
    "count_atypical_statuses",
    "describe_excluded_statuses",
    "paid_hk1_exists_clause",
    "select_paid_hk1_cohort",
]
