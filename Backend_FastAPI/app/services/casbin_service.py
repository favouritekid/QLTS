# app/services/casbin_service.py
"""
Casbin Policy Management Service

This service provides high-level operations for managing Casbin policies with:
- Safety validation (prevent locking out admins)
- Batch operations
- Policy analysis
- Role management
"""

import asyncio
import weakref
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone

import casbin
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..casbin_config.policy_templates import (
    POLICY_TEMPLATES,
    SYSTEM_ROLES,
    CRITICAL_POLICIES,
    is_critical_policy,
    is_system_role,
    apply_template,
)
from .. import models


# =============================================================================
# THU HỒI QUYỀN — MỘT NGUỒN CHUẨN
# =============================================================================
#
# `auth_model.conf` khai `p = sub, obj, act, eft` (từ B1). Mọi đường THÊM đã
# chuyển sang bốn trường, nhưng bốn đường THU HỒI vẫn gọi
# ``remove_policy(sub, obj, act)`` với ba đối số — không khớp nổi rule bốn
# trường, nên KHÔNG xoá được gì. Đã đo cả bốn:
#
#   DELETE /policies            -> HTTP 404, xoá 0
#   remove_policies_batch       -> removed=0
#   refresh_role_from_template  -> success=True, policies_after SAI, rule mồ côi
#   delete_role_atomic          -> "deleted successfully", rule mồ côi
#
# Đây là A01 Broken Access Control: một ALLOW cấp nhầm không thu hồi được bằng
# bất kỳ đường nào người vận hành có.
#
# ⚠️ ĐỪNG "sửa" bằng remove_filtered_policy theo BA trường. Nó khớp mọi rule
# cùng ``(sub, obj, act)`` bất kể ``eft``, nên sẽ xoá LUÔN rule ``deny`` đi kèm
# — biến một lỗi "không thu hồi được" thành lỗi "âm thầm MỞ quyền", tệ hơn hẳn.
# Ca `test_xoa_allow_phai_giu_deny` khoá đúng điều này.

EFT_MAC_DINH = "allow"


# ---------------------------------------------------------------------------
# LOCK DÙNG CHUNG CHO MỘT ENFORCER
# ---------------------------------------------------------------------------
#
# `request.app.state.enforcer` là MỘT đối tượng dùng chung cho mọi request.
# Không có lock, hai coroutine đan nhau vẫn mở được quyền dù từng đường đã
# fail-closed. Đo được trên mã đã vá tuần tự:
#
#     xoá ĐƠN gỡ `allow A1` khỏi model rồi hỏng ở adapter;
#     thao tác NHÓM (đang chạy song song) thấy A1 vắng -> xếp `vang_san`
#     -> đi tiếp và xoá `deny`.
#
#     group_result: an_toan=True   vang_san=[allow A1]
#     durable: [allow A1]          FAIL_OPEN
#
# Nhóm báo an toàn trong khi PostgreSQL cuối cùng chỉ còn `allow`.


class KhoaTaiVao:
    """``asyncio.Lock`` nhưng TÁI VÀO ĐƯỢC trong cùng một task.

    Vì sao phải tái vào: cổng cần bao TRỌN đồng bộ → dựng snapshot → hai pha
    thu hồi → hậu điều kiện, mà snapshot được dựng ở NGOÀI helper
    (``delete_role_atomic``, ``refresh_role_from_template``). Đặt lock riêng
    trong helper thì khoảng hở vẫn còn.

    Nhưng nếu người gọi cũng khoá mà lock không tái vào được thì request TREO —
    fail-closed kiểu treo còn tệ hơn. Tái vào theo task giữ được cả hai: người
    gọi khoá rộng, helper vẫn khoá vô điều kiện, và không ai phải nhớ truyền cờ
    — tức không có đường nào "quên khoá" được.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._chu = None
        self._sau = 0

    async def __aenter__(self):
        task = asyncio.current_task()
        if self._sau > 0 and self._chu is task:
            self._sau += 1
            return self
        await self._lock.acquire()
        self._chu = task
        self._sau = 1
        return self

    async def __aexit__(self, *exc):
        self._sau -= 1
        if self._sau <= 0:
            self._sau = 0
            self._chu = None
            self._lock.release()
        return False


_KHOA_ENFORCER: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def khoa_enforcer(enforcer) -> KhoaTaiVao:
    """Lock của RIÊNG một enforcer. Cùng enforcer ⇒ cùng lock.

    Khoá theo đối tượng chứ không phải một lock toàn cục: hai enforcer khác
    nhau (ví dụ trong test) không có lý do gì phải chờ nhau.

    ``asyncio.Lock`` gắn với event loop lần đầu được dùng và NÉM nếu sau đó bị
    dùng ở loop khác. Test tạo loop mới cho mỗi hàm, nên nếu loop đổi thì dựng
    lock mới. Trong tiến trình thật chỉ có một loop nên nhánh ấy không chạy;
    còn một enforcer bị chia sẻ qua hai loop thì vốn đã hỏng sẵn.
    """
    loop = asyncio.get_running_loop()
    cu = _KHOA_ENFORCER.get(enforcer)
    if cu is None or cu[0] is not loop:
        cu = (loop, KhoaTaiVao())
        _KHOA_ENFORCER[enforcer] = cu
    return cu[1]


def chuan_hoa_rule(rule) -> List[str]:
    """(sub, obj, act) hoặc (sub, obj, act, eft) -> rule ĐỦ bốn trường.

    Payload ba trường của admin UI là dạng lịch sử; nó chỉ dựng được policy
    ``allow``, nên chuẩn hoá về ``eft="allow"`` là ĐÚNG ngữ nghĩa của nó — chứ
    không phải một mặc định tuỳ tiện.
    """
    r = [str(x) for x in rule]
    if len(r) == 3:
        r.append(EFT_MAC_DINH)
    if len(r) != 4:
        raise ValueError(
            f"rule policy phải có 3 hoặc 4 trường, nhận {len(r)}: {r!r}"
        )
    return r


async def xoa_rule_chinh_xac(enforcer, rule) -> bool:
    """Xoá ĐÚNG MỘT rule bằng ĐỦ bốn trường. True nếu thật sự xoá được.

    Mọi đường thu hồi phải đi qua đây. Gọi thẳng ``remove_policy`` với ba đối
    số là cách lỗi này phát sinh, và rải ở bốn nơi thì sửa một chỗ sót ba chỗ.
    """
    # Lock ở ĐÂY phủ luôn endpoint xoá ĐƠN (`DELETE /policies`), vì đường ấy
    # cũng đi qua hàm này. Một lượt xoá đơn hỏng ở adapter mà chen vào giữa một
    # thao tác nhóm chính là kịch bản fail-open đã đo được.
    async with khoa_enforcer(enforcer):
        return await enforcer.remove_policy(*chuan_hoa_rule(rule))


def policy_cua_role(enforcer, role: str) -> List[List[str]]:
    """Trạng thái THẬT: mọi rule bốn trường đang thuộc ``role``.

    Dùng để đo HẬU ĐIỀU KIỆN. Counter suy từ ``added`` không nói được gì về
    thứ CÒN LẠI — đó chính là cách ``policies_after`` từng báo 4 trong khi
    thực tế là 6.
    """
    return [list(p) for p in enforcer.get_policy() if p and p[0] == role]


EFT_DENY = "deny"


def rule_con_trong_model(enforcer, rule) -> bool:
    """Rule còn trong MODEL BỘ NHỚ hay không.

    ⚠️ Chỉ nói về bộ nhớ. KHÔNG nói gì về hàng trong PostgreSQL. PyCasbin gỡ
    rule khỏi model TRƯỚC rồi mới gọi adapter, nên adapter hỏng thì hàm trả
    ``False`` trong khi model đã sạch. Đã đo:

        remove_policy(allow) -> False
        MODEL   = [deny]           <- đã mất allow
        DURABLE = [allow, deny]    <- hàng vẫn còn nguyên

    Vì thế "vắng khỏi model" MỘT MÌNH không đủ để kết luận đã thu hồi được.
    Xem ``xoa_nhom_rule_fail_closed``.

    ``has_policy`` là API ĐỒNG BỘ kể cả trên ``AsyncEnforcer`` (định nghĩa ở
    ``AsyncManagementEnforcer``) — đã kiểm. Thiếu ``await`` ở đây không tạo ra
    coroutine truthy.
    """
    return enforcer.has_policy(*chuan_hoa_rule(rule))


async def dong_bo_tu_nguon_ben_vung(enforcer) -> Optional[str]:
    """Nạp lại policy từ NGUỒN BỀN VỮNG (adapter/PostgreSQL) vào model.

    Trả ``None`` nếu đồng bộ được; trả chuỗi mô tả lỗi nếu KHÔNG.

    Vì sao BẮT BUỘC trước mỗi thao tác nhóm: một lượt thu hồi hỏng để lại model
    và CSDL LỆCH NHAU — PyCasbin đã gỡ rule khỏi model rồi mới gọi adapter, nên
    adapter hỏng thì model quên ``allow`` trong khi hàng vẫn nằm trong CSDL.
    Lượt RETRY dựng danh sách rule từ model sẽ chỉ thấy ``deny``, xoá nó, và để
    lại CSDL đúng một hàng ``allow``. Đo được:

        lượt 1:  an_toan=False  MODEL=[deny]  DURABLE=[allow, deny]
        lượt 2:  rules=[deny]   an_toan=True  MODEL=[]  DURABLE=[allow]

    Lượt hai "thành công" và mở quyền. Nói cách khác: chính cơ chế fail-closed
    của lượt trước tạo ra cái bẫy cho lượt sau, nếu lượt sau tin vào model.

    Cùng lý do đó làm ``vang_san`` chỉ an toàn SAU khi đồng bộ: "vắng khỏi
    model" chỉ đồng nghĩa với "vắng trong CSDL" nếu model vừa được nạp lại từ
    CSDL. Không có cổng này thì retry của feature-toggle trả 200 cho một hàng
    ``allow`` vẫn còn nguyên.

    Đồng bộ hỏng thì DỪNG TRƯỚC MỌI MUTATION — không đoán, không "bù" bằng cách
    thêm lại rule: đọc CSDL đã không xong thì mọi suy luận về nó đều là bịa.

    ``load_policy`` là API BẤT ĐỒNG BỘ trên ``AsyncEnforcer`` — đã kiểm; thiếu
    ``await`` ở đây thì hàm trả coroutine và cổng coi như đồng bộ xong trong
    khi chưa đọc gì.
    """
    try:
        async with khoa_enforcer(enforcer):
            await enforcer.load_policy()
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


async def xoa_nhom_rule_fail_closed(
    enforcer, rules, xu_ly_mot_rule, *, da_dong_bo: bool = False
) -> dict:
    """Xoá một NHÓM rule theo thứ tự BẮT BUỘC: non-deny trước, ``deny`` sau.

    Xoá tuần tự theo thứ tự tuỳ ý là FAIL-OPEN, không phải chỉ kém gọn. Với
    cặp ``(allow, deny)`` cùng ``(sub, obj, act)``: nếu xoá ``allow`` hụt mà
    vòng lặp vẫn chạy tiếp rồi xoá ``deny``, quyền hiệu lực đi từ TỪ CHỐI sang
    CHO PHÉP — trạng thái sau còn nguy hiểm hơn lúc chưa làm gì. Đo trên
    enforcer thật: hàm báo ``success=False`` trong khi ``enforce(...)`` trả
    ``True``.

    Nên: pha 1 xoá non-deny; XÁC NHẬN; còn non-deny nào chưa xác nhận thì DỪNG
    và KHÔNG chạm tới bất kỳ rule ``deny`` nào. Pha 2 chỉ chạy khi pha 1 sạch.

    ⚠️ XÁC NHẬN cần HAI điều kiện, vì ranh giới model ↔ CSDL. PyCasbin gỡ rule
    khỏi model TRƯỚC rồi mới gọi adapter; adapter hỏng thì hàm trả ``False``
    nhưng model đã sạch. Một cổng chỉ ĐO MODEL sẽ thấy "xoá xong" rồi đi tiếp
    xoá ``deny`` — và ``deny`` thì xoá được thật. Sau reload, hoặc trên worker
    khác, CSDL chỉ còn ``allow``: quyền lại mở, lần này BỀN VỮNG. Đã đo:

        RESULT.an_toan = True    CALLS = [allow, deny]
        MEMORY         = []      DURABLE = [allow]

    Nên một rule chỉ được coi là đã thu hồi khi handler trả ``True`` VÀ rule
    biến khỏi model. Handler trả ``False`` (hoặc ném lỗi) thì chặn pha ``deny``
    BẤT KỂ model đang thể hiện gì — vì ``False`` chính là cách PyCasbin báo
    adapter hỏng.

    Rule vốn đã VẮNG trong model ngay từ đầu được xếp riêng (``vang_san``):
    không có gì để thu hồi nên không phải thất bại, và không chặn pha sau.
    ⚠️ Điều đó CHỈ đúng sau khi đã đồng bộ model từ CSDL — xem
    ``dong_bo_tu_nguon_ben_vung``. Không có cổng ấy thì "vắng khỏi model" có
    thể là DI CHỨNG của một lượt hỏng trước đó, và retry sẽ báo thành công cho
    một hàng vẫn nằm trong CSDL.

    Cổng đo theo NHÓM chứ không ghép cặp theo ``(sub, obj, act)``: một
    ``allow`` dạng mẫu (``/api/x/*``) che được ``deny`` ở đường cụ thể
    (``/api/x/1``) mà hai bộ ba lại không bằng nhau, nên ghép cặp chính xác sẽ
    lọt đúng ca nguy hiểm nhất. Chặn cả nhóm là chặt hơn cần thiết, và chặt hơn
    về phía an toàn.

    KHÔNG "bù" bằng cách thêm lại ``allow`` khi đang ở trạng thái bất định:
    thêm lại một rule vừa không xoá nổi là đoán mò về nguyên nhân hỏng, và nếu
    chính adapter đang hỏng thì lệnh thêm cũng hỏng nốt — chỉ khác là lần này
    ta đã kịp tuyên bố thành công.

    Args:
        rules: rule ba hoặc bốn trường, chuẩn hoá qua ``chuan_hoa_rule``.
        xu_ly_mot_rule: async callable(rule bốn trường) -> bool, True nếu đã
            xoá. Giá trị trả về là MỘT NỬA điều kiện xác nhận bảo mật, không
            phải số liệu báo cáo: ``False`` chính là cách PyCasbin báo adapter
            hỏng, và nửa kia (rule biến khỏi model) không thay thế được nó.
            Nửa còn lại che chiều ngược: handler khai ``True`` mà rule vẫn sống.
        da_dong_bo: người gọi ĐÃ tự đồng bộ rồi. Chỉ đặt ``True`` khi người gọi
            dựng ``rules`` TỪ MODEL — khi ấy nó buộc phải đồng bộ trước lúc
            dựng, chứ đồng bộ ở đây thì đã muộn: danh sách đã sai rồi. Mặc định
            ``False`` để một người gọi quên thì vẫn được che.

    Returns:
        dict: ``da_xoa``, ``con_song``, ``vang_san``, ``deny_chua_cham``,
        ``an_toan``, ``dong_bo``, ``loi_dong_bo``.
        ``an_toan=False`` nghĩa là pha 2 đã bị chặn — người gọi PHẢI coi đó là
        thất bại, vì nhóm rule mới chỉ bị xoá một phần.
    """
    # Lock bao TRỌN đồng bộ → snapshot → hai pha → hậu điều kiện. Tái vào được
    # nên người gọi đã khoá rộng hơn thì đoạn này không chặn chính nó.
    async with khoa_enforcer(enforcer):
        chuan = [chuan_hoa_rule(r) for r in rules]
        non_deny = [r for r in chuan if r[3] != EFT_DENY]
        deny = [r for r in chuan if r[3] == EFT_DENY]

        if not da_dong_bo:
            loi_dong_bo = await dong_bo_tu_nguon_ben_vung(enforcer)
            if loi_dong_bo is not None:
                # Chưa đọc được CSDL thì chưa biết gì. DỪNG trước mọi mutation.
                return {
                    "an_toan": False,
                    "dong_bo": False,
                    "loi_dong_bo": loi_dong_bo,
                    "da_xoa": [],
                    "con_song": chuan,
                    "vang_san": [],
                    "deny_chua_cham": deny,
                }

        async def _pha(nhom):
            """Chạy một pha, phân loại từng rule thành ba nhóm rời nhau."""
            da_xac_nhan, chua_xac_nhan, vang_san = [], [], []
            for r in nhom:
                von_co = rule_con_trong_model(enforcer, r)
                ket_qua = await xu_ly_mot_rule(r)
                if not von_co:
                    # Vốn đã không có trong model: không có gì để thu hồi, nên
                    # không phải thất bại và KHÔNG chặn pha sau. Idempotent.
                    vang_san.append(r)
                elif ket_qua and not rule_con_trong_model(enforcer, r):
                    # HAI điều kiện, thiếu một là hở:
                    #  - thiếu `ket_qua`  -> adapter hỏng vẫn bị coi là xong;
                    #  - thiếu phép đo    -> handler khai man vẫn được tin.
                    da_xac_nhan.append(r)
                else:
                    chua_xac_nhan.append(r)
            return da_xac_nhan, chua_xac_nhan, vang_san

        da1, chua1, vang1 = await _pha(non_deny)
        if chua1 and deny:
            # DỪNG. Không chạm deny. Xem docstring: đây chính là cửa fail-open.
            return {
                "an_toan": False,
                "dong_bo": True,
                "loi_dong_bo": None,
                "da_xoa": da1,
                "con_song": chua1,
                "vang_san": vang1,
                "deny_chua_cham": deny,
            }

        da2, chua2, vang2 = await _pha(deny)

        return {
            "an_toan": True,
            "dong_bo": True,
            "loi_dong_bo": None,
            "da_xoa": da1 + da2,
            # `chua2` (deny xoá hụt) là fail-CLOSED — không mở quyền — nhưng vẫn là
            # việc chưa xong, nên phải vào `con_song` để người gọi báo thất bại.
            "con_song": chua1 + chua2,
            "vang_san": vang1 + vang2,
            "deny_chua_cham": [],
        }


class ValidationSeverity(str, Enum):
    """Severity levels for policy validation warnings."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PolicyValidationResult:
    """Result of policy validation check."""
    is_valid: bool
    is_safe: bool
    severity: ValidationSeverity
    warnings: List[str]
    affected_users: List[int]


@dataclass
class PolicyRule:
    """Represents a single Casbin policy rule."""
    subject: str
    object: str
    action: str


class CasbinPolicyService:
    """Service for managing Casbin policies with safety checks."""

    def __init__(self, db: AsyncSession, enforcer: casbin.AsyncEnforcer):
        """
        Initialize Casbin service.

        Args:
            db: Database session
            enforcer: Casbin enforcer instance
        """
        self.db = db
        self.enforcer = enforcer

    # =========================================================================
    # ROLE MANAGEMENT
    # =========================================================================

    async def get_all_roles(self) -> List[dict]:
        """
        Get all roles with their metadata.

        Returns:
            List of role dictionaries with:
            - name: Role identifier (e.g., "role:admin")
            - display_name: Human-readable name
            - description: Role description
            - is_system_role: Whether this is a core system role
            - policy_count: Number of policies for this role
        """
        roles_info = []

        # Get all unique subjects from policies
        all_policies = self.enforcer.get_policy()
        role_subjects = set(policy[0] for policy in all_policies if policy[0].startswith("role:"))

        # Add system roles info
        for system_role in SYSTEM_ROLES:
            policy_count = sum(1 for p in all_policies if p[0] == system_role["name"])
            roles_info.append({
                **system_role,
                "policy_count": policy_count,
            })

        # Add custom roles (roles not in SYSTEM_ROLES)
        system_role_names = {r["name"] for r in SYSTEM_ROLES}
        custom_roles = role_subjects - system_role_names

        for role_name in custom_roles:
            policy_count = sum(1 for p in all_policies if p[0] == role_name)
            roles_info.append({
                "name": role_name,
                "display_name": role_name.replace("role:", "").title(),
                "description": f"Custom role: {role_name}",
                "is_system_role": False,
                "template_id": None,
                "policy_count": policy_count,
            })

        return roles_info

    async def get_role_policies(self, role: str) -> List[PolicyRule]:
        """
        Get all policies for a specific role.

        Args:
            role: Role name (e.g., "role:manager")

        Returns:
            List of PolicyRule objects
        """
        all_policies = self.enforcer.get_policy()
        role_policies = [
            PolicyRule(subject=p[0], object=p[1], action=p[2])
            for p in all_policies
            if p[0] == role
        ]
        return role_policies

    # =========================================================================
    # USER ROLE ASSIGNMENT (g-rules)
    # =========================================================================

    async def assign_role_to_user(self, user_id: int, role: str) -> bool:
        """
        Assign a role to a user (create g-rule mapping user:ID -> role:NAME).

        Args:
            user_id: User ID
            role: Role name (e.g., "officer", "manager") - WITHOUT "role:" prefix

        Returns:
            True if assignment was created, False if already exists
        """
        user_subject = f"user:{user_id}"
        role_subject = f"role:{role}"
        return await self.enforcer.add_grouping_policy(user_subject, role_subject)

    async def remove_user_roles(self, user_id: int) -> int:
        """
        Remove ALL role assignments for a user.

        Args:
            user_id: User ID

        Returns:
            Number of role assignments removed
        """
        user_subject = f"user:{user_id}"
        removed_count = 0

        # Get all grouping policies (g-rules)
        # We filter manually because get_roles_for_user() might return inherited roles
        all_grouping = self.enforcer.get_grouping_policy()
        user_rules = [p for p in all_grouping if p[0] == user_subject]

        for rule in user_rules:
            # rule is (user_subject, role_subject)
            role_subject = rule[1]
            success = await self.enforcer.remove_grouping_policy(user_subject, role_subject)
            if success:
                removed_count += 1

        return removed_count

    # =========================================================================
    # POLICY VALIDATION
    # =========================================================================

    async def validate_policy_addition(
        self,
        subject: str,
        obj: str,
        action: str
    ) -> PolicyValidationResult:
        """
        Validate adding a new policy.

        Args:
            subject: Policy subject (e.g., "role:custom")
            obj: Resource path (e.g., "/api/leads/*")
            action: HTTP method or regex (e.g., "GET", ".*")

        Returns:
            PolicyValidationResult with warnings
        """
        warnings = []
        severity = ValidationSeverity.INFO

        # Check if policy already exists
        existing_policies = self.enforcer.get_policy()
        if [subject, obj, action] in existing_policies:
            return PolicyValidationResult(
                is_valid=False,
                is_safe=True,
                severity=ValidationSeverity.WARNING,
                warnings=["Policy already exists"],
                affected_users=[],
            )

        # Warn about overly permissive policies
        if obj == "/*" and action == ".*":
            warnings.append(
                "This grants full access to all resources. "
                "Only use for administrator roles."
            )
            severity = ValidationSeverity.WARNING

        # Warn about wildcard access to sensitive paths
        if "/api/admin" in obj and action == ".*":
            warnings.append(
                "This grants full access to admin endpoints. "
                "Ensure this is intentional."
            )
            severity = ValidationSeverity.WARNING

        return PolicyValidationResult(
            is_valid=True,
            is_safe=True,
            severity=severity,
            warnings=warnings,
            affected_users=[],
        )

    async def validate_policy_removal(
        self,
        subject: str,
        obj: str,
        action: str
    ) -> PolicyValidationResult:
        """
        Validate removing a policy with STRICT safety checks.

        Args:
            subject: Policy subject
            obj: Resource path
            action: HTTP method or regex

        Returns:
            PolicyValidationResult with safety status
        """
        warnings = []
        severity = ValidationSeverity.INFO

        # CRITICAL: Check if this is a protected policy
        if is_critical_policy(subject, obj, action):
            return PolicyValidationResult(
                is_valid=False,
                is_safe=False,
                severity=ValidationSeverity.CRITICAL,
                warnings=[
                    "⛔ CRITICAL: This is a system-critical policy and cannot be removed. "
                    "Removing this policy will lock all administrators out of the system!"
                ],
                affected_users=[],
            )

        # Check if this is the last admin wildcard policy
        if subject == "role:admin":
            admin_policies = [
                p for p in self.enforcer.get_policy()
                if p[0] == "role:admin"
            ]
            if len(admin_policies) == 1:
                warnings.append(
                    "⚠️ WARNING: This is the last policy for role:admin. "
                    "Removing it may lock administrators out."
                )
                severity = ValidationSeverity.CRITICAL

        # Get affected users (users who have this role)
        affected_users = await self._get_affected_users_by_role(subject)

        if len(affected_users) > 10:
            warnings.append(
                f"This change will affect {len(affected_users)} users with role {subject}"
            )
            severity = ValidationSeverity.WARNING

        return PolicyValidationResult(
            is_valid=True,
            is_safe=(severity != ValidationSeverity.CRITICAL),
            severity=severity,
            warnings=warnings,
            affected_users=affected_users,
        )

    async def _get_affected_users_by_role(self, role_subject: str) -> List[int]:
        """
        Get list of user IDs who have a specific role.

        Args:
            role_subject: Role identifier (e.g., "role:manager")

        Returns:
            List of user IDs
        """
        # Get grouping policies (user-role assignments)
        grouping_policies = self.enforcer.get_grouping_policy()

        # Extract role name from subject (e.g., "role:manager" -> "manager")
        if not role_subject.startswith("role:"):
            return []

        role_name = role_subject.replace("role:", "")

        # Find all users with this role from DB
        result = await self.db.execute(
            select(models.User.id).where(models.User.role == role_name)
        )
        user_ids = [row[0] for row in result.all()]

        return user_ids

    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================

    async def add_policies_batch(
        self,
        policies: List[Tuple[str, ...]],
        validate: bool = True,
        template_id: Optional[str] = None,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Add multiple policies in a batch with validation and template tracking.

        Args:
            policies: List of policy tuples. Each entry is either
                ``(subject, object, action)`` (3-tuple — eft defaults to
                ``"allow"`` for backward compatibility with admin UI
                payloads) or ``(subject, object, action, eft)`` (4-tuple,
                produced by ``apply_template`` post-B1 deny-first).
            validate: Whether to validate before adding.
            template_id: Template ID for tracking (optional).
            applied_by: User ID who applied this (optional).

        Returns:
            Dictionary with:
            - added: Number of policies successfully added
            - skipped: Number of policies skipped (duplicates)
            - errors: List of error messages
            - warnings: List of warnings
        """
        added = 0
        skipped = 0
        errors = []
        warnings = []
        # Track which policies were added for template tracking — keep
        # the 4-field shape so the SQL UPDATE matches v3 explicitly and
        # never touches a peer (sub, obj, act) row of opposite eft.
        added_policies: List[Tuple[str, str, str, str]] = []

        for entry in policies:
            if len(entry) == 3:
                subject, obj, action = entry
                eft = "allow"
            elif len(entry) == 4:
                subject, obj, action, eft = entry
            else:
                errors.append(
                    f"Invalid policy tuple length {len(entry)} (expected 3 or 4): {entry!r}"
                )
                continue

            # Validate if requested. Validation is eft-agnostic — the
            # checks (duplicate, conflict, critical) key on (subject,
            # object, action). A deny variant of an existing allow rule
            # is intentionally NOT a duplicate.
            if validate:
                validation = await self.validate_policy_addition(subject, obj, action)
                if not validation.is_valid:
                    skipped += 1
                    warnings.extend(validation.warnings)
                    continue

                warnings.extend(validation.warnings)

            # Add policy. casbin.AsyncEnforcer.add_policy accepts the
            # eft as the 4th positional argument; the canonical
            # auth_model.conf since B1 declares
            #   p = sub, obj, act, eft.
            try:
                async with khoa_enforcer(self.enforcer):
                    success = await self.enforcer.add_policy(
                        subject, obj, action, eft
                    )
                if success:
                    added += 1
                    added_policies.append((subject, obj, action, eft))
                else:
                    skipped += 1
                    warnings.append(
                        f"Policy already exists: {subject} {obj} {action} {eft}"
                    )
            except Exception as e:
                errors.append(
                    f"Failed to add policy {subject} {obj} {action} {eft}: {str(e)}"
                )

        # Update template tracking for added policies
        if added_policies and template_id:
            await self._update_template_tracking(added_policies, template_id, applied_by)

        return {
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "warnings": warnings,
        }

    async def _update_template_tracking(
        self,
        policies: List[Tuple[str, str, str, str]],
        template_id: str,
        applied_by: Optional[int] = None
    ) -> None:
        """
        Update template tracking columns for policies.

        This is called after policies are added via enforcer to set:
        - template_id: Which template this policy came from
        - applied_at: When this policy was applied
        - applied_by: User ID who applied this policy

        IMPORTANT: We use AsyncSessionLocal instead of self.db because:
        - Casbin enforcer.add_policy() uses its own adapter with its own session
        - The DI session (self.db) is in a different transaction and can't see
          the row that enforcer committed
        - We need a fresh session that starts AFTER enforcer's commit

        Args:
            policies: List of ``(subject, object, action, eft)`` tuples
                (B1 4-field shape — eft is included in the WHERE clause
                so allow/deny variants of the same (sub, obj, act) get
                their own tracking row, never collide).
            template_id: Template identifier
            applied_by: User ID (optional)
        """
        from app.database import AsyncSessionLocal
        import logging
        log = logging.getLogger(__name__)

        try:
            # Use a fresh session to see the rows committed by enforcer
            async with AsyncSessionLocal() as fresh_session:
                for subject, obj, action, eft in policies:
                    result = await fresh_session.execute(
                        text("""
                            UPDATE casbin_rule
                            SET template_id = :template_id,
                                applied_at = :applied_at,
                                applied_by = :applied_by
                            WHERE ptype = 'p'
                              AND v0 = :subject
                              AND v1 = :obj
                              AND v2 = :action
                              AND v3 = :eft
                              AND template_id IS NULL
                        """),
                        {
                            "template_id": template_id,
                            # Naive UTC: asyncpg's TIMESTAMP WITHOUT TIME ZONE
                            # column rejects tz-aware values, so strip the
                            # tz after using the non-deprecated constructor.
                            "applied_at": datetime.now(timezone.utc).replace(tzinfo=None),
                            "applied_by": applied_by,
                            "subject": subject,
                            "obj": obj,
                            "action": action,
                            "eft": eft,
                        }
                    )
                    log.info(f"Tracking UPDATE for {subject} {obj} {action} {eft}: rowcount={result.rowcount}")
                
                # Commit the tracking update
                await fresh_session.commit()
                log.info(f"✅ Tracking columns committed for {len(policies)} policies")
        except Exception as e:
            # Non-critical: don't fail if tracking update fails
            # This can happen if tracking columns don't exist (e.g., migration not applied)
            # Just log and continue - the policy was already added by enforcer
            log.warning(f"⚠️ Failed to update tracking columns: {e}")

    async def remove_policies_batch(
        self,
        policies: List[Tuple[str, ...]],
        validate: bool = True,
        force: bool = False
    ) -> dict:
        """
        Remove multiple policies in a batch with safety checks.

        Args:
            policies: List of (subject, object, action) HOẶC
                (subject, object, action, eft) tuples. Tuple ba trường được
                chuẩn hoá thành ``eft="allow"`` — xem ``chuan_hoa_rule``.
                Việc xoá LUÔN gọi ``remove_policy`` với ĐỦ bốn trường; ba đối
                số không khớp nổi rule bốn trường nên không xoá được gì.
            validate: Whether to validate before removing
            force: Skip safety checks (DANGEROUS - admin override only)

        Returns:
            Dictionary with removal results
        """
        removed = 0
        blocked = 0
        errors = []
        warnings = []

        async def xu_ly(rule):
            nonlocal removed, blocked
            subject, obj, action = rule[0], rule[1], rule[2]
            # Validate if requested
            if validate and not force:
                validation = await self.validate_policy_removal(
                    subject, obj, action
                )
                if not validation.is_safe:
                    blocked += 1
                    errors.append(f"Blocked for safety: {subject} {obj} {action}")
                    warnings.extend(validation.warnings)
                    return False

                warnings.extend(validation.warnings)

            # Remove policy
            try:
                if await xoa_rule_chinh_xac(self.enforcer, rule):
                    removed += 1
                    return True
                warnings.append(
                    f"Policy not found: {' '.join(chuan_hoa_rule(rule))}"
                )
                return False
            except Exception as e:
                errors.append(
                    f"Failed to remove policy {subject} {obj} {action}: {str(e)}"
                )
                return False

        # Thứ tự non-deny -> deny do helper chung giữ. Vòng `for` phẳng ở đây
        # từng xoá `deny` sau khi `allow` xoá hụt, tức MỞ quyền.
        kq = await xoa_nhom_rule_fail_closed(self.enforcer, policies, xu_ly)
        if kq["loi_dong_bo"] is not None:
            errors.append(
                f"KHÔNG đồng bộ được policy từ CSDL trước khi xoá, nên chưa "
                f"chạm vào rule nào: {kq['loi_dong_bo']}"
            )
        elif not kq["an_toan"]:
            errors.append(
                f"DỪNG fail-closed: {len(kq['con_song'])} rule non-deny chưa "
                f"xoá được, nên {len(kq['deny_chua_cham'])} rule deny KHÔNG bị "
                f"chạm tới — xoá deny khi allow còn sống là MỞ quyền."
            )

        return {
            "removed": removed,
            "blocked": blocked,
            "errors": errors,
            "warnings": warnings,
            # ĐO enforcer. Người gọi phải dùng `con_song` thay cho phép trừ
            # `len - removed`: rule vốn đã không tồn tại làm phép trừ báo động
            # giả, còn rule bị chặn/ném lỗi thì phép trừ lại đếm hụt.
            "da_xoa": kq["da_xoa"],
            "con_song": kq["con_song"],
            # Rule vốn đã vắng: không phải thất bại, nhưng cũng không phải
            # "đã xoá" — tách riêng để người gọi không đếm nhầm vào `removed`.
            "vang_san": kq["vang_san"],
            "deny_chua_cham": kq["deny_chua_cham"],
            "an_toan": kq["an_toan"],
            "dong_bo": kq["dong_bo"],
            "loi_dong_bo": kq["loi_dong_bo"],
        }

    # =========================================================================
    # TEMPLATE OPERATIONS
    # =========================================================================

    async def apply_template_to_role(
        self,
        template_id: str,
        role: str,
        validate: bool = True,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Apply a policy template to a role.

        Args:
            template_id: Template identifier (e.g., "officer")
            role: Role name (e.g., "role:custom")
            validate: Whether to validate before applying
            applied_by: User ID who applied this template (for audit trail)

        Returns:
            Dictionary with application results
        """
        try:
            # Get policies from template
            template_policies = apply_template(template_id, role)

            # Convert to 4-tuples (subject, object, action, eft) for the
            # batch operation. ``apply_template`` since B1 always
            # populates ``eft`` (default "allow", explicit "deny" for
            # accountant admission state-machine guards).
            policies_tuples = [
                (p["subject"], p["object"], p["action"], p["eft"])
                for p in template_policies
            ]

            # Apply batch with template tracking
            result = await self.add_policies_batch(
                policies_tuples,
                validate=validate,
                template_id=template_id,
                applied_by=applied_by
            )

            return {
                **result,
                "template_id": template_id,
                "role": role,
                "template_policy_count": len(template_policies),
            }

        except KeyError:
            return {
                "added": 0,
                "skipped": 0,
                "errors": [f"Template not found: {template_id}"],
                "warnings": [],
            }

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    async def get_policy_count(self) -> dict:
        """
        Get count statistics for policies.

        Returns:
            Dictionary with:
            - total_policies: Total number of policies
            - total_roles: Number of unique roles
            - total_grouping_policies: Number of user-role assignments
        """
        all_policies = self.enforcer.get_policy()
        grouping_policies = self.enforcer.get_grouping_policy()

        unique_roles = set(p[0] for p in all_policies if p[0].startswith("role:"))

        return {
            "total_policies": len(all_policies),
            "total_roles": len(unique_roles),
            "total_grouping_policies": len(grouping_policies),
        }

    # =========================================================================
    # ADVANCED PERMISSION TOOLS
    # =========================================================================

    async def get_subjects_for_permission(self, obj: str, act: str) -> List[str]:
        """
        ✅ PATCHED FOR DoS (v15):
        Reverse permission lookup - Find all roles that can access a resource.

        SECURITY FIX:
        - Only loops through ROLES (not individual users)
        - Casbin's enforce() automatically handles role inheritance
        - Prevents DoS attack where 50k+ users could crash server

        Args:
            obj: Resource path (e.g., "/api/leads", "/api/admin/users")
            act: HTTP method (e.g., "GET", "POST", ".*")

        Returns:
            List of roles (e.g., ["role:admin", "role:manager"])

        Example:
            >>> await get_subjects_for_permission("/api/leads", "GET")
            ["role:admin", "role:manager", "role:officer"]

        PERFORMANCE:
            - OLD: O(n) where n = all users + roles (50,000+ iterations) ⚠️
            - NEW: O(r) where r = number of roles (~10 iterations) ✅
            - Speedup: ~5000x for systems with 50k users
        """
        allowed_subjects = []

        # CHỈ LẤY CÁC VAI TRÒ (VÀI CHỤC ROLES)
        # This returns only roles, not individual users - preventing DoS
        # Note: get_all_roles() is synchronous in pycasbin
        all_roles = self.enforcer.get_all_roles()

        # CHỈ LẶP QUA CÁC VAI TRÒ
        # Casbin's enforce() automatically handles role inheritance
        for role in all_roles:
            is_allowed = self.enforcer.enforce(role, obj, act)
            if is_allowed:
                allowed_subjects.append(role)

        return sorted(list(set(allowed_subjects)))

    # =========================================================================
    # TEMPLATE DRIFT DETECTION & SYNC (Phase 4 Fix)
    # Reference: AUTHORIZATION_DECISIONS.md Decision 14
    # =========================================================================

    async def detect_template_drift(self, role: str, template_id: str) -> dict:
        """
        Detect drift between template definition and actual DB policies.

        This is critical for audit and production maintenance.
        Drift can occur when:
        - Policies are added via UI without template
        - Policies are deleted manually
        - Template is updated but DB not synced

        Args:
            role: Role name (e.g., "role:officer")
            template_id: Template identifier (e.g., "officer")

        Returns:
            Dictionary with:
            - has_drift: True if template != DB
            - missing_in_db: Policies in template but not in DB
            - extra_in_db: Policies in DB but not in template
            - drift_percentage: How much drift (0-100%)
            - template_count: Number of policies in template
            - db_count: Number of policies in DB for this role
        """
        try:
            # Get template policies
            template_policies = apply_template(template_id, role)
            template_set = set(
                (p["subject"], p["object"], p["action"])
                for p in template_policies
            )

            # Get DB policies for this role
            all_policies = self.enforcer.get_policy()
            db_policies_for_role = [
                (p[0], p[1], p[2])
                for p in all_policies
                if p[0] == role
            ]
            db_set = set(db_policies_for_role)

            # Calculate drift
            missing_in_db = template_set - db_set
            extra_in_db = db_set - template_set

            total_unique = len(template_set | db_set)
            drift_count = len(missing_in_db) + len(extra_in_db)
            drift_percentage = (drift_count / total_unique * 100) if total_unique > 0 else 0

            return {
                "has_drift": bool(missing_in_db or extra_in_db),
                "missing_in_db": [
                    {"subject": s, "object": o, "action": a}
                    for s, o, a in missing_in_db
                ],
                "extra_in_db": [
                    {"subject": s, "object": o, "action": a}
                    for s, o, a in extra_in_db
                ],
                "drift_percentage": round(drift_percentage, 2),
                "template_count": len(template_set),
                "db_count": len(db_set),
                "role": role,
                "template_id": template_id,
            }

        except KeyError:
            # Handle special template IDs gracefully
            if template_id == "_legacy":
                # Legacy policies have no template to compare - not an error
                return {
                    "has_drift": False,
                    "info": "Legacy policies - no template to compare. Consider migrating to a proper template.",
                    "missing_in_db": [],
                    "extra_in_db": [],
                    "drift_percentage": 0,
                    "template_count": 0,
                    "db_count": 0,
                    "role": role,
                    "template_id": template_id,
                }
            elif template_id == "_manual":
                # Manual policies are intentionally outside templates
                return {
                    "has_drift": False,
                    "info": "Manual policies - added via UI, not linked to any template.",
                    "missing_in_db": [],
                    "extra_in_db": [],
                    "drift_percentage": 0,
                    "template_count": 0,
                    "db_count": 0,
                    "role": role,
                    "template_id": template_id,
                }
            # Unknown template - actual error
            return {
                "has_drift": True,
                "error": f"Template not found: {template_id}",
                "missing_in_db": [],
                "extra_in_db": [],
                "drift_percentage": 100.0,
                "template_count": 0,
                "db_count": 0,
                "role": role,
                "template_id": template_id,
            }

    async def detect_all_drift(self) -> dict:
        """
        Detect drift for all system roles.

        Returns:
            Dictionary with drift status for each role and overall health.
        """
        results = {}
        total_drift = 0
        roles_with_drift = 0

        for system_role in SYSTEM_ROLES:
            role_name = system_role["name"]
            template_id = system_role.get("template_id")

            if template_id:
                drift = await self.detect_template_drift(role_name, template_id)
                results[role_name] = drift

                if drift["has_drift"]:
                    roles_with_drift += 1
                    total_drift += drift["drift_percentage"]

        return {
            "roles": results,
            "summary": {
                "total_roles_checked": len(results),
                "roles_with_drift": roles_with_drift,
                "average_drift_percentage": round(total_drift / len(results), 2) if results else 0,
                "health_status": "HEALTHY" if roles_with_drift == 0 else "DRIFT_DETECTED",
            }
        }

    async def refresh_role_from_template(
        self,
        role: str,
        template_id: str,
        force: bool = False,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Force reset role to match template exactly.

        WARNING: This will:
        - Remove ALL current policies for the role
        - Apply fresh policies from template
        - Any manual additions will be LOST

        Args:
            role: Role name (e.g., "role:officer")
            template_id: Template identifier (e.g., "officer")
            force: Must be True to execute (safety check)
            applied_by: User ID who triggered this refresh (for audit trail)

        Returns:
            Dictionary with operation results
        """
        if not force:
            return {
                "success": False,
                "error": "Safety check: Set force=True to confirm destructive operation",
                "hint": "This will remove ALL current policies for the role and apply template fresh",
            }

        # Prevent refresh of admin role without extra safety
        if role == "role:admin" and not is_system_role(role):
            return {
                "success": False,
                "error": "Cannot refresh admin role - too dangerous",
            }

        try:
            # ĐỒNG BỘ TRƯỚC KHI DỰNG DANH SÁCH. Danh sách dưới đây lấy TỪ MODEL,
            # nên nếu model đang lệch với CSDL (di chứng một lượt hỏng trước)
            # thì mọi thứ sau đó thao tác trên một bức tranh sai — kể cả phần
            # fail-closed. Đồng bộ SAU khi dựng danh sách là vô nghĩa.
            # `current_policies` dựng TỪ MODEL ở trong vùng này, nên lock phải bao cả
            # lúc dựng — khoá riêng trong helper thì snapshot đã kịp cũ.
            async with khoa_enforcer(self.enforcer):
                loi_dong_bo = await dong_bo_tu_nguon_ben_vung(self.enforcer)
                if loi_dong_bo is not None:
                    return {
                        "success": False,
                        "error": (
                            "refresh KHÔNG chạy: không đồng bộ được policy từ CSDL "
                            f"nên chưa chạm vào rule nào — {loi_dong_bo}"
                        ),
                        "role": role,
                        "template_id": template_id,
                        "dong_bo": False,
                        "loi_dong_bo": loi_dong_bo,
                    }

                # Get current policies before delete (for audit log)
                all_policies = self.enforcer.get_policy()
                current_policies = [p for p in all_policies if p[0] == role]
                current_count = len(current_policies)

                # Remove all policies for this role — bằng ĐỦ rule hiện có, gồm
                # `eft`. Bản cũ chỉ truyền `policy[0..2]` nên không xoá được gì,
                # rồi vẫn áp template mới lên trên: rule cũ thành MỒ CÔI và người
                # vận hành tin là đã bị xoá.
                removed = 0
                giu_co_y = []

                async def xu_ly(policy):
                    nonlocal removed
                    subject, obj, action = policy[0], policy[1], policy[2]

                    # Skip critical policies
                    if is_critical_policy(subject, obj, action):
                        giu_co_y.append(chuan_hoa_rule(policy))
                        return False

                    if await xoa_rule_chinh_xac(self.enforcer, policy):
                        removed += 1
                        return True
                    return False

                # Thứ tự non-deny -> deny do helper chung giữ.
                kq = await xoa_nhom_rule_fail_closed(
                    self.enforcer, current_policies, xu_ly, da_dong_bo=True
                )

                # HẬU ĐIỀU KIỆN — kiểm TRƯỚC khi áp template.
                # Kiểm SAU là sai: template có thể chứa đúng rule vừa bị xoá, nên
                # một rule được xoá RỒI RE-ADD ĐÚNG sẽ bị tính nhầm là "còn sót".
                # Ghi nhận thất bại ngay tại chỗ xoá thì không có chỗ cho nhầm lẫn.
                #
                # `giu_co_y` là giữ CÓ CHỦ Ý nên không tính là thất bại — nhưng nếu
                # nó chặn pha deny (`an_toan=False`) thì refresh vẫn DỞ DANG, phải
                # báo thất bại chứ không được im lặng bỏ qua nhóm deny.
                xoa_that_bai = [r for r in kq["con_song"] if r not in giu_co_y]
                if xoa_that_bai or not kq["an_toan"]:
                    return {
                        "success": False,
                        "error": (
                            "refresh KHÔNG hoàn tất: không xoá được rule cũ — "
                            "quyền cũ vẫn có hiệu lực"
                        ),
                        "role": role,
                        "template_id": template_id,
                        "policies_removed": removed,
                        "policies_before": current_count,
                        "policies_added": 0,
                        "policies_after": len(policy_cua_role(self.enforcer, role)),
                        "policies_xoa_that_bai": xoa_that_bai,
                        "policies_deny_chua_cham": kq["deny_chua_cham"],
                        "an_toan": kq["an_toan"],
                        "warnings": [],
                    }

                # Apply template fresh (with template tracking)
                result = await self.apply_template_to_role(
                    template_id, role, validate=False, applied_by=applied_by
                )

                # `policies_after` phải ĐO enforcer, không suy từ `added`:
                # `result["added"]` không nhìn vào enforcer, nên từng báo 4 trong
                # khi thực tế còn 6.
                sau = policy_cua_role(self.enforcer, role)
                return {
                    "success": True,
                    "role": role,
                    "template_id": template_id,
                    "policies_removed": removed,
                    "policies_before": current_count,
                    "policies_added": result.get("added", 0),
                    "policies_after": len(sau),
                    "policies_giu_co_y": giu_co_y,
                    "warnings": result.get("warnings", []),
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "role": role,
                "template_id": template_id,
            }

    async def sync_all_roles_from_templates(self, dry_run: bool = True) -> dict:
        """
        Sync all system roles to match their templates.

        Args:
            dry_run: If True, only report what would change (default: True)

        Returns:
            Dictionary with sync results for each role
        """
        results = {}

        for system_role in SYSTEM_ROLES:
            role_name = system_role["name"]
            template_id = system_role.get("template_id")

            if not template_id:
                results[role_name] = {"skipped": True, "reason": "No template defined"}
                continue

            # Skip admin to prevent lockout
            if role_name == "role:admin":
                results[role_name] = {"skipped": True, "reason": "Admin role not synced for safety"}
                continue

            # Detect drift first
            drift = await self.detect_template_drift(role_name, template_id)

            if not drift["has_drift"]:
                results[role_name] = {"skipped": True, "reason": "No drift detected"}
                continue

            if dry_run:
                results[role_name] = {
                    "dry_run": True,
                    "would_remove": len(drift["extra_in_db"]),
                    "would_add": len(drift["missing_in_db"]),
                    "drift": drift,
                }
            else:
                sync_result = await self.refresh_role_from_template(
                    role_name, template_id, force=True
                )
                results[role_name] = sync_result

        return {
            "dry_run": dry_run,
            "results": results,
            "hint": "Set dry_run=False to apply changes" if dry_run else "Changes applied",
        }
