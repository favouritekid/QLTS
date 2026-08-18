"""Dựng SÁU persona smoke trên `qlts_smoke` — và chỉ persona, không gì khác.

Hai việc tách bạch, cố ý không gộp:

* ``verify_foundation()`` — **chỉ XÁC MINH**. Đơn vị, `manager01`/`accountant01`,
  danh mục `consultation_status` và `PaymentMethod code='cash'` đều do **migration**
  tạo (`zq6w7x8y9z0a1_seed_operational_baseline`, `fin20260131002_seed_payment_
  methods_and_plans`). Script này KHÔNG gieo lại chúng: một script vừa kiểm vừa vá
  sẽ che mất ca "migration chưa chạy", và ca ấy phải là DỪNG chứ không phải tự sửa.
* ``provision_personas()`` — tạo/hội tụ sáu tài khoản `smoke_*`.

Vì sao cần persona riêng thay vì dùng `accountant01`/`manager01`: hai tài khoản ấy
là dữ liệu nền dùng chung; smoke đổi mật khẩu hay trạng thái của chúng là đổi nền
cho mọi lượt sau. Persona `smoke_*` thuộc về lượt smoke và chỉ lượt smoke.

Mật khẩu
--------
DẪN XUẤT từ một master secret bằng HMAC-SHA256, không sinh ngẫu nhiên mỗi lần và
không dùng chung một chuỗi cho cả sáu:

* dẫn xuất ⇒ chạy lại cho ra đúng mật khẩu cũ, nên lượt hai HỘI TỤ được thay vì
  phải đọc mật khẩu từ đâu đó;
* theo tên persona ⇒ sáu mật khẩu KHÁC nhau, lộ một cái không suy ra được cái khác;
* master secret chỉ tới `smoke-runner` qua `.env.smoke.runner` — backend và hai
  Celery không đọc được nó.

**Không bao giờ in mật khẩu ra log.** Muốn lấy để đăng nhập tay thì gọi
``--in-mat-khau <persona>``, nó in ĐÚNG một dòng ra stdout và không ghi gì khác.

Hội tụ, không phải "đã tồn tại nên bỏ qua"
------------------------------------------
Lượt hai phải đưa persona về ĐÚNG trạng thái mong muốn — mật khẩu, đơn vị, vai
trò, `status`, `user_unit_assignment`, và dòng Casbin — rồi **đọc lại từ DB để
chứng minh**. Một script chỉ `if exists: return` sẽ báo thành công cho một tài
khoản đã bị lượt trước đổi mật khẩu hoặc chuyển đơn vị.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, "/app")

from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.security import get_password_hash  # noqa: E402


class ChanLai(RuntimeError):
    """Một hàng rào đã chặn. Không có nhánh nào đi tiếp."""


# Allowlist, KHÔNG phải blocklist. `smoke_finance_seed.py` hiện chỉ cấm
# `production`/`prod`, nên `staging`, chuỗi rỗng hay một tên gõ sai đều đi lọt —
# với một script TẠO tài khoản thì "không nhận ra là production" là không đủ.
APP_ENV_CHO_PHEP = {"development"}
DB_DUY_NHAT = "qlts_smoke"

# Migration nào tạo nền — nêu tên trong thông báo lỗi để người trực biết chạy gì.
_MIGRATION_NEN = "zq6w7x8y9z0a1 (đơn vị + user nền) · fin20260131002 (payment method)"

# Sáu persona. `unit` là nhãn logic: A = đơn vị của `accountant01`, B = một đơn vị
# active KHÁC (dùng để kiểm IDOR chéo đơn vị).
PERSONA = (
    {"username": "smoke_acc_a", "role": "accountant", "unit": "A", "ten": "Smoke Ke toan A"},
    {"username": "smoke_acc_b", "role": "accountant", "unit": "B", "ten": "Smoke Ke toan B"},
    {"username": "smoke_mgr_a", "role": "manager", "unit": "A", "ten": "Smoke Quan ly A"},
    {"username": "smoke_mgr_b", "role": "manager", "unit": "B", "ten": "Smoke Quan ly B"},
    {"username": "smoke_off_a", "role": "officer", "unit": "A", "ten": "Smoke Chuyen vien A"},
    {"username": "smoke_admin", "role": "admin", "unit": "A", "ten": "Smoke Quan tri"},
)

# Ba persona đặc quyền. `deps.py:368` chặn 403 ở MỌI endpoint đi qua
# `get_current_active_user` khi `role ∈ MFA_ENFORCE_ROLES` mà `mfa_enabled=False`.
# Đo ở BL20260817A: phiên `smoke_mgr_a` nhận 195 phản hồi 403 mang thông điệp
# "MFA is required" trong cửa sổ log 24h; `/api/users/me` cũng 403 nên giao diện
# không tải nổi ⇒ FIN-09 bị ghi BLOCKED_MFA.
#
# Đây là blocker HARNESS, không phải lỗi sản phẩm: `MFA_ENFORCE_ROLES` đúng như
# thiết kế và KHÔNG được nới. Thứ thiếu là bước onboarding cho persona smoke.
PERSONA_CAN_MFA = ("smoke_mgr_a", "smoke_mgr_b", "smoke_admin")


# =============================================================================
# Hàng rào
# =============================================================================
def _ten_db() -> str:
    return (settings.DATABASE_URL or "").rstrip("/").rsplit("/", 1)[-1].split("?")[0]


def kiem_moi_truong(*, can_ghi: bool) -> None:
    app_env = (getattr(settings, "APP_ENV", "") or "").strip().lower()
    if app_env not in APP_ENV_CHO_PHEP:
        raise ChanLai(
            f"APP_ENV={app_env!r} không nằm trong allowlist {sorted(APP_ENV_CHO_PHEP)}. "
            "Script này tạo tài khoản và đặt mật khẩu — một giá trị lạ hay rỗng phải "
            "là dừng, không phải mặc định cho qua."
        )
    ten = _ten_db()
    if ten != DB_DUY_NHAT:
        raise ChanLai(f"database {ten!r} không phải {DB_DUY_NHAT!r}")
    if can_ghi and os.environ.get("SMOKE_ALLOW_DESTRUCTIVE") != "1":
        raise ChanLai(
            "thiếu SMOKE_ALLOW_DESTRUCTIVE=1 — cờ phải do người chạy đặt cho từng lượt"
        )


#: Dấu hiệu một giá trị được chép nguyên từ tệp `.example` mà chưa thay.
#
# Danh sách này phải phủ CẢ placeholder do chính kho này viết. Bản đầu chỉ chặn
# `CHANGE_ME_IN_PRODUCTION` (giá trị mặc định của `config.py`) nên
# `THAY_BANG_CHUOI_NGAU_NHIEN_CUA_BAN` trong `.env.smoke.app.example` đi lọt —
# tức là chính cái placeholder mình viết ra lại không bị chính guard của mình bắt.
_DAU_HIEU_PLACEHOLDER = ("THAY_BANG", "CHANGE_ME", "TODO", "XXXX", "<", ">")


def _la_placeholder(gt: str) -> bool:
    hoa = gt.upper()
    return any(d in hoa for d in _DAU_HIEU_PLACEHOLDER)


def kiem_moi_truong_mfa() -> None:
    """Fail-closed TRƯỚC mọi mutation MFA — thiếu khoá là DỪNG, không "thử xem".

    Hai biến này quyết định MFA có chạy được không, và cả hai đều có đường
    **âm thầm hỏng**:

    * ``MFA_ENCRYPTION_KEY`` rỗng ⇒ ``mfa_service._get_fernet()`` ném
      ``BusinessRuleViolation`` giữa chừng, sau khi `setup_mfa` đã ghi secret vào
      Redis — để lại một secret mồ côi và một persona nửa vời.
    * ``config.py`` **tự sinh** giá trị thay thế khi thiếu (dòng 811-815) và chỉ
      in một dòng WARNING. Nghĩa là lượt sau sinh khoá KHÁC, và
      ``decrypt_secret`` ném "Key may have changed" trên chính secret mình vừa
      ghi. Một persona "đã bật MFA" nhưng không đăng nhập được.

    Vì vậy phải đòi giá trị đến từ **env của stack smoke**, và đòi nó là khoá
    Fernet hợp lệ — không nhận giá trị mặc định, không nhận giá trị tự sinh.
    """
    thieu: List[str] = []

    salt = (os.environ.get("DEVICE_FINGERPRINT_SALT") or "").strip()
    if not salt:
        thieu.append(
            "DEVICE_FINGERPRINT_SALT rỗng — config.py sẽ TỰ SINH một giá trị khác "
            "cho mỗi lượt"
        )
    elif _la_placeholder(salt):
        thieu.append(
            f"DEVICE_FINGERPRINT_SALT còn là placeholder ({salt!r}) — chép nguyên "
            "từ `.env.smoke.app.example` mà chưa thay. Đổi khoá Fernet nhưng quên "
            "đổi muối là ca có thật, và guard cũ để lọt vì chỉ chặn đúng chuỗi "
            "`CHANGE_ME_IN_PRODUCTION`"
        )
    elif len(salt) < 16:
        thieu.append(
            f"DEVICE_FINGERPRINT_SALT chỉ {len(salt)} ký tự — quá ngắn để làm muối"
        )

    khoa = (os.environ.get("MFA_ENCRYPTION_KEY") or "").strip()
    if not khoa:
        thieu.append(
            "MFA_ENCRYPTION_KEY — config.py sẽ TỰ SINH khoá Fernet mới mỗi lượt, "
            "và secret ghi lượt trước sẽ không giải mã được ở lượt sau"
        )
    elif _la_placeholder(khoa):
        # Fernet() cũng sẽ từ chối placeholder, nhưng bằng một thông điệp mã hoá
        # khó đọc. Nói thẳng "còn là placeholder" thì người trực sửa được ngay.
        thieu.append(
            f"MFA_ENCRYPTION_KEY còn là placeholder ({khoa[:24]}…) — chép nguyên "
            "từ `.env.smoke.app.example` mà chưa thay"
        )
    else:
        try:
            from cryptography.fernet import Fernet
            Fernet(khoa.encode())
        except Exception as e:
            thieu.append(f"MFA_ENCRYPTION_KEY không phải khoá Fernet hợp lệ ({e})")

    if thieu:
        raise ChanLai(
            "thiếu cấu hình MFA trong env của stack smoke:\n    - "
            + "\n    - ".join(thieu)
            + "\n  Đặt chúng trong `.env.smoke.app` (xem `.env.smoke.app.example`). "
            "KHÔNG hardcode và KHÔNG dùng giá trị tự sinh: cả hai đều làm persona "
            "bật được MFA lượt này rồi không đăng nhập được lượt sau."
        )


def _master() -> bytes:
    gt = os.environ.get("SMOKE_PERSONA_MASTER_SECRET", "").strip()
    if len(gt) < 16:
        raise ChanLai(
            "thiếu SMOKE_PERSONA_MASTER_SECRET (≥16 ký tự) trong `.env.smoke.runner`. "
            "Đây là cổng fail-closed thật của stack smoke: `docker-compose.smoke.yml` "
            "khai env file ấy `required: true`, và mật khẩu persona được DẪN XUẤT từ "
            "biến này chứ không sinh ngẫu nhiên."
        )
    return gt.encode("utf-8")


def mat_khau(username: str, master: Optional[bytes] = None) -> str:
    """HMAC-SHA256(master, username) → chuỗi 32 ký tự + hậu tố đủ hạng ký tự.

    Hậu tố `Aa1!` để mật khẩu luôn qua được mọi chính sách độ phức tạp mà không
    phải đọc chính sách ấy — nó không làm giảm entropy của phần dẫn xuất.
    """
    m = master if master is not None else _master()
    thô = hmac.new(m, username.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(thô).decode("ascii")[:32] + "Aa1!"


# =============================================================================
# verify_foundation — CHỈ xác minh
# =============================================================================
async def verify_foundation(db) -> Dict[str, int]:
    """Trả về `{"unit_a": id, "unit_b": id}`. Thiếu bất cứ gì ⇒ ChanLai."""
    loi: List[str] = []

    head = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    if not head:
        loi.append("bảng alembic_version rỗng — migration chưa chạy")

    don_vi = (
        await db.execute(
            select(models.OrganizationUnit).where(
                models.OrganizationUnit.is_active.is_(True)
            )
        )
    ).scalars().all()
    if len(don_vi) < 2:
        loi.append(
            f"chỉ có {len(don_vi)} đơn vị active — cần ≥2 để kiểm IDOR chéo đơn vị"
        )

    nen: Dict[str, models.User] = {}
    for ten in ("accountant01", "manager01"):
        u = (
            await db.execute(select(models.User).where(models.User.username == ten))
        ).scalars().first()
        if u is None:
            loi.append(f"thiếu tài khoản nền {ten!r}")
        elif u.status != "active":
            loi.append(f"{ten} có status={u.status!r}, chờ 'active'")
        elif u.unit_id is None:
            loi.append(f"{ten} chưa thuộc đơn vị nào")
        else:
            nen[ten] = u

    if len(nen) == 2 and nen["accountant01"].unit_id != nen["manager01"].unit_id:
        loi.append(
            f"accountant01 (unit {nen['accountant01'].unit_id}) và manager01 "
            f"(unit {nen['manager01'].unit_id}) phải cùng một đơn vị"
        )

    so_tt = (
        await db.execute(select(models.ConsultationStatus))
    ).scalars().all()
    if not so_tt:
        loi.append("bảng consultation_status rỗng — danh mục chưa được seed")

    cash = (
        await db.execute(
            select(models.PaymentMethod).where(models.PaymentMethod.code == "cash")
        )
    ).scalars().first()
    if cash is None:
        loi.append("thiếu PaymentMethod code='cash'")
    elif not cash.is_active:
        loi.append("PaymentMethod 'cash' tồn tại nhưng KHÔNG active")

    if loi:
        raise ChanLai(
            "nền chưa sẵn sàng — script này CHỈ xác minh, không gieo lại:\n  - "
            + "\n  - ".join(loi)
            + f"\nNền do migration tạo: {_MIGRATION_NEN}. Chạy `alembic upgrade head` "
            "trên chính database này rồi thử lại."
        )

    unit_a = nen["accountant01"].unit_id
    khac = [u.id for u in don_vi if u.id != unit_a]
    if not khac:
        raise ChanLai(
            f"không có đơn vị active nào khác đơn vị A ({unit_a}) — không dựng được "
            "persona B để kiểm IDOR chéo"
        )
    return {"unit_a": unit_a, "unit_b": min(khac)}


# =============================================================================
# provision_personas — tạo hoặc HỘI TỤ
# =============================================================================
def _chu_the(user_id: int) -> str:
    """Định dạng chủ thể Casbin của ỨNG DỤNG, không phải định dạng ta tự nghĩ ra.

    Runtime dùng `user:<id>` / `role:<role>` — xem `user_service.py` (`user_subject
    = f"user:{db_user.id}"`, `role_name = f"role:{db_user.role}"`) và migration
    `zq6w7x8y9z0a1` (`('g', 'user:1', 'role:admin')`).

    Bản đầu của script này ghi `v0=<username>`, `v1=<role>` trần, và hàm hậu kiểm
    lại kiểm ĐÚNG định dạng sai ấy — nên nó xanh trong khi enforcer không thấy
    persona nào có vai trò. Một phép kiểm viết theo cùng giả định sai với mã nó
    kiểm thì không phát hiện được gì.
    """
    return f"user:{int(user_id)}"


def _vai(role: str) -> str:
    return f"role:{role}"


async def _casbin(db, user_id: int, role: str) -> None:
    """Đúng một dòng `g, user:<id>, role:<role>` — xoá dòng cũ để hội tụ khi đổi vai."""
    await db.execute(
        text("DELETE FROM casbin_rule WHERE ptype = 'g' AND v0 = :u"),
        {"u": _chu_the(user_id)},
    )
    await db.execute(
        text("INSERT INTO casbin_rule (ptype, v0, v1) VALUES ('g', :u, :r)"),
        {"u": _chu_the(user_id), "r": _vai(role)},
    )


async def provision_personas(db, don_vi: Dict[str, int]) -> Dict[str, int]:
    master = _master()
    ket: Dict[str, int] = {}

    for p in PERSONA:
        ten = p["username"]
        unit_id = don_vi["unit_a"] if p["unit"] == "A" else don_vi["unit_b"]
        bam = get_password_hash(mat_khau(ten, master))

        u = (
            await db.execute(select(models.User).where(models.User.username == ten))
        ).scalars().first()
        if u is None:
            u = models.User(
                username=ten, email=f"{ten}@smoke.invalid",
                password_hash=bam, full_name=p["ten"], role=p["role"],
                unit_id=unit_id, status="active",
            )
            db.add(u)
        else:
            # HỘI TỤ: đặt lại MỌI thuộc tính, kể cả khi bản ghi đã tồn tại. Một
            # nhánh `if exists: return` sẽ báo thành công cho một tài khoản mà
            # lượt trước đã đổi mật khẩu hoặc chuyển sang đơn vị khác.
            u.email = f"{ten}@smoke.invalid"
            u.password_hash = bam
            u.full_name = p["ten"]
            u.role = p["role"]
            u.unit_id = unit_id
            u.status = "active"
        await db.flush()

        # Assignment là NGUỒN SỰ THẬT về đơn vị/vai trò (xem
        # `models/user_unit_assignment.py`), nên nó phải hội tụ chứ không phải
        # được chèn thêm mỗi lượt. Bản đầu vô hiệu hoá hàng cũ rồi chèn hàng mới
        # KHÔNG điều kiện: chạy lần thứ hai không có drift vẫn đẻ thêm một dòng
        # lịch sử, và `end_date` của hàng cũ để rỗng nên lịch sử ấy không đọc được.
        hien = (await db.execute(
            select(models.UserUnitAssignment).where(
                models.UserUnitAssignment.user_id == u.id,
                models.UserUnitAssignment.is_active.is_(True),
            )
        )).scalars().all()

        dung = [a for a in hien if a.unit_id == unit_id and a.role == p["role"]]
        if len(hien) == 1 and dung:
            giu = hien[0]          # không drift ⇒ giữ nguyên, không sinh lịch sử
        else:
            bay_gio = datetime.now(timezone.utc)
            for a in hien:
                a.is_active = False
                a.end_date = bay_gio     # thiếu nó thì lịch sử không có mốc đóng
                a.updated_at = bay_gio
            giu = models.UserUnitAssignment(
                user_id=u.id, unit_id=unit_id, role=p["role"],
                start_date=bay_gio, end_date=None, is_active=True,
                created_at=bay_gio, updated_at=bay_gio,
            )
            db.add(giu)
            await db.flush()

        # Con trỏ trên `user` phải trỏ đúng hàng đang hiệu lực — `user_service`
        # duy trì nó, nên bỏ qua ở đây là để lại một bản ghi nửa vời.
        u.current_assignment_id = giu.id

        await _casbin(db, u.id, p["role"])
        ket[ten] = u.id

    await db.commit()
    return ket


async def bat_mfa(db, u) -> str:
    """Bật MFA cho một persona qua ĐÚNG hợp đồng sản phẩm.

    Đi trọn đường thật, không tắt đường nào::

        mfa_service.setup_mfa()  → sinh secret, cất Redis (TTL 10')
        pyotp.TOTP(secret).now() → mã 6 số của cửa sổ hiện tại
        mfa_service.enable_mfa() → verify mã, mã hoá secret vào DB,
                                   sinh backup code, thu hồi phiên khác

    KHÔNG đặt ``mfa_enabled = True`` bằng SQL hay bằng gán thẳng: làm vậy thì
    ``totp_secret_encrypted`` rỗng, người dùng không sinh nổi mã, và ta có một
    persona "đã bật MFA" mà không đăng nhập được — tệ hơn trạng thái ban đầu vì
    nó trông như đã xong.

    Idempotent: đã bật rồi thì trả ``"da_bat"`` và không chạm gì.
    """
    if u.mfa_enabled:
        return "da_bat"

    import pyotp
    from app.services import mfa_service, session_service

    setup, _ = await mfa_service.setup_mfa(user_id=u.id, username=u.username)
    secret = setup["secret"]

    ma = pyotp.TOTP(secret).now()
    await mfa_service.enable_mfa(db=db, user=u, code=ma, current_session_id=None)

    # 🔴 PHẢI thu hồi MỌI phiên cũ — `enable_mfa` KHÔNG làm việc đó ở đây.
    #
    # `mfa_service.enable_mfa` chỉ thu hồi khi `current_session_id` truthy
    # (`mfa_service.py:241`: `if current_session_id:`). Đường sản phẩm luôn truyền
    # id phiên đang dùng nên nhánh ấy chạy; bootstrap thì KHÔNG có phiên của mình
    # nên truyền `None`, và hệ quả là **không phiên nào bị thu hồi**.
    #
    # Vì sao đó là lỗi chứ không phải chi tiết: `get_current_active_user` chỉ kiểm
    # CỜ `mfa_enabled`. Một phiên đăng nhập TRƯỚC khi bật MFA vẫn hợp lệ sau đó, và
    # đi qua cổng mà chưa hề trả lời một challenge TOTP nào. Lượt smoke sau đó sẽ
    # "chứng minh" FIN-09 chạy được bằng đúng một phiên chưa qua MFA — tức bằng
    # chứng SAI, và sai theo hướng dễ tin nhất.
    #
    # `except_session_id=None` ⇒ thu hồi TẤT CẢ, đúng ý ở đây: bootstrap không có
    # phiên nào cần giữ.
    so_thu_hoi, callback = await session_service.revoke_all_other_sessions(
        db=db, user_id=u.id, except_session_id=None
    )
    if callback:
        await callback()
    return f"vua_bat(thu_hoi={so_thu_hoi})"


async def ma_totp(db, username: str) -> str:
    """In mã TOTP 6 số hiện tại — **không bao giờ in secret**.

    Người trực cần một mã để đăng nhập tay. Đưa secret ra là đưa vĩnh viễn:
    nó vào log, vào lịch sử shell, vào ảnh chụp màn hình. Mã 6 số sống 30 giây
    và vô dụng ngay sau đó, nên đó mới là thứ đúng để in.
    """
    u = (
        await db.execute(select(models.User).where(models.User.username == username))
    ).scalars().first()
    if u is None:
        raise ChanLai(f"{username!r} không tồn tại")
    if not u.mfa_enabled or not u.totp_secret_encrypted:
        raise ChanLai(
            f"{username!r} chưa bật MFA — chạy bootstrap trước rồi mới xin mã"
        )

    import pyotp
    from app.services import mfa_service

    return pyotp.TOTP(mfa_service.decrypt_secret(u.totp_secret_encrypted)).now()


async def kiem_hoi_tu(db, don_vi: Dict[str, int]) -> None:
    """Đọc LẠI từ DB và chứng minh trạng thái đúng như mong muốn.

    Không tin vào việc "lệnh UPDATE đã chạy": đây đúng lớp lỗi `UPDATE … WHERE
    <giá trị cũ>` khớp 0 hàng mà không ai báo lỗi.
    """
    master = _master()
    loi: List[str] = []
    for p in PERSONA:
        ten = p["username"]
        unit_id = don_vi["unit_a"] if p["unit"] == "A" else don_vi["unit_b"]
        u = (
            await db.execute(select(models.User).where(models.User.username == ten))
        ).scalars().first()
        if u is None:
            loi.append(f"{ten}: không tồn tại sau khi provision")
            continue
        if u.unit_id != unit_id:
            loi.append(f"{ten}: unit_id={u.unit_id}, chờ {unit_id}")
        if u.role != p["role"]:
            loi.append(f"{ten}: role={u.role!r}, chờ {p['role']!r}")
        if u.status != "active":
            loi.append(f"{ten}: status={u.status!r}")

        from app.security import verify_password
        if not verify_password(mat_khau(ten, master), u.password_hash):
            loi.append(f"{ten}: mật khẩu KHÔNG khớp giá trị dẫn xuất")

        # Ba persona đặc quyền phải MFA-ready, và phải ready THẬT: cờ bật mà
        # không có secret là trạng thái tệ hơn chưa bật — nó trông như đã xong.
        can_mfa = ten in PERSONA_CAN_MFA
        if can_mfa:
            if not u.mfa_enabled:
                loi.append(
                    f"{ten}: mfa_enabled=False — role {u.role!r} nằm trong "
                    "MFA_ENFORCE_ROLES nên mọi endpoint qua get_current_active_user "
                    "sẽ trả 403"
                )
            if not u.totp_secret_encrypted:
                loi.append(
                    f"{ten}: mfa_enabled={u.mfa_enabled} nhưng KHÔNG có "
                    "totp_secret_encrypted — không sinh được mã, không đăng nhập được"
                )
            else:
                # giải mã thật: khoá đổi giữa hai lượt thì lỗi phải nổ Ở ĐÂY,
                # không phải lúc người trực đứng trước màn hình đăng nhập
                try:
                    from app.services import mfa_service
                    mfa_service.decrypt_secret(u.totp_secret_encrypted)
                except Exception as e:
                    loi.append(
                        f"{ten}: không giải mã được totp_secret ({e}) — "
                        "MFA_ENCRYPTION_KEY đã đổi so với lượt ghi secret"
                    )
        elif u.mfa_enabled:
            # officer/accountant KHÔNG được đổi: chúng không thuộc
            # MFA_ENFORCE_ROLES, bật MFA cho chúng là tự thêm một bước đăng nhập
            # mà sản phẩm không đòi.
            loi.append(
                f"{ten}: mfa_enabled=True nhưng role {u.role!r} không thuộc "
                "MFA_ENFORCE_ROLES — bootstrap không được chạm persona này"
            )

        # Đếm một hàng active là CHƯA ĐỦ: một hàng active trỏ sai đơn vị vẫn cho
        # count = 1. Phải kiểm cả nội dung hàng ấy và con trỏ trên `user`.
        hang = (await db.execute(
            select(models.UserUnitAssignment).where(
                models.UserUnitAssignment.user_id == u.id,
                models.UserUnitAssignment.is_active.is_(True),
            )
        )).scalars().all()
        if len(hang) != 1:
            loi.append(f"{ten}: có {len(hang)} assignment đang hiệu lực, chờ đúng 1")
        else:
            a = hang[0]
            if a.unit_id != unit_id:
                loi.append(f"{ten}: assignment unit_id={a.unit_id}, chờ {unit_id}")
            if a.role != p["role"]:
                loi.append(f"{ten}: assignment role={a.role!r}, chờ {p['role']!r}")
            if a.end_date is not None:
                loi.append(f"{ten}: assignment đang hiệu lực mà có end_date={a.end_date}")
            if u.current_assignment_id != a.id:
                loi.append(
                    f"{ten}: current_assignment_id={u.current_assignment_id}, "
                    f"chờ {a.id}"
                )

        # Định dạng của ỨNG DỤNG, không phải của script. Kiểm bằng định dạng sai
        # thì phép kiểm chỉ xác nhận script nhất quán với chính nó.
        g = (await db.execute(
            text("SELECT count(*) FROM casbin_rule WHERE ptype='g' AND v0=:u AND v1=:r"),
            {"u": _chu_the(u.id), "r": _vai(p["role"])},
        )).scalar()
        if g != 1:
            loi.append(
                f"{ten}: có {g} dòng casbin g/{_chu_the(u.id)}/{_vai(p['role'])}, chờ 1"
            )

    if loi:
        raise ChanLai("HỘI TỤ THẤT BẠI:\n  - " + "\n  - ".join(loi))


# =============================================================================
# CLI
# =============================================================================
async def _chay(in_mat_khau: Optional[str], in_ma_totp: Optional[str]) -> int:
    if in_mat_khau:
        kiem_moi_truong(can_ghi=False)
        if in_mat_khau not in {p["username"] for p in PERSONA}:
            raise ChanLai(f"{in_mat_khau!r} không phải persona smoke")
        # ĐÚNG một dòng ra stdout, không kèm nhãn, để tiện `read`/pipe mà không
        # lẫn vào log.
        print(mat_khau(in_mat_khau))
        return 0

    if in_ma_totp:
        kiem_moi_truong(can_ghi=False)
        kiem_moi_truong_mfa()
        if in_ma_totp not in PERSONA_CAN_MFA:
            raise ChanLai(
                f"{in_ma_totp!r} không thuộc {PERSONA_CAN_MFA} — chỉ persona đặc "
                "quyền mới bật MFA"
            )
        async with AsyncSessionLocal() as db:
            # ĐÚNG một dòng: mã 6 số, không secret, không nhãn.
            print(await ma_totp(db, in_ma_totp))
        return 0

    kiem_moi_truong(can_ghi=True)
    # Đòi cấu hình MFA TRƯỚC khi tạo bất kỳ tài khoản nào: hỏng giữa chừng thì
    # còn lại vài persona đã tạo và vài persona chưa, không cái nào nói ra điều đó.
    kiem_moi_truong_mfa()
    async with AsyncSessionLocal() as db:
        don_vi = await verify_foundation(db)
        print(f"  nền ĐẠT · đơn vị A={don_vi['unit_a']} · B={don_vi['unit_b']}")
        ket = await provision_personas(db, don_vi)

        mfa_ket: Dict[str, str] = {}
        for ten in PERSONA_CAN_MFA:
            u = (
                await db.execute(
                    select(models.User).where(models.User.username == ten)
                )
            ).scalars().first()
            if u is None:
                raise ChanLai(f"{ten}: không tồn tại sau provision")
            mfa_ket[ten] = await bat_mfa(db, u)
        await db.commit()

        await kiem_hoi_tu(db, don_vi)
    print(f"  sáu persona đã hội tụ: {', '.join(sorted(ket))}")
    print(f"  MFA: {', '.join(f'{k}={v}' for k, v in sorted(mfa_ket.items()))}")
    print("  lấy mã đăng nhập: --in-ma-totp <persona>  (in mã 6 số, KHÔNG in secret)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Dựng persona smoke trên qlts_smoke")
    p.add_argument(
        "--in-mat-khau", metavar="PERSONA", default=None,
        help="in mật khẩu dẫn xuất của một persona ra stdout rồi thoát (không ghi DB)",
    )
    p.add_argument(
        "--in-ma-totp", metavar="PERSONA", default=None,
        help=(
            "in mã TOTP 6 số hiện tại của một persona đặc quyền rồi thoát "
            "(KHÔNG in secret, không ghi DB)"
        ),
    )
    a = p.parse_args()
    if a.in_mat_khau and a.in_ma_totp:
        print("DỪNG: chọn MỘT trong --in-mat-khau / --in-ma-totp", file=sys.stderr)
        return 1
    try:
        return asyncio.run(_chay(a.in_mat_khau, a.in_ma_totp))
    except ChanLai as e:
        print(f"DỪNG: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
