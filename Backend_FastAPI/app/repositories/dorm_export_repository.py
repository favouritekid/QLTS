"""Cohort "đã đóng học phí HK1" — nguồn cho export sang ứng dụng KTX.

Đây là NƠI DUY NHẤT định nghĩa "học viên nào được đưa sang hệ KTX". Ứng dụng KTX
là hệ tách rời (Supabase) nên nếu vị từ này lệch khỏi QLTS, hai bên sẽ nói hai
danh sách khác nhau mà không có gì nổ ra — vì vậy điều kiện tiền BẮT BUỘC lấy từ
``constants/hk1_fee.confirmed_paid_hk1_conditions`` chứ không viết lại tại chỗ.

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

from sqlalchemy import Select, select

from app import models
from app.constants.hk1_fee import confirmed_paid_hk1_conditions
from app.services.admission_state_machine import AdmissionStatus

# Trạng thái hồ sơ được đưa sang hệ KTX.
#
# LOẠI có chủ đích:
#   * ``draft`` / ``rejected``            — chưa vào hoặc đã bị từ chối
#   * ``withdrawn``                       — đã rút hẳn
#   * ``withdrawal_pending``              — ĐANG rút, chờ hoàn tiền. Nhóm này
#     gần như luôn có ``paid_amount > 0`` (chính vì đã đóng tiền mới phải chờ
#     hoàn) nên nếu không loại tường minh sẽ lọt vào cohort.
#   * ``reviewing`` / ``result_published`` / ``waitlisted`` / ``revision_requested``
#     — chưa có kết quả trúng tuyển. Hồ sơ ở các trạng thái này mà đã đóng học
#     phí HK1 là bất thường; nếu thực tế có, chúng sẽ KHÔNG xuất hiện trong
#     cohort và cần xử lý riêng thay vì âm thầm xếp chỗ ở.
DORM_COHORT_STATUSES: tuple = (
    AdmissionStatus.SUBMITTED.value,
    AdmissionStatus.RESUBMITTED.value,
    AdmissionStatus.APPROVED.value,
    AdmissionStatus.OVERRIDDEN.value,
    AdmissionStatus.ADMITTED.value,
    AdmissionStatus.CONFIRMED.value,
    AdmissionStatus.ENROLLED.value,
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


def _resolved_major_name_subquery() -> Any:
    """Tên ngành TRÚNG TUYỂN, lấy từ ``fee.resolved_major_id``.

    Trả ``NULL`` khi hồ sơ chưa chốt ngành — KHÔNG loại hồ sơ đó khỏi cohort.
    ``limit(1)`` phòng ca dữ liệu có nhiều dòng phí HK1 (ví dụ một dòng đã huỷ
    và một dòng mới): vị từ đã loại ``cancelled`` nên còn lại tối đa một dòng,
    ``limit`` chỉ là chốt an toàn để subquery không bao giờ trả nhiều hàng.
    """
    return (
        select(models.MajorProgram.name)
        .select_from(models.Fee)
        .join(
            models.MajorProgram,
            models.MajorProgram.id == models.Fee.resolved_major_id,
        )
        .where(*confirmed_paid_hk1_conditions(models.AdmissionProfile.id))
        .correlate(models.AdmissionProfile)
        .limit(1)
        .scalar_subquery()
    )


def select_paid_hk1_cohort(academic_year: int) -> Select:
    """Câu truy vấn cohort học viên đã đóng học phí HK1 của MỘT năm học.

    Args:
        academic_year: năm học cần lấy. Bắt buộc — xem docstring module.

    Returns:
        ``Select`` trả mỗi hồ sơ đủ điều kiện một hàng, kèm officer phụ trách và
        tên ngành trúng tuyển (có thể ``None``).

    Raises:
        ValueError: khi ``academic_year`` không được truyền hoặc không phải số
            nguyên — chặn ca gọi nhầm khiến cohort trải khắp mọi năm.
    """
    if academic_year is None or isinstance(academic_year, bool):
        raise ValueError("academic_year là tham số bắt buộc")
    if not isinstance(academic_year, int):
        raise ValueError("academic_year phải là số nguyên")

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


def cohort_status_values() -> List[str]:
    """Bản sao danh sách trạng thái — cho tầng gọi hiển thị/kiểm tra."""
    return list(DORM_COHORT_STATUSES)


def describe_excluded_statuses() -> List[str]:
    """Trạng thái KHÔNG thuộc cohort — dùng cho log đối soát khi export."""
    allowed = set(DORM_COHORT_STATUSES)
    return sorted(s.value for s in AdmissionStatus if s.value not in allowed)


__all__ = [
    "DORM_COHORT_STATUSES",
    "cohort_status_values",
    "describe_excluded_statuses",
    "paid_hk1_exists_clause",
    "select_paid_hk1_cohort",
]
