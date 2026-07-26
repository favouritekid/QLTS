"""NGUỒN SỰ THẬT DUY NHẤT cho việc ĐỊNH GIÁ học phí (số PHẢI THU).

Tách bạch với ``app/constants/cash_ledger.py`` — file đó nói về tiền ĐÃ VÀO/RA
(giao dịch đã xảy ra); file này nói về số PHẢI THU (tính trước khi thu).

Vì sao cần: cùng một công thức "base − giảm giá − miễn giảm tay = phải thu" trước
đây được viết lại ở nhiều nơi (tính phí lần đầu, tính lại, xem trước, định giá lại
khi đổi ngành). Mỗi bản sao là một cơ hội drift, và tiền lệch thì không ai thấy cho
tới lúc đối soát. Ở đây là hàm THUẦN (không session, không I/O) nên:

* mọi nơi gọi cùng một phép tính ⇒ sửa một chỗ, mọi nơi tự đúng;
* test được không cần CSDL, nên quy tắc nghiệp vụ có lưới thật.

Bên gọi chịu trách nhiệm TRUY VẤN chính sách (``TuitionDiscountPolicy``) rồi truyền
danh sách vào; file này không biết gì về DB.

────────────────────────────────────────────────────────────────────────────
QUY TẮC GIẢM GIÁ (``resolve_discounts``) — và vì sao từng cái tồn tại
────────────────────────────────────────────────────────────────────────────
1. **Loại giảm** đọc từ enum ``DiscountTypeEnum`` (``amount`` | ``percentage``),
   KHÔNG so chuỗi tự viết. Bản cũ so ``policy.discount_type == "percent"`` trong
   khi CSDL lưu ``"percentage"`` ⇒ mọi chính sách phần trăm rơi xuống nhánh
   "số tiền cố định": chính sách **10% giảm đúng 10 ĐỒNG**, chính sách 50% giảm 50
   đồng. Prod có 3 chính sách (10% / 50% / 500.000đ) nên lỗi này sẽ nổ ngay lần
   đầu gắn chính sách cho một ngành.
2. **Hiệu lực theo ngày** (``valid_from`` / ``valid_to``, NULL = không giới hạn).
   Bản cũ không xét nên hai cột này chỉ để trưng: chính sách "Giảm đăng ký sớm"
   hết hạn 30/06 vẫn được áp cho hồ sơ tính phí tháng 7.
3. **Cộng dồn** (``is_stackable``). Sắp theo ``priority`` giảm dần (cao = xét
   trước), rồi ``id`` tăng cho tính xác định. Gặp chính sách KHÔNG cộng dồn thì áp
   nó rồi DỪNG — "không cộng dồn" nghĩa là không đứng cùng chính sách khác, không
   phải "vẫn cộng nhưng ghi chú".
4. **Giới hạn lượt** (``max_usage`` / ``current_usage``): hết lượt thì không áp.
   ⚠️ Hàm này KHÔNG tăng ``current_usage`` (nó thuần, và ``preview`` cũng gọi nó —
   tăng lượt khi khách chỉ xem thử là sai). Việc tăng lượt là quyết định nghiệp vụ
   còn treo, xem ``PENDING_DECISIONS`` dưới đây.
5. **CHỈ ÁP THEO CẤU HÌNH.** Chính sách được áp khi và chỉ khi nó được GẮN
   TƯỜNG MINH cho ngành (``offering_academic_info.applied_discount_policy_ids``).
   Engine KHÔNG tự suy diễn từ ``applicable_scope`` / ``target_criteria`` để
   "tìm thêm" chính sách áp được.
   🔴 Vì sao (owner đính chính 26-07): chính sách kiểu ``{"is_heavy_only": true}``
   ("Giảm ngành nặng nhọc") KHÔNG phải giảm học phí thí sinh phải đóng — đó là
   **Nhà nước CẤP BÙ học phí**, thí sinh **vẫn đóng đủ**. Suy diễn "ngành nặng
   nhọc ⇒ tự giảm 50%" làm trường **thu thiếu 50% học phí thật**. Chính sách nào
   khai điều kiện mà máy không kiểm được ⇒ bỏ qua + log, chờ owner chốt nghiệp vụ.
6. **Chặn trên**: tổng giảm không vượt ``base_amount`` (final không âm). Bản cũ cap
   theo "tổng phần trăm ≤ 100" nên chính sách kiểu VND vượt base vẫn lọt.

7. **AI ĐƯỢC CHỌN** (``select_configured_policies``). Officer/kế toán chỉ chọn
   được TRONG TẬP đã cấu hình cho ngành; id ngoài tập ⇒ lỗi có chữ, KHÔNG lọc im
   lặng (lọc im lặng = người dùng tưởng đã giảm mà hoá đơn thì không).
8. **ĐỊNH GIÁ LẠI** (``resolve_repricing``). Ba đường tính lại — bấm "Tính lại
   phí" · đổi ngành · nhà trường đổi giá học kỳ — dùng CHUNG một hàm. Phần chính
   sách tính lại theo base mới; phần MIỄN/GIẢM TAY giữ nguyên số đã duyệt (owner
   chốt 26-07, Hướng A). Trước đó ba nơi trả ba câu trả lời khác nhau.

PENDING_DECISIONS (cần owner chốt, đang fail-closed / bỏ qua có ghi log):
* Tăng ``current_usage`` ở đâu (khi ghi ``FeeAppliedDiscount``? khi thu tiền?) và
  có hoàn lượt khi huỷ phí không.
* Chính sách khai ``applicable_scope`` riêng, hoặc ``target_criteria`` ngoài
  ``priority_types`` (vd vùng/GPA), vẫn BỊ BỎ QUA dù đã gắn cấu hình — chưa chốt
  nghiệp vụ nên fail-closed. (Điều kiện ĐỐI TƯỢNG ƯU TIÊN thì đã chốt: chỉ áp khi
  minh chứng ``verified``. Ngành nặng nhọc thì KHÔNG giảm — Nhà nước cấp bù.)
* ``tuition_discount_service.get_applicable_policies`` (dùng cho trang admin xem
  thử) TỰ ĐỘNG match scope/criteria trên mọi chính sách active — nên nó có thể
  hứa một con số mà luồng thu thật không áp. Chốt xong nghiệp vụ thì gom một
  nguồn; trước đó ĐỪNG nối hai đường lại.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional, Sequence

import structlog

from app.models.tuition_discount_policy import DiscountTypeEnum

log = structlog.get_logger(__name__)

_CENT = Decimal("0.01")

# Nhãn ``source`` trong snapshot của dòng giảm TAY. Máy đọc được (đừng dựa
# ``policy_id IS NULL`` — chính sách bị xoá cũng để lại NULL).
MANUAL_DISCOUNT_SOURCE = "manual_discount"


@dataclass(frozen=True)
class DiscountContext:
    """Ngữ cảnh để xét chính sách có ĐIỀU KIỆN ĐỐI TƯỢNG.

    Chỉ chứa mã đối tượng ưu tiên ĐÃ ĐƯỢC XÁC MINH của hồ sơ (owner chốt 26-07:
    máy chỉ tự giảm khi minh chứng ở trạng thái ``verified`` — mã mới khai
    (``pending``) hoặc bị từ chối thì KHÔNG giảm, tránh giảm cho người chưa chứng
    minh rồi phải truy thu).

    Mã dùng chuẩn TT 05/2021 Phụ lục 01: ``"01"``…``"07"`` (xem
    ``priority_object_config``), KHÔNG phải chuỗi tự đặt.

    CỐ Ý KHÔNG có ``is_heavy_program``: ngành nặng nhọc/độc hại KHÔNG được giảm học
    phí — đó là Nhà nước cấp bù, thí sinh vẫn đóng đủ; cờ ngành
    ``major_program.is_heavy`` chỉ dùng cho phụ lục minh chứng sau này.
    """

    verified_priority_codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DiscountLine:
    """Một dòng giảm giá đã áp. ``policy_id=None`` = giảm tay (ad-hoc)."""

    policy_id: Optional[int]
    amount: Decimal
    snapshot: dict[str, Any]

    def as_tuple(self) -> tuple[Optional[int], Decimal, dict[str, Any]]:
        """Dạng tuple mà ``_write_discount_lines`` đang dùng (giữ tương thích)."""
        return (self.policy_id, self.amount, self.snapshot)


@dataclass(frozen=True)
class FeePricing:
    """Kết quả định giá một khoản phí — output DUY NHẤT của luồng tính phí."""

    base_amount: Decimal
    total_discount: Decimal
    final_amount: Decimal
    lines: list[DiscountLine] = field(default_factory=list)

    @property
    def policy_discount(self) -> Decimal:
        """Phần giảm do CHÍNH SÁCH (không gồm giảm tay)."""
        return sum(
            (line.amount for line in self.lines if line.policy_id is not None),
            Decimal("0"),
        )

    def lines_as_tuples(self) -> list[tuple[Optional[int], Decimal, dict[str, Any]]]:
        return [line.as_tuple() for line in self.lines]


def verified_priority_codes(profile: Any) -> frozenset[str]:
    """Mã đối tượng ưu tiên ĐÃ XÁC MINH của hồ sơ — nguồn duy nhất cho ngữ cảnh giảm giá.

    Đọc ``priority_object_codes`` (thí sinh khai) giao với những mã có minh chứng
    ``priority_object_evidence[mã]["status"] == "verified"``. Khai mà chưa xác minh
    (``pending``) hoặc bị từ chối ⇒ KHÔNG tính (owner chốt 26-07).

    Trả frozenset rỗng khi hồ sơ chưa khai gì — nghĩa là chính sách có điều kiện
    đối tượng sẽ không áp, đúng hướng fail-closed về tiền.
    """
    codes = getattr(profile, "priority_object_codes", None) or []
    evidence = getattr(profile, "priority_object_evidence", None) or {}
    return frozenset(
        str(code)
        for code in codes
        if (evidence.get(str(code)) or {}).get("status") == "verified"
    )


def discount_context_for_profile(profile: Any) -> DiscountContext:
    """``DiscountContext`` từ một hồ sơ — dùng ở mọi luồng tính phí."""
    return DiscountContext(verified_priority_codes=verified_priority_codes(profile))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _is_stackable(policy: Any) -> bool:
    """``is_stackable`` với None = MẶC ĐỊNH CỘNG DỒN.

    Cột có server default TRUE, nhưng một instance vừa tạo trong Python (chưa
    refresh từ DB) mang ``None``. Coi None là "không cộng dồn" sẽ âm thầm bỏ mọi
    chính sách sau chính sách đầu tiên — chỉ dừng khi giá trị TƯỜNG MINH là False.
    """
    value = getattr(policy, "is_stackable", None)
    return True if value is None else bool(value)


def _policy_type_value(policy: Any) -> Optional[str]:
    """Giá trị chuỗi của ``discount_type`` dù nó là Enum hay str.

    SQLAlchemy có thể trả Enum member hoặc chuỗi thô tuỳ cách load/seed, nên đọc
    qua ``.value`` khi có. Không so chuỗi tự viết ở call site — đó là gốc của lỗi
    "10% giảm 10 đồng".
    """
    raw = getattr(policy, "discount_type", None)
    if raw is None:
        return None
    return getattr(raw, "value", raw)


def is_policy_effective(
    policy: Any,
    as_of: date,
    context: Optional["DiscountContext"] = None,
) -> tuple[bool, Optional[str]]:
    """Chính sách có áp được tại ngày ``as_of``? Trả ``(ok, lý_do_loại)``.

    Chỉ kiểm các điều kiện KHÁCH QUAN, kiểm được từ chính bản ghi chính sách:
    còn hoạt động · trong hạn hiệu lực · còn lượt dùng. Lý do được trả về để bên
    gọi log được vì sao một chính sách kế toán tưởng "đã bật" lại không giảm đồng
    nào — im lặng bỏ qua là cách nhanh nhất để mất niềm tin vào số liệu.

    🔴 KHÔNG suy diễn điều kiện từ ``applicable_scope`` / ``target_criteria``.
    Chính sách chỉ được áp khi ĐƯỢC GẮN TƯỜNG MINH cho ngành
    (``offering_academic_info.applied_discount_policy_ids``) — đó là "theo cấu
    hình". Suy diễn kiểu "ngành nặng nhọc thì tự giảm 50%" là SAI nghiệp vụ:
    chính sách nặng nhọc/độc hại là **Nhà nước cấp bù học phí**, thí sinh **vẫn
    phải đóng đủ**; tự trừ vào ``final_amount`` là thu thiếu tiền thật của
    trường. Chính sách nào khai điều kiện mà máy không kiểm được ⇒ bỏ qua + log,
    chờ owner chốt nghiệp vụ (xem PENDING_DECISIONS ở đầu file).
    """
    if not getattr(policy, "is_active", True):
        return False, "inactive"

    valid_from = getattr(policy, "valid_from", None)
    valid_to = getattr(policy, "valid_to", None)
    if valid_from is not None and as_of < valid_from:
        return False, "chua_den_hieu_luc"
    if valid_to is not None and as_of > valid_to:
        return False, "da_het_hieu_luc"

    max_usage = getattr(policy, "max_usage", None)
    if max_usage is not None:
        current = getattr(policy, "current_usage", 0) or 0
        if current >= max_usage:
            return False, "het_luot_su_dung"

    # Phạm vi ngành: KHÔNG suy diễn. Việc "chính sách này áp cho ngành nào" do
    # CẤU HÌNH quyết định (``offering_academic_info.applied_discount_policy_ids``),
    # nên chính sách khai thêm phạm vi riêng mà máy chưa chốt nghiệp vụ ⇒ bỏ qua.
    scope = getattr(policy, "applicable_scope", None)
    if scope and scope != {"all_programs": True}:
        return False, "co_pham_vi_rieng_chua_chot_nghiep_vu"

    criteria = getattr(policy, "target_criteria", None) or {}
    if criteria:
        # Chỉ hỗ trợ điều kiện ĐỐI TƯỢNG ƯU TIÊN (đã chốt). Điều kiện khác
        # (vùng/GPA) chưa chốt nghiệp vụ ⇒ fail-closed.
        unsupported = set(criteria) - {"priority_types"}
        if unsupported:
            return False, "co_dieu_kien_chua_chot_nghiep_vu"
        required = {str(c) for c in (criteria.get("priority_types") or [])}
        if not required:
            return False, "dieu_kien_doi_tuong_rong"
        if context is None:
            return False, "thieu_ngu_canh_doi_tuong"
        if not (required & set(context.verified_priority_codes)):
            return False, "khong_thuoc_doi_tuong_da_xac_minh"

    return True, None


# Mã lý do → chữ tiếng Việt. Ở CẠNH predicate sinh ra mã (``is_policy_effective``)
# nên thêm một lý do mới là thấy ngay phải viết câu giải thích cho người dùng —
# để bảng này ở tầng router/FE thì sớm muộn cũng có mã không ai dịch, và giao
# diện hiện ô tích xám không kèm lý do.
DISCOUNT_SKIP_REASON_TEXT: dict[str, str] = {
    "inactive": "Chính sách đã ngừng hoạt động",
    "chua_den_hieu_luc": "Chưa tới ngày bắt đầu hiệu lực",
    "da_het_hieu_luc": "Đã hết hạn hiệu lực",
    "het_luot_su_dung": "Đã dùng hết số lượt cho phép",
    "co_pham_vi_rieng_chua_chot_nghiep_vu": (
        "Chính sách khai phạm vi riêng — chưa chốt nghiệp vụ nên không áp tự động"
    ),
    "co_dieu_kien_chua_chot_nghiep_vu": (
        "Chính sách khai điều kiện mà hệ thống chưa kiểm được"
    ),
    "dieu_kien_doi_tuong_rong": "Cấu hình đối tượng ưu tiên đang để trống",
    "thieu_ngu_canh_doi_tuong": "Không đọc được đối tượng ưu tiên của hồ sơ",
    "khong_thuoc_doi_tuong_da_xac_minh": (
        "Hồ sơ không thuộc đối tượng ưu tiên đã được xác minh"
    ),
}


def skip_reason_text(reason: Optional[str]) -> Optional[str]:
    """Chữ tiếng Việt cho mã lý do; mã lạ thì trả chính nó (không nuốt thông tin)."""
    if not reason:
        return None
    return DISCOUNT_SKIP_REASON_TEXT.get(reason, reason)


def _policy_sort_key(policy: Any) -> tuple[int, int]:
    """``priority`` giảm dần (cao xét trước), rồi ``id`` tăng cho xác định."""
    priority = getattr(policy, "priority", 0) or 0
    pid = getattr(policy, "id", 0) or 0
    return (-int(priority), int(pid))


def select_configured_policies(
    configured_ids: Sequence[int],
    selected_ids: Optional[Sequence[int]],
) -> list[int]:
    """Tập chính sách sẽ áp = lựa chọn của người dùng GIAO với cấu hình của ngành.

    Owner chốt 26-07: officer/kế toán **chỉ được chọn trong tập đã cấu hình cho
    ngành** — không được tự thêm chính sách ngoài cấu hình. Ở đây là chỗ DUY
    NHẤT quyết định điều đó, để giao diện và luồng thu thật không lệch nhau.

    * ``selected_ids is None`` = người dùng không nêu ý kiến ⇒ áp toàn bộ cấu
      hình (hành vi cũ, giữ nguyên cho mọi caller sẵn có).
    * ``selected_ids == []`` = chọn KHÔNG áp chính sách nào ⇒ tôn trọng.
    * id ngoài cấu hình ⇒ ``ValueError`` (bên gọi đổi thành lỗi HTTP có chữ).
      Lọc im lặng thì người dùng tưởng đã giảm mà hoá đơn lại không giảm.

    Trả về theo THỨ TỰ cấu hình để kết quả xác định, không phụ thuộc thứ tự bấm.
    """
    configured = list(dict.fromkeys(configured_ids or []))
    if selected_ids is None:
        return configured

    selected = list(dict.fromkeys(selected_ids))
    ngoai_cau_hinh = [pid for pid in selected if pid not in configured]
    if ngoai_cau_hinh:
        raise ValueError(
            "Chính sách ưu đãi không nằm trong cấu hình của ngành: "
            + ", ".join(str(pid) for pid in ngoai_cau_hinh)
        )
    return [pid for pid in configured if pid in set(selected)]


def resolve_discounts(
    base_amount: Decimal,
    policies: Sequence[Any],
    *,
    as_of: Optional[date] = None,
    calculated_at: Optional[str] = None,
    context: Optional[DiscountContext] = None,
    selected_by: Optional[int] = None,
) -> tuple[Decimal, list[DiscountLine]]:
    """Tính giảm giá theo CHÍNH SÁCH. Thuần — không DB, không side effect.

    Args:
        base_amount: học phí gốc (canonical) của kỳ.
        policies: các ``TuitionDiscountPolicy`` ĐÃ load (bên gọi query).
        as_of: ngày xét hiệu lực (mặc định hôm nay).
        calculated_at: ISO timestamp ghi vào snapshot (bên gọi truyền để mọi dòng
            trong cùng một lần tính có CÙNG mốc thời gian).
        selected_by: id người TỰ TAY chọn chính sách này (None = áp theo cấu hình
            mặc định của ngành). Ghi vào snapshot để sau này còn truy được ai
            quyết định giảm cho hồ sơ nào.

    Returns:
        ``(total_discount, lines)`` — đã làm tròn tới đồng-xu và chặn trên ở
        ``base_amount``.
    """
    if base_amount <= 0 or not policies:
        return Decimal("0"), []

    as_of = as_of or date.today()
    ordered = sorted(policies, key=_policy_sort_key)

    lines: list[DiscountLine] = []
    total = Decimal("0")

    for policy in ordered:
        ok, reason = is_policy_effective(policy, as_of, context)
        if not ok:
            log.info(
                "discount_policy_skipped",
                policy_id=getattr(policy, "id", None),
                policy_name=getattr(policy, "name", None),
                reason=reason,
                as_of=str(as_of),
            )
            continue

        type_value = _policy_type_value(policy)
        raw_value = Decimal(str(getattr(policy, "discount_value", 0) or 0))
        if type_value == DiscountTypeEnum.PERCENTAGE.value:
            amount = _q(base_amount * raw_value / Decimal("100"))
        elif type_value == DiscountTypeEnum.AMOUNT.value:
            amount = _q(raw_value)
        else:
            # Loại lạ (dữ liệu bẩn / enum mới chưa xử) → KHÔNG đoán.
            log.warning(
                "discount_policy_unknown_type",
                policy_id=getattr(policy, "id", None),
                discount_type=type_value,
            )
            continue

        # Chặn trên: tổng giảm không vượt base (final không âm).
        remaining = base_amount - total
        if amount > remaining:
            log.info(
                "discount_capped_at_base",
                policy_id=getattr(policy, "id", None),
                requested=str(amount),
                capped_to=str(remaining),
            )
            amount = remaining
        if amount <= 0:
            continue

        total += amount
        snapshot = {
            "policy_name": getattr(policy, "name", None),
            "discount_type": type_value,
            "discount_value": str(raw_value),
            "priority": getattr(policy, "priority", 0),
            "is_stackable": _is_stackable(policy),
            "as_of": str(as_of),
            "calculated_at": calculated_at,
        }
        if selected_by is not None:
            snapshot["selected_by"] = selected_by
        lines.append(
            DiscountLine(
                policy_id=getattr(policy, "id", None),
                amount=amount,
                snapshot=snapshot,
            )
        )

        # KHÔNG cộng dồn → áp một mình rồi dừng.
        if not _is_stackable(policy):
            log.info(
                "discount_stop_non_stackable",
                policy_id=getattr(policy, "id", None),
            )
            break

        if total >= base_amount:
            break

    return total, lines


def build_manual_discount_line(
    base_amount: Decimal,
    policy_discount: Decimal,
    target_final_amount: Decimal,
    *,
    reason: Optional[str],
    approved_by: Optional[int],
    calculated_at: Optional[str] = None,
) -> DiscountLine:
    """Dòng giảm TAY để final chạm đúng ``target_final_amount``.

    Giảm tay = ``base − giảm-chính-sách − target`` (KHÔNG phải ``base − target``):
    nếu trừ thẳng từ base thì phần chính sách đã giảm bị trừ hai lần ⇒ giảm quá tay.
    Bên gọi PHẢI kiểm ``target`` nhỏ hơn mức sau giảm hiện hành trước khi gọi
    (``compute_manual_discount_amount`` trả số âm để bên gọi báo lỗi rõ ràng).
    """
    amount = compute_manual_discount_amount(
        base_amount, policy_discount, target_final_amount
    )
    return DiscountLine(
        policy_id=None,
        amount=amount,
        snapshot={
            "source": MANUAL_DISCOUNT_SOURCE,
            "reason": reason,
            "approved_by": approved_by,
            "canonical_amount": str(base_amount),
            "existing_policy_discount": str(policy_discount),
            "target_final_amount": str(target_final_amount),
            "discount_amount": str(amount),
            "calculated_at": calculated_at,
            # Nhãn hiển thị cho builder response (tránh "Unknown" trên giao diện).
            "policy_name": "Miễn/giảm học phí (thủ công)",
            "discount_type": "manual_amount",
            "discount_value": str(amount),
        },
    )


def compute_manual_discount_amount(
    base_amount: Decimal,
    policy_discount: Decimal,
    target_final_amount: Decimal,
) -> Decimal:
    """Số tiền giảm tay cần thiết (có thể ≤ 0 → bên gọi từ chối)."""
    return _q(base_amount - policy_discount - target_final_amount)


def _line_snapshot(line: Any) -> dict[str, Any]:
    return getattr(line, "calculation_snapshot", None) or {}


def is_manual_discount_line(line: Any) -> bool:
    """Dòng giảm TAY? Đọc nhãn ``source`` trong snapshot.

    KHÔNG dựa ``policy_id IS NULL``: cột đó là ``ON DELETE SET NULL``, nên một
    chính sách bị xoá cũng để lại dòng ``policy_id=None`` — dòng đó KHÔNG phải
    quyết định miễn/giảm của con người và không được bảo toàn như giảm tay.
    """
    return _line_snapshot(line).get("source") == MANUAL_DISCOUNT_SOURCE


def resolve_repricing(
    base_amount: Decimal,
    policies: Sequence[Any],
    existing_lines: Sequence[Any],
    *,
    as_of: Optional[date] = None,
    calculated_at: Optional[str] = None,
    context: Optional[DiscountContext] = None,
) -> FeePricing:
    """ĐỊNH GIÁ LẠI một khoản phí ĐÃ TỒN TẠI — nguồn duy nhất cho cả ba đường.

    Ba tình huống khiến giá gốc của một khoản phí đã tạo phải tính lại:

    1. kế toán bấm **"Tính lại phí"** (``recalculate_fee``);
    2. **đổi ngành** có khấu trừ phiếu thu (``reprice_for_major_change``);
    3. nhà trường **đổi giá học phí học kỳ** hàng loạt
       (``recalculate_fees_for_semester_tuition_change``).

    Trước đây ba nơi trả ba câu trả lời khác nhau cho cùng một câu hỏi "khoản
    giảm TAY đã duyệt thì sao?" — hai nơi TỪ CHỐI tính lại, một nơi giữ nguyên
    số. Owner chốt 26-07: **giữ nguyên số tiền đã duyệt ở cả ba**.

    Vì sao giữ nguyên chứ không rescale: giảm tay là quyết định của con người
    cho một hoàn cảnh cụ thể (học bổng, gia cảnh), kèm lý do và người duyệt.
    Trường tăng giá hay thí sinh đổi ngành không làm hoàn cảnh đó thay đổi, và
    máy KHÔNG biết ý định gốc là "giảm 1 triệu" hay "giảm 13,7%" — tự suy sẽ âm
    thầm đổi mức đã có người ký. Bên gọi nên log để kế toán rà lại nếu muốn đổi.

    Còn phần giảm theo CHÍNH SÁCH thì tính lại đầy đủ trên ``base_amount`` mới
    (đúng phần trăm, đúng hiệu lực ngày, đúng cộng dồn) — đó là số máy suy được.

    Args:
        base_amount: học phí gốc MỚI.
        policies: các ``TuitionDiscountPolicy`` đã load (bên gọi query).
        existing_lines: các ``FeeAppliedDiscount`` hiện có của khoản phí.

    Returns:
        ``FeePricing`` với ``lines`` = dòng chính sách tính lại + dòng giảm tay
        giữ nguyên. Dòng ``policy_id`` NULL mà KHÔNG phải giảm tay (chính sách
        đã bị xoá) bị BỎ + log: không còn cơ sở nào để áp tiếp.
    """
    policy_total, lines = resolve_discounts(
        base_amount,
        policies,
        as_of=as_of,
        calculated_at=calculated_at,
        context=context,
    )

    total = policy_total
    for line in existing_lines:
        if not is_manual_discount_line(line):
            if getattr(line, "policy_id", None) is None:
                log.warning(
                    "discount_line_orphan_dropped",
                    fee_id=getattr(line, "fee_id", None),
                    line_id=getattr(line, "id", None),
                    amount=str(getattr(line, "discount_amount", 0) or 0),
                )
            continue

        amount = _q(Decimal(str(getattr(line, "discount_amount", 0) or 0)))
        if amount <= 0:
            continue

        snapshot = dict(_line_snapshot(line))
        remaining = base_amount - total
        if amount > remaining:
            # Giá gốc mới thấp hơn cả mức đã giảm ⇒ cắt cho final không âm. Ghi
            # rõ trong snapshot: kế toán phải thấy mức duyệt đã bị cắt, không
            # phải đoán vì sao con số khác giấy tờ.
            log.warning(
                "manual_discount_capped_on_reprice",
                fee_id=getattr(line, "fee_id", None),
                approved=str(amount),
                capped_to=str(max(remaining, Decimal("0"))),
                new_base=str(base_amount),
            )
            snapshot["capped_from"] = str(amount)
            snapshot["capped_at"] = calculated_at
            amount = max(remaining, Decimal("0"))
            if amount <= 0:
                continue

        total += amount
        lines.append(
            DiscountLine(policy_id=None, amount=amount, snapshot=snapshot)
        )

    return FeePricing(
        base_amount=base_amount,
        total_discount=total,
        final_amount=compute_final_amount(base_amount, total),
        lines=lines,
    )


def compute_final_amount(base_amount: Decimal, total_discount: Decimal) -> Decimal:
    """``final = max(0, base − tổng giảm)`` — một chỗ duy nhất, không lặp lại."""
    return max(Decimal("0"), _q(base_amount - total_discount))


def resolve_fee_pricing(
    base_amount: Decimal,
    policies: Sequence[Any],
    *,
    target_final_amount: Optional[Decimal] = None,
    manual_reason: Optional[str] = None,
    approved_by: Optional[int] = None,
    as_of: Optional[date] = None,
    calculated_at: Optional[str] = None,
    context: Optional[DiscountContext] = None,
    selected_by: Optional[int] = None,
) -> FeePricing:
    """LUỒNG TÍNH PHÍ DUY NHẤT: base → giảm chính sách → giảm tay → final.

    Dùng bởi: tính phí lần đầu, tính lại, xem trước (preview), định giá lại khi đổi
    ngành. Nếu cần thêm một bước định giá mới (phụ phí, ưu đãi theo đợt…), thêm
    Ở ĐÂY để cả bốn đường tự áp dụng.

    ``target_final_amount`` = "học phí áp dụng" do người có thẩm quyền ấn định
    (miễn/giảm tay). Khi có, ``final`` bằng đúng số đó.
    """
    total_discount, lines = resolve_discounts(
        base_amount,
        policies,
        as_of=as_of,
        calculated_at=calculated_at,
        context=context,
        selected_by=selected_by,
    )

    if target_final_amount is not None:
        manual_line = build_manual_discount_line(
            base_amount,
            total_discount,
            target_final_amount,
            reason=manual_reason,
            approved_by=approved_by,
            calculated_at=calculated_at,
        )
        lines.append(manual_line)
        total_discount = total_discount + manual_line.amount

    return FeePricing(
        base_amount=base_amount,
        total_discount=total_discount,
        final_amount=compute_final_amount(base_amount, total_discount),
        lines=lines,
    )
