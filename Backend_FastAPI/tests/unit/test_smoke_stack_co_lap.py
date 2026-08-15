"""Stack smoke phải CÔ LẬP, và cleanup phải điều khiển ĐÚNG stack đã đo baseline.

Hai lỗ mà tệp này canh, cả hai đều là "xanh mà không canh gì":

* `-p qltssmoke` chọn TÊN PROJECT, không chọn MODEL. Thiếu `-f`/`--env-file` thì
  lệnh dọn nạp `docker-compose.override.yml` của dev và đọc `.env.production` —
  một model khác hẳn model đã dựng stack.
* Cô lập bằng project + database là CHƯA ĐỦ. `docker-compose.yml` khai
  `env_file: ${QLTS_ENV_FILE:-.env.production}`; không đặt biến ấy thì stack
  "riêng" nạp nguyên cấu hình production. Đo được 15-08-2026: model render ra
  `FRONTEND_URL=https://qlts.tnpc.edu.vn` và 18 tham chiếu Zalo.

Phần lớn ca ở đây là Python thuần nên chạy ở mọi môi trường. Ca dựng model thật
cần Docker; nó KHÔNG thay thế các ca kia mà kiểm điều chúng không kiểm được: rằng
tệp compose đang có trong repo thật sự cho ra một model cô lập.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess as _sp
import sys
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

from scripts.smoke_lib import baseline, cli  # noqa: E402

_CO_DOCKER = shutil.which("docker") is not None


_SAU_SERVICE = (
    "postgres", "redis", "backend", "celery-worker", "celery-beat", "frontend",
)


def _env_ung_dung(**doi) -> dict:
    env = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql+asyncpg://qlts:x@postgres:5432/qlts_smoke",
        "REDIS_URL": "redis://redis:6379/1",
        "CELERY_BROKER_URL": "redis://redis:6379/2",
        "CELERY_RESULT_BACKEND_URL": "redis://redis:6379/3",
        "MAIL_SERVER": "127.0.0.1",
        "FRONTEND_URL": "http://127.0.0.1:3100",
        "CORS_ORIGINS": "http://127.0.0.1:3100",
        "PUBLIC_BACKEND_URL": "http://127.0.0.1:8100",
        "HIBP_CHECK_ENABLED": "False",
        "ZALO_ENABLED": "False",
        "ZALO_BOT_ENABLED": "False",
    }
    env.update(doi)
    return env


def _cong(ip: str, pub: int, target: int) -> dict:
    return {"mode": "ingress", "host_ip": ip, "published": str(pub),
            "target": target, "protocol": "tcp"}


def _model(**doi) -> dict:
    """Model ĐẠT, đủ sáu service + tài nguyên đúng. Mỗi ca chỉ đổi MỘT chỗ."""
    env = _env_ung_dung(**doi.pop("env", {}))
    dv = {s: {} for s in _SAU_SERVICE}
    for s in ("backend", "celery-worker", "celery-beat"):
        dv[s] = {"environment": dict(env)}
    dv["backend"]["ports"] = [_cong("127.0.0.1", 8100, 8000)]
    dv["frontend"] = {"ports": [_cong("127.0.0.1", 3100, 3000)]}
    for s, ch in (doi.pop("services", {}) or {}).items():
        dv[s] = ch
    m = {
        "name": "qltssmoke",
        "services": dv,
        "volumes": {
            k: {"name": f"qltssmoke_{k}"}
            for k in ("postgres_data", "redis_data", "backend_uploads",
                      "backend_static_uploads", "backend_logs", "geoip_data",
                      "sms_private_exports")
        },
        "networks": {"default": {"name": "qltssmoke_default"}},
    }
    m.update(doi.pop("goc", {}))
    return m


# =============================================================================
# BoCompose — không có mặc định nào
# =============================================================================
def test_thieu_compose_file_thi_BLOCK():
    with pytest.raises(cli.LoiCLI, match="--compose-file"):
        cli.BoCompose([], ".env.smoke")


def test_thieu_env_file_thi_BLOCK():
    with pytest.raises(cli.LoiCLI, match="--compose-env-file"):
        cli.BoCompose(["docker-compose.yml"], "")


def test_lenh_mang_DU_moi_manh_va_dung_thu_tu():
    bo = cli.BoCompose(["a.yml", "b.yml"], ".env.smoke")
    argv = bo.lenh("stop", "backend")
    assert argv[:4] == ["docker", "compose", "-p", "qltssmoke"]
    assert argv[4:8] == ["-f", "a.yml", "-f", "b.yml"], "thiếu hoặc sai thứ tự -f"
    assert argv[8:10] == ["--env-file", ".env.smoke"]
    assert argv[-2:] == ["stop", "backend"]


# =============================================================================
# kiem_model_smoke — cổng chạy trên MODEL THẬT
# =============================================================================
def test_model_dat_thi_qua():
    baseline.kiem_model_smoke(_model(), app_env="development")


def test_database_url_khac_qlts_smoke_thi_BLOCK():
    m = _model(env={"DATABASE_URL": "postgresql+asyncpg://q:x@postgres:5432/qlts_dev"})
    with pytest.raises(baseline.ChanLai, match="DATABASE_URL"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_app_env_render_khac_tham_so_thi_BLOCK():
    """`--app-env` tự khai không chứng minh model nạp đúng env file."""
    m = _model(env={"APP_ENV": "production"})
    with pytest.raises(baseline.ChanLai, match="APP_ENV"):
        baseline.kiem_model_smoke(m, app_env="development")


@pytest.mark.parametrize(
    "khoa,gt",
    [
        ("FRONTEND_URL", "https://qlts.tnpc.edu.vn"),
        ("SMS_PUBLIC_BASE_URL", "https://qlts.tnpc.edu.vn"),
        ("VNPAY_PAYMENT_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"),
        ("MOMO_ENDPOINT", "https://test-payment.momo.vn/v2/gateway/api/create"),
        ("SENTRY_DSN", "https://abc@o1.ingest.sentry.io/2"),
    ],
)
def test_url_tro_ra_ngoai_thi_BLOCK(khoa, gt):
    """Allowlist host, không phải blocklist tên miền.

    Danh sách cấm luôn thiếu một cái: bốn giá trị dưới đây là MẶC ĐỊNH của
    `app/config.py`, không nằm trong env file nào, nên một phép kiểm chỉ soi
    `.env.*` sẽ không thấy chúng.
    """
    with pytest.raises(baseline.ChanLai, match="ra ngoài"):
        baseline.kiem_model_smoke(_model(env={khoa: gt}), app_env="development")


def test_build_arg_cung_bi_soi():
    """`NEXT_PUBLIC_*` là BUILD ARG — không nằm ở `environment`.

    Bỏ sót chúng là bỏ sót đúng đường mà trình duyệt đi: ảnh frontend build với
    API URL trỏ stack khác thì mọi kết luận smoke vô nghĩa.
    """
    m = _model(services={
        "frontend": {"build": {"args": {"NEXT_PUBLIC_API_URL": "https://qlts.tnpc.edu.vn"}}}
    })
    with pytest.raises(baseline.ChanLai, match="build.args.NEXT_PUBLIC_API_URL"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_host_service_noi_bo_va_invalid_deu_qua():
    m = _model(env={
        "SMS_PUBLIC_BASE_URL": "http://frontend:3000",
        "MAIL_SERVER": "http://smoke.invalid/x",
    })
    baseline.kiem_model_smoke(m, app_env="development")


def test_service_THUA_thi_BLOCK():
    """Chỉ đếm THIẾU là deny-by-default một nửa.

    Model đủ sáu service cộng thêm `nginx` vẫn qua nếu chỉ kiểm thiếu — mà thứ dư
    ra ấy có thể mở cổng, mount volume hoặc gọi ra ngoài.
    """
    m = _model()
    m["services"]["nginx"] = {"image": "nginx:1.27-alpine"}
    with pytest.raises(baseline.ChanLai, match="THỪA"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_db_host_la_may_NGOAI_thi_BLOCK():
    """Hậu tố `/qlts_smoke` một mình không loại được máy chủ lạ."""
    m = _model(env={
        "DATABASE_URL": "postgresql+asyncpg://q:x@evil.example:5432/qlts_smoke"
    })
    with pytest.raises(baseline.ChanLai, match="evil.example"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_userinfo_khong_duoc_doc_THANH_host():
    """`https://127.0.0.1@evil.example` — phần trước `@` là USERINFO.

    Regex bản trước đọc ra host `127.0.0.1` và cho qua; host thật là
    `evil.example`. Đây là ca chứng minh `urlsplit` đã thay được regex.
    """
    m = _model(env={"SMS_PUBLIC_BASE_URL": "https://127.0.0.1@evil.example/x"})
    with pytest.raises(baseline.ChanLai, match="evil.example"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_db_path_phai_khop_CHINH_XAC():
    """`endswith` cho `/xx_qlts_smoke` đi lọt."""
    m = _model(env={
        "DATABASE_URL": "postgresql+asyncpg://q:x@postgres:5432/xx_qlts_smoke"
    })
    with pytest.raises(baseline.ChanLai, match="path"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_db_scheme_la_thu_khac_thi_BLOCK():
    """Đúng host, đúng path, nhưng scheme khác ⇒ không phải kết nối PostgreSQL."""
    m = _model(env={"DATABASE_URL": "mysql+aiomysql://q:x@postgres:5432/qlts_smoke"})
    with pytest.raises(baseline.ChanLai, match="scheme"):
        baseline.kiem_model_smoke(m, app_env="development")


@pytest.mark.parametrize(
    "khoa", ["APP_ENV", "DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL",
             "CELERY_RESULT_BACKEND_URL", "HIBP_CHECK_ENABLED"],
)
def test_gia_tri_THIEU_cung_la_hong(khoa):
    """Fail-closed theo nghĩa hẹp: thiếu giá trị cũng là hỏng.

    Bản trước chỉ kiểm khi giá trị truthy, nên rỗng/không khai đều lọt — đúng hình
    dạng mà một env file sai hay một tên biến gõ nhầm tạo ra.
    """
    env = _env_ung_dung()
    env.pop(khoa)
    m = {"name": "qltssmoke", "services": {s: {} for s in _SAU_SERVICE}}
    for s in ("backend", "celery-worker", "celery-beat"):
        m["services"][s] = {"environment": dict(env)}
    with pytest.raises(baseline.ChanLai, match=khoa):
        baseline.kiem_model_smoke(m, app_env="development")


@pytest.mark.parametrize(
    "khoa", ["HIBP_CHECK_ENABLED", "ZALO_ENABLED", "ZALO_BOT_ENABLED"],
)
def test_cong_tac_outbound_BAT_thi_BLOCK(khoa):
    """Endpoint của ba tích hợp này hard-code ra Internet trong mã.

    Khai rỗng URL không cứu được — chỉ tắt công tắc mới chặn.
    """
    with pytest.raises(baseline.ChanLai, match=khoa):
        baseline.kiem_model_smoke(_model(env={khoa: "true"}), app_env="development")


@pytest.mark.parametrize(
    "khoa", ["ZALO_APP_SECRET", "ZALO_REFRESH_TOKEN", "SENTRY_DSN"],
)
def test_credential_outbound_CO_gia_tri_thi_BLOCK(khoa):
    with pytest.raises(baseline.ChanLai, match=khoa):
        baseline.kiem_model_smoke(
            _model(env={khoa: "gia-tri-that"}), app_env="development"
        )


# =============================================================================
# Tài nguyên hạ tầng — biến môi trường đúng KHÔNG có nghĩa là stack cô lập
# =============================================================================
# Một model có thể đủ sáu service và `DATABASE_URL` vẫn là
# `postgres:5432/qlts_smoke`, trong khi nó publish PostgreSQL ra 0.0.0.0 hoặc
# mount volume của stack khác. CLI cho phép truyền `--compose-file` tuỳ ý, nên
# đây không phải tình huống giả định.
def test_postgres_publish_cong_thi_BLOCK():
    m = _model()
    m["services"]["postgres"] = {"ports": [_cong("0.0.0.0", 5433, 5432)]}
    with pytest.raises(baseline.ChanLai, match="postgres.*không được mở"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_backend_publish_ra_moi_giao_dien_thi_BLOCK():
    m = _model()
    m["services"]["backend"]["ports"] = [_cong("0.0.0.0", 8100, 8000)]
    with pytest.raises(baseline.ChanLai, match="loopback"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_backend_publish_sai_cong_thi_BLOCK():
    m = _model()
    m["services"]["backend"]["ports"] = [_cong("127.0.0.1", 8000, 8000)]
    with pytest.raises(baseline.ChanLai, match="publish cổng"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_volume_cua_stack_KHAC_thi_BLOCK():
    """`qlts_postgres_data` là volume của stack dev — dùng lại là ghi đè dữ liệu dev."""
    m = _model()
    m["volumes"]["postgres_data"] = {"name": "qlts_postgres_data"}
    with pytest.raises(baseline.ChanLai, match="tiền tố"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_volume_external_thi_BLOCK():
    m = _model()
    m["volumes"]["backend_uploads"] = {
        "name": "qltssmoke_backend_uploads", "external": True,
    }
    with pytest.raises(baseline.ChanLai, match="external"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_container_name_thi_BLOCK():
    """Tên cố định phá cơ chế đặt tên theo project — đụng thẳng container stack `qlts`."""
    m = _model()
    m["services"]["backend"]["container_name"] = "qlts-backend-1"
    with pytest.raises(baseline.ChanLai, match="container_name"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_network_khong_dung_tien_to_thi_BLOCK():
    m = _model()
    m["networks"] = {"default": {"name": "qlts_default"}}
    with pytest.raises(baseline.ChanLai, match="network"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_ten_project_khac_thi_BLOCK():
    m = _model()
    m["name"] = "qlts"
    with pytest.raises(baseline.ChanLai, match="project"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_bind_mount_thi_BLOCK():
    """Danh mục volume cấp cao đúng KHÔNG chứng minh service dùng đúng thứ đó.

    `postgres` bind-mount một thư mục host vào `/var/lib/postgresql/data` vẫn giữ
    nguyên danh mục `qltssmoke_*` hợp lệ — mà đó là ghi thẳng vào máy host.
    """
    m = _model()
    m["services"]["postgres"] = {"volumes": [{
        "type": "bind", "source": "D:/du-lieu-that",
        "target": "/var/lib/postgresql/data",
    }]}
    with pytest.raises(baseline.ChanLai, match="bind mount"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_network_mode_host_thi_BLOCK():
    """`network_mode: host` vượt hẳn namespace — mọi phép kiểm network thành vô nghĩa."""
    m = _model()
    m["services"]["frontend"] = {"network_mode": "host"}
    with pytest.raises(baseline.ChanLai, match="network_mode"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_mount_volume_NGOAI_danh_muc_thi_BLOCK():
    m = _model()
    m["services"]["postgres"] = {"volumes": [{
        "type": "volume", "source": "qlts_postgres_data",
        "target": "/var/lib/postgresql/data",
    }]}
    with pytest.raises(baseline.ChanLai, match="không có trong danh mục"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_volume_AN_DANH_thi_BLOCK():
    m = _model()
    m["services"]["postgres"] = {"volumes": [{"type": "volume", "target": "/x"}]}
    with pytest.raises(baseline.ChanLai, match="ẩn danh"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_volumes_from_thi_BLOCK():
    m = _model()
    m["services"]["backend"]["volumes_from"] = ["qlts-backend-1"]
    with pytest.raises(baseline.ChanLai, match="volumes_from"):
        baseline.kiem_model_smoke(m, app_env="development")


def test_mount_named_volume_dung_danh_muc_thi_QUA():
    """Chiều ngược: mount hợp lệ KHÔNG được chặn — nếu không guard chỉ là 'cấm hết'."""
    m = _model()
    m["services"]["postgres"] = {"volumes": [{
        "type": "volume", "source": "postgres_data",
        "target": "/var/lib/postgresql/data",
    }]}
    baseline.kiem_model_smoke(m, app_env="development")


def test_celery_publish_cong_thi_BLOCK():
    """Service không nằm trong danh sách được mở thì KHÔNG được publish gì."""
    m = _model()
    m["services"]["celery-worker"]["ports"] = [_cong("127.0.0.1", 5555, 5555)]
    with pytest.raises(baseline.ChanLai, match="không nằm trong danh sách"):
        baseline.kiem_model_smoke(m, app_env="development")


# =============================================================================
# van_tay_model — kiểm TRƯỚC khi hash, và digest thay vì bỏ khoá
# =============================================================================
def test_van_tay_kiem_truoc_khi_hash():
    """Hash trước rồi kiểm sau là để ngỏ đúng ca cần chặn: một model SAI vẫn cho
    hai vân tay khớp nhau ở hai đầu."""
    xau = json.dumps(_model(env={"APP_ENV": "production"}))
    with pytest.raises(baseline.ChanLai, match="APP_ENV"):
        baseline.van_tay_model(xau, app_env="development")


def test_model_khong_co_services_thi_BLOCK():
    with pytest.raises(baseline.ChanLai, match="services"):
        baseline.van_tay_model('{"name":"qltssmoke"}', app_env="development")


def test_doi_secret_van_LAM_DOI_van_tay():
    """Giá trị nhạy cảm được thay bằng DIGEST, không bị loại bỏ.

    Loại bỏ thì một lần đổi secret trở nên vô hình với phép so — mà đó đúng là
    loại thay đổi cần thấy.
    """
    a = baseline.van_tay_model(
        json.dumps(_model(env={"POSTGRES_PASSWORD": "mat-khau-A"})),
        app_env="development",
    )
    b = baseline.van_tay_model(
        json.dumps(_model(env={"POSTGRES_PASSWORD": "mat-khau-B"})),
        app_env="development",
    )
    assert a != b, "đổi secret mà vân tay không đổi ⇒ khoá đã bị bỏ qua"


def test_van_tay_KHONG_chua_secret_nguyen_van():
    mk = "mat-khau-rat-de-nhan-ra"
    chuan = baseline.chuan_hoa_model(_model(env={"POSTGRES_PASSWORD": mk}))
    xau = json.dumps(chuan)
    assert mk not in xau, "bản chuẩn hoá còn giữ secret nguyên văn"
    assert "sha256:" + hashlib.sha256(mk.encode()).hexdigest() in xau


# =============================================================================
# Model THẬT dựng từ tệp compose trong repo
# =============================================================================
def _goc_repo() -> Path:
    for g in Path(__file__).resolve().parents:
        if (g / "docker-compose.yml").is_file():
            return g
    pytest.fail("không tìm thấy gốc repo")


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để phân giải model thật")
def test_model_that_tu_repo_la_stack_co_lap(tmp_path):
    """Dựng model từ chính hai tệp compose trong repo, với env FIXTURE.

    Cố ý KHÔNG dùng `.env.smoke` thật của máy: ca test không được phụ thuộc một
    tệp không nằm trong git, và tuyệt đối không được chạm `.env.production` —
    `compose config` render env_file ra plaintext, nên chạy nó với env sai là tự
    tạo một bản sao secret.
    """
    goc = _goc_repo()

    # ⚠️ Dùng CHÍNH tệp mẫu được ship, không viết lại một bản rút gọn trong test.
    # Bản rút gọn đầu tiên của ca này thiếu `ZALO_ENABLED`/`ZALO_BOT_ENABLED` — nó
    # trôi khỏi `.env.smoke.app.example` ngay trong lượt viết đầu, và một fixture
    # đã trôi thì chỉ chứng minh giả định của người viết test. Đọc tệp thật khiến
    # ca này canh đúng thứ người vận hành sẽ chép.
    mau = (goc / ".env.smoke.app.example").read_text(encoding="utf-8")
    assert "DIEN_" in mau, "tệp mẫu không còn chỗ điền — đọc lại giả định của ca này"
    app_env = tmp_path / "app.env"
    app_env.write_text(
        "\n".join(
            d.replace("DIEN_CHUOI_NGAU_NHIEN_KHAC_NUA", "y")
             .replace("DIEN_CHUOI_NGAU_NHIEN_KHAC", "x")
            for d in mau.splitlines()
        ) + "\n", encoding="utf-8",
    )
    # Env của runner: `required: true` trong compose nên tệp này PHẢI có. Test trỏ
    # sang tmp_path thay vì đòi `.env.smoke.runner` thật — vừa chạy được trên
    # checkout sạch, vừa không hạ cổng của vận hành xuống optional.
    runner_env = tmp_path / "runner.env"
    runner_env.write_text("SMOKE_PERSONA_MASTER_SECRET=chi-de-test\n", encoding="utf-8")

    env = tmp_path / "compose.env"
    env.write_text(
        "\n".join([
            f"QLTS_ENV_FILE={app_env}",
            f"QLTS_SMOKE_RUNNER_ENV_FILE={runner_env}",
            "POSTGRES_USER=qlts", "POSTGRES_PASSWORD=x", "POSTGRES_DB=qlts_smoke",
            "NEXT_PUBLIC_API_URL=http://127.0.0.1:8100",
            "NEXT_PUBLIC_SOCKET_URL=http://127.0.0.1:8100",
            "DOMAIN=smoke.invalid",
        ]) + "\n", encoding="utf-8",
    )

    ket = _sp.run(
        ["docker", "compose", "-p", "qltssmoke",
         "-f", str(goc / "docker-compose.yml"),
         "-f", str(goc / "docker-compose.smoke.yml"),
         "--env-file", str(env), "config", "--format", "json"],
        cwd=str(goc), capture_output=True, text=True, timeout=300,
    )
    assert ket.returncode == 0, f"compose config hỏng: {(ket.stderr or '')[:600]}"

    model = json.loads(ket.stdout)
    # Cổng thật chạy trên chính model này — nếu tệp compose trong repo cho ra một
    # model không cô lập thì ca này đỏ, không phải chờ tới lúc vận hành.
    baseline.kiem_model_smoke(model, app_env="development")

    dv = model["services"]
    assert set(dv) == {
        "postgres", "redis", "backend", "celery-worker", "celery-beat", "frontend",
    }, f"profile mặc định phải cho đúng sáu service, nhận {sorted(dv)}"

    # smoke-runner chỉ hiện khi bật profile — và khi hiện thì không được mang
    # volume dữ liệu của ứng dụng, cũng không được có build riêng.
    ket2 = _sp.run(
        ["docker", "compose", "-p", "qltssmoke",
         "-f", str(goc / "docker-compose.yml"),
         "-f", str(goc / "docker-compose.smoke.yml"),
         "--env-file", str(env), "--profile", "smoke-tools",
         "config", "--format", "json"],
        cwd=str(goc), capture_output=True, text=True, timeout=300,
    )
    assert ket2.returncode == 0, f"compose config (profile) hỏng: {(ket2.stderr or '')[:600]}"
    runner = json.loads(ket2.stdout)["services"]["smoke-runner"]

    assert "build" not in runner or not runner["build"], (
        "smoke-runner có build riêng ⇒ đẻ ảnh thứ hai thay vì dùng ảnh backend"
    )
    assert runner.get("restart") in (None, "no"), (
        f"restart={runner.get('restart')!r} — công cụ destructive không được tự "
        "khởi động lại"
    )
    nguon = {v.get("source", "") for v in runner.get("volumes", [])}
    cam = {"backend_uploads", "backend_static_uploads", "sms_private_exports",
           "geoip_data", "backend_logs"}
    assert not (nguon & cam), (
        f"smoke-runner thừa kế volume dữ liệu ứng dụng: {sorted(nguon & cam)}"
    )
    assert any("/evidence" == v.get("target") for v in runner.get("volumes", [])), (
        "thiếu mount ghi được cho bằng chứng — `compose run --rm` sẽ làm output "
        "biến mất cùng container"
    )


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để phân giải model thật")
def test_thieu_env_runner_thi_compose_DO(tmp_path):
    """Kiểm ngược cho `required: true`: thiếu env runner phải DỪNG.

    Bản trước để `required: false` với lý do "checkout sạch không có tệp này", và
    đẩy fail-closed sang `smoke_bootstrap_personas.py`. Nhưng tệp ấy chưa tồn tại,
    nên đó là một lời hứa chứ không phải một cổng: model vẫn render sạch trong khi
    runner KHÔNG có `SMOKE_PERSONA_MASTER_SECRET`.
    """
    goc = _goc_repo()

    # ⚠️ App env phải HỢP LỆ, chỉ để THIẾU đúng env của runner. Bản đầu của ca này
    # trỏ cả hai biến tới tệp không tồn tại, nên `compose config` có thể đỏ vì app
    # env — và khi ấy hạ runner về `required: false` test VẪN đỏ, tức ca này không
    # canh cái nó định canh. Một ca chỉ được vi phạm MỘT bất biến.
    app_env = tmp_path / "app.env"
    app_env.write_text(
        (goc / ".env.smoke.app.example").read_text(encoding="utf-8")
        .replace("DIEN_CHUOI_NGAU_NHIEN_KHAC_NUA", "y")
        .replace("DIEN_CHUOI_NGAU_NHIEN_KHAC", "x"),
        encoding="utf-8",
    )
    env = tmp_path / "compose.env"
    env.write_text(
        f"QLTS_ENV_FILE={app_env}\n"
        f"QLTS_SMOKE_RUNNER_ENV_FILE={tmp_path / 'chi-tep-nay-thieu.env'}\n"
        "POSTGRES_USER=qlts\nPOSTGRES_PASSWORD=x\nPOSTGRES_DB=qlts_smoke\n"
        "NEXT_PUBLIC_API_URL=http://127.0.0.1:8100\n"
        "NEXT_PUBLIC_SOCKET_URL=http://127.0.0.1:8100\nDOMAIN=smoke.invalid\n",
        encoding="utf-8",
    )
    ket = _sp.run(
        ["docker", "compose", "-p", "qltssmoke",
         "-f", str(goc / "docker-compose.yml"),
         "-f", str(goc / "docker-compose.smoke.yml"),
         "--env-file", str(env), "--profile", "smoke-tools",
         "config", "--format", "json"],
        cwd=str(goc), capture_output=True, text=True, timeout=300,
    )
    assert ket.returncode != 0, (
        "compose config VẪN render dù thiếu env file — `required: true` không có "
        "tác dụng"
    )


def test_thu_muc_evidence_bi_git_ignore():
    """Registry/ID/ảnh do runner ghi có thể chứa PII — không được lọt vào git.

    `.smoke_*` trong `.gitignore` KHÔNG khớp `.smoke-evidence` (gạch ngang, không
    phải gạch dưới), nên thư mục này từng hoàn toàn không được che.
    """
    goc = _goc_repo()

    # Tầng 1 — kiểm tĩnh, LUÔN chạy. `git` không dùng được ở mọi môi trường: trong
    # container test, `/repo` là bind mount thuộc user khác nên git từ chối với
    # `dubious ownership` và trả khác 0 cho MỌI lệnh. Một ca chỉ dựa vào git khi ấy
    # đỏ vì lý do chẳng liên quan gì tới điều nó định canh.
    dong = {
        d.strip()
        for d in (goc / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    assert ".smoke-evidence/*" in dong, (
        "thiếu `.smoke-evidence/*` — `.smoke_*` KHÔNG khớp `.smoke-evidence` "
        "(gạch ngang, không phải gạch dưới), nên registry và ảnh chụp có thể chứa "
        "PII sẽ lọt vào git"
    )
    assert "!.smoke-evidence/.gitkeep" in dong, (
        "thiếu ngoại lệ cho .gitkeep ⇒ thư mục biến mất trên checkout sạch, và "
        "bind-mount sẽ tự tạo lại nó rỗng mà `up` vẫn exit 0"
    )

    # Tầng 2 — kiểm HÀNH VI, chỉ khi git thực sự dùng được ở cây này.
    #
    # `shutil.which` trước: image backend KHÔNG cài git, nên gọi thẳng sẽ ném
    # `FileNotFoundError` — một ca đỏ vì thiếu công cụ, không phải vì lỗi nó canh.
    #
    # `git check-ignore -q` có BA mã thoát, và gộp chúng là cách để một ca test
    # đỏ vì lý do chẳng liên quan: 0 = bị ignore, 1 = KHÔNG bị ignore, 128 = git
    # lỗi. Trong container test, `/repo` là một git worktree mà `.git` chỉ là tệp
    # trỏ sang đường dẫn Windows không được mount ⇒ 128. Đó là môi trường không
    # trả lời được câu hỏi, không phải câu trả lời "không ignore".
    if shutil.which("git") is None:
        pytest.skip("không có git ở môi trường này — tầng kiểm tĩnh ở trên đã chạy")

    ket = _sp.run(
        ["git", "check-ignore", "-q",
         str(goc / ".smoke-evidence" / "SMK1" / "registry.json")],
        cwd=str(goc), capture_output=True, text=True, timeout=60,
    )
    if ket.returncode not in (0, 1):
        pytest.skip(
            f"git không trả lời được ở {goc} (mã {ket.returncode}): "
            f"{(ket.stderr or '').strip()[:120]}"
        )
    assert ket.returncode == 0, "tệp lồng trong .smoke-evidence KHÔNG bị git ignore"

    # Chiều `.gitkeep`: `--no-index` để hỏi CHÍNH quy tắc ignore, không phải hỏi
    # "tệp này đã tracked chưa" — `.gitkeep` đang tracked nên `check-ignore` mặc
    # định trả 1 bất kể `.gitignore` viết gì, và một ca dựa vào đó luôn xanh.
    #
    # `-v` để đọc ĐƯỢC quy tắc nào khớp. `returncode != 0` một mình cũng sai: mã
    # 128 (git lỗi) khi ấy được tính PASS — đúng lỗi ba-mã-thoát vừa sửa ở trên.
    giu = _sp.run(
        ["git", "check-ignore", "--no-index", "-v",
         str(goc / ".smoke-evidence" / ".gitkeep")],
        cwd=str(goc), capture_output=True, text=True, timeout=60,
    )
    assert giu.returncode in (0, 1), (
        f"git lỗi (mã {giu.returncode}): {(giu.stderr or '').strip()[:120]}"
    )
    if giu.returncode == 0:
        # Có quy tắc khớp — nó BẮT BUỘC phải là quy tắc phủ định, nếu không thư
        # mục sẽ biến mất khi clone và bind-mount tự tạo lại nó rỗng.
        assert "!.smoke-evidence/.gitkeep" in giu.stdout, (
            f".gitkeep khớp quy tắc KHÔNG phải phủ định: {giu.stdout.strip()!r}"
        )
