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

import os
import shutil
import subprocess
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
    *pre_deploy_check.py*)
        exit "${STUB_PREDEPLOY_RC:-0}"
        ;;
    *"alembic upgrade head"*)
        exit "${STUB_ALEMBIC_RC:-0}"
        ;;
    *" ps "*)
        # deploy.sh chờ bằng `... ps <svc> | grep -q healthy`
        echo "qlts-gia   running   healthy"
        exit 0
        ;;
    *)
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


def _dung_san_khau(tmp_path: Path, deploy_sh: str | None = None) -> Path:
    """Dựng một cây dự án tối thiểu đủ để `scripts/deploy.sh` chạy tới Step 8."""
    goc = tmp_path / "qlts"
    (goc / "scripts").mkdir(parents=True)
    (goc / "nginx" / "templates").mkdir(parents=True)
    (goc / "bin").mkdir()

    noi_dung = deploy_sh if deploy_sh is not None else _DEPLOY.read_text(encoding="utf-8")
    (goc / "scripts" / "deploy.sh").write_text(noi_dung, encoding="utf-8", newline="\n")
    for ten, than in (
        ("scripts/nginx-apply.sh", _STUB_NGINX_APPLY),
        ("bin/docker", _STUB_DOCKER),
        ("bin/git", _STUB_GIT),
    ):
        duong = goc / ten
        duong.write_text(than, encoding="utf-8", newline="\n")
        duong.chmod(0o755)

    (goc / ".env.production").write_text(_ENV_PRODUCTION, encoding="utf-8", newline="\n")
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
    }
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
