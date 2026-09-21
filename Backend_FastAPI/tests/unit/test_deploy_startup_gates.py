"""Khoá ba cổng khởi động của đường deploy (F6 · F7 · F8, vá 13-08-2026).

Vì sao tệp này tồn tại
----------------------
Ba lỗ được tìm ra khi audit đường deploy trên `079ae179`, và cả ba đều thuộc
loại "xanh mà không bảo vệ gì":

* **F6** — `celery-worker` và `celery-beat` dùng CHUNG
  `Backend_FastAPI/docker-entrypoint.sh` với backend (compose ``command:`` chỉ
  đè CMD, không đè ENTRYPOINT). Khi hai cờ ``RUN_MIGRATIONS_ON_STARTUP`` và
  ``RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP`` còn nội suy ``${...:-true}`` cho
  cả ba service thì mỗi lần dựng lại Celery là thêm một tiến trình chạy
  ``alembic upgrade head`` + ``sync_notification_rules``. Đo trên prod
  13-08-2026: hai container Celery mang env ``false`` (di sản cold cutover)
  trong khi model Compose nói ``true`` ⇒ **lệch model** ⇒ Compose recreate
  chúng ngay cả với một bản vá không đụng gì tới Celery.

* **F7** — Step 5 sao lưu CSDL trước đây chỉ ``warn`` ở cả ba nhánh hỏng rồi
  đi tiếp vào Step 6, tức chạy migration khi không có đường lùi.

* **F8** — Step 7 nuốt mã thoát của ``pre_deploy_check.py`` bằng ``|| warn``.
  Script đó tự phân loại rồi mới chọn mã thoát: thiếu WARNING_POLICIES thì
  exit 0, thiếu CRITICAL_POLICIES thì exit 1 kèm "CRITICAL: DEPLOY BLOCKED".
  Nhánh ``|| warn`` biến đúng cổng chặn ấy thành một dòng chữ vàng.

Nguyên tắc của tệp: **không tin phép kiểm chuỗi**. Phần F7/F8 chạy THẬT
`scripts/deploy.sh` bằng bash với `docker`/`git` giả trên PATH, rồi đọc nhật
ký lệnh để khẳng định ``alembic upgrade head`` (Step 6) và ``up -d backend``
(Step 8) có được gọi hay không. Mỗi guard còn có một ca **kiểm ngược**: gỡ
đúng guard ấy khỏi một bản sao và chứng minh nhánh hỏng lại đi lọt — nếu
không có ca đó thì "vẫn xanh" chẳng chứng minh được điều gì.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")


def _tim_goc() -> Path:
    """Đi ngược lên tìm gốc repo bằng MỐC, không đếm số tầng thư mục.

    Cùng lý do đã ghi ở `test_nginx_template_packaging.py`: dưới lệnh mà
    CLAUDE.md ghi là cách chạy test tại máy, tệp này nằm ở `/app/tests/...`
    nên đếm tầng sẽ ra thẳng `/` và cả tệp bị bỏ qua trong im lặng.
    """
    ung_vien = list(Path(__file__).resolve().parents)
    tu_env = os.environ.get("QLTS_REPO_ROOT")
    if tu_env:
        ung_vien.insert(0, Path(tu_env))
    for thu_muc in ung_vien:
        if (thu_muc / "docker-compose.yml").is_file() and (thu_muc / ".git").exists():
            return thu_muc
    pytest.skip(
        "không thấy gốc repo (cần docker-compose.yml + .git). Chạy trong "
        "container backend thì mount cây repo và đặt QLTS_REPO_ROOT.",
        allow_module_level=True,
    )


_GOC = _tim_goc()
_COMPOSE = _GOC / "docker-compose.yml"
_DEPLOY = _GOC / "scripts" / "deploy.sh"

_CO_MIGRATION = "RUN_MIGRATIONS_ON_STARTUP"
_CO_SYNC = "RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP"
_CO_CASBIN = "RUN_CASBIN_LOAD_ON_STARTUP"

# Hai cờ PHẢI đóng cứng "false" ở Celery. Casbin cố ý KHÔNG nằm đây: worker và
# beat vẫn cần enforcer nạp policy, nên cờ ấy còn đi theo cold cutover.
_CO_DONG_CUNG = (_CO_MIGRATION, _CO_SYNC)
_DV_CELERY = ("celery-worker", "celery-beat")

# Dấu hiệu trong nhật ký lệnh giả — mốc của Step 6 và Step 8.
#
# Cố ý KHÔNG dùng chuỗi "alembic upgrade head": sau khi one-off chuyển sang
# `--entrypoint alembic backend upgrade head` thì hai từ ấy không còn liền
# nhau, và một mốc quá khít sẽ làm test xanh/đỏ theo cách viết lệnh chứ không
# theo hành vi. "upgrade head" khớp cả hai dạng, kể cả dạng cũ đang được ca
# kiểm ngược dựng lại.
_MOC_ALEMBIC = "upgrade head"
_MOC_PGDUMP = "pg_dump"
_MOC_PREFLIGHT = "preflight_config"
_MOC_STEP8 = "up -d backend celery-worker celery-beat"
# Dấu hiệu ENTRYPOINT của ảnh backend chạy KÈM một one-off (xem stub docker).
_MOC_EP_ALEMBIC = "entrypoint: alembic upgrade head"
_MOC_EP_SYNC = "entrypoint: sync_notification_rules"


# =============================================================================
# F6 — model Compose
# =============================================================================
@pytest.fixture(scope="module")
def compose() -> dict:
    if not _COMPOSE.is_file():
        pytest.skip(f"không thấy {_COMPOSE}")
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _vi_pham_f6(mo_hinh: dict) -> list[str]:
    """Trả về danh sách vi phạm F6 trong một mô hình compose bất kỳ.

    Tách thành hàm thuần để ca kiểm ngược chạy được ĐÚNG logic này trên một
    bản đã đột biến, thay vì viết lại một bản kiểm khác trong test — bản viết
    lại chỉ chứng minh giả định của người viết test.
    """
    vi_pham: list[str] = []
    dich_vu = mo_hinh.get("services", {})
    for ten in _DV_CELERY:
        moi_truong = (dich_vu.get(ten) or {}).get("environment") or {}
        for co in _CO_DONG_CUNG:
            if co not in moi_truong:
                vi_pham.append(f"{ten}: thiếu hẳn {co}")
                continue
            gia_tri = str(moi_truong[co])
            if "${" in gia_tri:
                vi_pham.append(
                    f"{ten}.{co} = {gia_tri!r} — còn nội suy từ biến host; "
                    "biến host bật true là Celery lại chạy alembic/sync"
                )
            elif gia_tri.strip().lower() != "false":
                vi_pham.append(f"{ten}.{co} = {gia_tri!r}, phải là \"false\"")
    return vi_pham


def test_hai_celery_dong_cung_khong_chay_migration_va_sync(compose: dict) -> None:
    assert _vi_pham_f6(compose) == []


@pytest.mark.parametrize("ten_dv", _DV_CELERY)
def test_celery_van_giu_casbin_theo_cold_cutover(compose: dict, ten_dv: str) -> None:
    """Casbin KHÔNG được đóng cứng — worker/beat cần enforcer có policy."""
    moi_truong = compose["services"][ten_dv]["environment"]
    assert moi_truong[_CO_CASBIN] == "${" + _CO_CASBIN + ":-true}", (
        f"{ten_dv}.{_CO_CASBIN} phải còn nội suy để cold cutover tắt được nó"
    )


@pytest.mark.parametrize("co", _CO_DONG_CUNG)
def test_backend_van_la_noi_duy_nhat_chay_migration_va_sync(
    compose: dict, co: str
) -> None:
    """Backend giữ nội suy: `COLD_CUTOVER=true` vẫn phải tắt được hai cờ này."""
    gia_tri = compose["services"]["backend"]["environment"][co]
    assert gia_tri == "${" + co + ":-true}", (
        f"backend.{co} = {gia_tri!r} — mất nội suy thì COLD_CUTOVER không còn "
        "đường nào bơm 'false' vào container"
    )


def test_kiem_nguoc_dat_lai_noi_suy_cho_celery_thi_bi_bat(compose: dict) -> None:
    """Gỡ guard ra thì phép kiểm phải ĐỎ — nếu không, nó không canh gì cả."""
    import copy

    for ten in _DV_CELERY:
        for co in _CO_DONG_CUNG:
            dot_bien = copy.deepcopy(compose)
            dot_bien["services"][ten]["environment"][co] = "${" + co + ":-true}"
            phat_hien = _vi_pham_f6(dot_bien)
            assert any(ten in v and co in v for v in phat_hien), (
                f"đặt lại nội suy cho {ten}.{co} mà _vi_pham_f6 không bắt được"
            )


def test_model_compose_that_giu_celery_false_du_bien_host_dat_true(
    tmp_path: Path,
) -> None:
    """Phép kiểm ĐỘNG: hỏi chính Compose, không suy luận từ YAML thô.

    Đây là ca tái hiện đúng tình huống prod 13-08: `.env.production` đặt cả ba
    cờ = true. Backend phải nhận `true`, hai Celery vẫn phải nhận `false`.
    """
    if shutil.which("docker") is None:
        pytest.skip("không có docker CLI để hỏi model compose")

    # Mọi service ứng dụng khai `env_file: ${QLTS_ENV_FILE:-.env.production}`,
    # mà `.env.production` KHÔNG có trong repo (và không được có). Thiếu nó thì
    # `config` đổ ngay. Trỏ biến ấy vào một tệp tạm để phép kiểm chạy được ở
    # CI y như ở máy.
    env_gia = tmp_path / "env.gia"
    env_gia.write_text("DOMAIN=vidu.test\nPOSTGRES_PASSWORD=matkhau-gia\n", encoding="utf-8")

    moi_truong = {
        **os.environ,
        # Đặt SAU `**os.environ` — nếu không, một biến cùng tên sẵn có trong
        # môi trường người chạy sẽ ghi đè và phép kiểm lại đọc `.env.production`.
        "QLTS_ENV_FILE": str(env_gia),
        _CO_MIGRATION: "true",
        _CO_SYNC: "true",
        _CO_CASBIN: "true",
        "COMPOSE_PROJECT_NAME": "qlts-kiem-model",
        # Ba biến khai bằng `${...:?}` — thiếu là `config` đổ trước khi kịp
        # render gì. Giá trị chỉ để nội suy chạy được, không service nào được
        # dựng ở đây.
        "DOMAIN": "vidu.test",
        "POSTGRES_PASSWORD": "matkhau-gia",
        "NEXT_PUBLIC_API_URL": "https://vidu.test",
    }
    ket = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE), "config"],
        cwd=str(_GOC),
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=180,
    )
    # KHÔNG skip ở đây. Docker CLI đã có, lệnh đã chạy — mã thoát khác 0 nghĩa
    # là mô hình compose hỏng (YAML sai, biến bắt buộc thiếu, tag không hợp lệ).
    # Skip lúc này biến một CI đỏ đáng lẽ phải thấy thành một dòng "skipped"
    # trôi qua không ai đọc.
    assert ket.returncode == 0, (
        "`docker compose config` thất bại — mô hình compose không render được.\n"
        f"stderr:\n{ket.stderr[-1500:]}"
    )

    mo_hinh = yaml.safe_load(ket.stdout)
    dich_vu = mo_hinh["services"]

    for co in _CO_DONG_CUNG:
        assert str(dich_vu["backend"]["environment"][co]).lower() == "true", (
            f"backend.{co} phải theo biến host (true), nếu không thì "
            "COLD_CUTOVER mất đường vào container"
        )
        for ten in _DV_CELERY:
            thuc = str(dich_vu[ten]["environment"][co]).lower()
            assert thuc == "false", (
                f"{ten}.{co} = {thuc!r} dù biến host là true — Celery sẽ chạy "
                "alembic/sync song song với backend, và model lệch trạng thái "
                "container thật sẽ kéo theo recreate ngoài ý muốn"
            )


# =============================================================================
# F7 + F8 — chạy THẬT scripts/deploy.sh với docker/git giả
# =============================================================================
_STUB_DOCKER = r"""#!/usr/bin/env bash
# `docker` giả: ghi lại mọi lệnh rồi trả mã thoát theo kịch bản của test.
echo "docker $*" >> "$QLTS_STUB_LOG"
_tat_ca="$*"

# CID giả phải theo ĐÚNG hợp đồng production: `docker compose ps -q` và
# `docker inspect` trả ID ĐẦY ĐỦ 64 hex thường (đã đo: `ps -q` của compose ra
# 64, `docker ps -q` ra 12). Một fixture trả "cid-backend" làm cổng schema của
# marker không thể đòi 64 hex — tức fixture giả đang định nghĩa hợp đồng thay
# cho production. Mỗi service một chữ số hex riêng nên vẫn phân biệt bằng `case`.
_cid_gia() {
    case "$1" in
        backend)       _cc=1 ;;
        celery-worker) _cc=2 ;;
        celery-beat)   _cc=3 ;;
        frontend)      _cc=4 ;;
        *)             _cc=5 ;;
    esac
    _c8=$_cc$_cc$_cc$_cc$_cc$_cc$_cc$_cc
    printf '%s\n' "$_c8$_c8$_c8$_c8$_c8$_c8$_c8$_c8"
}

# --- Mô phỏng ENTRYPOINT của ảnh backend -----------------------------------
# `Backend_FastAPI/Dockerfile` khai ENTRYPOINT ["/app/docker-entrypoint.sh"],
# và `docker compose run` KHÔNG đè ENTRYPOINT — chỉ đè CMD. Nên mỗi one-off
# `run --rm backend <lệnh>` mà không có `--entrypoint` sẽ chạy TRỌN entrypoint
# (alembic + sync + casbin) TRƯỚC khi tới `<lệnh>`.
#
# Bản đầu của stub này bỏ qua đúng chỗ đó, nên harness xanh trong khi đường
# deploy thật chạy migration/sync thêm hai lượt mỗi lần deploy. Mô phỏng ở đây
# để test nói về hành vi thật chứ không về chuỗi ký tự.
case "$_tat_ca" in
    *" run "*)
        case "$_tat_ca" in
            *--entrypoint*)
                : # entrypoint bị đè ⇒ không chạy gì trước lệnh
                ;;
            *)
                if [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" != "false" ]; then
                    echo "entrypoint: alembic upgrade head" >> "$QLTS_STUB_LOG"
                fi
                if [ "${RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP:-true}" != "false" ]; then
                    echo "entrypoint: sync_notification_rules" >> "$QLTS_STUB_LOG"
                fi
                ;;
        esac
        ;;
esac

case "$_tat_ca" in
    *" ps -q "*)
        # Step 3b/8c hỏi ID container theo TỪNG service. Khác hẳn `ps -aq` của
        # vòng chờ health bên dưới — đừng gộp hai giao thức làm một.
        for _sv in backend celery-worker celery-beat frontend; do
            case "$_tat_ca" in
                *" $_sv"*)
                    # Kịch bản "thiếu một container": trả RỖNG đúng như compose
                    # khi service không chạy (và vẫn exit 0 — đó mới là cái bẫy).
                    if [ "${STUB_PS_Q_THIEU:-}" = "$_sv" ]; then exit 0; fi
                    # Biến thể theo GIAI ĐOẠN: chỉ hỏng SAU khi đã build, tức
                    # ở Step 8c. Không có nó thì Step 3b đỏ trước và nhánh lỗi
                    # của 8c không bao giờ được thi hành.
                    if [ "${STUB_PS_Q_THIEU_SAU_BUILD:-}" = "$_sv" ] \
                       && grep -q 'build --parallel' "$QLTS_STUB_LOG"; then exit 0; fi
                    _cid_gia "$_sv"; exit 0 ;;
            esac
        done
        echo "STUB: 'ps -q' cho service KHÔNG nhận diện được: $_tat_ca" >&2
        exit 92
        ;;
    "tag "*)
        # `STUB_TAG_RC` làm hỏng NGAY lệnh tag đầu tiên. Để dựng ca "hỏng GIỮA
        # CHỪNG" (đã tạo 1–3 tag rồi mới gãy) cần đếm lần gọi: dòng log của
        # chính lệnh này đã được ghi ở đầu tệp, nên phép đếm bao gồm nó.
        if [ -n "${STUB_TAG_FAIL_AT:-}" ]; then
            _lan=$(grep -c '^docker tag ' "$QLTS_STUB_LOG")
            if [ "$_lan" = "$STUB_TAG_FAIL_AT" ]; then exit 1; fi
            exit 0
        fi
        exit "${STUB_TAG_RC:-0}"
        ;;
    "image inspect"*)
        # Cổng chống va chạm hỏi "tag này CÓ chưa?". Mặc định là CHƯA (exit 1).
        # Trả 0 ở đây nghĩa là "đã tồn tại" ⇒ deploy phải từ chối ghi đè.
        exit "${STUB_IMAGE_INSPECT_RC:-1}"
        ;;
    *pg_isready*)
        exit "${STUB_PGISREADY_RC:-0}"
        ;;
    *pg_dump*)
        if [ "${STUB_PGDUMP_RC:-0}" != "0" ]; then exit "${STUB_PGDUMP_RC}"; fi
        # Ca "dump rỗng": thoát 0 mà không in gì, đúng như pg_dump chết giữa
        # chừng sau khi `>` đã tạo tệp.
        if [ "${STUB_PGDUMP_EMPTY:-0}" = "1" ]; then exit 0; fi
        printf -- '-- ban sao gia\nSELECT 1;\n'
        exit 0
        ;;
    *preflight_config*)
        # Khớp CẢ ``scripts/preflight_config.py`` lẫn ``-m scripts.preflight_config``:
        # mốc phải bám hành vi, không bám cách viết lệnh. Bản trước chỉ khớp
        # đuôi ``.py`` nên khi lệnh đổi sang module mode, stub im lặng trả 0 và
        # ba ca P2 xanh trong khi cổng không còn được kiểm.
        exit "${STUB_PREFLIGHT_RC:-0}"
        ;;
    *pre_deploy_check.py*)
        exit "${STUB_PREDEPLOY_RC:-0}"
        ;;
    *"alembic upgrade head"*)
        exit "${STUB_ALEMBIC_RC:-0}"
        ;;
    *" ps -aq "*)
        # Cổng health đọc ID container rồi hỏi `docker inspect`, KHÔNG grep một
        # dòng chữ dành cho người đọc.
        #
        # Bản trước của stub này trả "qlts-gia   running   healthy" cho MỌI lệnh
        # chứa " ps ", tức nó bám đúng bản cài đặt CÓ LỖI (`ps <svc> | grep -q
        # healthy`). Hệ quả: vòng chờ luôn thoát ở vòng đầu, nên nhánh quá hạn
        # CHƯA TỪNG được thi hành trong bất kỳ ca nào — guard xanh mà không canh
        # gì. Nay stub mô phỏng đúng giao thức: một ID cho mỗi service.
        case "$_tat_ca" in
            *" backend"*)  _cid_gia backend  ; exit 0 ;;
            *" frontend"*) _cid_gia frontend ; exit 0 ;;
        esac
        echo "STUB: 'ps -aq' cho service KHÔNG nhận diện được: $_tat_ca" >&2
        exit 90
        ;;
    inspect*)
        # Trả theo ĐÚNG trường được hỏi. Định dạng lạ ⇒ FAIL to tiếng, tuyệt đối
        # không im lặng trả rỗng: chuỗi rỗng trôi qua mọi phép so và biến một
        # thay đổi giao thức thành một ca xanh giả.
        case "$_tat_ca" in
            *".Image"*)
                # Image ID của container đang chạy — thứ Step 3b ghim, và thứ
                # Step 8c ghi vào marker. Một service có thể bị "đổi ảnh" qua
                # STUB_IMG_LECH để dựng ca marker lệch.
                for _sv in backend celery-worker celery-beat frontend; do
                    case "$_tat_ca" in
                        *"$(_cid_gia "$_sv")"*)
                            if [ "${STUB_IMG_LECH:-}" = "$_sv" ]; then
                                _z=9999999999999999
                                echo "sha256:$_z$_z$_z$_z"
                            elif [ "${STUB_IMG_RONG:-}" = "$_sv" ]; then
                                echo ""
                            elif [ "${STUB_IMG_RONG_SAU_BUILD:-}" = "$_sv" ] \
                                 && grep -q 'build --parallel' "$QLTS_STUB_LOG"
                            then
                                echo ""
                            else
                                case "$_sv" in
                                    backend)       _k=b ;;
                                    celery-worker) _k=c ;;
                                    celery-beat)   _k=d ;;
                                    frontend)      _k=f ;;
                                esac
                                _r=$_k$_k$_k$_k$_k$_k$_k$_k
                                echo "sha256:$_r$_r$_r$_r$_r$_r$_r$_r"
                            fi
                            exit 0 ;;
                    esac
                done
                echo "STUB: '{{.Image}}' container lạ: $_tat_ca" >&2
                exit 93
                ;;
            *".State.Status"*)
                case "$_tat_ca" in
                    *"$(_cid_gia frontend)"*) echo "${STUB_STATUS_FRONTEND:-running}" ;;
                    *)              echo "${STUB_STATUS_BACKEND:-running}"  ;;
                esac
                exit 0
                ;;
            *".State.Health"*)
                case "$_tat_ca" in
                    *"$(_cid_gia frontend)"*) echo "${STUB_HEALTH_FRONTEND:-healthy}" ;;
                    *)              echo "${STUB_HEALTH_BACKEND:-healthy}"  ;;
                esac
                exit 0
                ;;
            *".State.ExitCode"*)
                echo "${STUB_EXITCODE:-0}"
                exit 0
                ;;
        esac
        echo "STUB: 'docker inspect' với định dạng KHÔNG nhận diện được: $_tat_ca" >&2
        exit 91
        ;;
    *)
        # Các họ lệnh còn lại (up/build/exec/run/…) vốn trả 0 trên đường thuận
        # lợi. Chúng vẫn được GHI vào $QLTS_STUB_LOG ở đầu tệp, nên một lệnh
        # ngoài dự kiến đọc lại được, không biến mất.
        exit 0
        ;;
esac
"""

_STUB_GIT = r"""#!/usr/bin/env bash
case "$1" in
    rev-parse) echo "1111111111111111111111111111111111111111" ;;
    pull)      echo "[git gia] pull" ;;
    log)       : ;;
    *)         : ;;
esac
exit 0
"""

_STUB_NGINX_APPLY = r"""#!/usr/bin/env bash
echo "nginx-apply $*" >> "$QLTS_STUB_LOG"
exit 0
"""

_STUB_ROLLBACK_PREFLIGHT = r"""#!/usr/bin/env bash
# Ghi lại HỢP ĐỒNG chứ không chỉ "đã được gọi": ba biến này là toàn bộ giao
# diện giữa deploy.sh và preflight. Một lượt gọi thiếu `LOCAL_ONLY=1` sẽ đi
# nhánh GHCR và dừng ở cổng đăng nhập — test phải thấy được điều đó.
_L="$QLTS_STUB_LOG"
echo "rollback-preflight tag=${QLTS_ROLLBACK_TAG:-KHONG_DAT}" >> "$_L"
echo "rollback-preflight local_only=${QLTS_ROLLBACK_LOCAL_ONLY:-KHONG_DAT}" >> "$_L"
echo "rollback-preflight manifest=${QLTS_ROLLBACK_MANIFEST:-KHONG_DAT}" >> "$_L"
if [ -f "${QLTS_ROLLBACK_MANIFEST:-/khong-co}" ]; then
    echo "rollback-preflight manifest_ton_tai=1" >> "$QLTS_STUB_LOG"
fi
exit "${STUB_ROLLBACK_PREFLIGHT_RC:-0}"
"""

# Bản đồ image ID phải TRÙNG KHÍT với `docker` giả ở trên. Lệch một ký tự là
# mọi ca marker-khớp biến thành ca marker-lệch mà không ai nhận ra.
_ANH_GIA = {
    "backend": "sha256:" + "b" * 64,
    "celery-worker": "sha256:" + "c" * 64,
    "celery-beat": "sha256:" + "d" * 64,
    "frontend": "sha256:" + "f" * 64,
}
_DICH_VU_RA = ("backend", "celery-worker", "celery-beat", "frontend")
_SHA_CU = "a" * 40          # SHA trong marker = phiên bản ĐANG chạy
_SHA_MOI = "1" * 40         # `git` giả trả cái này cho rev-parse = phiên bản MỚI

_MOC_BUILD = "build --parallel"
_MOC_TAG_ANH = "docker tag"
_MOC_PREFLIGHT_RA = "rollback-preflight tag="

_ENV_PRODUCTION = (
    "DOMAIN=vidu.test\n"
    "POSTGRES_USER=qlts\n"
    "POSTGRES_DB=qlts_production\n"
    "POSTGRES_PASSWORD=matkhau-gia\n"
)

_bo_qua_neu_khong_posix = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="cần bash và PATH kiểu POSIX để chạy thật scripts/deploy.sh",
)


def _cid_gia(sv: str) -> str:
    """CID giả — ID ĐẦY ĐỦ 64 hex thường, đúng hợp đồng production.

    Phải khớp từng byte với hàm `_cid_gia` trong stub `docker`: marker do
    script ghi lấy CID từ stub, còn các ca kiểm ở đây so chuỗi trên tệp.
    """
    ky = {"backend": "1", "celery-worker": "2", "celery-beat": "3",
          "frontend": "4"}.get(sv, "5")
    return ky * 64


def _noi_dung_marker(sha: str = _SHA_CU, anh: dict[str, str] | None = None) -> str:
    """Marker hợp lệ: SHA đang chạy + image ID của bốn container đang chạy."""
    anh = anh if anh is not None else _ANH_GIA
    dong = [
        "# marker-version\t1",
        f"# deployed-sha\t{sha}",
        "# deployed-at\t2026-09-18T00:00:00Z",
    ]
    dong += [f"{s}\t{anh[s]}\t{_cid_gia(s)}" for s in _DICH_VU_RA if s in anh]
    return "\n".join(dong) + "\n"


# --- NGỮ CẢNH production: root + root:root ----------------------------------
# `deploy.sh` đòi uid 0 và `700 root:root` / `600 root:root`. Runner của
# required CI (`runs-on: ubuntu-latest`, KHÔNG khai `container:`) chạy dưới một
# user thường, nên sandbox KHÔNG dựng được trạng thái ấy thật. Đo ngày
# 21-09-2026 trên cùng một cây: chạy non-root cho **83 failed / 354 passed /
# 1 skipped**, chạy root cho **437 passed / 1 skipped**. Nghĩa là "xanh ở máy"
# đã KHÔNG chứng minh gì về PR gate.
#
# Harness này vốn ĐÃ mô phỏng `docker`, `git`, `mktemp`, `mv`, `ln`… bằng stub
# trên PATH. Chủ sở hữu và uid là mảnh còn thiếu của đúng lớp mô phỏng ấy.
#
# ⚠️ Hai shim dưới đây KHÔNG nới cổng của mã production — `deploy.sh` vẫn đòi
# đúng `0` và đúng `root:root`. Chúng dựng NGỮ CẢNH mà cổng ấy được thiết kế để
# chạy trong đó. Và mỗi cổng vẫn có ca riêng lái shim sang giá trị SAI
# (`QLTS_TEST_UID`, `QLTS_TEST_CHU_SO_HUU`) để chứng minh nó còn canh — trước
# bản vá này cổng uid KHÔNG có ca nào, nó chỉ "tình cờ xanh" vì người chạy
# đang là root.
_SHIM_NGU_CANH_STAT = """#!/usr/bin/env bash
# Thay ĐÚNG trường `%U:%G`, và CHỈ cho đường dẫn nằm trong sandbox của test.
# Mọi trường khác (`%a`, `%s`, `%h`, `%d:%i`) vẫn là giá trị THẬT của tệp thật.
_THAT=/usr/bin/stat
if [ "${1:-}" = "-c" ] && [ -n "${2:-}" ]; then
    _dang="$2"
    _dich="${@: -1}"
    case "$_dich" in
        "${QLTS_TEST_SANDBOX:-/khong/bao/gio/khop}"/*)
            _dang=${_dang//%U:%G/${QLTS_TEST_CHU_SO_HUU:-root:root}} ;;
    esac
    shift 2
    exec "$_THAT" -c "$_dang" "$@"
fi
exec "$_THAT" "$@"
"""

_SHIM_STAT = """#!/usr/bin/env bash
# Lớp mỏng. Ca kiểm nào cần can thiệp `stat` thì GHI ĐÈ tệp này, và PHẢI kết
# bằng `exec _ngu_canh_stat "$@"` chứ không phải `/usr/bin/stat` — nếu không,
# chính ca đó tự đánh rơi ngữ cảnh chủ sở hữu rồi đỏ vì một lý do khác hẳn.
exec _ngu_canh_stat "$@"
"""

_SHIM_ID = """#!/usr/bin/env bash
if [ "$#" = "1" ] && [ "${1:-}" = "-u" ]; then
    printf '%s\\n' "${QLTS_TEST_UID:-0}"
    exit 0
fi
exec /usr/bin/id "$@"
"""



def _viet_shim_ngu_canh(goc: Path) -> None:
    """Ghi ba shim ngữ cảnh vào `bin/` — dùng chung cho MỌI bộ test deploy."""
    for ten, than in (
        ("bin/_ngu_canh_stat", _SHIM_NGU_CANH_STAT),
        ("bin/stat", _SHIM_STAT),
        ("bin/id", _SHIM_ID),
    ):
        duong = goc / ten
        duong.write_text(than, encoding="utf-8", newline="\n")
        duong.chmod(0o755)


def _sandbox_cua(goc: Path) -> str:
    """Gốc sandbox mà shim `stat` coi là "trong phạm vi" — CHA của `goc`.

    Lấy cha chứ không lấy chính `goc`: vài ca cố ý đẩy `$OPS` hoặc nạn nhân
    symlink ra NGOÀI cây dự án (`ops_ngoai_pham_vi`, `nan_nhan_*`) và vẫn cần
    ngữ cảnh chủ sở hữu ở đó, nếu không chúng sẽ đỏ vì lý do sai.
    """
    return str(goc.parent)


def _dung_san_khau(
    tmp_path: Path,
    deploy_sh: str | None = None,
    marker: str | None = "MAC_DINH",
    env_them: str = "",
) -> Path:
    """Dựng một cây dự án tối thiểu đủ để `scripts/deploy.sh` chạy tới Step 8.

    ``marker``: ``"MAC_DINH"`` ⇒ marker hợp lệ khớp 4/4 (đường thuận lợi);
    ``None`` ⇒ KHÔNG tạo marker; chuỗi khác ⇒ ghi nguyên văn chuỗi đó.
    """
    goc = tmp_path / "qlts"
    (goc / "scripts").mkdir(parents=True)
    (goc / "nginx" / "templates").mkdir(parents=True)
    (goc / "bin").mkdir()
    _viet_shim_ngu_canh(goc)
    # Hop dong MOI cua deploy.sh: $OPS phai duoc cap quyen TRUOC; script
    # KHONG con "mkdir -p" + "chmod 700" de sua ho. Fixture phai dung dung
    # trang thai production, khong phai trang thai tien cho test.
    (goc / "ops").mkdir(mode=0o700)
    os.chmod(goc / "ops", 0o700)
    if marker is not None:
        than = _noi_dung_marker() if marker == "MAC_DINH" else marker
        _mk = goc / "ops" / "last-deploy.marker"
        _mk.write_text(than, encoding="utf-8", newline="\n")
        # Step 8c tu choi thay mot marker sai quyen; 600 la quyen that.
        os.chmod(_mk, 0o600)

    noi_dung = deploy_sh if deploy_sh is not None else _DEPLOY.read_text(encoding="utf-8")
    (goc / "scripts" / "deploy.sh").write_text(noi_dung, encoding="utf-8", newline="\n")
    for ten, than in (
        ("scripts/nginx-apply.sh", _STUB_NGINX_APPLY),
        ("scripts/rollback-preflight.sh", _STUB_ROLLBACK_PREFLIGHT),
        ("bin/docker", _STUB_DOCKER),
        ("bin/git", _STUB_GIT),
    ):
        duong = goc / ten
        duong.write_text(than, encoding="utf-8", newline="\n")
        duong.chmod(0o755)

    (goc / ".env.production").write_text(
        _ENV_PRODUCTION + env_them, encoding="utf-8", newline="\n"
    )
    (goc / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8", newline="\n")
    (goc / "nginx" / "templates" / "default.conf.template").write_text(
        "server { server_name ${DOMAIN}; }\n", encoding="utf-8", newline="\n"
    )
    return goc


def _chay_deploy(goc: Path, **kich_ban: str) -> tuple[subprocess.CompletedProcess, str]:
    nhat_ky = goc / "lenh.log"
    nhat_ky.write_text("", encoding="utf-8")
    moi_truong = {
        **os.environ,
        "PATH": f"{goc / 'bin'}:{os.environ.get('PATH', '')}",
        "QLTS_STUB_LOG": str(nhat_ky),
        # Mặc định của script là /opt/qlts-ops/rollback — tuyệt đối không để
        # test ghi ra đó. Trỏ vào tmp_path để mỗi ca có ops dir riêng.
        "QLTS_ROLLBACK_OPS_DIR": str(goc / "ops"),
        # Ngữ cảnh production mà shim `stat`/`id` mô phỏng.
        "QLTS_TEST_SANDBOX": _sandbox_cua(goc),
    }
    # Cùng lý do với ba cờ entrypoint bên dưới: hai biến thoát hiểm PHẢI đến từ
    # kịch bản của test. Nếu môi trường người chạy đang đặt chúng thì mọi ca
    # fail-closed sẽ xanh giả vì khối asset bị bỏ qua hoàn toàn.
    # `QLTS_TEST_UID` / `QLTS_TEST_CHU_SO_HUU` cũng vậy: chúng lái shim ngữ
    # cảnh, nên một biến còn sót trong shell người chạy sẽ làm cả hai ca cổng
    # uid và chủ sở hữu xanh giả.
    for co in ("QLTS_SKIP_ROLLBACK_ASSET", "QLTS_SKIP_ROLLBACK_ASSET_REASON",
               "QLTS_TEST_UID", "QLTS_TEST_CHU_SO_HUU"):
        moi_truong.pop(co, None)
    # Ba cờ này quyết định stub có mô phỏng entrypoint hay không, nên chúng
    # PHẢI đến từ kịch bản của test chứ không từ môi trường người chạy. Bỏ sót
    # chỗ này thì `docker compose run ... -e RUN_MIGRATIONS_ON_STARTUP=false`
    # (đúng cách chạy test tại máy) làm ca kiểm ngược đỏ oan, và tệ hơn: nếu
    # ai đó chạy với `=true` thì ca P1 xanh mà chẳng chứng minh gì.
    for co in (_CO_MIGRATION, _CO_SYNC, _CO_CASBIN):
        moi_truong.pop(co, None)
    moi_truong.update(kich_ban)
    ket = subprocess.run(
        ["bash", "scripts/deploy.sh"],
        cwd=str(goc),
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return ket, nhat_ky.read_text(encoding="utf-8")


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban",
    [
        ("postgres không sẵn sàng", {"STUB_PGISREADY_RC": "1"}),
        ("pg_dump hỏng", {"STUB_PGDUMP_RC": "1"}),
        ("bản sao rỗng", {"STUB_PGDUMP_EMPTY": "1"}),
    ],
)
def test_f7_moi_nhanh_sao_luu_hong_deu_dung_truoc_alembic(
    tmp_path: Path, ten_ca: str, kich_ban: dict
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, **kich_ban)

    assert ket.returncode != 0, f"{ten_ca}: deploy phải dừng, nhưng thoát 0"
    assert _MOC_ALEMBIC not in nhat_ky, (
        f"{ten_ca}: đã chạy `{_MOC_ALEMBIC}` dù không có đường lùi.\n"
        f"nhật ký:\n{nhat_ky}"
    )
    assert _MOC_STEP8 not in nhat_ky, f"{ten_ca}: đã tới Step 8"


@_bo_qua_neu_khong_posix
def test_f7_duong_thuan_loi_van_di_toi_alembic(tmp_path: Path) -> None:
    """Guard không được chặn nhầm ca lành — nếu không, nó vô dụng theo cách khác."""
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc)

    assert _MOC_ALEMBIC in nhat_ky, f"đường thuận lợi mà không tới migration:\n{nhat_ky}"
    assert ket.returncode == 0, f"stdout:\n{ket.stdout[-2000:]}\nstderr:\n{ket.stderr[-2000:]}"
    ban_sao = list((goc / "backups").glob("pre_deploy_*.sql"))
    assert ban_sao and ban_sao[0].stat().st_size > 0, "bản sao lưu phải tồn tại và khác rỗng"


@_bo_qua_neu_khong_posix
def test_f8_pre_deploy_check_do_thi_chan_truoc_step8(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_PREDEPLOY_RC="1")

    assert ket.returncode != 0, "pre_deploy_check exit 1 mà deploy vẫn thoát 0"
    assert _MOC_STEP8 not in nhat_ky, (
        "đã mở traffic (Step 8) vào hệ thống mà pre_deploy_check vừa tuyên bố là "
        f"UNUSABLE.\nnhật ký:\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix
def test_f8_pre_deploy_check_chi_canh_bao_thi_van_di_tiep(tmp_path: Path) -> None:
    """`pre_deploy_check.py` exit 0 khi chỉ thiếu WARNING_POLICIES — không được chặn."""
    goc = _dung_san_khau(tmp_path)
    _, nhat_ky = _chay_deploy(goc, STUB_PREDEPLOY_RC="0")
    assert _MOC_STEP8 in nhat_ky, f"cảnh báo suông mà đã chặn deploy:\n{nhat_ky}"


# =============================================================================
# P1 — one-off KHÔNG được kéo theo ENTRYPOINT
# =============================================================================
# `docker compose run --rm backend <lệnh>` chỉ đè CMD. ENTRYPOINT của ảnh
# (`/app/docker-entrypoint.sh`) vẫn chạy trọn vẹn trước `<lệnh>`, nên mỗi
# one-off là thêm một lượt `alembic upgrade head` + `sync_notification_rules`
# mà không ai gọi. Nặng nhất là ở cold cutover: Step 7 xảy ra TRƯỚC khi Step 8
# export ba cờ = false, nên nó tự migrate/sync đúng lúc quy trình đang hứa với
# người trực rằng mọi thứ do họ chạy tay.
def _truoc_step8(nhat_ky: str) -> str:
    """Phần nhật ký TRƯỚC khi Step 8 bắt đầu dựng container ứng dụng."""
    vi_tri = nhat_ky.find(_MOC_STEP8)
    return nhat_ky if vi_tri < 0 else nhat_ky[:vi_tri]


@_bo_qua_neu_khong_posix
def test_p1_one_off_khong_keo_theo_entrypoint(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    _, nhat_ky = _chay_deploy(goc)

    assert _MOC_EP_ALEMBIC not in nhat_ky, (
        "một one-off đã chạy TRỌN entrypoint (alembic) trước lệnh của nó — "
        f"thiếu `--entrypoint`.\nnhật ký:\n{nhat_ky}"
    )
    assert _MOC_EP_SYNC not in nhat_ky, (
        f"một one-off đã chạy sync qua entrypoint — thiếu `--entrypoint`.\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix
def test_p1_routine_dung_mot_alembic_va_mot_preflight(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    _, nhat_ky = _chay_deploy(goc)

    # Chỉ đếm lệnh TƯỜNG MINH (dòng bắt đầu bằng "docker "), để không lẫn với
    # dòng "entrypoint: ..." mà stub ghi khi một one-off kéo theo entrypoint.
    so_alembic = sum(
        1
        for dong in nhat_ky.splitlines()
        if dong.startswith("docker ") and _MOC_ALEMBIC in dong
    )
    so_preflight = nhat_ky.count("pre_deploy_check.py")
    so_sync = nhat_ky.count("sync_notification_rules")

    assert so_alembic == 1, f"routine chạy {so_alembic} lượt alembic, phải đúng 1"
    assert so_preflight == 1, f"routine chạy {so_preflight} lượt preflight, phải đúng 1"
    assert so_sync == 0, (
        f"routine chạy {so_sync} lượt sync từ one-off — sync là việc của "
        "container backend ở Step 8, đúng MỘT lần"
    )


@_bo_qua_neu_khong_posix
def test_p1_cold_cutover_khong_tu_migrate_hay_sync_truoc_step8(tmp_path: Path) -> None:
    """Cold cutover hứa: operator chạy tay. Không lệnh nào được đi trước họ."""
    goc = _dung_san_khau(tmp_path)
    _, nhat_ky = _chay_deploy(goc, COLD_CUTOVER="true")
    som = _truoc_step8(nhat_ky)

    for moc in (_MOC_ALEMBIC, _MOC_EP_ALEMBIC, _MOC_EP_SYNC, "sync_notification_rules"):
        assert moc not in som, (
            f"cold cutover đã chạy {moc!r} trước Step 8 — phá đúng ngữ nghĩa "
            f"'operator chạy tay'.\nnhật ký (phần sớm):\n{som}"
        )


@pytest.mark.parametrize("co", ["--entrypoint", "--no-deps"])
def test_p1_moi_one_off_deu_khai_co(co: str) -> None:
    """Quét tĩnh: MỌI `compose run --rm` trong deploy.sh phải mang cả hai cờ.

    Canh theo mẫu chứ không theo số lượng, để lệnh one-off thứ ba thêm sau này
    cũng bị bắt.
    """
    ma = _DEPLOY.read_text(encoding="utf-8")
    # Nối các dòng bị gấp bằng `\` để mỗi lệnh nằm trên một dòng logic.
    lien = ma.replace("\\\n", " ")
    thieu = [
        dong.strip()
        for dong in lien.splitlines()
        if "run --rm" in dong and co not in dong
    ]
    assert thieu == [], f"lệnh one-off thiếu `{co}`: {thieu}"


# --- Kiểm ngược: gỡ guard ra thì nhánh hỏng phải đi lọt trở lại --------------
# Ba guard của Step 5 CHE NHAU, nên gỡ một cái chưa chắc làm nhánh hỏng đi lọt
# — bản đầu của ca kiểm ngược này đã đỏ đúng vì lẽ đó: gỡ `pg_dump THẤT BẠI`
# thì `rm -f` vẫn chạy, và guard "bản sao rỗng" bắt tiếp. Nên mỗi guard phải
# được gỡ CÙNG những guard nằm sau nó trên đúng đường đi của kịch bản ấy; đó
# mới là "hình dạng mã trước bản vá" cho riêng nhánh đang xét.
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_guard,can_go,kich_ban",
    [
        (
            "PostgreSQL không sẵn sàng",
            ["PostgreSQL không sẵn sàng"],
            {"STUB_PGISREADY_RC": "1"},
        ),
        (
            "bản sao rỗng",
            ["Bản sao lưu RỖNG"],
            {"STUB_PGDUMP_EMPTY": "1"},
        ),
        (
            "pg_dump hỏng (che bởi guard rỗng ⇒ phải gỡ cả hai)",
            ["pg_dump THẤT BẠI", "Bản sao lưu RỖNG"],
            {"STUB_PGDUMP_RC": "1"},
        ),
    ],
)
def test_kiem_nguoc_go_guard_sao_luu_thi_alembic_chay_lai(
    tmp_path: Path, ten_guard: str, can_go: list[str], kich_ban: dict
) -> None:
    """Gỡ guard ra thì migration PHẢI chạy lại — nếu không, ca F7 xanh vì lý do khác."""
    goc_ban = _DEPLOY.read_text(encoding="utf-8")
    dot_bien = goc_ban
    for neo in can_go:
        truoc = dot_bien
        dot_bien = dot_bien.replace(f'error "{neo}', f'warn "{neo}')
        assert dot_bien != truoc, f"không tìm thấy guard {neo!r} — test này đã lỗi thời"

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nhat_ky = _chay_deploy(goc, **kich_ban)

    assert _MOC_ALEMBIC in nhat_ky, (
        f"gỡ guard {ten_guard!r} mà migration VẪN không chạy ⇒ ca F7 tương ứng "
        f"xanh vì lý do khác, không phải nhờ guard.\nnhật ký:\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_buoc,truoc,sau",
    [
        (
            "Step 6 alembic",
            "--no-deps --entrypoint alembic backend upgrade head",
            "--no-deps backend alembic upgrade head",
        ),
        (
            "Step 7 preflight",
            "--no-deps --entrypoint python backend scripts/pre_deploy_check.py",
            "--no-deps backend python scripts/pre_deploy_check.py",
        ),
    ],
)
def test_kiem_nguoc_bo_entrypoint_thi_one_off_keo_theo_entrypoint(
    tmp_path: Path, ten_buoc: str, truoc: str, sau: str
) -> None:
    """Bỏ `--entrypoint` ở một bước ⇒ entrypoint chạy lại — đúng hình dạng mã cũ."""
    goc_ban = _DEPLOY.read_text(encoding="utf-8")
    assert truoc in goc_ban, f"không tìm thấy lệnh {ten_buoc} — test này đã lỗi thời"
    dot_bien = goc_ban.replace(truoc, sau, 1)

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nhat_ky = _chay_deploy(goc)

    assert _MOC_EP_ALEMBIC in nhat_ky, (
        f"bỏ `--entrypoint` ở {ten_buoc} mà entrypoint VẪN không chạy ⇒ ca P1 "
        f"xanh vì lý do khác.\nnhật ký:\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_cold_cutover_bo_entrypoint_thi_tu_migrate_truoc_step8(
    tmp_path: Path,
) -> None:
    """Ca đắt nhất: cold cutover mất override là tự migrate/sync trước Step 8."""
    goc_ban = _DEPLOY.read_text(encoding="utf-8")
    dot_bien = goc_ban.replace(
        "--no-deps --entrypoint python backend scripts/pre_deploy_check.py",
        "--no-deps backend python scripts/pre_deploy_check.py",
        1,
    )
    assert dot_bien != goc_ban, "không tìm thấy lệnh preflight — test này đã lỗi thời"

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nhat_ky = _chay_deploy(goc, COLD_CUTOVER="true")
    som = _truoc_step8(nhat_ky)

    assert _MOC_EP_SYNC in som, (
        "bỏ `--entrypoint` ở Step 7 mà cold cutover VẪN không tự sync trước "
        f"Step 8 ⇒ ca P1 cold-cutover xanh vì lý do khác.\n{som}"
    )


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_khoi_phuc_or_warn_thi_step8_chay_lai(tmp_path: Path) -> None:
    """Khôi phục `|| warn` — đúng hình dạng mã TRƯỚC bản vá F8."""
    goc_ban = _DEPLOY.read_text(encoding="utf-8")
    neo = "    run --rm --no-deps --entrypoint python backend scripts/pre_deploy_check.py\n"
    assert neo in goc_ban, "không tìm thấy lệnh pre_deploy_check — test này đã lỗi thời"
    dot_bien = goc_ban.replace(
        neo,
        "    run --rm --no-deps --entrypoint python backend scripts/pre_deploy_check.py \\\n"
        '        || warn "Pre-deploy checks had warnings (non-fatal)"\n',
        1,
    )

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nhat_ky = _chay_deploy(goc, STUB_PREDEPLOY_RC="1")

    assert _MOC_STEP8 in nhat_ky, (
        "khôi phục `|| warn` mà Step 8 VẪN không chạy ⇒ ca F8 ở trên xanh vì lý "
        "do khác, không phải nhờ việc bỏ nhánh nuốt mã thoát"
    )


# =============================================================================
# P2 — Cấu hình hỏng phải dừng TRƯỚC pg_dump, không được vào nhánh restore
# =============================================================================
# Trước bản vá 24-08-2026, thứ tự là: build → pg_dump → alembic → pre_deploy_check.
# ``alembic upgrade head`` import ``app.config``, nên một biến môi trường thiếu
# làm ``Settings()`` raise BÊN TRONG Step 6, nơi mọi mã thoát khác 0 bị phân
# loại là "Migration failed" và kích hoạt replay bản sao lên CSDL production —
# cho một CSDL chưa hề thay đổi.
#
# Bốn ca dưới đây khoá đúng chuỗi nhân quả ấy bằng cách CHẠY THẬT `deploy.sh`
# với `docker` giả, rồi đọc nhật ký lệnh. Ca cuối là kiểm ngược: đưa preflight
# xuống SAU backup trên một bản sao và chứng minh nhánh hỏng lại đi lọt — không
# có nó thì "vẫn xanh" chẳng chứng minh được gì.


@_bo_qua_neu_khong_posix
def test_p2_cau_hinh_hong_dung_truoc_pg_dump(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_PREFLIGHT_RC="1")

    assert ket.returncode != 0, "cấu hình hỏng mà deploy vẫn thoát 0"
    assert _MOC_PREFLIGHT in nhat_ky, f"preflight không hề chạy:\n{nhat_ky}"
    assert _MOC_PGDUMP not in nhat_ky, (
        "đã chạy pg_dump dù cấu hình hỏng — bản sao thừa, và bước kế tiếp sẽ "
        f"phân loại lỗi cấu hình thành migration failure.\nnhật ký:\n{nhat_ky}"
    )
    assert _MOC_ALEMBIC not in nhat_ky, f"đã chạy migration:\n{nhat_ky}"
    assert _MOC_STEP8 not in nhat_ky, f"đã tới Step 8:\n{nhat_ky}"
    # Không có bản sao nào được tạo ⇒ không có gì để nhánh restore chạm vào.
    assert not list((goc / "backups").glob("pre_deploy_*.sql")), (
        "cấu hình hỏng mà vẫn tạo bản sao lưu"
    )


@_bo_qua_neu_khong_posix
def test_p2_preflight_chay_sau_build_va_truoc_pg_dump(tmp_path: Path) -> None:
    """Thứ tự, không chỉ sự tồn tại.

    Một preflight đặt sai chỗ vẫn "có chạy" mà không bảo vệ gì: sau ``pg_dump``
    thì bản sao thừa đã được tạo, sau ``alembic`` thì đã quá muộn hoàn toàn.
    """
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc)
    assert ket.returncode == 0, f"stdout:\n{ket.stdout[-2000:]}"

    dong = nhat_ky.splitlines()
    vt_build = next(
        i
        for i, d in enumerate(dong)
        if " build " in d or d.endswith(" build --parallel")
    )
    vt_preflight = next(i for i, d in enumerate(dong) if _MOC_PREFLIGHT in d)
    vt_pgdump = next(i for i, d in enumerate(dong) if _MOC_PGDUMP in d)

    assert vt_build < vt_preflight < vt_pgdump, (
        f"thứ tự sai: build={vt_build} preflight={vt_preflight} pg_dump={vt_pgdump}.\n"
        f"nhật ký:\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix
def test_p2_preflight_khong_keo_theo_entrypoint(tmp_path: Path) -> None:
    """Thiếu ``--entrypoint`` thì chính preflight chạy migration nó sinh ra để ngăn."""
    goc = _dung_san_khau(tmp_path)
    _, nhat_ky = _chay_deploy(goc)

    truoc_pgdump = nhat_ky.split(_MOC_PGDUMP)[0]
    assert "entrypoint: alembic upgrade head" not in truoc_pgdump, (
        "preflight kéo theo entrypoint ⇒ đã migrate TRƯỚC cả khi có bản sao.\n"
        f"nhật ký trước pg_dump:\n{truoc_pgdump}"
    )
    assert "entrypoint: sync_notification_rules" not in truoc_pgdump


@_bo_qua_neu_khong_posix
def test_p2_kiem_nguoc_dat_preflight_sau_backup_thi_bi_bat(tmp_path: Path) -> None:
    """Gỡ đúng thứ đang được canh: chuyển preflight xuống SAU Step 5.

    Bản đột biến vẫn "có preflight", vẫn dừng deploy — nhưng đã kịp tạo bản sao
    lưu. Nếu ca P2 đầu tiên không đỏ ở đây thì nó chỉ đang canh sự tồn tại của
    một dòng lệnh, không canh thứ tự.
    """
    goc_that = _DEPLOY.read_text(encoding="utf-8")
    moc_dau = 'log "Step 4b/8: Config preflight (candidate image)..."'
    moc_cuoi = 'log "Config preflight passed — CSDL chưa bị chạm"'
    assert moc_dau in goc_that and moc_cuoi in goc_that, "neo đột biến không còn khớp"

    i = goc_that.index(moc_dau)
    j = goc_that.index(moc_cuoi) + len(moc_cuoi) + 1
    khoi = goc_that[i:j]
    con_lai = goc_that[:i] + goc_that[j:]

    neo_sau_backup = 'log "Database backup saved: pre_deploy_${TIMESTAMP}.sql"\n'
    assert neo_sau_backup in con_lai
    dot_bien = con_lai.replace(neo_sau_backup, neo_sau_backup + khoi, 1)

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, nhat_ky = _chay_deploy(goc, STUB_PREFLIGHT_RC="1")

    assert ket.returncode != 0, "đột biến phải vẫn dừng deploy"
    assert _MOC_PGDUMP in nhat_ky, (
        "đột biến đáng lẽ chạy pg_dump TRƯỚC preflight — nếu không, phép đột "
        f"biến này không mô phỏng đúng lỗi cũ.\nnhật ký:\n{nhat_ky}"
    )
    assert list((goc / "backups").glob("pre_deploy_*.sql")), (
        "đột biến đáng lẽ để lại bản sao thừa"
    )


# =============================================================================
# P3 — Đường deploy không được in credential ra log
# =============================================================================


_BIEN_BI_MAT = {
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND_URL",
    "SECRET_KEY",
    "JWT_SECRET_KEY",
}


def _cac_lat_cat_bi_mat(nguon: str) -> list[str]:
    """Tìm mọi phép CẮT trên một biến bí mật, đọc bằng AST.

    Cố ý KHÔNG khớp chuỗi trên nội dung tệp: chú thích giải thích lỗi cũ có
    nhắc tới ``url[:30]``, nên một phép kiểm chuỗi sẽ đỏ vì đúng dòng văn mô tả
    bản vá — canh chữ chứ không canh mã.
    """
    cay = ast.parse(nguon)
    thay = []
    for nut in ast.walk(cay):
        if not isinstance(nut, ast.Subscript) or not isinstance(nut.slice, ast.Slice):
            continue
        goc = nut.value
        ten = goc.attr if isinstance(goc, ast.Attribute) else getattr(goc, "id", None)
        if ten in _BIEN_BI_MAT:
            thay.append(f"{ten}[...] tại dòng {nut.lineno}")
    return thay


def test_p3_config_khong_cat_gia_tri_bi_mat_vao_log() -> None:
    """``DATABASE_URL[:30]`` cắt đúng vào 5 ký tự đầu của MẬT KHẨU.

    ``postgresql+asyncpg://qlts:`` dài 25 ký tự. Log deploy nhiều người đọc và
    giữ rất lâu — lâu hơn chính cái mật khẩu.
    """
    nguon = (_tim_goc() / "Backend_FastAPI" / "app" / "config.py").read_text(
        encoding="utf-8"
    )
    lat = _cac_lat_cat_bi_mat(nguon)
    assert not lat, f"config.py còn cắt giá trị bí mật: {lat}"


def test_p3_kiem_nguoc_phep_do_bat_duoc_mot_lat_cat() -> None:
    """Chứng minh phép đo trên biết đỏ — nếu không, "sạch" chẳng nói lên gì."""
    assert _cac_lat_cat_bi_mat(
        "print(f'{settings.DATABASE_URL[:30]}')"
    ), "AST không bắt được lát cắt hiển nhiên"
    assert not _cac_lat_cat_bi_mat("# settings.DATABASE_URL[:30] trong chú thích")


@pytest.mark.parametrize(
    "van_ban,cam",
    [
        ("postgresql+asyncpg://qlts:SieuMatKhau@db:5432/x", "SieuMatKhau"),
        ("redis://user:p@ssw0rd@h:6379/1", "ssw0rd"),
        ("rediss://u:token-bi-mat@h:6380/2", "token-bi-mat"),
    ],
)
def test_p3_che_userinfo_khong_de_lot_mat_khau(van_ban: str, cam: str) -> None:
    from app.utils.redact import che_userinfo

    ra = che_userinfo(van_ban)
    assert cam not in ra, f"mật khẩu lọt qua bộ che: {ra!r}"
    assert "***:***@" in ra


def test_p3_che_userinfo_khong_pha_url_khong_co_credential() -> None:
    """Che quá tay làm thông báo vô dụng, và người vận hành sẽ đi tìm giá trị
    thật ở chỗ khác."""
    from app.utils.redact import che_userinfo

    assert che_userinfo("redis://h:6379/1") == "redis://h:6379/1"
    ra = che_userinfo("loi o redis://u:pw@h va mail a@b.com")
    assert "a@b.com" in ra, f"đã nuốt nhầm địa chỉ email: {ra!r}"
    assert "pw" not in ra


def test_p3_module_che_khong_co_side_effect() -> None:
    """``app.utils.redact`` phải import được KHÔNG kéo theo ``Settings``.

    Đây là điều kiện để nó dùng được ở đúng ca cần nhất: khi ``Settings()`` vừa
    raise và ``app.config`` không import nổi. Nếu hàm che nằm trong config.py
    thì ca hỏng ấy vừa mất cấu hình vừa mất cách in lỗi an toàn.

    Đọc bằng AST, không khớp chuỗi: docstring của redact.py CÓ nhắc chữ
    "Settings" để giải thích chính lý do này.
    """
    cay = ast.parse(
        (_tim_goc() / "Backend_FastAPI" / "app" / "utils" / "redact.py").read_text(
            encoding="utf-8"
        )
    )
    nhap = []
    for nut in ast.walk(cay):
        if isinstance(nut, ast.Import):
            nhap += [a.name for a in nut.names]
        elif isinstance(nut, ast.ImportFrom):
            nhap.append("." * (nut.level or 0) + (nut.module or ""))
    # ``__future__`` là chỉ thị biên dịch, không kéo theo gì lúc chạy.
    that_su = [x for x in nhap if x != "__future__"]
    assert that_su == ["re"], (
        f"redact.py chỉ được import `re` (ngoài __future__), đang import: {nhap}"
    )


def test_p3_preflight_dung_module_che_khong_side_effect() -> None:
    nguon = (
        _tim_goc() / "Backend_FastAPI" / "scripts" / "preflight_config.py"
    ).read_text(encoding="utf-8")
    # Đọc bằng AST. Ba lần liên tiếp trong chính tệp này, một phép kiểm bằng
    # ``in`` đã đỏ vì trúng đoạn docstring GIẢI THÍCH điều nó đang cấm — canh
    # chữ chứ không canh mã, đúng thứ docstring đầu tệp cảnh báo.
    cay = ast.parse(nguon)

    nhap = {
        a.name
        for nut in ast.walk(cay)
        if isinstance(nut, ast.ImportFrom) and (nut.module or "").endswith("redact")
        for a in nut.names
    }
    assert "mo_ta_loi_an_toan" in nhap, f"preflight không dùng bộ mô tả an toàn: {nhap}"

    goi_str_exc = [
        nut.lineno
        for nut in ast.walk(cay)
        if isinstance(nut, ast.Call)
        and isinstance(nut.func, ast.Name)
        and nut.func.id == "str"
        and any(isinstance(t, ast.Name) and t.id == "exc" for t in nut.args)
    ]
    assert not goi_str_exc, (
        "preflight in message thô của exception tại dòng "
        f"{goi_str_exc} — pydantic nhúng input_value=<giá trị> vào đó"
    )


# =============================================================================
# P4 — Preflight phải CHẠY ĐƯỢC, và không rò giá trị cấu hình
# =============================================================================
# Ba ca P2 ở trên chạy `deploy.sh` với `docker` GIẢ; stub chỉ nhìn thấy tên
# `preflight_config.py` rồi trả mã thoát theo kịch bản — nó KHÔNG chạy script.
# Vì vậy chúng xanh kể cả khi script chết ngay ở dòng import.
#
# Đó không phải giả định: bản đầu của Step 4b gọi
# ``python scripts/preflight_config.py``. Chạy theo đường tệp thì
# ``sys.path[0]`` là ``/app/scripts`` chứ không phải ``/app``, nên ``import
# app`` chết bằng ModuleNotFoundError TRƯỚC mọi phép kiểm — mọi deploy dừng ở
# Step 4b kể cả khi cấu hình hoàn toàn đúng. Toàn bộ P2 vẫn xanh.
#
# Bốn ca dưới đây chạy THẬT script bằng subprocess, đúng cách production gọi.

_CANARY = "canary-cau-hinh-khong-duoc-log"


def _chay_preflight(*lenh: str, them_env: dict | None = None):
    """Chạy preflight bằng chính interpreter đang chạy test, cwd = Backend_FastAPI.

    Lấy thư mục từ vị trí CHÍNH TỆP TEST chứ không từ ``_tim_goc()``: production
    chạy với ``WORKDIR /app``, và dưới lệnh chạy test tại máy thì cây repo có
    thể được mount ở chỗ khác (thậm chí chỉ-đọc) — khi ấy ``import app.config``
    chết vì ``os.makedirs`` thư mục upload chứ không vì cấu hình, và ca kiểm đỏ
    vì lý do môi trường.
    """
    thu_muc = Path(__file__).resolve().parents[2]
    moi_truong = {**os.environ, **(them_env or {})}
    # Bỏ PYTHONPATH của môi trường test: nếu nó tình cờ chứa thư mục app thì ca
    # kiểm ngược (đường tệp phải hỏng) sẽ xanh oan.
    moi_truong.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, *lenh],
        cwd=str(thu_muc),
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_p4_preflight_chay_duoc_voi_cau_hinh_hop_le() -> None:
    ket = _chay_preflight("-m", "scripts.preflight_config")
    assert ket.returncode == 0, (
        "preflight chặn một cấu hình HỢP LỆ ⇒ mọi deploy dừng ở Step 4b.\n"
        f"stdout:\n{ket.stdout[-1500:]}\nstderr:\n{ket.stderr[-1500:]}"
    )
    assert "ĐẠT" in ket.stdout


def test_p4_kiem_nguoc_goi_theo_duong_tep_thi_hong() -> None:
    """Chứng minh ``-m`` là bắt buộc, không phải sở thích viết lệnh.

    Nếu ca này xanh (đường tệp cũng chạy được) thì phép khoá cách gọi ở dưới
    chỉ đang canh một chuỗi ký tự.
    """
    ket = _chay_preflight("scripts/preflight_config.py")
    assert ket.returncode != 0, (
        "đường tệp lại chạy được ⇒ ca khoá cách gọi mất ý nghĩa nhân quả"
    )
    assert "ModuleNotFoundError" in ket.stderr, ket.stderr[-800:]


def test_p4_deploy_goi_preflight_bang_module_mode() -> None:
    noi_dung = _DEPLOY.read_text(encoding="utf-8")
    assert "-m scripts.preflight_config" in noi_dung, (
        "deploy.sh không gọi preflight ở module mode"
    )
    assert "python backend scripts/preflight_config.py" not in noi_dung


def test_p4_loi_cau_hinh_khong_ro_gia_tri_ra_log() -> None:
    """Canary đặt vào một biến SAI KIỂU: pydantic nhúng ``input_value=`` vào
    ``str(exc)``. Đo trên đúng runtime của image: rò nguyên văn.

    Ca này chạy thật rồi soi CẢ stdout LẪN stderr — nhánh lỗi in ở cả hai chỗ
    (``config.py`` in ra stdout, preflight in ra stderr).
    """
    ket = _chay_preflight(
        "-m",
        "scripts.preflight_config",
        them_env={"ACCESS_TOKEN_EXPIRE_MINUTES": _CANARY},
    )
    assert ket.returncode != 0, "cấu hình sai kiểu mà preflight vẫn ĐẠT"

    ca_hai = ket.stdout + ket.stderr
    assert _CANARY not in ca_hai, (
        "giá trị cấu hình lọt vào log deploy — với một biến bí mật thì đây là "
        f"secret nằm thẳng trong log CI/CD.\n{ca_hai[-1500:]}"
    )
    # Vẫn phải đủ dùng: nêu tên biến và loại lỗi.
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in ca_hai
    assert "ValidationError" in ca_hai


# =============================================================================
# P5 — Không tệp nào trong app/ + scripts/ được cắt giá trị bí mật vào log
# =============================================================================
# Mở rộng từ một tệp ra toàn bộ mã chạy trong ảnh production. Đường rò đầu tiên
# tìm được là ``config.py`` (``DATABASE_URL[:30]``), nhưng
# ``scripts/rebuild_database.py`` in ``DATABASE_URL[:60]`` — đủ để lộ TRỌN mật
# khẩu, host và một phần tên CSDL, trong một tệp có khả năng phá huỷ dữ liệu.
# Loại trừ ``tests/`` vì test có quyền dựng chuỗi giả để kiểm chính bộ che.

_BIEN_BI_MAT_TOAN_CUC = _BIEN_BI_MAT | {
    "MFA_ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "DEVICE_FINGERPRINT_SALT",
    "MAIL_PASSWORD",
}


def test_p5_khong_tep_nao_cat_gia_tri_bi_mat() -> None:
    thu_muc_goc = _tim_goc() / "Backend_FastAPI"
    thay: list[str] = []
    for goc in ("app", "scripts"):
        for duong in (thu_muc_goc / goc).rglob("*.py"):
            cay = ast.parse(duong.read_text(encoding="utf-8"))
            for nut in ast.walk(cay):
                if not isinstance(nut, ast.Subscript) or not isinstance(
                    nut.slice, ast.Slice
                ):
                    continue
                muc = nut.value
                ten = (
                    muc.attr
                    if isinstance(muc, ast.Attribute)
                    else getattr(muc, "id", None)
                )
                if ten in _BIEN_BI_MAT_TOAN_CUC:
                    thay.append(f"{duong.relative_to(thu_muc_goc)}:{nut.lineno} {ten}")
    assert not thay, f"còn cắt giá trị bí mật vào log: {thay}"


# =============================================================================
# P6 — mo_ta_loi_an_toan không được tin `msg` của pydantic
# =============================================================================
# Bản trước xuất ``loc``/``msg``/``type`` và tuyên bố là an toàn vì đã bỏ
# ``input``. Sai: với validator TỰ VIẾT, ``msg`` chính là text của
# ``ValueError`` mà tác giả raise, nên nó mang được bất cứ thứ gì —
# ``raise ValueError(f"gia tri bi mat la {value}")``. Đo được: canary nằm
# nguyên văn trong ``msg`` NGAY CẢ khi đã gọi ``errors(include_input=False,
# include_context=False, include_url=False)``.
#
# Ca canary cũ (P4) dùng lỗi ``int_parsing`` có sẵn — message của nó TÌNH CỜ
# không chứa giá trị, nên nó không canh được biến thể này. Đó là một guard canh
# hụt vì ca kiểm quá dễ.

_CANARY_MSG = "canary-trong-msg-khong-duoc-log"


def test_p6_validator_tu_viet_nhet_gia_tri_vao_msg_khong_lot() -> None:
    from pydantic import BaseModel, field_validator

    from app.utils.redact import mo_ta_loi_an_toan

    class _Mau(BaseModel):
        secret: str = ""

        @field_validator("secret")
        @classmethod
        def _tu_choi(cls, x):
            raise ValueError(f"gia tri bi mat la {x}")

    with pytest.raises(Exception) as thong_tin:
        _Mau(secret=_CANARY_MSG)

    ra = mo_ta_loi_an_toan(thong_tin.value)
    assert _CANARY_MSG not in ra, f"msg của validator tự viết lọt vào log: {ra}"
    # Vẫn phải đủ để sửa: nêu tên field và mã lỗi.
    assert "secret" in ra and "value_error" in ra


def test_p6_khoa_do_nguoi_dung_dat_trong_loc_bi_thay_bang_dau_hoi() -> None:
    """``loc`` có thể chứa KHOÁ của một dict — chính khoá ấy là dữ liệu."""
    from typing import Dict

    from pydantic import BaseModel

    from app.utils.redact import mo_ta_loi_an_toan

    class _Mau(BaseModel):
        m: Dict[str, int] = {}

    with pytest.raises(Exception) as thong_tin:
        _Mau(m={_CANARY_MSG: "khong-phai-so"})

    ra = mo_ta_loi_an_toan(thong_tin.value)
    assert _CANARY_MSG not in ra, f"khoá người dùng lọt vào log: {ra}"
    assert "?" in ra


class _LoiGiaKhongNhanCo(Exception):
    """``errors()`` kiểu cũ: không nhận cờ loại trừ."""

    def __init__(self):
        super().__init__("khong dung message nay")
        self.so_lan_goi_tran = 0

    def errors(self, **kwargs):
        if kwargs:
            raise TypeError("errors() got an unexpected keyword argument")
        self.so_lan_goi_tran += 1
        return [{"type": "value_error", "loc": ("x",), "msg": _CANARY_MSG}]


def test_p6_errors_khong_nhan_co_thi_ve_ten_lop_va_khong_goi_lai() -> None:
    """Không được "thử lại không tham số" — bản trần chính là bản MANG giá trị."""
    from app.utils.redact import mo_ta_loi_an_toan

    loi = _LoiGiaKhongNhanCo()
    ra = mo_ta_loi_an_toan(loi)

    assert _CANARY_MSG not in ra, ra
    assert loi.so_lan_goi_tran == 0, (
        "đã gọi lại errors() không tham số — đó đúng là bản mang giá trị"
    )
    assert "_LoiGiaKhongNhanCo" in ra


class _LoiGiaCauTrucLa(Exception):
    def errors(self, **kwargs):
        return ["khong phai dict", 123]


def test_p6_cau_truc_la_thi_ve_ten_lop() -> None:
    from app.utils.redact import mo_ta_loi_an_toan

    ra = mo_ta_loi_an_toan(_LoiGiaCauTrucLa())
    assert "_LoiGiaCauTrucLa" in ra
    assert "khong phai dict" not in ra


def test_p6_loi_cau_hinh_van_duoc_in_message() -> None:
    """``LoiCauHinh`` là lời cam kết theo KIỂU rằng message chỉ nêu tên biến.

    Nếu ca này đỏ thì mọi thông báo cấu hình thành "chỉ tên lớp", và người vận
    hành mất hẳn manh mối — che quá tay cũng là một kiểu hỏng.
    """
    from app.utils.redact import LoiCauHinh, mo_ta_loi_an_toan

    ra = mo_ta_loi_an_toan(LoiCauHinh("CRITICAL: MFA_ENCRYPTION_KEY must be set"))
    assert "MFA_ENCRYPTION_KEY" in ra


def test_p6_mo_ta_khong_lay_msg_tu_pydantic() -> None:
    """Cổng cấu trúc: bộ mô tả không được đọc khoá ``msg``.

    Đọc bằng AST — một phép kiểm bằng ``in`` sẽ trúng chính đoạn docstring giải
    thích vì sao KHÔNG dùng ``msg``.
    """
    nguon = (
        _tim_goc() / "Backend_FastAPI" / "app" / "utils" / "redact.py"
    ).read_text(encoding="utf-8")
    cay = ast.parse(nguon)
    ham = next(
        n
        for n in ast.walk(cay)
        if isinstance(n, ast.FunctionDef) and n.name == "mo_ta_loi_an_toan"
    )
    doc_msg = [
        n.lineno
        for n in ast.walk(ham)
        if isinstance(n, ast.Constant) and n.value == "msg"
    ]
    assert not doc_msg, f"mo_ta_loi_an_toan còn đọc 'msg' tại dòng {doc_msg}"


# =============================================================================
# Step 3b — tài sản rollback: mọi nhánh hỏng đều phải DỪNG TRƯỚC build
# =============================================================================
# Bất biến của cả nhóm: khi tài sản rollback KHÔNG tạo được, `docker compose
# build` không được chạy. Build là biên đầu tiên tốn kém và là biên cuối cùng
# còn rẻ để quay đầu — sau nó là pg_dump, alembic, rồi thay container.
#
# Mỗi ca dưới đây vi phạm ĐÚNG MỘT bất biến, để khi đỏ thì biết đỏ vì gì.

_MARKER_THIEU_SHA = (
    "# marker-version\t1\n"
    "backend\t" + _ANH_GIA["backend"] + "\t" + _cid_gia("backend") + "\n"
)


def _manifest_da_xuat_ban(goc: Path) -> list[Path]:
    return sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))


@_bo_qua_neu_khong_posix
def test_ra_duong_thuan_loi_tao_du_bon_tag_va_goi_preflight(tmp_path: Path) -> None:
    """Guard không được chặn nhầm ca lành — nếu không, nó vô dụng theo cách khác."""
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode == 0, (
        f"stdout:\n{ket.stdout[-3000:]}\nstderr:\n{ket.stderr[-3000:]}"
    )
    assert _MOC_BUILD in nhat_ky, "đường thuận lợi mà không tới build"

    # Bốn tag, không phải hai: celery-worker/celery-beat có ảnh RIÊNG.
    for dv in _DICH_VU_RA:
        assert f"docker tag {_ANH_GIA[dv]} qlts-{dv}:pre-" in nhat_ky, (
            f"thiếu lệnh tag cho '{dv}' — rollback sẽ lùi thiếu service.\n{nhat_ky}"
        )

    ban_ke = _manifest_da_xuat_ban(goc)
    assert len(ban_ke) == 1, f"phải có đúng một bản kê, thấy {ban_ke}"
    noi_dung = ban_ke[0].read_text(encoding="utf-8")

    # `# git-rev` phải là SHA CŨ (từ marker), KHÔNG phải HEAD hiện tại. Đây là
    # toàn bộ lý do marker tồn tại: deploy.yml đã ff-merge nên HEAD đã là SHA mới.
    assert f"# git-rev\t{_SHA_CU}" in noi_dung, (
        f"bản kê phải ghim SHA CŨ {_SHA_CU}, không phải HEAD.\n{noi_dung}"
    )
    assert f"# target-rev\t{_SHA_MOI}" in noi_dung
    for dv in _DICH_VU_RA:
        assert (
            f"{dv}\t{_cid_gia(dv)}\t{_ANH_GIA[dv]}\t" in noi_dung
        ), f"bản kê thiếu dòng '{dv}'"

    # Preflight phải chạy NGAY, và phải ở chế độ local-only: nhánh GHCR sẽ dừng
    # ở cổng đăng nhập vì VPS có `auths` rỗng.
    assert _MOC_PREFLIGHT_RA in nhat_ky, "không gọi rollback-preflight"
    assert "rollback-preflight local_only=1" in nhat_ky, (
        f"preflight phải được gọi với LOCAL_ONLY=1.\n{nhat_ky}"
    )
    assert "rollback-preflight manifest_ton_tai=1" in nhat_ky, (
        "preflight được gọi trước khi bản kê tồn tại — sai thứ tự"
    )

    # Marker mới phải mô tả SHA vừa deploy.
    marker = (goc / "ops" / "last-deploy.marker").read_text(encoding="utf-8")
    assert f"# deployed-sha\t{_SHA_MOI}" in marker, f"marker chưa cập nhật:\n{marker}"
    for dv in _DICH_VU_RA:
        assert f"{dv}\t{_ANH_GIA[dv]}\t" in marker, f"marker thiếu '{dv}'"


@_bo_qua_neu_khong_posix
def test_ra_thieu_marker_thi_dung_truoc_build(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path, marker=None)
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode != 0, "thiếu marker mà deploy vẫn thoát 0"
    assert _MOC_BUILD not in nhat_ky, (
        f"đã build dù không biết ảnh cũ thuộc commit nào:\n{nhat_ky}"
    )
    assert _MOC_PGDUMP not in nhat_ky, "đã chạm CSDL"
    assert not _manifest_da_xuat_ban(goc), "không được xuất bản bản kê nào"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,than_marker",
    [
        ("thiếu dòng deployed-sha", _MARKER_THIEU_SHA),
        ("sha không đủ 40 ký tự", _noi_dung_marker(sha="a" * 39)),
        ("sha có ký tự không phải hex", _noi_dung_marker(sha="g" * 40)),
        (
            "marker chỉ có 3/4 service",
            _noi_dung_marker(
                anh={k: v for k, v in _ANH_GIA.items() if k != "frontend"}
            ),
        ),
    ],
)
def test_ra_marker_hong_thi_dung_truoc_build(
    tmp_path: Path, ten_ca: str, than_marker: str
) -> None:
    goc = _dung_san_khau(tmp_path, marker=than_marker)
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode != 0, f"{ten_ca}: deploy phải dừng"
    assert _MOC_BUILD not in nhat_ky, f"{ten_ca}: đã build\n{nhat_ky}"
    assert not _manifest_da_xuat_ban(goc), f"{ten_ca}: đã xuất bản bản kê"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("dich_vu", _DICH_VU_RA)
def test_ra_marker_lech_mot_service_thi_dung(tmp_path: Path, dich_vu: str) -> None:
    """Lệch DÙ CHỈ MỘT service thì dừng.

    Ca này chạy cho cả bốn service vì một guard chỉ so `backend` sẽ xanh ở ba
    ca còn lại — đúng lớp lỗi "vá một nhánh còn bốn nhánh".
    """
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_IMG_LECH=dich_vu)

    assert ket.returncode != 0, f"'{dich_vu}' lệch mà deploy vẫn thoát 0"
    assert (
        dich_vu in ket.stdout + ket.stderr
    ), "thông điệp lỗi phải nêu ĐÍCH DANH service lệch"
    assert _MOC_BUILD not in nhat_ky, f"đã build dù marker lệch ở '{dich_vu}'"
    assert not _manifest_da_xuat_ban(goc)


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("dich_vu", _DICH_VU_RA)
def test_ra_thieu_mot_container_thi_dung(tmp_path: Path, dich_vu: str) -> None:
    """`compose ps -q` trả RỖNG mà vẫn exit 0 — đúng cái bẫy "lệnh trả 0"."""
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_PS_Q_THIEU=dich_vu)

    assert ket.returncode != 0, f"thiếu container '{dich_vu}' mà deploy vẫn thoát 0"
    assert _MOC_BUILD not in nhat_ky, f"đã build dù thiếu container '{dich_vu}'"
    assert not _manifest_da_xuat_ban(goc)


@_bo_qua_neu_khong_posix
def test_ra_image_id_rong_thi_dung(tmp_path: Path) -> None:
    """Chuỗi rỗng trôi qua mọi phép so — phải bắt tại chỗ đọc, không để nó đi xa."""
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_IMG_RONG="celery-beat")

    assert ket.returncode != 0, "image ID rỗng mà deploy vẫn thoát 0"
    assert _MOC_BUILD not in nhat_ky
    assert not _manifest_da_xuat_ban(goc)


@_bo_qua_neu_khong_posix
def test_ra_tag_da_ton_tai_thi_khong_ghi_de(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_IMAGE_INSPECT_RC="0")

    assert ket.returncode != 0, "tag đã tồn tại mà deploy vẫn thoát 0"
    assert _MOC_TAG_ANH not in nhat_ky, f"đã ghi đè tag có sẵn:\n{nhat_ky}"
    assert _MOC_BUILD not in nhat_ky
    assert not _manifest_da_xuat_ban(goc)


@_bo_qua_neu_khong_posix
def test_ra_loi_giua_chung_khong_xuat_ban_ban_ke(tmp_path: Path) -> None:
    """`docker tag` hỏng ở giữa thì KHÔNG được để lại bản kê nào.

    Bản kê nửa vời nguy hiểm hơn không có bản kê: preflight của lượt sau sẽ đọc
    được vài dòng đầu rồi tuyên bố có đường lùi cho một bộ ảnh không đủ.
    """
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_TAG_RC="1")

    assert ket.returncode != 0, "tag hỏng mà deploy vẫn thoát 0"
    assert not _manifest_da_xuat_ban(goc), "đã xuất bản bản kê dù tag hỏng giữa chừng"
    assert _MOC_BUILD not in nhat_ky
    assert (
        _MOC_PREFLIGHT_RA not in nhat_ky
    ), "gọi preflight trên bộ tài sản chưa hoàn chỉnh"


@_bo_qua_neu_khong_posix
def test_ra_preflight_do_thi_dung_truoc_build(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_ROLLBACK_PREFLIGHT_RC="1")

    assert ket.returncode != 0, "preflight đỏ mà deploy vẫn thoát 0"
    assert _MOC_PREFLIGHT_RA in nhat_ky, "preflight phải được gọi rồi mới đỏ"
    assert _MOC_BUILD not in nhat_ky, (
        f"đã build dù tài sản rollback không dùng được:\n{nhat_ky}"
    )
    assert _MOC_PGDUMP not in nhat_ky, "đã chạm CSDL"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban",
    [
        ("bật mà thiếu lý do", {"QLTS_SKIP_ROLLBACK_ASSET": "1"}),
        (
            "lý do rỗng",
            {"QLTS_SKIP_ROLLBACK_ASSET": "1", "QLTS_SKIP_ROLLBACK_ASSET_REASON": ""},
        ),
        (
            "lý do có xuống dòng",
            {
                "QLTS_SKIP_ROLLBACK_ASSET": "1",
                "QLTS_SKIP_ROLLBACK_ASSET_REASON": "vi\nly do",
            },
        ),
        (
            "lý do có tab",
            {
                "QLTS_SKIP_ROLLBACK_ASSET": "1",
                "QLTS_SKIP_ROLLBACK_ASSET_REASON": "vi\tly do",
            },
        ),
        (
            "giá trị 'true' không được coi là bật",
            {
                "QLTS_SKIP_ROLLBACK_ASSET": "true",
                "QLTS_SKIP_ROLLBACK_ASSET_REASON": "co ly do",
            },
        ),
        ("giá trị 'yes'", {"QLTS_SKIP_ROLLBACK_ASSET": "yes"}),
        ("giá trị rỗng", {"QLTS_SKIP_ROLLBACK_ASSET": ""}),
    ],
)
def test_ra_thoat_hiem_khong_hop_le_thi_dung(
    tmp_path: Path, ten_ca: str, kich_ban: dict
) -> None:
    """Cổng thoát hiểm phải fail-closed ở MỌI cách dùng sai.

    Đặc biệt: một giá trị lạ (`true`, `yes`, rỗng) KHÔNG được hiểu là "bật".
    Biến đặt sai chính tả mà được coi như bỏ qua là cách cổng tự tắt đúng lúc
    cần canh nhất.
    """
    goc = _dung_san_khau(tmp_path, marker=None)
    ket, nhat_ky = _chay_deploy(goc, **kich_ban)

    assert ket.returncode != 0, f"{ten_ca}: deploy phải dừng"
    assert _MOC_BUILD not in nhat_ky, f"{ten_ca}: đã build\n{nhat_ky}"


@_bo_qua_neu_khong_posix
def test_ra_thoat_hiem_hop_le_thi_di_tiep_va_ghi_vet(tmp_path: Path) -> None:
    """Bỏ qua ĐÚNG CÁCH thì deploy chạy — nhưng phải để lại vết đọc được."""
    goc = _dung_san_khau(tmp_path, marker=None)
    ket, nhat_ky = _chay_deploy(
        goc,
        QLTS_SKIP_ROLLBACK_ASSET="1",
        QLTS_SKIP_ROLLBACK_ASSET_REASON="hotfix P0, registry dang sap",
    )

    assert ket.returncode == 0, (
        f"stdout:\n{ket.stdout[-3000:]}\nstderr:\n{ket.stderr[-3000:]}"
    )
    assert _MOC_BUILD in nhat_ky, "bỏ qua hợp lệ mà không tới build"
    assert not _manifest_da_xuat_ban(goc), "bỏ qua rồi mà vẫn tạo bản kê"
    assert "hotfix P0" in ket.stdout, "lý do phải xuất hiện trong log deploy"

    marker = (goc / "ops" / "last-deploy.marker").read_text(encoding="utf-8")
    assert "# asset-skipped\thotfix P0, registry dang sap" in marker, (
        f"marker phải ghi lại rằng lượt này KHÔNG có tài sản:\n{marker}"
    )


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_go_khoi_tai_san_thi_thieu_marker_van_build(tmp_path: Path) -> None:
    """Gỡ đúng khối đang canh và xác nhận nó ĐỎ — không thì "vẫn xanh" vô nghĩa.

    Biến thể tinh vi nhất: xoá trọn Step 3b nhưng giữ nguyên mọi thứ khác. Nếu
    build vẫn không chạy sau khi gỡ, guard này không phải thứ đang chặn và cả
    nhóm ca trên đang xanh nhờ một cơ chế khác.
    """
    van = _DEPLOY.read_text(encoding="utf-8")
    dau = van.rindex("# ====", 0, van.index("# Step 3b: TÀI SẢN ROLLBACK"))
    cuoi = van.rindex("# ====", 0, van.index("# Step 4: Build Docker images"))
    dot_bien = van[:dau] + van[cuoi:]
    # Bám vào THÂN guard, không bám chữ "Step 3b": chuỗi đó còn xuất hiện trong
    # chú thích của Step 8c, nên phép kiểm theo tên mục sẽ luôn đỏ và ca đột
    # biến không bao giờ chạy tới phần có nghĩa.
    assert "LỆCH marker ở" not in dot_bien, "đột biến chưa gỡ được thân guard"
    assert "rollback-preflight.sh" not in dot_bien, "đột biến còn sót lời gọi preflight"

    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien, marker=None)
    _, nhat_ky = _chay_deploy(goc)

    assert _MOC_BUILD in nhat_ky, (
        "gỡ Step 3b mà build VẪN không chạy ⇒ thứ chặn build không phải guard này.\n"
        f"nhật ký:\n{nhat_ky}"
    )


# =============================================================================
# Bốn lỗ fail-closed phát hiện khi rà lại (18-09-2026) — mỗi lỗ một nhóm ca
# =============================================================================


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,env_them",
    [
        (
            "cả hai biến",
            "QLTS_SKIP_ROLLBACK_ASSET=1\nQLTS_SKIP_ROLLBACK_ASSET_REASON=x\n",
        ),
        ("chỉ biến cờ", "QLTS_SKIP_ROLLBACK_ASSET=1\n"),
        ("chỉ biến lý do", "QLTS_SKIP_ROLLBACK_ASSET_REASON=x\n"),
        ("cờ đặt =0", "QLTS_SKIP_ROLLBACK_ASSET=0\n"),
    ],
)
def test_ra_thoat_hiem_trong_env_production_thi_dung(
    tmp_path: Path, ten_ca: str, env_them: str
) -> None:
    """Cổng thoát hiểm KHÔNG được trở thành cấu hình thường trực.

    `deploy.sh` `source .env.production`, nên hai biến ghi vào tệp đó một lần
    rồi quên sẽ khiến MỌI deploy sau tự bỏ qua tài sản — trái hợp đồng "gõ tay
    mỗi lượt". Kể cả `=0` cũng phải từ chối: vấn đề là chúng NẰM TRONG TỆP,
    không phải giá trị chúng mang.
    """
    goc = _dung_san_khau(tmp_path, env_them=env_them)
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode != 0, f"{ten_ca}: deploy phải dừng"
    assert ".env.production" in ket.stdout, f"{ten_ca}: thông điệp phải nêu đúng nguồn"
    assert _MOC_BUILD not in nhat_ky, f"{ten_ca}: đã build"


@_bo_qua_neu_khong_posix
def test_ra_thoat_hiem_dong_lenh_van_chay_du_env_sach(tmp_path: Path) -> None:
    """Kiểm ngược của ca trên: gõ tay trên dòng lệnh thì VẪN phải đi tiếp.

    Không có ca này thì một guard chặn nhầm cả đường hợp lệ vẫn xanh.
    """
    goc = _dung_san_khau(tmp_path, marker=None)
    ket, _ = _chay_deploy(
        goc,
        QLTS_SKIP_ROLLBACK_ASSET="1",
        QLTS_SKIP_ROLLBACK_ASSET_REASON="hotfix P0",
    )
    assert ket.returncode == 0, f"stdout:\n{ket.stdout[-2500:]}"


@_bo_qua_neu_khong_posix
def test_ra_ly_do_co_backslash_thi_dung(tmp_path: Path) -> None:
    """`\\n` là HAI ký tự, không phải newline — phép kiểm cntrl không bắt được.

    Với `echo -e` nó từng đẻ ra một dòng log giả. Hai lớp phòng thủ: log đã
    chuyển sang `printf '%s'`, và lý do từ chối dấu gạch chéo ngược.
    """
    goc = _dung_san_khau(tmp_path, marker=None)
    ket, _ = _chay_deploy(
        goc,
        QLTS_SKIP_ROLLBACK_ASSET="1",
        QLTS_SKIP_ROLLBACK_ASSET_REASON="hotfix\\n[DEPLOY] gia mao",
    )
    assert ket.returncode != 0, "lý do chứa backslash mà deploy vẫn chạy"
    assert "\n[DEPLOY] gia mao" not in ket.stdout, "đã đẻ ra dòng log giả"


@_bo_qua_neu_khong_posix
def test_ra_log_khong_dien_giai_escape_trong_thong_diep(tmp_path: Path) -> None:
    """Chứng minh chính hàm log đã hết diễn giải escape, độc lập với guard lý do."""
    goc = _dung_san_khau(tmp_path, marker=None)
    (goc / "scripts" / "thu.sh").write_text(
        "source scripts/deploy.sh 2>/dev/null || true\n", encoding="utf-8", newline="\n"
    )
    ket = subprocess.run(
        ["bash", "-c", 'sed -n "/^log()/,/^cutover()/p" scripts/deploy.sh > /tmp/f.sh; '
         'RED=; GREEN=; YELLOW=; NC=; . /tmp/f.sh; log "a\\nb"'],
        cwd=str(goc), capture_output=True, text=True, timeout=60,
    )
    assert ket.stdout.count("\n") == 1, (
        f"log() vẫn tách '\\n' thành dòng mới: {ket.stdout!r}"
    )
    assert "a\\nb" in ket.stdout, f"log() phải in nguyên văn: {ket.stdout!r}"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,than_marker",
    [
        (
            "thiếu marker-version",
            _noi_dung_marker().replace("# marker-version\t1\n", ""),
        ),
        (
            "marker-version khác 1",
            _noi_dung_marker().replace("# marker-version\t1", "# marker-version\t2"),
        ),
        (
            "marker-version hai lần",
            "# marker-version\t1\n" + _noi_dung_marker(),
        ),
        (
            "deployed-sha hai lần mâu thuẫn",
            _noi_dung_marker() + f"# deployed-sha\t{'e' * 40}\n",
        ),
        (
            "một service khai hai lần",
            _noi_dung_marker() + f"backend\t{_ANH_GIA['backend']}\t{_cid_gia('backend')}\n",
        ),
        (
            "có dòng service lạ",
            _noi_dung_marker() + f"postgres\t{_ANH_GIA['backend']}\t{_cid_gia('postgres')}\n",
        ),
        (
            "image ID thiếu tiền tố sha256",
            _noi_dung_marker(anh={**_ANH_GIA, "frontend": "f" * 64}),
        ),
        (
            "image ID chỉ 12 hex (tiền tố rút gọn)",
            _noi_dung_marker(anh={**_ANH_GIA, "celery-beat": "sha256:" + "d" * 12}),
        ),
        (
            "image ID có ký tự không phải hex",
            _noi_dung_marker(anh={**_ANH_GIA, "backend": "sha256:" + "z" * 64}),
        ),
    ],
)
def test_ra_marker_sai_hinh_dang_thi_dung(
    tmp_path: Path, ten_ca: str, than_marker: str
) -> None:
    """Marker phải ĐÚNG HÌNH DẠNG, không chỉ "có dòng ta cần".

    `head -1` là cái bẫy: marker có hai dòng `deployed-sha` mâu thuẫn vẫn qua
    cổng và ta ghim theo dòng đầu mà không biết dòng sau nói khác.
    """
    goc = _dung_san_khau(tmp_path, marker=than_marker)
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode != 0, f"{ten_ca}: deploy phải dừng"
    assert _MOC_BUILD not in nhat_ky, f"{ten_ca}: đã build\n{nhat_ky}"
    assert not _manifest_da_xuat_ban(goc), f"{ten_ca}: đã xuất bản bản kê"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("lan_hong", [2, 3, 4])
def test_ra_tag_hong_GIUA_CHUNG_khong_xuat_ban_ban_ke(
    tmp_path: Path, lan_hong: int
) -> None:
    """Hỏng ở tag thứ 2/3/4 — tức ĐÃ tạo được 1–3 tag rồi mới gãy.

    `STUB_TAG_RC=1` làm hỏng ngay lệnh đầu, nên nó chưa từng thi hành nhánh
    "dở dang thật". Ca này mới là ca mà bản kê nửa vời có thể ra đời.
    """
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_TAG_FAIL_AT=str(lan_hong))

    assert ket.returncode != 0, f"gãy ở tag #{lan_hong} mà deploy vẫn thoát 0"
    assert nhat_ky.count("docker tag ") == lan_hong, (
        f"kịch bản chưa đúng: muốn gãy ở lần {lan_hong}, "
        f"thấy {nhat_ky.count('docker tag ')} lần gọi"
    )
    assert not _manifest_da_xuat_ban(goc), "đã xuất bản bản kê dù tag gãy giữa chừng"
    assert _MOC_PREFLIGHT_RA not in nhat_ky, "gọi preflight trên bộ tài sản dở dang"
    assert _MOC_BUILD not in nhat_ky


@_bo_qua_neu_khong_posix
def test_ra_preflight_do_thi_khong_co_ban_ke_chinh_thuc(tmp_path: Path) -> None:
    """Preflight đỏ ⇒ KHÔNG được để lại bản kê mang tên chính thức.

    Bản trước `mv` sang tên thật RỒI mới chạy preflight, nên khi đỏ vẫn còn một
    tệp trông hoàn chỉnh, không dấu hiệu nào nói nó chưa đạt — và lượt sau sẽ
    tin nó.
    """
    goc = _dung_san_khau(tmp_path)
    ket, nhat_ky = _chay_deploy(goc, STUB_ROLLBACK_PREFLIGHT_RC="1")

    assert ket.returncode != 0
    assert _MOC_PREFLIGHT_RA in nhat_ky, "preflight phải được gọi rồi mới đỏ"
    assert not _manifest_da_xuat_ban(goc), (
        "preflight ĐỎ mà bản kê chính thức vẫn nằm lại — lượt sau sẽ tin nó"
    )
    # Và cũng không để lại tệp tạm nào.
    con_lai = [p.name for p in (goc / "ops").rglob("*") if p.is_file()]
    assert not [n for n in con_lai if ".tmp" in n], f"còn tệp tạm: {con_lai}"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban",
    [
        ("thiếu container ở 8c", {"STUB_PS_Q_THIEU_SAU_BUILD": "celery-beat"}),
        ("image ID rỗng ở 8c", {"STUB_IMG_RONG_SAU_BUILD": "frontend"}),
    ],
)
def test_ra_loi_o_step_8c_giu_marker_cu_nguyen_ven(
    tmp_path: Path, ten_ca: str, kich_ban: dict
) -> None:
    """Nhánh lỗi của Step 8c chưa từng được thi hành trước ca này.

    `STUB_PS_Q_THIEU`/`STUB_IMG_RONG` làm Step 3b đỏ NGAY, nên chúng không bao
    giờ chạm tới 8c. Hai kịch bản `_SAU_BUILD` chỉ hỏng sau khi build đã chạy.

    Bất biến: marker CŨ phải còn byte-identical, không tệp tạm nào nằm lại, và
    KHÔNG in dòng hoàn tất.
    """
    goc = _dung_san_khau(tmp_path)
    truoc = (goc / "ops" / "last-deploy.marker").read_bytes()

    ket, nhat_ky = _chay_deploy(goc, **kich_ban)

    assert _MOC_BUILD in nhat_ky, f"{ten_ca}: chưa tới build ⇒ chưa chạm được 8c"
    assert ket.returncode != 0, f"{ten_ca}: lỗi ở 8c mà deploy vẫn thoát 0"

    sau = (goc / "ops" / "last-deploy.marker").read_bytes()
    assert sau == truoc, f"{ten_ca}: marker cũ đã bị sửa — lượt sau sẽ ghim nhầm"

    con_lai = [p.name for p in (goc / "ops").rglob("*") if p.is_file()]
    assert not [n for n in con_lai if ".tmp" in n], f"{ten_ca}: còn tệp tạm {con_lai}"
    assert "Deployment completed successfully" not in ket.stdout, (
        f"{ten_ca}: in dòng hoàn tất dù marker chưa ghi được"
    )


def _go_moi_lop_bao_ve_env(van: str) -> str:
    """Đột biến: gỡ TẤT CẢ các lớp chặn `.env.production`.

    Có BA lớp, không phải hai — lượt viết ca này đầu tiên đã sót lớp 3 và đột
    biến không tái hiện được lỗ:

    1. chụp giá trị TRƯỚC `source` rồi chỉ dùng bản chụp ⇒ giá trị từ tệp env
       không bao giờ được đọc;
    2. từ chối to tiếng nếu tệp env tái khai báo;
    3. `unset` sau `source` ⇒ dù có lọt qua (1) và (2), biến vẫn bị xoá trước
       khi tới Step 3b.

    Gỡ riêng lớp 2 thì lỗ KHÔNG mở lại, nên một ca đột biến chỉ gỡ lớp 2 sẽ
    chứng minh nhầm. Phải gỡ cả ba.
    """
    dau = van.index('if [ "${QLTS_SKIP_ROLLBACK_ASSET+co}" = "co" ] \\')
    # Cắt qua HẾT dòng `unset` (lớp 3), không dừng ngay trước nó.
    cuoi = van.index("\n", van.index("unset QLTS_SKIP_ROLLBACK_ASSET", dau)) + 1
    van = van[:dau] + van[cuoi:]
    van = van.replace('if [ "$_RA_SKIP_CO" = "1" ]; then', 'if true; then', 1)
    van = van.replace(
        'case "$_RA_SKIP_GIATRI" in', 'case "${QLTS_SKIP_ROLLBACK_ASSET:-0}" in', 1
    )
    van = van.replace('if [ "$_RA_REASON_CO" != "1" ]; then', "if false; then", 1)
    van = van.replace(
        'if [ -z "$_RA_REASON_GIATRI" ]; then', "if false; then", 1
    )
    return van


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_go_moi_lop_thi_env_production_bat_duoc_vinh_vien(
    tmp_path: Path,
) -> None:
    """Gỡ đúng thứ đang canh và xác nhận lỗ MỞ LẠI — không thì "vẫn xanh" vô nghĩa.

    Sau đột biến, `.env.production` khai hai biến là đủ để deploy **âm thầm bỏ
    qua** tài sản rollback: thoát 0, tới build, không bản kê nào. Đó chính là
    hình dạng của lỗ "bật vĩnh viễn" mà bản vá đóng lại.
    """
    dot_bien = _go_moi_lop_bao_ve_env(_DEPLOY.read_text(encoding="utf-8"))
    assert "được khai báo trong .env.production" not in dot_bien

    goc = _dung_san_khau(
        tmp_path,
        deploy_sh=dot_bien,
        env_them="QLTS_SKIP_ROLLBACK_ASSET=1\nQLTS_SKIP_ROLLBACK_ASSET_REASON=x\n",
    )
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode == 0, (
        f"đột biến phải chạy trót lọt mới chứng minh được lỗ.\n"
        f"stdout:\n{ket.stdout[-2500:]}"
    )
    assert _MOC_BUILD in nhat_ky, "đột biến chưa tới build"
    assert not _manifest_da_xuat_ban(goc), (
        "đột biến vẫn tạo bản kê ⇒ chưa tái hiện được lỗ bỏ-qua"
    )


@_bo_qua_neu_khong_posix
def test_ra_lop_chup_truoc_source_tu_no_da_du_vo_hieu_env(tmp_path: Path) -> None:
    """Chỉ gỡ lớp 2: lỗ KHÔNG mở lại, vì lớp 1 vẫn bỏ qua giá trị từ tệp env.

    Ca này khoá lại đúng lý do vì sao ca đột biến ở trên phải gỡ CẢ BA lớp —
    nếu ai đó sau này rút gọn nó, ca này sẽ đỏ.
    """
    van = _DEPLOY.read_text(encoding="utf-8")
    dau = van.index('if [ "${QLTS_SKIP_ROLLBACK_ASSET+co}" = "co" ] \\')
    cuoi = van.index("unset QLTS_SKIP_ROLLBACK_ASSET", dau)
    chi_go_lop2 = van[:dau] + van[cuoi:]

    goc = _dung_san_khau(
        tmp_path,
        deploy_sh=chi_go_lop2,
        env_them="QLTS_SKIP_ROLLBACK_ASSET=1\nQLTS_SKIP_ROLLBACK_ASSET_REASON=x\n",
    )
    ket, nhat_ky = _chay_deploy(goc)

    assert ket.returncode == 0, f"stdout:\n{ket.stdout[-2500:]}"
    assert _manifest_da_xuat_ban(goc), (
        "giá trị từ .env.production KHÔNG được có hiệu lực — lớp chụp-trước-source "
        "phải khiến deploy vẫn tạo tài sản bình thường"
    )
