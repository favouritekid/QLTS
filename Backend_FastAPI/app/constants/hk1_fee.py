"""Vị từ phí HK1 dùng chung — NGUỒN CHUẨN cho các consumer đã refactor.

⚠️ PHẠM VI TUYÊN BỐ — đọc trước khi tin: file này là nguồn chuẩn cho ĐÚNG BA
consumer đã chuyển sang dùng nó, **không phải** nguồn duy nhất toàn hệ thống:

* ``repositories/admission_repository._hk1_fee_predicate``   (danh sách hồ sơ)
* ``services/assignment_service._hk1_fee_exists``            (giảm trừ tải lead)
* ``repositories/dorm_export_repository``                    (cohort KTX)

CÒN NỢ — các nơi vẫn viết tay vị từ này, CHƯA refactor (để PR riêng, vì đụng báo
cáo và export là vùng dễ làm lệch số):

* ``repositories/admission_report_repository`` (~:534, ~:580)
* ``services/admission_summary_export_service`` (SQL thô, ~:183 và ~:314)
* ``services/admission_service`` (~:5141, ~:5196, ~:6661)

Nghĩa là: đổi phạm vi HK1 ở đây thì ba consumer trên tự đúng theo, nhưng vẫn
PHẢI rà tay các nơi còn nợ. Đừng đọc file này thành "sửa một chỗ là xong".

⚠️ Không có test nào nối ba consumer đã refactor với năm nơi còn nợ — nới hay
thu phạm vi ở đây mà quên rà tay sẽ làm DANH SÁCH HỒ SƠ và BÁO CÁO nói hai con
số khác nhau, và cả hai đều xanh.

``services/fee_calculation_service.is_hk1_settled`` cố ý KHÔNG dùng file này: nó
nhận giá trị đã đọc sẵn (không phải biểu thức SQL) và mang nghĩa KHÁC — "đóng ĐỦ
hoặc miễn", trong khi hai tầng dưới đây phục vụ "phạm vi" và "đã có tiền vào".

HAI TẦNG — cố ý KHÔNG gộp làm một
=================================

``hk1_fee_scope_conditions`` — PHẠM VI dòng phí HK1, KHÔNG xét đã thu hay chưa.
    Mọi phép CỘNG TIỀN (Σ paid, Σ remaining, Σ final) BẮT BUỘC dùng tầng này.
    Thêm ``paid_amount > 0`` vào đây sẽ loại các dòng phí chưa thu đồng nào ra
    khỏi phép tính, khiến "còn phải thu" báo THIẾU và hồ sơ đã có phí nhưng chưa
    nộp bị đọc nhầm thành "chưa có HK1".

``confirmed_paid_hk1_conditions`` — tầng trên CỘNG ``paid_amount > 0``.
    Nghĩa: kế toán ĐÃ XÁC NHẬN thu tiền. ``fee.paid_amount`` chỉ tăng ở money-math
    chạy SAU khi payment chuyển ``verified``, và hoàn tiền giảm ngược lại, nên
    bằng chứng tự rút lại khi tiền đi ra. Một phần hay đủ đều tính.
    Cố ý KHÔNG xét ``waived_amount``: miễn giảm không phải "đã đóng".

⚠️ ``semester_no == 1`` BẮT BUỘC ở cả hai tầng — CHỈ HK1 điều khiển pipeline
sts14/sts10. Nới ra mọi học kỳ thì lead còn NỢ HK1 nhưng đã đóng HK2+ bị trừ khỏi
tải OAN trong khi officer vẫn đang phải đòi HK1. Ghim bởi
``test_hk2_paid_hk1_unpaid_stays_in_workload``.

⚠️ Hai tầng này chỉ mô tả DÒNG PHÍ. Chúng KHÔNG ràng buộc năm học, KHÔNG loại hồ
sơ đã rút / lead đã xoá mềm. Call site nào cần "lần ứng tuyển hiện tại" phải tự
thêm mốc năm (xem ``assignment_service._current_admission_year_subquery``); call
site nào cần một NĂM CỤ THỂ phải tự ràng ``AdmissionProfile.academic_year`` —
đừng mượn mốc ``max(academic_year)`` vì nó luôn kéo về mùa mới nhất.
"""

from typing import Any, List


def hk1_fee_scope_conditions(profile_id_expr: Any = None) -> List[Any]:
    """Phạm vi dòng phí HK1 (chưa xét đã thu tiền hay chưa).

    Args:
        profile_id_expr: biểu thức profile-id để nối ``Fee`` ↔ ``AdmissionProfile``.
            Truyền khi call site CHƯA nối bằng JOIN (dùng dạng correlated
            predicate / EXISTS). Bỏ trống khi call site đã có JOIN sẵn, để không
            phát sinh điều kiện nối trùng lặp.

    Returns:
        Danh sách điều kiện SQLAlchemy, dùng bằng ``and_(*conds)`` hoặc trải vào
        ``.where(...)``.
    """
    from app.models.finance import Fee, FeeStatusEnum

    conditions: List[Any] = [
        Fee.fee_type == "tuition",
        Fee.semester_no == 1,
        Fee.status != FeeStatusEnum.cancelled,
    ]
    if profile_id_expr is not None:
        conditions.insert(0, Fee.admission_profile_id == profile_id_expr)
    return conditions


def confirmed_paid_hk1_conditions(profile_id_expr: Any = None) -> List[Any]:
    """Phạm vi HK1 + kế toán ĐÃ XÁC NHẬN thu tiền (``paid_amount > 0``).

    Một phần hay đủ đều tính. Xem docstring module cho lý do không xét
    ``waived_amount`` và vì sao tầng này tách khỏi ``hk1_fee_scope_conditions``.

    Args:
        profile_id_expr: xem ``hk1_fee_scope_conditions``.
    """
    from app.models.finance import Fee

    return hk1_fee_scope_conditions(profile_id_expr) + [Fee.paid_amount > 0]
