#!/usr/bin/env python3
"""Fail-closed MFA bootstrap and authentication gate for nightly E2E.

The nightly database is recreated on every run, while the application requires
MFA for the seeded ``admin`` and ``manager`` roles.  This module keeps the
entire harness contract in one place:

``generate``
    Create ephemeral Fernet/TOTP material, mask it in Actions logs, and append
    it to ``GITHUB_ENV``.  No secret is committed or printed as ordinary text.

``bootstrap``
    Run inside the backend container after seeding.  Enable MFA for exactly the
    configured admin and manager, verify their roles and encrypted secrets, and
    prove that the seeded officer remains outside MFA.

``sync-casbin``
    Run on the Actions host, after seeding.  Authenticate as admin through the
    full two-factor path, then call the product's own template-sync endpoint.
    This is a **database write step only**.  It is *not* proof that the running
    fleet agrees: ``app/routers/admin_v2_casbin.py`` states that a single API
    call reloads the enforcer of the one worker that served it, while Gunicorn
    runs two or more.  The command also records the TOTP counter it consumed so
    the later ``preflight`` can wait past it instead of retrying.

``preflight``
    Run on the Actions host, **after the backend has been recreated** so every
    worker reloaded the policy the previous step wrote.  Read-only: it changes
    no policy.  It exercises **four login paths across three seeded accounts**
    — ``setup`` reuses the officer account and differs only by User-Agent —
    proves the password-only stage grants no session, completes the MFA
    challenge for the privileged paths, and requires HTTP 200 from the
    Casbin-protected ``/api/pipeline/all`` route before Playwright starts.
    It then samples that route over 32 fresh connections per privileged label
    as *supporting* evidence; the primary proof that every worker converged is
    the process count and the startup log, measured by the cutover step.

The module intentionally uses only the Python standard library until the
``bootstrap`` subcommand imports application dependencies inside the backend
container.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import secrets
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, NamedTuple


RUNTIME_ENV_KEYS = (
    "MFA_ENCRYPTION_KEY",
    "E2E_ADMIN_TOTP_SECRET",
    "E2E_MANAGER_TOTP_SECRET",
)

# (label, username env, password env, expected role, TOTP env or None)
LOGIN_ACCOUNTS = (
    (
        "admin",
        "E2E_ADMIN_USERNAME",
        "E2E_ADMIN_PASSWORD",
        "admin",
        "E2E_ADMIN_TOTP_SECRET",
    ),
    (
        "officer",
        "E2E_OFFICER_USERNAME",
        "E2E_OFFICER_PASSWORD",
        "officer",
        None,
    ),
    (
        "manager",
        "E2E_MANAGER_USERNAME",
        "E2E_MANAGER_PASSWORD",
        "manager",
        "E2E_MANAGER_TOTP_SECRET",
    ),
    ("setup", "TEST_USERNAME", "TEST_PASSWORD", "officer", None),
)

# Officer and setup intentionally use the same seeded account.  Distinct
# fingerprints keep the second proof from revoking the first session as a
# same-device replacement.  These are fixed public browser identifiers, not
# secrets and not trust inputs; the server still derives/parses the fingerprint.
USER_AGENTS = {
    "admin": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "officer": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    ),
    "manager": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:142.0) " "Gecko/20100101 Firefox/142.0"
    ),
    "setup": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
        "Mobile/15E148 Safari/604.1"
    ),
}

PRIVILEGED_ACCOUNTS = tuple(account for account in LOGIN_ACCOUNTS if account[4])
PROTECTED_ROUTE = "/api/pipeline/all"

#: Cookie phiên do ``/api/auth/login`` (không MFA) và ``/api/auth/verify-mfa``
#: đặt. Chặng chỉ-mật-khẩu của tài khoản BẬT MFA tuyệt đối không được đặt chúng:
#: ``auth.py`` trả về một ``JSONResponse`` trần cho nhánh challenge, nên bất kỳ
#: cookie nào trong tập này xuất hiện sớm đều là rò phiên trước yếu tố thứ hai.
#: ``csrf_token`` KHÔNG nằm ở đây — nó không phải bằng chứng xác thực.
COOKIE_PHIEN = ("access_token", "refresh_token")
CASBIN_SYNC_ROUTE = "/api/admin/roles/sync-all-from-templates?dry_run=false"

#: Đúng sáu vai hệ thống mà ``sync_all_roles_from_templates`` phải trả về —
#: khoá cứng theo ``app/casbin_config/policy_templates.py::SYSTEM_ROLES``.
#: Một map ``results`` RỖNG, thiếu vai, hay thừa vai đều là bằng chứng lượt sync
#: không chạy đúng tập; nếu chỉ kiểm "không có vai nào fail" thì cả ba ca ấy
#: đều đi lọt vì tập rỗng không có phần tử nào để fail.
#: `test_sync_casbin_khop_system_roles_cua_san_pham` khoá cặp này bằng nhau.
EXPECTED_SYNC_ROLES = (
    "role:admin",
    "role:manager",
    "role:accountant",
    "role:officer",
    "role:collaborator",
    "role:user",
)

#: `role:admin` CỐ Ý không được đồng bộ (tránh tự khoá mình ra ngoài), nên nó
#: phải bỏ qua với ĐÚNG lý do này. Bất kỳ lý do nào khác — kể cả "success" —
#: nghĩa là nhánh an toàn đã đổi hoặc đã bị vượt.
LY_DO_BO_QUA_ADMIN = "Admin role not synced for safety"

#: Lý do bỏ qua HỢP LỆ cho vai KHÔNG phải admin. "No template defined" KHÔNG
#: nằm ở đây: cả sáu vai hệ thống đều khai `template_id`, nên lý do ấy chỉ xuất
#: hiện khi `SYSTEM_ROLES` đã trôi — im lặng chấp nhận là bỏ qua một vai chưa
#: bao giờ được áp template.
LY_DO_BO_QUA_HOP_LE = ("No drift detected",)
_TOTP_SECRET_RE = re.compile(r"[A-Z2-7]{32}\Z")

#: Bước thời gian TOTP theo RFC 6238. Mọi phép tính counter và mọi phép căn
#: ranh giới bên dưới đều xoay quanh con số này — để rời rạc ra nhiều nơi là
#: mời một nguồn-chuẩn-thứ-hai vào đúng chỗ khó thấy nhất.
TOTP_STEP_SECONDS = 30

#: Timeout socket cho MỌI request của cổng (``_request_json``).
#:
#: ⚠️ Đây là timeout MỖI THAO TÁC socket của ``urllib`` (connect, rồi từng
#: ``recv``), KHÔNG phải deadline của cả request — thời gian tường xấu nhất có
#: thể lớn hơn con số này.
HTTP_TIMEOUT_SECONDS = 10

#: Biên an toàn cộng thêm, bù ba thứ mà mô hình ``Δ ≤ HTTP_TIMEOUT`` không phủ:
#: timeout-mỗi-thao-tác ở trên, thời gian xếp hàng sau hai gunicorn worker lúc
#: nightly đang tải, và lệch đồng hồ giữa runner và container.
TOTP_BOUNDARY_SAFETY_SECONDS = 5

#: Ngưỡng căn lại cửa sổ 30 giây TRƯỚC khi sinh mã cho preflight.
#:
#: Mã được sinh ở counter ``c = ⌊t/30⌋ - 1``. Backend
#: (``mfa_service.verify_totp_with_counter``) chấp nhận ``c ∈ {n'-1, n', n'+1}``
#: với ``n' = ⌊t'/30⌋`` tại thời điểm ĐÁNH GIÁ, chứ không phải lúc sinh. Vì
#: ``t' ≥ t`` nên chấp nhận ⟺ ``n' = n``; TỪ CHỐI ⟺ độ trễ ``Δ ≥ remaining``,
#: khi ấy ``c = n'-2`` — ngoài cửa sổ ±1.
#:
#: ⚠️ PHẠM VI CỦA KẾT LUẬN — mô hình hữu hạn, không phải deadline tuyệt đối.
#: Trong **mô hình giả định độ trễ từ lúc sinh mã tới lúc đánh giá không vượt
#: ``HTTP_TIMEOUT_SECONDS``**, điều kiện cần và đủ để mã không bị từ chối là
#: ngưỡng **lớn hơn hẳn** timeout. Dấu ``>`` là chặt, không phải ``>=``:
#: ``remaining = Δ = 10`` rơi đúng mốc 30 giây và VẪN hỏng — cùng cái bẫy
#: ``>`` / ``>=`` mà ``_cho_counter_vuot`` đã dính và đã có ca canh riêng.
#:
#: Giả định ``Δ ≤ HTTP_TIMEOUT_SECONDS`` KHÔNG được bảo đảm ở thực tế: như ghi
#: chú ở ``HTTP_TIMEOUT_SECONDS``, đó là timeout MỖI THAO TÁC socket, nên tổng
#: thời gian một request có thể vượt con số ấy. Vì vậy ngưỡng dưới đây là một
#: BIÊN VẬN HÀNH có dự phòng, không phải chứng minh cho mọi độ trễ.
#:
#: Cận trên là 29,75: sau ``sleep(remaining + 0.25)`` thì remaining mới đúng
#: bằng ``30 - 0.25``, nên ngưỡng lớn hơn số đó khiến guard một-lần không bao
#: giờ đạt nổi hậu điều kiện của chính nó.
TOTP_MIN_REMAINING_SECONDS = HTTP_TIMEOUT_SECONDS + TOTP_BOUNDARY_SAFETY_SECONDS

#: Khoảng vượt qua mốc khi căn lại — quyết định cận trên 29,75 nói trên.
TOTP_BOUNDARY_OVERSHOOT_SECONDS = 0.25


class GateError(RuntimeError):
    """Expected fail-closed rejection safe to show in a CI log."""


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise GateError(f"missing required environment variable {name}")
    if "\n" in value or "\r" in value:
        raise GateError(f"{name} contains a newline")
    return value


def _decode_totp_secret(secret: str, name: str) -> bytes:
    """Validate the exact 160-bit base32 shape generated by this harness."""
    if not _TOTP_SECRET_RE.fullmatch(secret):
        raise GateError(f"{name} is not an unpadded 160-bit base32 TOTP secret")
    try:
        decoded = base64.b32decode(secret, casefold=False)
    except ValueError as exc:
        raise GateError(f"{name} is not valid base32") from exc
    if len(decoded) != 20:
        raise GateError(f"{name} does not decode to 160 bits")
    return decoded


def _totp_tu_counter(secret: str, name: str, counter: int) -> str:
    """RFC 6238 SHA-1/6 chữ số cho ĐÚNG một counter, stdlib thuần.

    Tách khỏi ``_totp_now`` để chỉ có MỘT nơi biết counter nào đã sinh ra mã
    nào. Ai cần biết counter thì nhận nó về, không tự tính lại — hai phép
    ``int(time.time() // 30)`` chạy cách nhau vài mili giây có thể rơi hai bên
    mốc 30 giây và cho hai counter khác nhau.
    """
    key = _decode_totp_secret(secret, name)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def _totp_now(secret: str, name: str, now: float | None = None) -> str:
    """Generate RFC 6238 SHA-1/6-digit/30-second TOTP using stdlib only."""
    counter = int((time.time() if now is None else now) // TOTP_STEP_SECONDS)
    return _totp_tu_counter(secret, name, counter)


def _totp_for_preflight(secret: str, name: str) -> tuple[str, int]:
    """``(mã, counter đã tiêu)`` — dùng counter TRƯỚC, trả về cả hai.

    Backend nhận ``valid_window=1`` và ghi counter đã khớp vào Redis
    ``totp_used:{user_id}`` (TTL 180 s) để chống replay; script Lua từ chối khi
    ``counter <= counter_đã_lưu`` — đơn điệu NGHIÊM NGẶT. Tiêu counter hiện tại
    ở đây sẽ làm lượt đăng nhập đầu của Playwright hỏng vì replay.

    Trả về counter là phần chịu lực của thiết kế: bước ``sync-casbin`` phải ghi
    ĐÚNG counter nó vừa đốt ra tệp, và bước ``preflight`` chờ tới khi counter
    trước đã vượt qua số ấy. Nếu chỗ khác tự tính lại counter thì đó là nguồn
    chuẩn thứ hai, và nó lệch đúng một bậc mỗi khi hai phép tính rơi hai bên
    mốc 30 giây.

    Nếu cửa sổ 30 giây còn ít hơn ``TOTP_MIN_REMAINING_SECONDS`` thì chờ sang
    cửa sổ sau rồi mới lấy cửa sổ liền trước — đây là căn chỉnh đồng hồ, KHÔNG
    phải retry xác thực. Ngưỡng ấy phải LỚN HƠN ``HTTP_TIMEOUT_SECONDS``: mã
    được đánh giá ở phía backend tại thời điểm request TỚI NƠI, nên nếu độ trễ
    vượt quá phần còn lại của cửa sổ thì counter đã tụt ra ngoài ``valid_window``
    và bị từ chối — trong khi thiết kế này CẤM retry.

    Kết luận an toàn ở đây chỉ đúng **trong mô hình giả định độ trễ từ lúc sinh
    mã tới lúc đánh giá không vượt ``HTTP_TIMEOUT_SECONDS``**. Giả định ấy không
    được bảo đảm — timeout của ``urllib`` áp cho từng thao tác socket, không cho
    cả request — nên ngưỡng là biên vận hành có dự phòng, không phải deadline.
    """
    now = time.time()
    remaining = TOTP_STEP_SECONDS - (now % TOTP_STEP_SECONDS)
    if remaining < TOTP_MIN_REMAINING_SECONDS:
        time.sleep(remaining + TOTP_BOUNDARY_OVERSHOOT_SECONDS)
        now = time.time()
    counter = int(now // TOTP_STEP_SECONDS) - 1
    return _totp_tu_counter(secret, name, counter), counter


def generate_runtime_environment() -> None:
    """Generate fresh material and publish it only through ``GITHUB_ENV``."""
    github_env = Path(_required_env("GITHUB_ENV"))
    values = {
        "MFA_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "E2E_ADMIN_TOTP_SECRET": base64.b32encode(os.urandom(20)).decode(),
        "E2E_MANAGER_TOTP_SECRET": base64.b32encode(os.urandom(20)).decode(),
    }

    for name in ("E2E_ADMIN_TOTP_SECRET", "E2E_MANAGER_TOTP_SECRET"):
        _decode_totp_secret(values[name], name)
    if secrets.compare_digest(
        values["E2E_ADMIN_TOTP_SECRET"], values["E2E_MANAGER_TOTP_SECRET"]
    ):
        raise GateError("admin and manager received the same TOTP secret")

    # Che TRƯỚC khi bất kỳ bước sau nào có thể echo giá trị đã bung.
    #
    # ``::add-mask::`` chỉ có tác dụng bên trong GitHub Actions: runner đọc dòng
    # lệnh ấy rồi thay giá trị bằng ``***`` ở mọi log về sau. Chạy TAY ở máy
    # local thì không có ai đọc nó cả — dòng đó in thẳng khoá Fernet và hai TOTP
    # secret ra terminal, vào scrollback, vào transcript. Nên nó phải là hành vi
    # CÓ ĐIỀU KIỆN, không phải mặc định.
    #
    # So BẰNG với chuỗi ``"true"`` chứ không kiểm truthiness: ``GITHUB_ACTIONS``
    # chỉ tồn tại bên trong Actions và luôn mang đúng giá trị ấy, nên
    # ``GITHUB_ACTIONS=false`` phải nghĩa là KHÔNG che.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for value in values.values():
            print(f"::add-mask::{value}")
    with github_env.open("a", encoding="utf-8", newline="\n") as stream:
        for name in RUNTIME_ENV_KEYS:
            stream.write(f"{name}={values[name]}\n")
    print("Generated ephemeral MFA material for this nightly run.")


def _runtime_account_values() -> list[tuple[str, str, str, str, str | None]]:
    values: list[tuple[str, str, str, str, str | None]] = []
    for label, username_env, password_env, role, totp_env in LOGIN_ACCOUNTS:
        username = _required_env(username_env)
        password = _required_env(password_env)
        totp_secret = _required_env(totp_env) if totp_env else None
        if totp_secret:
            _decode_totp_secret(totp_secret, totp_env or "TOTP secret")
        values.append((label, username, password, role, totp_secret))

    usernames = [account[1] for account in values]
    if len(usernames) != len(set(usernames)) + 1:
        # The only intentional duplicate is setup == officer.
        raise GateError("nightly identities are duplicated outside setup == officer")
    officer = next(account for account in values if account[0] == "officer")
    setup = next(account for account in values if account[0] == "setup")
    if officer[1] != setup[1]:
        raise GateError("TEST_USERNAME must identify the seeded officer account")
    if not secrets.compare_digest(officer[2], setup[2]):
        raise GateError("TEST_PASSWORD must match the seeded officer password")
    return values


def _bootstrap_account_values() -> tuple[dict[str, tuple[str, str]], tuple[str, str]]:
    """Read only the identities/secrets the backend-side bootstrap needs.

    Passwords deliberately stay on the Actions host.  The backend container
    needs three usernames to bind seeded rows to roles, plus the two ephemeral
    TOTP secrets it will encrypt.
    """
    privileged = {
        _required_env("E2E_ADMIN_USERNAME"): (
            "admin",
            _required_env("E2E_ADMIN_TOTP_SECRET"),
        ),
        _required_env("E2E_MANAGER_USERNAME"): (
            "manager",
            _required_env("E2E_MANAGER_TOTP_SECRET"),
        ),
    }
    officer = (_required_env("E2E_OFFICER_USERNAME"), "officer")
    if len(privileged) != 2 or officer[0] in privileged:
        raise GateError("bootstrap identities must be three distinct seeded users")
    for username, (_, totp_secret) in privileged.items():
        _decode_totp_secret(totp_secret, f"{username} TOTP secret")
    return privileged, officer


async def bootstrap_runtime_mfa() -> None:
    """Enable and verify MFA in the ephemeral nightly database."""
    expected_privileged, officer = _bootstrap_account_values()

    # Imports stay inside this subcommand: generate/preflight must remain stdlib.
    from cryptography.fernet import Fernet
    from sqlalchemy import select
    from sqlalchemy.engine import make_url

    from app import models
    from app.config import settings
    from app.database import AsyncSessionLocal, safe_redis_delete, safe_redis_set
    from app.services import mfa_service

    if settings.APP_ENV != "test":
        raise GateError(f"bootstrap requires APP_ENV=test, got {settings.APP_ENV!r}")
    database_name = make_url(str(settings.DATABASE_URL)).database
    if database_name != "qlts_test":
        raise GateError(
            f"bootstrap requires database 'qlts_test', got {database_name!r}"
        )
    if set(settings.MFA_ENFORCE_ROLES) != {"admin", "manager"}:
        raise GateError(
            "MFA_ENFORCE_ROLES drifted; nightly bootstrap only covers admin and manager"
        )

    encryption_key = _required_env("MFA_ENCRYPTION_KEY")
    try:
        Fernet(encryption_key.encode())
    except (TypeError, ValueError) as exc:
        raise GateError("MFA_ENCRYPTION_KEY is not a valid Fernet key") from exc
    if not secrets.compare_digest(encryption_key, settings.MFA_ENCRYPTION_KEY):
        raise GateError("process environment and application MFA key do not match")

    usernames = set(expected_privileged) | {officer[0]}
    touched_redis_keys: list[str] = []
    callbacks: list[Callable[[], Any]] = []

    # Hai phiên DB TUẦN TỰ, KHÔNG lồng nhau.
    #
    # Phiên GHI đóng tự nhiên khi rời `async with` — không gọi `close()` tay
    # bên trong nó, vì `rollback()` ở nhánh lỗi sẽ áp lên một session đã đóng.
    # `rollback()` vì thế chỉ phủ lỗi TRƯỚC commit, đúng phạm vi của nó.
    #
    # Phiên KIỂM mở SAU khi phiên ghi kết thúc. `AsyncSessionLocal` khai
    # `expire_on_commit=False` (`app/database.py:55`) nên sau `commit()` các đối
    # tượng vẫn nằm trong identity map với giá trị TRONG BỘ NHỚ; đọc lại trên
    # chính phiên ấy chỉ đọc lại thứ vừa gán, và sẽ XANH kể cả khi không dòng
    # nào chạm đĩa. Phiên mới có identity map rỗng ⇒ buộc phát SELECT thật.
    #
    # Dọn Redis nằm ở `finally` NGOÀI cùng nên phủ mọi đường lỗi của cả hai phiên.
    try:
        async with AsyncSessionLocal() as db:
            try:
                users = (
                    (
                        await db.execute(
                            select(models.User)
                            .where(models.User.username.in_(sorted(usernames)))
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                by_username = {user.username: user for user in users}
                missing = sorted(usernames - set(by_username))
                if missing:
                    raise GateError(
                        "seeded MFA identities are missing: " + ", ".join(missing)
                    )

                for username, (expected_role, totp_secret) in expected_privileged.items():
                    user = by_username[username]
                    if user.role != expected_role:
                        raise GateError(
                            f"{username}: role is {user.role!r}, expected {expected_role!r}"
                        )
                    if user.status != "active":
                        raise GateError(f"{username}: account status is {user.status!r}")
                    encrypted = user.totp_secret_encrypted
                    if user.mfa_enabled:
                        if not encrypted:
                            raise GateError(
                                f"{username}: MFA enabled without encrypted secret"
                            )
                        current = mfa_service.decrypt_secret(encrypted)
                        if not secrets.compare_digest(current, totp_secret or ""):
                            raise GateError(
                                f"{username}: existing TOTP secret differs from this run"
                            )
                    elif encrypted:
                        raise GateError(
                            f"{username}: encrypted TOTP secret exists while MFA is disabled"
                        )

                officer_user = by_username[officer[0]]
                if officer_user.role != officer[1]:
                    raise GateError(
                        f"{officer[0]}: role is {officer_user.role!r}, "
                        f"expected {officer[1]!r}"
                    )
                if officer_user.mfa_enabled or officer_user.totp_secret_encrypted:
                    raise GateError(
                        f"{officer[0]}: officer must remain outside MFA bootstrap"
                    )

                already_enabled = (
                    (
                        await db.execute(
                            select(models.User).where(models.User.mfa_enabled.is_(True))
                        )
                    )
                    .scalars()
                    .all()
                )
                unexpected = sorted(
                    user.username
                    for user in already_enabled
                    if user.username not in expected_privileged
                )
                if unexpected:
                    raise GateError(
                        "unexpected MFA-enabled users before bootstrap: "
                        + ", ".join(unexpected)
                    )

                for username, (_, totp_secret) in expected_privileged.items():
                    user = by_username[username]
                    if user.mfa_enabled:
                        continue
                    redis_key = f"mfa_setup:{user.id}"
                    touched_redis_keys.append(redis_key)
                    stored = await safe_redis_set(redis_key, totp_secret or "", ex=600)
                    if stored is not True:
                        raise GateError(
                            f"{username}: could not stage the TOTP secret in Redis"
                        )
                    code = _totp_now(totp_secret or "", f"{username} TOTP secret")
                    _, callback = await mfa_service.enable_mfa(
                        db=db, user=user, code=code, current_session_id=None
                    )
                    if callback:
                        callbacks.append(callback)

                await db.commit()
            except Exception:
                await db.rollback()
                raise

        # Phiên ghi ĐÃ đóng ở đây. Mọi SELECT dưới đây đi qua `kiem`.
        async with AsyncSessionLocal() as kiem:
            verified = (
                (
                    await kiem.execute(
                        select(models.User).where(
                            models.User.username.in_(sorted(usernames))
                        )
                    )
                )
                .scalars()
                .all()
            )
            verified_by_username = {user.username: user for user in verified}
            thieu = sorted(set(usernames) - set(verified_by_username))
            if thieu:
                raise GateError(
                    f"fresh session could not read back account(s): {thieu}"
                )

            for username, (
                expected_role,
                totp_secret,
            ) in expected_privileged.items():
                user = verified_by_username[username]
                if user.status != "active":
                    raise GateError(
                        f"{username}: status is {user.status!r}, expected 'active'"
                    )
                if user.role != expected_role or user.mfa_enabled is not True:
                    raise GateError(f"{username}: role/MFA state did not converge")
                if not user.totp_secret_encrypted:
                    raise GateError(f"{username}: encrypted TOTP secret is missing")
                plaintext = mfa_service.decrypt_secret(user.totp_secret_encrypted)
                if not secrets.compare_digest(plaintext, totp_secret or ""):
                    raise GateError(
                        f"{username}: encrypted TOTP secret failed round-trip"
                    )

            officer_after = verified_by_username[officer[0]]
            if officer_after.status != "active":
                raise GateError(
                    f"{officer[0]}: status is {officer_after.status!r}, "
                    "expected 'active'"
                )
            if officer_after.mfa_enabled or officer_after.totp_secret_encrypted:
                raise GateError(
                    f"{officer[0]}: officer was changed by MFA bootstrap"
                )

            enabled_after = (
                (
                    await kiem.execute(
                        select(models.User).where(models.User.mfa_enabled.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            enabled_names = {user.username for user in enabled_after}
            if enabled_names != set(expected_privileged):
                raise GateError(
                    "MFA-enabled user set differs from exact admin/manager "
                    f"contract: {sorted(enabled_names)} vs "
                    f"{sorted(expected_privileged)}"
                )
    finally:
        for redis_key in touched_redis_keys:
            await safe_redis_delete(redis_key)

    # Product callbacks are post-commit by contract.  With no existing nightly
    # session they are no-ops, but preserving the ordering prevents future drift.
    for callback in callbacks:
        await callback()
    print("MFA bootstrap passed for exact admin/manager; officer remains disabled.")


def _request_json(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    *,
    form: dict[str, str] | None = None,
    payload: dict[str, str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    if form is not None and payload is not None:
        raise GateError("request cannot contain both form and JSON payload")
    data: bytes | None = None
    headers: dict[str, str] = dict(extra_headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise GateError(f"request to {urllib.parse.urlsplit(url).path} failed") from exc

    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(
            f"{urllib.parse.urlsplit(url).path} returned non-JSON HTTP {status}"
        ) from exc
    return status, body


def _response_detail(body: Any) -> str:
    """Return a bounded non-secret API error detail for diagnostics."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, str) or not detail:
        return ""
    return f": {detail[:240]}"


def _sync_casbin_after_seed(
    opener: urllib.request.OpenerDirector,
    cookie_jar: http.cookiejar.CookieJar,
    base_url: str,
) -> None:
    """Synchronize policy templates through the authenticated live enforcer.

    ``AUTO_SYNC_TEMPLATES``, *when enabled*, runs as each backend worker starts
    — but the nightly workflow deliberately sets it to ``false``, precisely
    because one such writer per worker races the others.  The nightly workbook
    also seeds Casbin rows *after* startup, so a startup-time sync would be
    reading a database that is not finished yet.  A standalone DB script would
    instead leave the already-running enforcer stale.  Calling the product
    endpoint as the freshly MFA-authenticated admin updates the ephemeral DB
    and the live enforcer together, before any non-admin identity is trusted.

    Scope: this is the only writer of the *post-seed template-policy sync*.  It
    is not the only writer of ``casbin_rule`` — Alembic migrations and
    ``seed_from_xlsx`` both insert rows earlier in the run.
    """
    csrf_token = next(
        (cookie.value for cookie in cookie_jar if cookie.name == "csrf_token"), None
    )
    if not csrf_token:
        raise GateError("admin login did not issue the CSRF cookie needed for sync")
    status, result = _request_json(
        opener,
        "POST",
        f"{base_url}{CASBIN_SYNC_ROUTE}",
        payload={},
        extra_headers={"X-CSRF-Token": csrf_token},
    )
    if status != 200 or not isinstance(result, dict):
        raise GateError(f"Casbin template sync returned HTTP {status}")
    if result.get("dry_run") is not False or not isinstance(
        result.get("results"), dict
    ):
        raise GateError("Casbin template sync returned an invalid/non-applying result")

    # Fail-closed trên KẾT QUẢ, không chỉ trên "có ai fail không".
    #
    # Phép cũ dựng một tập `failed` rồi báo lỗi khi tập ấy khác rỗng. Nó XANH
    # cho `results = {}` (không phần tử nào để fail), cho map thiếu vai, cho
    # `{"success": None}` và cho `{"skipped": False}` — tức mọi ca mà lượt sync
    # KHÔNG hội tụ. Ở đây mỗi vai phải tự chứng minh MỘT trong hai kết cục.
    ket_qua = result["results"]
    if not ket_qua:
        raise GateError(
            "Casbin template sync returned an EMPTY results map; no role converged"
        )
    thieu = sorted(set(EXPECTED_SYNC_ROLES) - set(ket_qua))
    thua = sorted(set(ket_qua) - set(EXPECTED_SYNC_ROLES))
    if thieu or thua:
        raise GateError(
            "Casbin template sync role set drifted (missing: "
            + (", ".join(thieu) or "none")
            + " | unexpected: "
            + (", ".join(thua) or "none")
            + ")"
        )

    da_dong_bo: list[str] = []
    for role in EXPECTED_SYNC_ROLES:
        chi_tiet = ket_qua[role]
        if not isinstance(chi_tiet, dict) or not chi_tiet:
            raise GateError(
                f"Casbin sync: {role} returned an empty/invalid result object"
            )

        thanh_cong = chi_tiet.get("success") is True
        bo_qua = chi_tiet.get("skipped") is True
        # XOR tường minh: `False`, `None`, `0`, `"false"` đều KHÔNG phải thành
        # công, và "vừa success vừa skipped" là trạng thái mơ hồ, không phải đạt.
        if thanh_cong == bo_qua:
            raise GateError(
                f"Casbin sync: {role} is ambiguous — success="
                f"{chi_tiet.get('success')!r} skipped={chi_tiet.get('skipped')!r}; "
                "exactly one of them must be True"
            )
        if chi_tiet.get("error"):
            raise GateError(
                f"Casbin sync: {role} reported an error"
                + _response_detail({"detail": str(chi_tiet.get("error"))})
            )

        if thanh_cong:
            if role == "role:admin":
                raise GateError(
                    "Casbin sync: role:admin reported success; it must stay skipped "
                    "for safety — the lockout guard has been bypassed"
                )
            da_dong_bo.append(role)
            continue

        ly_do = chi_tiet.get("reason")
        if not isinstance(ly_do, str) or not ly_do.strip():
            raise GateError(
                f"Casbin sync: {role} was skipped without a reason; a silent skip "
                "cannot be distinguished from a skipped sync"
            )
        if role == "role:admin":
            if ly_do != LY_DO_BO_QUA_ADMIN:
                raise GateError(
                    f"Casbin sync: role:admin skipped for the wrong reason {ly_do!r}, "
                    f"expected {LY_DO_BO_QUA_ADMIN!r}"
                )
        elif ly_do not in LY_DO_BO_QUA_HOP_LE:
            raise GateError(
                f"Casbin sync: {role} skipped with an unacceptable reason {ly_do!r}; "
                f"only {list(LY_DO_BO_QUA_HOP_LE)} mean the role already matches "
                "its template"
            )

    print(
        "PASS Casbin templates: post-seed sync converged %d/%d system roles "
        "(applied: %s)"
        % (
            len(EXPECTED_SYNC_ROLES),
            len(EXPECTED_SYNC_ROLES),
            ", ".join(da_dong_bo) or "none - already in sync",
        )
    )


class PhienDaXacThuc(NamedTuple):
    """Một phiên ĐÃ qua đủ hai yếu tố, kèm counter TOTP nó đã đốt.

    ``counter_da_tieu`` là ``None`` với tài khoản không bật MFA — không phải 0.
    Số 0 là một counter hợp lệ (1970-01-01), nên gộp hai ca vào một giá trị sẽ
    làm phép so ``counter > counter_da_tieu`` nói dối ở đúng ca không có MFA.
    """

    label: str
    opener: urllib.request.OpenerDirector
    cookie_jar: http.cookiejar.CookieJar
    than: dict
    counter_da_tieu: int | None


def _dang_nhap_va_chung_minh(
    account: tuple[str, str, str, str, str | None],
    base_url: str,
) -> PhienDaXacThuc:
    """login → chứng minh chặng chỉ-mật-khẩu KHÔNG phải phiên → verify → kiểm vai.

    MỘT nguồn chuẩn cho cả ``sync-casbin`` lẫn ``preflight``. Có hai bản sao
    của đoạn này thì mọi hàng rào ở đây phải được vá hai lần, và lần thứ hai
    là lần bị quên.

    Hàm KHÔNG chạm route nào ngoài ``/api/auth/*``: phép probe Casbin thuộc về
    người gọi, vì hai người gọi cần hai kỳ vọng khác nhau — ở bước sync thì
    policy CHƯA hội tụ (đòi 200 ở đó là tự khoá mình), còn ở preflight thì 200
    chính là thứ phải chứng minh.
    """
    label, username, password, expected_role, totp_secret = account
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    opener.addheaders = [("User-Agent", USER_AGENTS[label])]

    status, login = _request_json(
        opener,
        "POST",
        f"{base_url}/api/auth/login",
        form={"username": username, "password": password},
    )
    if status != 200 or not isinstance(login, dict):
        raise GateError(f"{label}: password login returned HTTP {status}")

    expects_mfa = totp_secret is not None
    if expects_mfa:
        if login.get("mfa_required") is not True:
            raise GateError(
                f"{label}: login returned 200 without the required MFA challenge"
            )
        mfa_token = login.get("mfa_token")
        if not isinstance(mfa_token, str) or not mfa_token:
            raise GateError(f"{label}: MFA challenge omitted mfa_token")

        # Chặng chỉ-mật-khẩu KHÔNG được là một phiên.
        #
        # `/api/auth/login` trả HTTP 200 cho CẢ hai nhánh — đăng nhập xong và
        # mới qua yếu tố thứ nhất. Nên một cổng chỉ kiểm "200" là fail-open:
        # nó xanh y hệt khi MFA bị vô hiệu hoá. Ba phép đo ĐỘC LẬP dưới đây,
        # mỗi phép bắt một đường rò khác nhau:
        #   (a) thân phản hồi không mang access/refresh token;
        #   (b) không cookie phiên nào được đặt;
        #   (c) route Casbin trả ĐÚNG 401 — chưa xác thực. Không chấp nhận 403:
        #       403 nghĩa là đã có danh tính rồi mới bị chặn quyền, tức phiên
        #       ĐÃ được cấp — đúng thứ ta đang chứng minh là không xảy ra.
        # Kiểm SỰ HIỆN DIỆN của khoá, không kiểm truthiness.
        #
        # `login.get(khoa)` cho falsy với `""`, `None`, `0` — nên một challenge
        # trả `{"access_token": ""}` sẽ đi lọt, dù chính việc khoá ấy CÓ MẶT đã
        # là bằng chứng chặng chỉ-mật-khẩu đang cấp phát trường phiên.
        for khoa in ("access_token", "refresh_token"):
            if khoa in login:
                raise GateError(
                    f"{label}: MFA challenge leaked {khoa!r} in the response body "
                    "— password-only stage granted a session before the second factor"
                )
        cookie_som = sorted(c.name for c in cookie_jar if c.name in COOKIE_PHIEN)
        if cookie_som:
            raise GateError(
                f"{label}: MFA challenge set session cookie(s) {cookie_som} "
                "— password-only stage granted a session before the second factor"
            )
        status_som, than_som = _request_json(
            opener, "GET", f"{base_url}{PROTECTED_ROUTE}"
        )
        if status_som != 401:
            raise GateError(
                f"{label}: {PROTECTED_ROUTE} returned HTTP {status_som} BEFORE MFA "
                f"verification, expected exactly 401{_response_detail(than_som)}"
            )

        code, counter_da_tieu = _totp_for_preflight(
            totp_secret or "", f"{label} TOTP secret"
        )
        status, authenticated = _request_json(
            opener,
            "POST",
            f"{base_url}/api/auth/verify-mfa",
            payload={"mfa_token": mfa_token, "code": code},
        )
        if status != 200 or not isinstance(authenticated, dict):
            raise GateError(f"{label}: MFA verification returned HTTP {status}")
    else:
        if login.get("mfa_required") is True:
            raise GateError(
                f"{label}: non-privileged identity unexpectedly requires MFA"
            )
        authenticated = login
        counter_da_tieu = None

    user = authenticated.get("user")
    actual_role = user.get("role") if isinstance(user, dict) else None
    if actual_role != expected_role:
        raise GateError(
            f"{label}: authenticated role is {actual_role!r}, expected {expected_role!r}"
        )

    return PhienDaXacThuc(
        label=label,
        opener=opener,
        cookie_jar=cookie_jar,
        than=authenticated,
        counter_da_tieu=counter_da_tieu,
    )


def _preflight_account(
    account: tuple[str, str, str, str, str | None],
    base_url: str,
) -> PhienDaXacThuc:
    """Đường CHỈ-ĐỌC: xác thực rồi đòi route Casbin trả 200.

    Không còn tham số ``before_probe``. Trước đây lượt sync policy được móc vào
    đây, và hệ quả là cái 200 đo được một phần do CHÍNH nó vừa tạo ra — cổng tự
    chứng minh mình bằng thứ mình vừa thay đổi. Sync nay là một bước riêng chạy
    TRƯỚC cutover; tới lượt này thì mọi thứ chỉ được ĐỌC.
    """
    phien = _dang_nhap_va_chung_minh(account, base_url)
    label, expected_role = phien.label, account[3]
    opener = phien.opener

    status, _ = _request_json(opener, "GET", f"{base_url}{PROTECTED_ROUTE}")
    if status != 200:
        raise GateError(
            f"{label}: authenticated session cannot access {PROTECTED_ROUTE} "
            f"(HTTP {status}){_response_detail(_)}"
        )
    print(f"PASS {label} ({expected_role}): MFA contract and Casbin probe HTTP 200")
    return phien


def _duong_tep_counter() -> Path:
    """Tệp trung gian mang counter TOTP mà ``sync-casbin`` đã đốt."""
    return Path(_required_env("QLTS_TOTP_COUNTER_FILE"))


def _ghi_counter_da_tieu(duong: Path, counter: int) -> None:
    """Ghi ĐÚNG một số nguyên thập phân, không gì khác.

    Tệp này đi qua ranh giới giữa hai bước workflow nên nó là một kênh dữ liệu
    thật. Chỉ được mang MỘT con số: mọi thứ khác lọt vào đây — secret, mã TOTP,
    tên tài khoản — là một bản sao bí mật nằm ngoài mọi cơ chế che, và chạy tay
    ở local thì không có cơ chế che nào cả.
    """
    if not isinstance(counter, int) or isinstance(counter, bool) or counter < 0:
        raise GateError(f"counter phải là số nguyên không âm, nhận {counter!r}")
    duong.write_text(f"{counter}\n", encoding="utf-8", newline="\n")


def _doc_counter_da_tieu(duong: Path) -> int:
    """Đọc lại counter, fail-closed trên MỌI thứ không phải chữ số."""
    if not duong.is_file():
        raise GateError(
            f"thiếu tệp counter {duong} — bước sync-casbin chưa chạy, hoặc đã "
            "chạy mà không ghi được counter nó vừa đốt"
        )
    noi_dung = duong.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+", noi_dung):
        raise GateError(f"tệp counter {duong} không chỉ chứa chữ số")
    return int(noi_dung)


def _cho_counter_vuot(counter_da_tieu: int, *, han_giay: float = 45.0) -> int:
    """Chờ tới khi counter TRƯỚC đã vượt hẳn counter mà ``sync`` đã đốt.

    Backend chống replay bằng một bất biến ĐƠN ĐIỆU NGHIÊM NGẶT: nó từ chối khi
    ``counter <= counter_đã_lưu``. Nếu ``sync`` đốt ``c`` và preflight lại gửi
    đúng ``c``, verify-mfa sẽ bị từ chối — và thiết kế này CẤM retry, nên cổng
    sẽ đỏ vì một lý do không liên quan gì tới thứ nó canh.

    Điều kiện chờ ``floor(t/30) - 1 > counter_đã_tiêu`` tương đương
    ``t >= 30*(counter_đã_tiêu + 2)``, nên nó bảo đảm mã mà preflight sắp sinh
    (ở counter ``floor(t/30) - 1``) LỚN HƠN HẲN counter đã đốt. Vì ``sync`` đốt
    counter trước của chính nó, cận trên lý thuyết của phép chờ là **dưới 30
    giây**; ``han_giay`` chỉ là hàng rào chống treo, không phải thời gian dự kiến.

    Hết hạn mà điều kiện chưa đạt thì ĐỎ. Đồng hồ không tiến là một sự cố thật,
    không phải thứ để thử lại.
    """
    het_han = time.monotonic() + han_giay
    while True:
        hien_tai = int(time.time() // TOTP_STEP_SECONDS)
        if hien_tai - 1 > counter_da_tieu:
            return hien_tai
        if time.monotonic() >= het_han:
            raise GateError(
                f"quá {han_giay:.0f}s mà counter TOTP chưa vượt "
                f"{counter_da_tieu} (hiện tại {hien_tai}); đồng hồ không tiến"
            )
        time.sleep(1.0)


#: Số kết nối MỚI dùng để lấy mẫu route Casbin sau cutover.
#:
#: ⚠️ Đây là bằng chứng BỔ TRỢ, không phải bằng chứng chính. Nếu ``accept()``
#: chia đều giữa hai worker thì 32 lượt bỏ sót một worker hỏng với xác suất
#: 2,3e-10; nhưng phép đo thật trên stack này cho tỷ lệ lệch 12,5%, và ở mức
#: ấy 32 lượt chỉ cho ~1,4% khả năng bỏ sót — kém tám bậc độ lớn. Bằng chứng
#: CHÍNH rằng mọi worker đã nạp policy là số tiến trình con và log khởi động
#: (đúng hai ``Booting worker`` + đúng hai ``policies loaded``), do bước cutover
#: trong workflow đo. Đừng đọc con số dưới đây thành "đã chứng minh".
PROBE_FLEET_LUOT = 32


def _probe_fleet(phien: PhienDaXacThuc, base_url: str) -> None:
    """Bắn ``PROBE_FLEET_LUOT`` kết nối MỚI vào route Casbin, đòi TOÀN BỘ 200.

    ``urllib.request`` dựng một ``HTTPConnection`` mới cho mỗi ``urlopen`` và
    tự đóng socket sau khi đọc xong, nên mỗi lượt là một ``accept()`` riêng —
    không cần và không thể bật keep-alive. Kết nối mới KHÔNG bảo đảm chạm
    worker khác; xem ghi chú ở ``PROBE_FLEET_LUOT``.
    """
    dem: dict[int, int] = {}
    for _ in range(PROBE_FLEET_LUOT):
        status, _than = _request_json(
            phien.opener, "GET", f"{base_url}{PROTECTED_ROUTE}"
        )
        dem[status] = dem.get(status, 0) + 1

    tong = sum(dem.values())
    # Hai phép RIÊNG: gộp lại thì khi đỏ không biết đỏ vì thiếu lượt hay vì mã lạ.
    if tong != PROBE_FLEET_LUOT:
        raise GateError(
            f"{phien.label}: phát {tong} lượt probe, cần đúng {PROBE_FLEET_LUOT}"
        )
    if set(dem) != {200}:
        raise GateError(
            f"{phien.label}: {PROTECTED_ROUTE} trả {dict(sorted(dem.items()))} "
            f"trên {PROBE_FLEET_LUOT} kết nối mới — fleet CHƯA hội tụ"
        )
    print(
        f"PASS {phien.label}: {PROBE_FLEET_LUOT}/{PROBE_FLEET_LUOT} kết nối mới "
        f"đều HTTP 200 (mẫu bổ trợ)"
    )


def sync_casbin() -> None:
    """Bước GHI DB: đưa policy về đúng template qua endpoint sản phẩm.

    KHÔNG phải bằng chứng fleet đã hội tụ. ``app/routers/admin_v2_casbin.py``
    ghi thẳng rằng một lượt gọi API chỉ nạp lại enforcer của **worker phục vụ
    chính request đó**; các worker còn lại giữ policy cũ trong bộ nhớ cho tới
    khi bị tạo lại. Vì vậy bước này chỉ chịu trách nhiệm cho trạng thái CSDL, và
    bước cutover sau nó mới là thứ đưa cả fleet về cùng một ảnh chụp.

    Counter TOTP mà lượt đăng nhập ở đây đốt được ghi ra tệp để ``preflight``
    biết phải chờ qua nó.
    """
    base_url = (_required_env("E2E_API_URL")).rstrip("/")
    duong_counter = _duong_tep_counter()
    accounts = _runtime_account_values()

    admin = [a for a in accounts if a[0] == "admin"]
    if len(admin) != 1:
        raise GateError(
            f"cần ĐÚNG một tài khoản nhãn 'admin' để sync, thấy {len(admin)}"
        )

    phien = _dang_nhap_va_chung_minh(admin[0], base_url)
    if phien.counter_da_tieu is None:
        raise GateError(
            "tài khoản sync không đi qua MFA — không có counter nào để cách ly"
        )
    # Ghi counter NGAY sau khi verify, TRƯỚC lượt sync: nếu sync đỏ thì counter
    # kia vẫn đã bị đốt thật, và bước sau vẫn phải chờ qua nó.
    _ghi_counter_da_tieu(duong_counter, phien.counter_da_tieu)

    _sync_casbin_after_seed(phien.opener, phien.cookie_jar, base_url)
    print(
        "Casbin policy đã ghi vào CSDL. Fleet CHƯA hội tụ — bước cutover "
        "tiếp theo mới tạo lại backend để mọi worker nạp lại."
    )


def preflight() -> None:
    """Cổng CUỐI, CHỈ ĐỌC: không sửa policy, không gọi route ghi nào."""
    base_url = (_required_env("E2E_API_URL")).rstrip("/")
    accounts = _runtime_account_values()

    # Đọc env TRƯỚC khi chờ: thiếu biến là lỗi cấu hình, phải đỏ ngay chứ không
    # đỏ sau ba mươi giây ngủ.
    counter_da_tieu = _doc_counter_da_tieu(_duong_tep_counter())
    _cho_counter_vuot(counter_da_tieu)

    phien_theo_nhan: dict[str, PhienDaXacThuc] = {}
    for account in accounts:
        phien_theo_nhan[account[0]] = _preflight_account(account, base_url)

    # Lấy mẫu trên PHIÊN ĐÃ CÓ — không đăng nhập lại. Khoá chống replay là
    # `totp_used:{user_id}`, tức theo NGƯỜI DÙNG chứ không theo phiên; mỗi lượt
    # đăng nhập MFA thêm là một counter nữa bị đốt và một lượt chờ nữa.
    for nhan in ("admin", "manager", "officer"):
        if nhan not in phien_theo_nhan:
            raise GateError(f"thiếu phiên {nhan!r} để lấy mẫu fleet")
        _probe_fleet(phien_theo_nhan[nhan], base_url)

    # "Bốn ĐƯỜNG ĐĂNG NHẬP trên BA tài khoản", không phải "bốn danh tính":
    # `setup` dùng lại chính tài khoản officer (`vothithuthuhien`), chỉ khác
    # User-Agent. Gọi nó là bốn danh tính là đếm thừa một tài khoản và che mất
    # việc hai đường ấy chia sẻ cùng một bản ghi người dùng.
    print(
        "Nightly MFA/authentication preflight passed: "
        "four login paths across three accounts."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("generate", "bootstrap", "sync-casbin", "preflight")
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            generate_runtime_environment()
        elif args.command == "bootstrap":
            asyncio.run(bootstrap_runtime_mfa())
        elif args.command == "sync-casbin":
            sync_casbin()
        else:
            preflight()
    except GateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
