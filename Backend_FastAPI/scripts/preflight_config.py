#!/usr/bin/env python
"""Preflight cấu hình: dựng ``Settings`` của ẢNH VỪA BUILD, TRƯỚC khi chạm CSDL.

Vì sao bước này tồn tại
-----------------------
``scripts/deploy.sh`` trước đây đi theo thứ tự:

    Step 4  build image
    Step 5  pg_dump                     ← bản sao được tạo
    Step 6  alembic upgrade head        ← mọi lỗi ⇒ "Migration failed" ⇒ RESTORE
    Step 7  pre_deploy_check.py         ← cổng cấu hình chạy SAU

``alembic upgrade head`` import ``app.config``, nên MỘT biến môi trường thiếu
làm ``Settings()`` raise **bên trong Step 6**. Script phân loại nhầm chuyện đó
là migration failure và kích hoạt replay ``pg_restore`` lên một CSDL production
**chưa hề thay đổi**. Bản thân lượt restore thừa đã tệ; tệ hơn là nếu chính nó
vấp thì hệ rơi vào trạng thái "schema nửa cũ nửa mới" mà deploy.sh cảnh báo là
không tiến không lùi.

Nói gọn: một lỗi CHÍNH TẢ trong ``.env.production`` có thể kéo theo một thao
tác khôi phục CSDL production. Bước này cắt đúng đường đó — cấu hình hỏng thì
dừng **trước** ``pg_dump``, nên không có bản sao nào được tạo, không có
migration nào chạy, và nhánh restore không bao giờ được chạm tới.

Vì sao chạy bằng ``--entrypoint python``
----------------------------------------
``Backend_FastAPI/Dockerfile`` khai ENTRYPOINT là ``docker-entrypoint.sh``, và
``docker compose run`` chỉ đè CMD chứ KHÔNG đè ENTRYPOINT. Thiếu
``--entrypoint`` thì chính bước preflight này sẽ chạy trọn
``alembic upgrade head`` + ``sync_notification_rules`` trước khi tới đây — tức
là gây ra đúng thứ nó sinh ra để ngăn. Cùng lý do với Step 7.

Không rò bí mật
---------------
Thông báo lỗi đi qua ``app.utils.redact.mo_ta_loi_an_toan``, KHÔNG qua
``str(exc)``. Lý do đo được: ``ValidationError`` của pydantic tự chèn
``input_value=<giá trị người dùng đặt>`` vào message, nên một biến bí mật đặt
sai kiểu sẽ nằm nguyên văn trong log. Bộ mô tả chỉ lấy ``loc``/``msg``/``type``
và bỏ hẳn ``input``.

Phải gọi bằng ``python -m scripts.preflight_config``
---------------------------------------------------
Chạy theo đường tệp (``python scripts/preflight_config.py``) thì ``sys.path[0]``
là ``/app/scripts`` chứ không phải ``/app``, và ``import app`` chết bằng
``ModuleNotFoundError`` TRƯỚC khi tới bất kỳ phép kiểm nào — tức mọi deploy
dừng ở đây kể cả khi cấu hình hoàn toàn đúng. Đo được cả hai chiều: đường tệp
rc=1, module mode rc=0. ``tests/unit/test_deploy_startup_gates.py`` khoá cả
cách gọi trong ``deploy.sh`` lẫn hành vi thật của hai cách gọi.
"""
from __future__ import annotations

import sys


def main() -> int:
    # Import TRƯỚC, và từ một module không side effect: ca hỏng cần tới nó là
    # đúng ca ``app.config`` không import nổi.
    from app.utils.redact import mo_ta_loi_an_toan

    try:
        # Chính hành vi import này là phép kiểm: ``app/config.py`` dựng
        # ``Settings()`` rồi gọi ``_validate_production_secrets()`` ở cấp module.
        from app.config import settings
    except Exception as exc:  # noqa: BLE001 — mọi lỗi cấu hình đều phải chặn
        print("PREFLIGHT CẤU HÌNH: THẤT BẠI", file=sys.stderr)
        print(f"  loại lỗi : {type(exc).__name__}", file=sys.stderr)
        print(f"  chi tiết : {mo_ta_loi_an_toan(exc)}", file=sys.stderr)
        print(
            "  cần làm  : sửa .env.production rồi chạy lại deploy. "
            "CSDL CHƯA bị chạm — không bản sao nào được tạo, "
            "không migration nào chạy.",
            file=sys.stderr,
        )
        return 1

    print(f"PREFLIGHT CẤU HÌNH: ĐẠT — APP_ENV={settings.APP_ENV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
