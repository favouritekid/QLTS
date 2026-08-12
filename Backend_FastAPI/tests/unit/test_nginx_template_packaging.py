"""Hợp đồng đóng gói cấu hình Nginx — canh đúng sự cố 12-08-2026.

Chuyện đã xảy ra: `docker-compose.yml` mount `./nginx/conf.d` vào
`/etc/nginx/conf.d`, và template nằm ngay trong đó. Nhưng entrypoint chính thức
của image `nginx` CHỈ quét `/etc/nginx/templates` (xem
``/docker-entrypoint.d/20-envsubst-on-templates.sh``: ``template_dir`` mặc định
là ``/etc/nginx/templates``, ``output_dir`` là ``/etc/nginx/conf.d``). Còn
``nginx/nginx.conf`` thì chỉ ``include /etc/nginx/conf.d/*.conf``.

Hệ quả: template KHÔNG bao giờ được render, `include *.conf` không khớp gì, và
nginx chạy với **không một server block nào**. Production sống sót suốt nhiều
tuần chỉ vì trên máy chủ có sẵn một `nginx/conf.d/default.conf` đã render —
tệp ấy bị `.gitignore` loại khỏi repo, nên **một clean checkout thì site chết**.

Điều khiến nó khó thấy: `nginx -t` vẫn báo *syntax is ok* (config rỗng vẫn hợp
lệ), container vẫn `Up`, Docker vẫn publish 80/443. Chỉ khi gọi từ ngoài mới
thấy `ECONNREFUSED`.

Các khẳng định dưới đây canh **hợp đồng đóng gói**, không canh cách viết config.
Chúng chạy không cần Docker nên nằm được trong lát unit của CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")

_GOC = Path(__file__).resolve().parents[3]
_COMPOSE = _GOC / "docker-compose.yml"
_THU_MUC_TEMPLATE = _GOC / "nginx" / "templates"
_TEMPLATE = _THU_MUC_TEMPLATE / "default.conf.template"

_DUONG_TEMPLATE_TRONG_CONTAINER = "/etc/nginx/templates"
_DUONG_OUTPUT_TRONG_CONTAINER = "/etc/nginx/conf.d"


@pytest.fixture(scope="module")
def dv_nginx() -> dict:
    if not _COMPOSE.is_file():
        pytest.skip(f"không thấy {_COMPOSE}")
    noi_dung = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    dich_vu = noi_dung.get("services", {}).get("nginx")
    assert dich_vu, "docker-compose.yml không có service `nginx`"
    return dich_vu


def _cac_mount(dv: dict) -> list[str]:
    return [m for m in dv.get("volumes", []) if isinstance(m, str)]


def _dich_cua_mount(mount: str) -> str:
    """`./nguon:/dich:ro` → `/dich`."""
    phan = mount.split(":")
    return phan[1] if len(phan) >= 2 else ""


def test_template_nam_dung_thu_muc_entrypoint_quet():
    """Template phải ở `nginx/templates/`, không phải `nginx/conf.d/`."""
    assert _TEMPLATE.is_file(), (
        f"thiếu {_TEMPLATE.relative_to(_GOC)} — entrypoint nginx chỉ render "
        f"template nằm ở {_DUONG_TEMPLATE_TRONG_CONTAINER}"
    )


def test_khong_con_template_trong_conf_d():
    """Chống tái phạm: đặt lại template vào `conf.d` là dựng lại sự cố."""
    conf_d = _GOC / "nginx" / "conf.d"
    if not conf_d.exists():
        return
    con_lai = sorted(p.name for p in conf_d.glob("*.template"))
    assert not con_lai, (
        f"còn template trong nginx/conf.d: {con_lai}. Entrypoint KHÔNG render "
        "chúng; nginx sẽ chạy mà không có server block nào."
    )


def test_compose_mount_template_vao_dung_duong(dv_nginx: dict):
    dich = [_dich_cua_mount(m) for m in _cac_mount(dv_nginx)]
    assert _DUONG_TEMPLATE_TRONG_CONTAINER in dich, (
        f"service nginx phải mount thư mục template vào "
        f"{_DUONG_TEMPLATE_TRONG_CONTAINER}. Hiện có: {dich}"
    )


def test_compose_KHONG_mount_de_len_conf_d(dv_nginx: dict):
    """`conf.d` là thư mục ĐẦU RA của entrypoint — mount đè là chặn render.

    Với mount read-only, chính entrypoint có nhánh
    ``if [ ! -w "$output_dir" ]`` → in lỗi và bỏ qua render.
    """
    dich = [_dich_cua_mount(m) for m in _cac_mount(dv_nginx)]
    assert _DUONG_OUTPUT_TRONG_CONTAINER not in dich, (
        f"service nginx đang mount đè {_DUONG_OUTPUT_TRONG_CONTAINER} — "
        "entrypoint cần GHI bản render vào đó."
    )


@pytest.mark.parametrize("bien", ["DOMAIN", "NGINX_ADMISSION_FROZEN"])
def test_bien_render_duoc_truyen_vao_container(dv_nginx: dict, bien: str):
    """`--env-file` chỉ nội suy tệp compose; envsubst chạy TRONG container."""
    moi_truong = dv_nginx.get("environment") or {}
    if isinstance(moi_truong, list):
        ten = {m.split("=", 1)[0] for m in moi_truong}
    else:
        ten = set(moi_truong)
    assert bien in ten, (
        f"service nginx chưa truyền `{bien}` vào container; envsubst sẽ render "
        "nó thành chuỗi rỗng."
    )


def test_domain_KHONG_duoc_lam_gay_parse_cua_dev(dv_nginx: dict):
    """`${DOMAIN:?}` là hồi quy: nó làm gãy cả `docker compose up -d` của dev.

    Compose nội suy TOÀN BỘ tệp trước khi lọc profile, nên một biến bắt buộc
    trong service `nginx` (profile `production`) vẫn chặn lệnh dev vốn không hề
    chạy nginx. Fail-closed thuộc về healthcheck và `scripts/deploy.sh`, không
    thuộc tầng nội suy.
    """
    moi_truong = dv_nginx.get("environment") or {}
    gia_tri = (
        dict(m.split("=", 1) for m in moi_truong if "=" in m)
        if isinstance(moi_truong, list)
        else moi_truong
    )
    khai_bao = str(gia_tri.get("DOMAIN", ""))
    assert ":?" not in khai_bao, (
        "khai báo DOMAIN dùng `:?` — nó làm `docker compose config` của dev đổ "
        f"dù không bật profile production. Hiện: {khai_bao!r}"
    )


# ---------------------------------------------------------------------------
# Consumer: không script nào được đọc đường template CŨ
# ---------------------------------------------------------------------------

_DUONG_CU = "nginx/conf.d/default.conf.template"


def _cac_script() -> list[Path]:
    thu_muc = _GOC / "scripts"
    return sorted(thu_muc.glob("*.sh")) if thu_muc.is_dir() else []


def test_khong_script_nao_doc_duong_template_cu():
    """Rename template mà quên consumer thì deploy kế tiếp dừng giữa chừng.

    12-08-2026 bản vá đầu chỉ sửa compose; `scripts/deploy.sh`,
    `scripts/setup-ssl.sh` và `scripts/test_nginx_admission_freeze.sh` vẫn trỏ
    đường cũ — cả ba sẽ gãy ở lần chạy tiếp theo, mà 12 test cấu trúc lúc đó
    vẫn xanh.
    """
    pham = []
    for sh in _cac_script():
        noi_dung = sh.read_text(encoding="utf-8", errors="replace")
        for so, dong in enumerate(noi_dung.splitlines(), 1):
            if _DUONG_CU in dong and not dong.lstrip().startswith("#"):
                pham.append(f"{sh.relative_to(_GOC)}:{so}")
    assert not pham, (
        f"còn script đọc `{_DUONG_CU}` (đường đã bị rename): {pham}"
    )


def test_deploy_khong_con_render_template_tren_host():
    """Render trên host chính là thứ đẻ ra `default.conf` nằm ngoài git."""
    deploy = _GOC / "scripts" / "deploy.sh"
    if not deploy.is_file():
        pytest.skip("không có scripts/deploy.sh")
    dong_pham = [
        f"{so}: {d.strip()}"
        for so, d in enumerate(deploy.read_text(encoding="utf-8").splitlines(), 1)
        if "envsubst" in d and not d.lstrip().startswith("#")
    ]
    assert not dong_pham, (
        "deploy.sh còn `envsubst` render template trên host; entrypoint nginx "
        f"phải là nơi duy nhất render. Dòng: {dong_pham}"
    )


def test_deploy_ap_config_bang_recreate_va_cho_healthy():
    """`nginx -s reload` KHÔNG áp được template mới.

    Template nay render lúc container khởi động; một tiến trình đang chạy chỉ
    nạp lại đúng bản render cũ của chính nó. Phải recreate rồi chờ healthcheck
    thật — `nginx -t` không phân biệt được "đang phục vụ" với "config rỗng".
    """
    deploy = _GOC / "scripts" / "deploy.sh"
    if not deploy.is_file():
        pytest.skip("không có scripts/deploy.sh")
    noi_dung = deploy.read_text(encoding="utf-8")
    ma_lenh = chr(10).join(
        d for d in noi_dung.splitlines() if not d.lstrip().startswith("#")
    )
    assert "--force-recreate" in ma_lenh and "nginx" in ma_lenh, (
        "deploy.sh phải recreate nginx để áp bản render mới"
    )
    assert "State.Health.Status" in ma_lenh, (
        "deploy.sh phải CHỜ healthcheck của nginx, không dừng ở `nginx -t`"
    )
    assert "nginx -s reload" not in ma_lenh, (
        "deploy.sh còn dùng `nginx -s reload` — nó nạp lại bản render CŨ"
    )


class TestHealthcheck:
    """Healthcheck phải chứng minh CÓ SERVER BLOCK ĐANG PHỤC VỤ."""

    @staticmethod
    def _lenh(dv: dict) -> str:
        hc = dv.get("healthcheck") or {}
        test = hc.get("test")
        assert test, "service nginx không có healthcheck"
        return " ".join(test) if isinstance(test, list) else str(test)

    def test_khong_dung_nginx_t_lam_bang_chung(self, dv_nginx: dict):
        """`nginx -t` xanh cả khi KHÔNG có server block — vô dụng ở đây."""
        lenh = self._lenh(dv_nginx)
        assert "nginx -t" not in lenh, (
            "healthcheck dựa vào `nginx -t`: một config RỖNG vẫn `syntax is ok`, "
            "nên nó không phân biệt được 'đang phục vụ' với 'không có server "
            "block nào'."
        )

    def test_co_gui_request_that_toi_health(self, dv_nginx: dict):
        lenh = self._lenh(dv_nginx)
        assert "/health" in lenh, "healthcheck phải gọi thật endpoint /health"
        assert "Host:" in lenh, (
            "phải đặt Host khớp server_name — catch-all `default_server` trả 444 "
            "cho Host lạ, nên thiếu Host là luôn đỏ vì lý do sai."
        )

    def test_kiem_ban_render_ton_tai_va_dung_server_name(self, dv_nginx: dict):
        lenh = self._lenh(dv_nginx)
        assert "server_name" in lenh and "default.conf" in lenh, (
            "healthcheck phải kiểm bản render `/etc/nginx/conf.d/default.conf` "
            "có đúng `server_name` — nếu không, trang mặc định của image nginx "
            "có thể làm phép kiểm xanh giả."
        )

    def test_domain_rong_lam_healthcheck_do(self, dv_nginx: dict):
        lenh = self._lenh(dv_nginx)
        assert "test -n" in lenh and "DOMAIN" in lenh, (
            "healthcheck phải đỏ khi DOMAIN rỗng — đó là ca render hỏng mà mọi "
            "phép kiểm khác đều bỏ lọt."
        )


def test_template_chi_dung_bien_da_duoc_truyen(dv_nginx: dict):
    """Mọi `${BIEN}` trong template phải nằm trong environment của container.

    envsubst chỉ thay biến CÓ trong môi trường; biến thiếu sẽ được giữ nguyên
    dạng `${...}` và nginx sẽ hiểu sai hoặc lỗi.
    """
    import re

    if not _TEMPLATE.is_file():
        pytest.skip("chưa có template")
    trong_template = set(
        re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _TEMPLATE.read_text(encoding="utf-8"))
    )
    moi_truong = dv_nginx.get("environment") or {}
    ten = (
        {m.split("=", 1)[0] for m in moi_truong}
        if isinstance(moi_truong, list)
        else set(moi_truong)
    )
    thieu = sorted(trong_template - ten)
    assert not thieu, (
        f"template dùng {thieu} nhưng service nginx không truyền vào container; "
        "envsubst sẽ để nguyên chuỗi `${...}` trong config."
    )

# ---------------------------------------------------------------------------
# Đường vận hành: workflow deploy và bootstrap SSL
# ---------------------------------------------------------------------------


def test_workflow_pull_TRUOC_khi_chay_deploy_script():
    """Bash nạp script vào bộ nhớ lúc gọi — phải cập nhật cây TRƯỚC.

    Gọi thẳng `./scripts/deploy.sh` thì bản CŨ chạy, rồi chính nó `git pull`
    cây mới; logic đang chạy vẫn là bản cũ. Với commit rename template, bản cũ
    đọc `nginx/conf.d/default.conf.template` — tệp đã biến mất — và deploy dừng
    giữa chừng. Caveat này được ghi ngay trong `scripts/deploy.sh` nhưng
    workflow chưa từng tuân theo.
    """
    wf = _GOC / ".github" / "workflows" / "deploy.yml"
    if not wf.is_file():
        pytest.skip("không có .github/workflows/deploy.yml")
    dong = [
        d for d in wf.read_text(encoding="utf-8").splitlines()
        if not d.lstrip().startswith("#")
    ]

    def _vi_tri(mau: str) -> int:
        for i, d in enumerate(dong):
            if mau in d:
                return i
        return -1

    vt_pull = _vi_tri("git pull")
    vt_chay = max(_vi_tri("scripts/deploy.sh"), _vi_tri("deploy.sh"))
    assert vt_pull != -1, "workflow deploy không cập nhật cây trước khi chạy script"
    assert vt_chay != -1, "workflow deploy không gọi scripts/deploy.sh"
    assert vt_pull < vt_chay, (
        "workflow chạy deploy.sh TRƯỚC khi pull — lần deploy đầu sau merge sẽ "
        "chạy bản script cũ"
    )
    assert "--ff-only" in chr(10).join(dong), (
        "dùng `git pull --ff-only` để merge lạ không âm thầm xảy ra trên prod"
    )


def test_workflow_khong_chay_script_tu_tmp():
    """Chép script sang /tmp làm PROJECT_DIR suy từ BASH_SOURCE thành `/`."""
    wf = _GOC / ".github" / "workflows" / "deploy.yml"
    if not wf.is_file():
        pytest.skip("không có deploy.yml")
    ma = chr(10).join(
        d for d in wf.read_text(encoding="utf-8").splitlines()
        if not d.lstrip().startswith("#")
    )
    assert "/tmp/deploy" not in ma, (
        "workflow chạy deploy.sh từ /tmp — script suy PROJECT_DIR từ BASH_SOURCE "
        "nên project root sẽ thành `/`"
    )


def test_setup_ssl_khong_keo_nginx_production_len():
    """`certbot` khai `depends_on: nginx` — thiếu `--no-deps` là tranh cổng 80.

    Ở bước bootstrap, chứng thư chưa tồn tại nên nginx production còn chưa khởi
    động được; đồng thời container bootstrap đang giữ cổng 80.
    """
    sh = _GOC / "scripts" / "setup-ssl.sh"
    if not sh.is_file():
        pytest.skip("không có scripts/setup-ssl.sh")
    for so, d in enumerate(sh.read_text(encoding="utf-8").splitlines(), 1):
        if d.lstrip().startswith("#") or "certbot" not in d:
            continue
        if "run --rm" in d:
            assert "--no-deps" in d, (
                f"setup-ssl.sh:{so} chạy `run --rm certbot` thiếu `--no-deps` — "
                "Compose sẽ kéo nginx production lên giữa lúc bootstrap."
            )
            # Service `certbot` override entrypoint thành vòng lặp
            # `certbot renew … sleep 12h`. `run` chỉ thay COMMAND, không thay
            # entrypoint — nên thiếu `--entrypoint certbot` thì container rơi
            # vào vòng gia hạn và phần `certonly …` chỉ là đối số không được
            # thực thi. Chứng thư sẽ không bao giờ được cấp, mà lệnh vẫn "chạy".
            assert "--entrypoint certbot" in d, (
                f"setup-ssl.sh:{so} thiếu `--entrypoint certbot` — service này "
                "override entrypoint thành vòng lặp renew, nên `certonly` sẽ "
                "không bao giờ chạy."
            )
