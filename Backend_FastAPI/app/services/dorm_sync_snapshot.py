# -*- coding: utf-8 -*-
"""Ảnh chụp nguồn v1 và token xem trước.

Hai việc, một mục đích: **buộc lần ghi phải đúng thứ người bấm đã nhìn**.

* ``build_source_snapshot`` + ``hash_source_snapshot`` chốt phía NGUỒN (QLTS);
* ``dorm_sync_target_snapshot`` phía KTX chốt phía ĐÍCH (đã có ở Gate 1);
* ``phat_hanh_token`` gói cả hai dấu vào một chuỗi có chữ ký, để bước apply
  không nhận bất kỳ tham số phạm vi nào từ client.

🔴 Module này THUẦN: không đọc biến môi trường, không chạm HTTP, không chạm
database. Khoá ký được truyền vào tường minh — cùng lý do với
``DormSyncConfig``: một hàm tự đi lấy bí mật là một hàm không kiểm được, và
tầng gọi nó mất khả năng chọn khoá.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.dorm_sync_service import _phan_payload_on_dinh
from app.utils.exceptions import DormSyncTokenError

# Phiên bản hình dạng snapshot. Đổi tập trường ⇒ TĂNG số này: một dấu băm cũ so
# với một snapshot dựng theo hình dạng mới là so hai thứ khác nhau, và nó sẽ
# lệch mà không ai biết vì sao.
SNAPSHOT_VERSION = 1

# Phiên bản token. Tách khỏi `SNAPSHOT_VERSION` vì hai thứ đổi vì hai lý do.
TOKEN_VERSION = 1

# 🔴 Năm phút. Token mang quyền chạy một lượt hạ cờ, nên nó phải chết sớm.
#
# Nhưng cũng không được quá ngắn: người bấm cần thời gian ĐỌC danh sách cảnh
# báo — mà đọc danh sách đó chính là lý do bước xem trước tồn tại. Ép họ vội là
# ép họ bấm mà không đọc.
TOKEN_TTL_GIAY = 300

# Trường thứ 13 của một hàng snapshot, KHÔNG có trong payload gửi đi.
#
# Nó nằm trong ảnh chụp vì nó quyết định TƯ CÁCH của hàng: một hồ sơ đổi từ
# `confirmed` sang `draft` rơi khỏi cohort ở lượt sau. Người bấm duyệt một danh
# sách mà mọi hồ sơ đều `confirmed`, rồi tới lúc ghi có hồ sơ đã về `draft` —
# đó là một thay đổi thật, và dấu băm phải thấy nó.
_TRUONG_TRANG_THAI = "profile_status"


def _chuan_hoa(gia_tri: Any) -> Any:
    """Chuẩn hoá một giá trị trước khi băm.

    ⚠️ Chuỗi được đưa về NFC. Tiếng Việt có hai cách mã hoá cùng một chữ —
    "Nguyễn" dựng sẵn (NFC) và "Nguyễn" tổ hợp (NFD) khác nhau từng byte nhưng
    giống hệt trên màn hình. Không chuẩn hoá thì một thay đổi vô hình ở tầng
    nhập liệu làm dấu băm đổi, và chốt chặn một lượt hoàn toàn bình thường
    bằng một lý do không ai nhìn thấy được.
    """
    if isinstance(gia_tri, str):
        return unicodedata.normalize("NFC", gia_tri)
    return gia_tri


def build_source_snapshot(rows: Sequence[Any]) -> Dict[str, Any]:
    """Ảnh chụp phía NGUỒN: 12 trường ổn định + ``profile_status``.

    ⚠️ Sắp theo ``qlts_profile_id`` Ở ĐÂY. Thứ tự hàng từ ``fetch_cohort`` là
    thứ tự kế hoạch thực thi của Postgres; hai lượt gọi liền nhau có thể trả
    cùng tập hàng theo hai thứ tự khác nhau, và dấu băm sẽ đổi mà dữ liệu thì
    không.
    """
    hang: List[Dict[str, Any]] = []
    for row in rows:
        ban_ghi = {
            khoa: _chuan_hoa(gia_tri)
            for khoa, gia_tri in _phan_payload_on_dinh(row).items()
        }
        ban_ghi[_TRUONG_TRANG_THAI] = _chuan_hoa(getattr(row, "profile_status", None))
        hang.append(ban_ghi)

    hang.sort(key=lambda h: h["qlts_profile_id"])

    return {
        "version": SNAPSHOT_VERSION,
        "row_count": len(hang),
        "rows": hang,
    }


def _json_canonical(gia_tri: Any) -> bytes:
    """JSON ổn định: khoá sắp xếp, không khoảng trắng thừa, UTF-8 nguyên bản.

    ``ensure_ascii=False`` để chuỗi tiếng Việt đi vào phép băm ở dạng UTF-8 đã
    chuẩn hoá NFC, thay vì dạng escape ``\\uXXXX`` — hai cách viết cùng một
    chuỗi cho hai dấu băm khác nhau.
    """
    return json.dumps(
        gia_tri,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def hash_source_snapshot(snapshot: Dict[str, Any]) -> str:
    """SHA-256 của snapshot, dạng hex 64 ký tự chữ thường."""
    return hashlib.sha256(_json_canonical(snapshot)).hexdigest()


# ---------------------------------------------------------------------------
# Token xem trước
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewTokenClaims:
    """Nội dung token sau khi đã xác thực chữ ký.

    🔴 KHÔNG trường nào ở đây là dữ liệu cá nhân. HMAC chỉ bảo đảm TOÀN VẸN —
    nó không mã hoá. Phần thân token là base64url và ai cầm chuỗi cũng đọc
    được: nhét họ tên, số điện thoại hay snapshot thô vào đây là phát tán danh
    sách người học qua thanh địa chỉ, log proxy và lịch sử trình duyệt.

    Danh sách cảnh báo (có họ tên, phòng, giường) đi trong THÂN PHẢN HỒI của
    bước xem trước — nơi có kiểm quyền — chứ không đi trong token.
    """

    version: int
    operation_id: uuid.UUID
    actor_id: int
    academic_year: int
    issued_at: int
    expires_at: int
    source_hash: str
    target_fingerprint: str


def _b64_ma(du_lieu: bytes) -> str:
    return base64.urlsafe_b64encode(du_lieu).decode("ascii").rstrip("=")


def _b64_giai(chuoi: str) -> bytes:
    # base64url bỏ dấu `=`; thêm lại đủ bội số 4 trước khi giải.
    thieu = (-len(chuoi)) % 4
    return base64.urlsafe_b64decode(chuoi + "=" * thieu)


def _ky(than: bytes, secret: str) -> str:
    return _b64_ma(hmac.new(secret.encode("utf-8"), than, hashlib.sha256).digest())


def phat_hanh_token(
    *,
    secret: str,
    actor_id: int,
    academic_year: int,
    source_hash: str,
    target_fingerprint: str,
    now_ts: int,
    operation_id: Optional[uuid.UUID] = None,
) -> Tuple[str, PreviewTokenClaims]:
    """Ký một token xem trước. Trả ``(chuỗi token, claims)``.

    🔴 ``operation_id`` do SERVER sinh. Tham số này chỉ để test bơm giá trị cố
    định; đường chạy thật không truyền, và ``DormSyncApplyRequest`` cũng không
    có trường đó. Nhận ``operation_id`` từ client là mở lại đúng cửa
    chống-replay mà sổ cái sinh ra để đóng: người gọi tự đặt một giá trị mới ở
    mỗi lần thử là chạy được bao nhiêu lượt tuỳ ý.

    ⚠️ ``now_ts`` truyền vào, không gọi ``time.time()`` bên trong. Một hàm tự
    đọc đồng hồ là một hàm không kiểm được ca hết hạn.
    """
    if not secret:
        raise DormSyncTokenError("Thiếu khoá ký token xem trước.")

    claims = PreviewTokenClaims(
        version=TOKEN_VERSION,
        operation_id=operation_id or uuid.uuid4(),
        actor_id=actor_id,
        academic_year=academic_year,
        issued_at=now_ts,
        expires_at=now_ts + TOKEN_TTL_GIAY,
        source_hash=source_hash,
        target_fingerprint=target_fingerprint,
    )

    than = _json_canonical(
        {
            "v": claims.version,
            "op": str(claims.operation_id),
            "actor": claims.actor_id,
            "year": claims.academic_year,
            "iat": claims.issued_at,
            "exp": claims.expires_at,
            "src": claims.source_hash,
            "tgt": claims.target_fingerprint,
        }
    )
    than_b64 = _b64_ma(than)
    return f"{than_b64}.{_ky(than, secret)}", claims


def doc_token(
    token: str,
    *,
    secret: str,
    actor_id: int,
    now_ts: int,
) -> PreviewTokenClaims:
    """Xác thực và giải một token. Ném :class:`DormSyncTokenError` nếu không hợp lệ.

    Thứ tự kiểm có chủ đích:

    1. **Chữ ký trước mọi thứ.** Đọc nội dung rồi mới kiểm chữ ký nghĩa là để
       dữ liệu chưa xác thực đi vào các phép so bên dưới.
    2. ``hmac.compare_digest``, KHÔNG dùng ``==``. So chuỗi bằng ``==`` thoát
       ngay ở byte đầu khác nhau, và thời gian thoát ấy rò rỉ chữ ký đúng từng
       byte một.
    3. Phiên bản, rồi mới tới thời gian và người bấm.

    🔴 ``actor_id`` phải KHỚP người đang gọi. Token là giấy phép chạy một lượt
    hạ cờ; một admin khác nhặt được chuỗi này (từ log, từ màn hình chia sẻ) mà
    dùng lại được thì nhật ký ghi tên người phát hành cho một thao tác của
    người khác.
    """
    if not secret:
        raise DormSyncTokenError("Thiếu khoá ký token xem trước.")

    phan = token.split(".")
    if len(phan) != 2:
        raise DormSyncTokenError("Token xem trước sai định dạng.")

    than_b64, chu_ky = phan
    try:
        than = _b64_giai(than_b64)
    except Exception:
        raise DormSyncTokenError("Token xem trước sai định dạng.") from None

    # 🔴 Chữ ký TRƯỚC. `compare_digest` so trong thời gian hằng định.
    if not hmac.compare_digest(_ky(than, secret), chu_ky):
        raise DormSyncTokenError("Chữ ký token xem trước không hợp lệ.")

    try:
        du_lieu = json.loads(than.decode("utf-8"))
    except Exception:
        raise DormSyncTokenError("Token xem trước sai định dạng.") from None
    if not isinstance(du_lieu, dict):
        raise DormSyncTokenError("Token xem trước sai định dạng.")

    if du_lieu.get("v") != TOKEN_VERSION:
        # Đổi hình dạng token mà vẫn nhận bản cũ là nhận một giấy phép được ký
        # theo một bộ quy tắc đã bị thay.
        raise DormSyncTokenError("Token xem trước thuộc phiên bản không còn dùng.")

    try:
        op = uuid.UUID(str(du_lieu["op"]))
        claims = PreviewTokenClaims(
            version=int(du_lieu["v"]),
            operation_id=op,
            actor_id=int(du_lieu["actor"]),
            academic_year=int(du_lieu["year"]),
            issued_at=int(du_lieu["iat"]),
            expires_at=int(du_lieu["exp"]),
            source_hash=str(du_lieu["src"]),
            target_fingerprint=str(du_lieu["tgt"]),
        )
    except (KeyError, TypeError, ValueError):
        raise DormSyncTokenError("Token xem trước thiếu trường bắt buộc.") from None

    # ⚠️ Kiểm CẢ khoảng sống, không chỉ `exp`. Một token có `exp` rất xa —
    # hoặc `iat` nằm ở tương lai — nghĩa là nó không do đường phát hành này
    # sinh ra, dù chữ ký đúng (ví dụ khoá bị dùng lại ở nơi khác).
    if claims.expires_at - claims.issued_at != TOKEN_TTL_GIAY:
        raise DormSyncTokenError("Token xem trước có khoảng sống bất thường.")
    if claims.issued_at > now_ts:
        raise DormSyncTokenError("Token xem trước mang thời điểm phát hành ở tương lai.")
    if now_ts >= claims.expires_at:
        raise DormSyncTokenError(
            "Token xem trước đã hết hạn. Xem lại danh sách rồi bấm lại."
        )

    if claims.actor_id != actor_id:
        raise DormSyncTokenError("Token xem trước không thuộc về người đang thao tác.")

    return claims
