"""Cấu hình đồng bộ ký túc xá — fail-closed, tách khỏi ``Settings``.

🔴 Vì sao tầng này tồn tại thay vì khai sáu biến ``DORM_*`` là bắt buộc trong
``Settings``: ``celery-worker`` và ``celery-beat`` nạp **cùng** lớp ``Settings``
nhưng không nhận các biến đó và cũng không cần chúng. Khai bắt buộc — hoặc nhét
vào ``_validate_production_secrets()`` — làm hai container ấy chết ngay lúc khởi
động vì thiếu khoá của một tính năng chúng không dùng.

Nên hợp đồng là: ``Settings`` giữ sáu trường **optional, default rỗng**; còn chỗ
nào thực sự định gọi sang KTX thì gọi :meth:`DormSyncConfig.from_settings`, và
hàm này từ chối dứt khoát nếu thiếu bất kỳ giá trị nào.

⚠️ Không hàm nào ở đây đoán giá trị mặc định. Đường ghi này hạ được cờ
đủ-điều-kiện của cả một khoá học; một đích đến đoán ra là một đích đến sẽ sai
vào ngày nào đó.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from app.utils.exceptions import DormSyncConfigError, DormSyncDisabledError

# Tên biến môi trường ↔ thuộc tính trên ``Settings``. Giữ nguyên tên biến để
# thông điệp lỗi nói đúng thứ người vận hành phải đặt.
_TRUONG_BAT_BUOC: Tuple[Tuple[str, str], ...] = (
    ("DORM_SUPABASE_URL", "DORM_SUPABASE_URL"),
    ("DORM_SUPABASE_SECRET_KEY", "DORM_SUPABASE_SECRET_KEY"),
    ("DORM_SYNC_TARGET_PROJECT_REF", "DORM_SYNC_TARGET_PROJECT_REF"),
    ("DORM_SYNC_SOURCE_DB", "DORM_SYNC_SOURCE_DB"),
    ("DORM_SYNC_SOURCE_SYSTEM_ID", "DORM_SYNC_SOURCE_SYSTEM_ID"),
)


@dataclass(frozen=True)
class DormSyncConfig:
    """Năm giá trị cần để nói chuyện với hệ KTX, đã kiểm đủ."""

    supabase_url: str
    supabase_secret_key: str
    target_project_ref: str
    source_db: str
    source_system_id: str

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "DormSyncConfig":
        """Dựng cấu hình, hoặc ném lỗi rõ ràng.

        :raises DormSyncDisabledError: cờ ``DORM_SYNC_ENABLED`` đang tắt.
        :raises DormSyncConfigError: cờ bật nhưng thiếu ít nhất một giá trị.

        🔴 Hai lỗi TÁCH RIÊNG. "Chưa bật" là trạng thái bình thường của mọi máy
        dev và của CI; "bật mà thiếu khoá" là cấu hình hỏng. Trả cùng một mã cho
        hai ca đó thì người vận hành đọc log không biết mình đang ở ca nào.
        """
        if settings is None:  # pragma: no cover - đường mặc định trong runtime
            from app.config import settings as _settings

            settings = _settings

        if not getattr(settings, "DORM_SYNC_ENABLED", False):
            raise DormSyncDisabledError(
                "Đồng bộ ký túc xá chưa được bật (DORM_SYNC_ENABLED=false)."
            )

        thieu: List[str] = []
        gia_tri = {}
        for ten_bien, thuoc_tinh in _TRUONG_BAT_BUOC:
            raw = getattr(settings, thuoc_tinh, "") or ""
            # ⚠️ ``.strip()`` chứ không chỉ kiểm rỗng: compose truyền
            # ``VAR=${VAR:-}`` nên một biến chưa đặt tới đây là chuỗi rỗng, còn
            # một biến đặt nhầm bằng dấu cách thì trông "có giá trị" mà vô dụng.
            if not raw.strip():
                thieu.append(ten_bien)
            else:
                gia_tri[thuoc_tinh] = raw.strip()

        if thieu:
            raise DormSyncConfigError(
                "Đồng bộ ký túc xá đang bật nhưng thiếu cấu hình: "
                + ", ".join(thieu)
                + ". Đặt đủ các biến này cho service backend (KHÔNG đặt cho "
                "celery-worker / celery-beat)."
            )

        return cls(
            supabase_url=gia_tri["DORM_SUPABASE_URL"],
            supabase_secret_key=gia_tri["DORM_SUPABASE_SECRET_KEY"],
            target_project_ref=gia_tri["DORM_SYNC_TARGET_PROJECT_REF"],
            source_db=gia_tri["DORM_SYNC_SOURCE_DB"],
            source_system_id=gia_tri["DORM_SYNC_SOURCE_SYSTEM_ID"],
        )
