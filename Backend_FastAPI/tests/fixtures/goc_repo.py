"""Tìm gốc repo cho test đọc tệp NGOÀI ``Backend_FastAPI/`` (template nginx, fixture giao diện) — review max PR #724 (R15).

``Path(__file__).resolve().parents[3]`` chỉ đúng khi cây repo đủ (runner CI, container ``kd_i.sh`` chép cả repo). Trong
container dev (``docker compose exec backend pytest`` — ``docker-compose.override.yml`` mount ``./Backend_FastAPI`` vào
``/app``) nó ra ``/`` ⇒ test HỎNG CỨNG vì "không có tệp" (không phải vì hành vi). Cùng lối của ``_tim_goc`` trong
``tests/unit/test_nginx_template_packaging.py`` nhưng theo TỪNG test: tìm theo ĐÚNG các tệp cần đọc, ưu tiên
``QLTS_REPO_ROOT``; không thấy ⇒ ``pytest.skip`` riêng test ấy (không bỏ qua cả mô-đun)."""
import os
from pathlib import Path

import pytest


def goc_repo_co(*duong_tuong_doi: str) -> Path:
    """Thư mục tổ tiên đầu tiên chứa ĐỦ mọi ``duong_tuong_doi``; không có ⇒ bỏ qua test đang chạy (nêu lý do)."""
    assert duong_tuong_doi, "phải nêu ít nhất một tệp cần đọc"
    ung_vien = list(Path(__file__).resolve().parents)
    tu_env = os.environ.get("QLTS_REPO_ROOT")
    if tu_env:
        ung_vien.insert(0, Path(tu_env))
    for thu_muc in ung_vien:
        if all((thu_muc / d).is_file() for d in duong_tuong_doi):
            return thu_muc
    pytest.skip(
        "không thấy gốc repo có %s (container chỉ mount Backend_FastAPI?) — mount cây repo và đặt QLTS_REPO_ROOT."
        % ", ".join(duong_tuong_doi)
    )
