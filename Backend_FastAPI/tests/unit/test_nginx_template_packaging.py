"""Hợp đồng đóng gói + áp cấu hình Nginx — canh sự cố 12-08-2026 và vòng hai của nó.

Vòng một (12-08-2026): `docker-compose.yml` mount `./nginx/conf.d` vào
`/etc/nginx/conf.d`, và template nằm ngay trong đó. Nhưng entrypoint chính thức
của image `nginx` CHỈ quét `/etc/nginx/templates`
(``/docker-entrypoint.d/20-envsubst-on-templates.sh``: ``template_dir`` mặc định
là ``/etc/nginx/templates``, ``output_dir`` là ``/etc/nginx/conf.d``), còn
``nginx/nginx.conf`` thì chỉ ``include /etc/nginx/conf.d/*.conf``. Template
KHÔNG bao giờ được render ⇒ nginx chạy với **không một server block nào**.
Production sống sót nhiều tuần chỉ nhờ một `nginx/conf.d/default.conf` đã render
nằm ngoài git — nên **một clean checkout thì site chết**.

Vòng hai (bản vá đầu của chính sự cố trên): template chuyển sang
`nginx/templates/` rồi bind-mount thư mục ấy vào container. Đo thật trên Docker
29.7.2: bind-mount một thư mục KHÔNG tồn tại thì daemon TỰ TẠO nó rỗng —
`create_host_path: false` chỉ ngăn Compose tạo, không ngăn daemon, và `up` vẫn
exit 0 — nên clean checkout vẫn cho ra đúng trạng thái vòng một, cộng thêm vhost
mặc định của image lộ ra (cổng 80 trả 200 "Welcome to nginx!" trong khi site
chết). Nay cấu hình được COPY VÀO IMAGE: thiếu template là `docker build` đỏ.

Điều khiến cả hai vòng khó thấy: `nginx -t` vẫn báo *syntax is ok* (config rỗng
vẫn hợp lệ), container vẫn `Up`, Docker vẫn publish 80/443.

Các khẳng định dưới đây canh **hợp đồng đóng gói và hợp đồng áp cấu hình**,
không canh cách viết config — một phép kiểm dựa vào cách đánh máy template sẽ
làm prod đỏ oan vì một lần đảo thứ tự vô hại (đã tái hiện). Bằng chứng "có phục
vụ thật" thuộc về `scripts/nginx-verify.sh` (TLS + SNI thật), chạy mỗi lần
deploy và trong bộ E2E `tests-e2e/nginx-packaging/`.

Chúng chạy không cần Docker nên nằm được trong lát unit của CI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")


def _tim_bash() -> str | None:
    """Đường dẫn tới một `bash` THỰC SỰ chạy được.

    ⚠️ Trên Windows, `shutil.which("bash")` thường trả về bash của **WSL**, và
    gọi nó bằng đường dẫn kiểu Windows cho `execvpe(/bin/bash) failed: No such
    file or directory`. Đã vấp hai lần. Nên ưu tiên Git Bash, và luôn kiểm
    bằng cách CHẠY THẬT chứ không tin `which`.
    """
    ung_vien = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        "/bin/bash",
        "/usr/bin/bash",
    ]
    duong = shutil.which("bash")
    if duong:
        ung_vien.append(duong)
    for uv in ung_vien:
        if not os.path.exists(uv):
            continue
        try:
            r = subprocess.run(
                [uv, "-c", "echo ok"], capture_output=True, text=True, timeout=20
            )
        except Exception:
            continue
        if r.returncode == 0 and "ok" in r.stdout:
            return uv
    return None


_BASH = _tim_bash()


def _tim_goc() -> Path:
    """Đi ngược lên tìm gốc repo bằng MỐC, không đếm số tầng thư mục.

    `parents[3]` chỉ đúng trên runner CI. Dưới lệnh mà CLAUDE.md ghi là cách
    chạy test tại máy — `docker compose exec backend python -m pytest tests/` —
    `docker-compose.override.yml` mount `./Backend_FastAPI` vào `/app`, nên tệp
    này là `/app/tests/unit/...` và `parents[3]` ra thẳng `/`. Hậu quả không
    phải là "bỏ qua": một test HỎNG CỨNG vì không thấy template (tệp rõ ràng
    đang có), fixture compose skip mất chín khẳng định, và guard "không script
    nào đọc đường cũ" XANH VÔ NGHĨA vì `/scripts` không tồn tại.
    """
    import os

    ung_vien = list(Path(__file__).resolve().parents)
    # Lối thoát cho ca chạy trong container backend: ở đó `/app` CHỈ là
    # `Backend_FastAPI/`, cây repo không hề có mặt, nên không mốc nào tìm được.
    # Mount cây repo vào rồi trỏ biến này là chạy được đúng lệnh mà CLAUDE.md
    # ghi, thay vì để cả tệp bị bỏ qua.
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
_THU_MUC_NGINX = _GOC / "nginx"
_TEMPLATE = _THU_MUC_NGINX / "templates" / "default.conf.template"
_DOCKERFILE = _THU_MUC_NGINX / "Dockerfile"

_DUONG_TEMPLATE_TRONG_CONTAINER = "/etc/nginx/templates"
_DUONG_OUTPUT_TRONG_CONTAINER = "/etc/nginx/conf.d"

# Hằng mà `location = /nginx-alive` trả về và healthcheck so khớp CHÍNH XÁC.
# Ba nơi phải cùng biết nó: template, healthcheck trong compose, và test này.
_THAN_ALIVE = "qlts-nginx-alive"


@pytest.fixture(scope="module")
def compose() -> dict:
    if not _COMPOSE.is_file():
        pytest.skip(f"không thấy {_COMPOSE}")
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dv_nginx(compose: dict) -> dict:
    dich_vu = compose.get("services", {}).get("nginx")
    assert dich_vu, "docker-compose.yml không có service `nginx`"
    return dich_vu


@pytest.fixture(scope="module")
def dv_candidate(compose: dict) -> dict:
    dich_vu = compose.get("services", {}).get("nginx-candidate")
    assert dich_vu, (
        "docker-compose.yml không có service `nginx-candidate` — không có nó thì "
        "không có cách nào thử cấu hình mới trước khi thay container đang phục vụ"
    )
    return dich_vu


def _cac_mount(dv: dict) -> list[str]:
    """Danh sách mount ở dạng chuỗi, chấp nhận cả cú pháp dài."""
    ra = []
    for m in dv.get("volumes", []):
        if isinstance(m, str):
            ra.append(m)
        elif isinstance(m, dict):
            ra.append(f"{m.get('source', '')}:{m.get('target', '')}")
    return ra


def _dich_cua_mount(mount: str) -> str:
    """`./nguon:/dich:ro` -> `/dich`."""
    phan = mount.split(":")
    return phan[1] if len(phan) >= 2 else ""


def _doc(duong: Path) -> str:
    return duong.read_text(encoding="utf-8")


class _LoaderCompose(yaml.SafeLoader):
    """SafeLoader hiểu hai thẻ riêng của Compose.

    `!reset` và `!override` không phải YAML chuẩn; `yaml.safe_load` đổ với
    `could not determine a constructor`. Chúng lại chính là hai thứ mà các tệp
    override ở đây bắt buộc phải dùng (Compose GỘP danh sách, không thay), nên
    bài kiểm phải đọc được chúng thay vì né.
    """


_LoaderCompose.add_constructor(
    "!reset", lambda loader, node: None
)
_LoaderCompose.add_constructor(
    "!override",
    lambda loader, node: (
        loader.construct_sequence(node, deep=True)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_object(node, deep=True)
    ),
)


def _tai_compose(duong: Path) -> dict:
    return yaml.load(_doc(duong), Loader=_LoaderCompose)


def _ma_lenh(duong: Path) -> str:
    r"""Nội dung tệp: bỏ dòng chú thích, rồi NỐI LẠI các dòng nối tiếp `\`.

    Bỏ chú thích để guard không khớp nhầm vào một câu văn nhắc lại lệnh cũ.
    Nối dòng vì nếu không thì mọi guard dưới đây đều né được bằng cách xuống
    dòng: `up -d --force-recreate \` + `    nginx` là cùng MỘT lệnh, nhưng một
    biểu thức `[^\n]*` sẽ không thấy. Chính bài kiểm này đã bắt được lỗ đó ở
    bản nháp đầu — nó báo đỏ cho một lệnh viết đúng chỉ vì lệnh ấy trải hai
    dòng, và cùng lúc lộ ra rằng chiều ngược lại cũng lọt.
    """
    khong_chu_thich = "\n".join(
        d for d in _doc(duong).splitlines() if not d.lstrip().startswith("#")
    )
    return re.sub(r"\\\n\s*", " ", khong_chu_thich)


# ---------------------------------------------------------------------------
# Đóng gói: cấu hình phải đi theo IMAGE
# ---------------------------------------------------------------------------


def test_template_nam_dung_thu_muc_entrypoint_quet():
    """Template phải ở `nginx/templates/`, không phải `nginx/conf.d/`."""
    assert _TEMPLATE.is_file(), (
        f"thiếu {_TEMPLATE.relative_to(_GOC)} — entrypoint nginx chỉ render "
        f"template nằm ở {_DUONG_TEMPLATE_TRONG_CONTAINER}"
    )


def test_khong_con_template_trong_conf_d():
    """Chống tái phạm: đặt lại template vào `conf.d` là dựng lại sự cố."""
    conf_d = _THU_MUC_NGINX / "conf.d"
    if not conf_d.exists():
        return
    con_lai = sorted(p.name for p in conf_d.glob("*.template"))
    assert not con_lai, (
        f"còn template trong nginx/conf.d: {con_lai}. Entrypoint KHÔNG render "
        "chúng; nginx sẽ chạy mà không có server block nào."
    )


def test_cau_hinh_di_theo_image_chu_khong_theo_thu_muc_host():
    """Thiếu template phải làm `docker build` ĐỎ, không thành thư mục rỗng.

    Đo trên Docker 29.7.2: `create_host_path: false` chỉ ngăn Compose tạo thư
    mục nguồn, daemon vẫn tạo và `up` vẫn exit 0 — nên bind-mount KHÔNG thể là
    cơ chế fail-closed cho ca "clean checkout thiếu tệp".
    """
    assert _DOCKERFILE.is_file(), "thiếu nginx/Dockerfile"
    df = _doc(_DOCKERFILE)
    assert re.search(r"^COPY\s+templates/\s+/etc/nginx/templates/", df, re.M), (
        "nginx/Dockerfile phải COPY templates/ vào image — đó là thứ biến "
        "'thiếu template' thành một lần build đỏ thay vì một site chết im lặng"
    )
    assert re.search(r"^COPY\s+nginx\.conf\s+/etc/nginx/nginx\.conf", df, re.M), (
        "nginx/Dockerfile phải COPY nginx.conf vào image"
    )
    assert re.search(r"rm\s+-f\s+/etc/nginx/conf\.d/\*\.conf", df), (
        "nginx/Dockerfile phải xoá vhost mặc định của image: chính nó biến ca "
        "'không có config' từ ECONNREFUSED ầm ĩ thành 200 OK 'Welcome to nginx!'"
    )
    assert re.search(r"chmod\s+\+x\s+/docker-entrypoint\.d/", df), (
        "phải `chmod +x` guard: entrypoint chính thức BỎ QUA (chỉ log 'Ignoring') "
        "mọi tệp .sh không có bit thực thi — guard sẽ im lặng không chạy"
    )


def test_compose_dung_build_khong_dung_image_tran(dv_nginx: dict):
    build = dv_nginx.get("build")
    assert build, "service nginx phải `build:` từ nginx/Dockerfile, không `image:` trần"
    context = build.get("context") if isinstance(build, dict) else build
    assert str(context).rstrip("/").endswith("nginx"), f"build.context lạ: {context!r}"


def test_compose_KHONG_mount_de_len_conf_d(dv_nginx: dict):
    """`conf.d` là thư mục ĐẦU RA của entrypoint — mount đè là chặn render."""
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


def test_nginx_KHONG_duoc_thay_bi_mat_cua_app(dv_nginx: dict):
    """nginx là container quay ra Internet — không cho nó `env_file` của app.

    `env_file: .env.production` sẽ chữa được cú trượt tay quên `--env-file`,
    nhưng giá phải trả là SECRET_KEY / JWT_SECRET_KEY / POSTGRES_PASSWORD nằm
    trong biến môi trường của tiến trình đứng ngay mặt Internet. Fail-closed
    thuộc về guard entrypoint, không đổi bằng một bậc leo thang đặc quyền.
    """
    assert not dv_nginx.get("env_file"), (
        "service nginx khai `env_file` — nó sẽ thấy toàn bộ bí mật của backend"
    )


def test_domain_KHONG_duoc_lam_gay_parse_cua_dev(dv_nginx: dict):
    """`${DOMAIN:?}` là hồi quy: nó làm gãy cả `docker compose up -d` của dev.

    Compose nội suy TOÀN BỘ tệp trước khi lọc profile, nên một biến bắt buộc
    trong service `nginx` (profile `production`) vẫn chặn lệnh dev vốn không hề
    chạy nginx. Fail-closed thuộc về guard entrypoint + healthcheck +
    `scripts/deploy.sh`, không thuộc tầng nội suy.
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
# Guard entrypoint: fail-closed NGAY TRONG container
# ---------------------------------------------------------------------------

_GUARD_BIEN = _THU_MUC_NGINX / "docker-entrypoint.d" / "10-qlts-kiem-bien.sh"
_GUARD_RENDER = _THU_MUC_NGINX / "docker-entrypoint.d" / "25-qlts-kiem-ban-render.sh"


def test_guard_chay_dung_thu_tu_quanh_envsubst():
    """Entrypoint duyệt `/docker-entrypoint.d/*.sh` theo `sort -V`.

    Guard biến phải chạy TRƯỚC `20-envsubst-on-templates.sh`, guard bản render
    phải chạy SAU. Sai thứ tự là guard kiểm một thứ chưa tồn tại.
    """
    assert _GUARD_BIEN.is_file(), "thiếu guard kiểm biến"
    assert _GUARD_RENDER.is_file(), "thiếu guard kiểm bản render"
    assert _GUARD_BIEN.name < "20-envsubst-on-templates.sh" < _GUARD_RENDER.name


def test_guard_chan_domain_rong_va_co_gat_go_nham():
    ma = _doc(_GUARD_BIEN)
    assert "DOMAIN" in ma and "exit 1" in ma
    assert "NGINX_ADMISSION_FROZEN" in ma, (
        "guard phải cưỡng chế NGINX_ADMISSION_FROZEN thuộc {true,false}: mặc "
        "định của cần gạt này fail-OPEN — template chỉ chặn khi khớp CHÍNH XÁC "
        "'true', nên một cú gõ nhầm (TRUE, 1) làm người trực tin đã đóng băng "
        "tuyển sinh trong khi traffic vẫn đi qua"
    )


def test_guard_bat_bien_chua_duoc_thay_trong_ban_render():
    """envsubst giữ NGUYÊN `${TEN}` cho biến thiếu — nginx nuốt im lặng."""
    assert "${" in _doc(_GUARD_RENDER)


# ---------------------------------------------------------------------------
# Healthcheck: phải đo HÀNH VI, trên HTTPS, với SNI thật
# ---------------------------------------------------------------------------


class TestHealthcheck:
    @staticmethod
    def _lenh(dv: dict) -> str:
        hc = dv.get("healthcheck") or {}
        test = hc.get("test")
        assert test, "service nginx không có healthcheck"
        return " ".join(test) if isinstance(test, list) else str(test)

    def test_khong_dung_nginx_t_lam_bang_chung(self, dv_nginx: dict):
        """`nginx -t` xanh cả khi KHÔNG có server block — vô dụng ở đây."""
        assert "nginx -t" not in self._lenh(dv_nginx), (
            "healthcheck dựa vào `nginx -t`: một config RỖNG vẫn `syntax is ok`, "
            "nên nó không phân biệt được 'đang phục vụ' với 'không có server "
            "block nào'."
        )

    def test_do_tren_HTTPS_chu_khong_phai_cong_80(self, dv_nginx: dict):
        """Cả ba lớp cũ đều đáp xuống cổng 80 — khối HTTPS mất mà vẫn healthy.

        Đã tái hiện bằng thực thi (hai lần, hai chiều): xoá trọn khối
        `HTTPS: Main server` rồi chạy chuỗi CMD-SHELL cũ cho rc=0 trong khi
        client thật nhận `Connection reset`; chạy chuỗi MỚI trên cùng bản đột
        biến thì container `unhealthy` và cổng deploy chặn lại.
        """
        lenh = self._lenh(dv_nginx)
        assert "https://" in lenh, (
            "healthcheck phải gọi HTTPS — khối 443 mới là nơi phục vụ production"
        )
        assert not re.search(r"http://127\.0\.0\.1/|http://localhost/", lenh), (
            "healthcheck còn đáp xuống cổng 80"
        )

    def test_dung_resolve_chu_khong_dung_header_Host(self, dv_nginx: dict):
        """`--header "Host:"` + nối tới 127.0.0.1 thì SNI vẫn là 127.0.0.1.

        Server block 443 có tên sẽ không được chọn; catch-all
        `ssl_reject_handshake` trả lời. Đó đúng là phép đo sai đã làm cả kíp
        trực tin site còn sống hôm 12-08-2026. `--resolve TÊN:CỔNG:IP` giữ tên
        trong URL (nên SNI và Host đều đúng) mà ép IP đích.
        """
        lenh = self._lenh(dv_nginx)
        assert "--resolve" in lenh, "healthcheck phải dùng `curl --resolve` để SNI đúng"
        assert "Host:" not in lenh, (
            "healthcheck đặt header Host thủ công — dấu hiệu đang nối tới "
            "127.0.0.1 với SNI sai"
        )

    def test_KHONG_grep_server_name(self, dv_nginx: dict):
        """Hồi quy: phép grep ấy buộc sống chết của prod vào cách đánh máy.

        Đã tái hiện: chỉ đảo thành `server_name www.${DOMAIN} ${DOMAIN};` là
        phép grep cũ ĐỎ trong khi nginx phục vụ hoàn hảo — và vì cổng deploy nay
        chí mạng, MỌI lần deploy sau đó sẽ hard-fail. Pattern còn là BRE không
        neo nên dấu chấm của tên miền là wildcard.
        """
        assert "server_name" not in self._lenh(dv_nginx), (
            "healthcheck đang grep `server_name` trong bản render — nó nói về "
            "CHỮ, không nói về hành vi. Bằng chứng phục vụ thật là một request "
            "TLS có SNI đúng."
        )

    def test_so_THAN_phan_hoi_chu_khong_chi_ma_200(self, dv_nginx: dict):
        """Chỉ nhìn mã 200 là chưa canh được gì — đã tái hiện.

        Gỡ `location = /nginx-alive` thì request rơi xuống catch-all
        `location /` → `proxy_pass http://frontend` → frontend trả 200 cho mọi
        đường dẫn, và một healthcheck chỉ nhìn mã vẫn XANH dù thứ nó tưởng đang
        canh đã biến mất (ca W1-E). So khớp chính xác thân phản hồi thì ca ấy đỏ.
        """
        lenh = self._lenh(dv_nginx)
        assert _THAN_ALIVE in lenh, (
            f"healthcheck phải so khớp chính xác thân phản hồi {_THAN_ALIVE!r}"
        )
        assert "--output /dev/null" not in lenh, (
            "vứt thân phản hồi đi thì chỉ còn mã trạng thái — mà catch-all "
            "proxy tới frontend trả 200 cho mọi đường dẫn"
        )

    def test_domain_rong_van_lam_healthcheck_do(self, dv_nginx: dict):
        assert "test -n" in self._lenh(dv_nginx), (
            "giữ lớp phòng xa cho DOMAIN rỗng (guard entrypoint đã chặn trước, "
            "nhưng healthcheck không được phụ thuộc vào việc đó)"
        )


def test_template_co_dau_moc_song_cua_khoi_HTTPS():
    """Healthcheck gọi `/nginx-alive`; nó phải nằm TRONG khối 443.

    Đặt nhầm sang khối 80 là dựng lại đúng ca xanh giả mà bản vá này đóng.
    """
    noi_dung = _doc(_TEMPLATE)
    i = noi_dung.index("# --- HTTPS: Main server ---")
    assert "location = /nginx-alive" in noi_dung[i:], (
        "`/nginx-alive` không nằm trong khối HTTPS — healthcheck sẽ lại chứng "
        "minh một thứ khác với thứ nó tuyên bố"
    )
    assert "location = /nginx-alive" not in noi_dung[:i], (
        "`/nginx-alive` xuất hiện TRƯỚC khối HTTPS"
    )
    assert f"return 200 '{_THAN_ALIVE}'" in noi_dung, (
        f"thân phản hồi phải đúng hằng {_THAN_ALIVE!r} mà healthcheck so khớp"
    )


def test_nginx_alive_khong_lo_ra_ngoai():
    """Nó là đầu dò nội bộ; healthcheck chạy TRONG container nên là 127.0.0.1."""
    noi_dung = _doc(_TEMPLATE)
    i = noi_dung.index("location = /nginx-alive")
    khoi = noi_dung[i : noi_dung.index("\n    }\n", i)]
    assert "allow 127.0.0.1" in khoi and "deny all" in khoi, (
        "`/nginx-alive` phải chỉ cho loopback — không có lý do gì để lộ một "
        "đầu dò hạ tầng ra Internet"
    )


def test_template_chi_dung_bien_da_duoc_truyen(dv_nginx: dict):
    """Mọi `${BIEN}` trong template phải nằm trong environment của container."""
    if not _TEMPLATE.is_file():
        pytest.skip("chưa có template")
    trong_template = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _doc(_TEMPLATE)))
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
# Áp cấu hình: THỬ TRƯỚC, THAY SAU
# ---------------------------------------------------------------------------

_APPLY = _GOC / "scripts" / "nginx-apply.sh"
_VERIFY = _GOC / "scripts" / "nginx-verify.sh"
_DEPLOY = _GOC / "scripts" / "deploy.sh"


def test_candidate_khong_publish_cong_nao(dv_candidate: dict):
    """Candidate mà bind 80/443 thì nó tranh cổng với bản đang phục vụ."""
    assert not dv_candidate.get("ports"), (
        "nginx-candidate KHÔNG được publish cổng — nó phải dựng được CẠNH "
        "container đang phục vụ, đo qua IP nội bộ của mạng project"
    )
    assert dv_candidate.get("profiles") == ["candidate"], (
        "nginx-candidate phải nằm riêng profile `candidate`, nếu không nó sẽ "
        "được kéo lên trong mọi lệnh production"
    )
    assert str(dv_candidate.get("restart", "")).strip('"') == "no", (
        "candidate phải `restart: no` — hỏng thì nó cần NẰM YÊN ở exited để đọc "
        "được log, không được quay vòng"
    )


def test_candidate_va_nginx_dung_CHUNG_mot_than(compose: dict):
    """Hai bên lệch nhau thì phép thử không chứng minh gì cho cái thật."""
    tho = _doc(_COMPOSE)
    assert "&nginx-base" in tho and tho.count("<<: *nginx-base") >= 2, (
        "nginx và nginx-candidate phải cùng dùng anchor `*nginx-base`; chép tay "
        "hai bản là mở đường cho chúng trôi lệch nhau"
    )
    n = compose["services"]["nginx"]
    c = compose["services"]["nginx-candidate"]
    for khoa in ("image", "environment", "healthcheck", "volumes"):
        assert n.get(khoa) == c.get(khoa), (
            f"nginx và nginx-candidate lệch nhau ở `{khoa}` — phép thử trên "
            "candidate sẽ không nói được gì về container thật"
        )


def test_deploy_uy_thac_cho_nginx_apply():
    assert _APPLY.is_file(), "thiếu scripts/nginx-apply.sh"
    assert "nginx-apply.sh" in _ma_lenh(_DEPLOY), "deploy.sh phải gọi scripts/nginx-apply.sh"


def test_deploy_KHONG_con_khoi_dong_nginx_o_step8():
    """Step 8 khởi động nginx rồi Step 8b thay lại = hai vòng đời mỗi deploy."""
    ma = _ma_lenh(_DEPLOY)
    assert not re.search(r"up -d[^\n]*\bnginx\b", ma), (
        "deploy.sh còn `up -d ... nginx` trực tiếp; việc khởi động nginx thuộc "
        "về nginx-apply.sh (thử trước, thay sau)"
    )
    assert re.search(r"up -d[^\n]*--no-deps[^\n]*certbot", ma), (
        "`certbot` khai `depends_on: nginx` — thiếu `--no-deps` là Compose vẫn "
        "kéo nginx lên bất kể ta đã bỏ tên nginx khỏi dòng lệnh"
    )


def test_khong_force_recreate_container_dang_phuc_vu():
    """`--force-recreate nginx` phá last-good TRƯỚC khi có gì được kiểm.

    Neo vào ĐÚNG chuỗi lệnh chứ không phải "có `--force-recreate` ở đâu đó và
    có chữ `nginx` ở đâu đó" — bản guard trước khớp cả khi cờ ấy nằm trên một
    service hoàn toàn khác (`up -d --force-recreate backend` cũng làm nó xanh).
    """
    ma = _ma_lenh(_APPLY)
    assert re.search(r"--force-recreate\s+nginx-candidate\b", ma), (
        "candidate PHẢI được dựng lại mỗi lần — nó là bản nháp"
    )
    assert not re.search(r"--force-recreate\s+nginx\b(?!-candidate)", ma), (
        "còn `--force-recreate nginx` trên container đang phục vụ: nó bị "
        "stop+remove trước khi cấu hình mới được kiểm, và không có đường lùi"
    )


def test_candidate_duoc_do_TRUOC_khi_dung_toi_container_that():
    """Thứ tự là toàn bộ giá trị của bản vá; đảo lại là mất sạch."""
    ma = _ma_lenh(_APPLY)
    vt_do_candidate = ma.index("nginx-verify.sh")
    # Neo vào ĐÚNG lệnh khởi động container ĐANG PHỤC VỤ, không phải bất kỳ
    # `--profile production up -d` nào: nhịp 0 cũng `up -d` nhưng chỉ để dựng
    # backend/frontend, và neo vào nó thì test đỏ oan.
    khoi_dong_that = re.search(r"up -d[^\n]*[^-]nginx;", ma)
    assert khoi_dong_that, "không thấy lệnh khởi động container nginx đang phục vụ"
    assert vt_do_candidate < khoi_dong_that.start(), (
        "container đang phục vụ bị đụng tới TRƯỚC khi candidate được đo"
    )


def test_apply_do_lai_tren_chinh_container_dang_phuc_vu():
    """Candidate đạt không chứng minh container THẬT đã nhận cấu hình ấy."""
    assert _ma_lenh(_APPLY).count("nginx-verify.sh") >= 2, (
        "phải đo hai lần: trên candidate, rồi trên chính container đang phục vụ"
    )


def test_verify_do_bang_SNI_that_va_cham_ca_hai_upstream():
    ma = _ma_lenh(_VERIFY)
    assert "--resolve" in ma, "phải dùng `curl --resolve` (SNI đúng)"
    assert "Host:" not in ma, (
        "đặt Host thủ công tới 127.0.0.1 là tái tạo đúng phép đo sai của cutover"
    )
    assert "/login" in ma, "phải chạm một route đi FRONTEND"
    assert "/api/" in ma, "phải chạm một route đi BACKEND"
    assert "khong-thuoc-ve.invalid" in ma, "phải chứng minh SNI lạ bị từ chối"
    assert "acme-challenge" in ma, (
        "phải chứng minh đường ACME còn sống — mất nó thì certbot gia hạn hỏng "
        "ÂM THẦM và chứng thư chỉ chết vào ngày hết hạn"
    )


def test_vong_cho_nhan_ra_container_da_chet():
    """Vòng chờ cũ chỉ thoát sớm ở đúng chữ `unhealthy`.

    nginx chết lúc nạp config thì container `exited`/`restarting` và
    `docker inspect` trả rỗng hoặc `starting` — nên nó chờ đủ ~120 giây với
    site đã chết rồi báo một câu vô nghĩa là `khong-doc-duoc`. Đo lại sau bản
    vá: ca DOMAIN rỗng báo hỏng sau 4 giây.
    """
    ma = _ma_lenh(_APPLY)
    assert "exited" in ma and "restarting" in ma, (
        "vòng chờ không nhận ra container đã dừng / đang quay vòng"
    )


# ---------------------------------------------------------------------------
# Cổng NỘI DUNG + cổng ĐỒNG NHẤT — `nginx-apply.sh` KHÔNG BUILD GÌ CẢ
# ---------------------------------------------------------------------------
# Khoảng trống được đóng ở đây:
#
#   `--profile candidate up -d --no-deps --force-recreate nginx-candidate` thay
#   CONTAINER chứ không thay IMAGE, và `nginx` với `nginx-candidate` dùng chung
#   đúng một tag (`qlts-nginx:local`, anchor `x-nginx-base`). Nên chuỗi
#       sửa nginx/templates/*  →  bash scripts/nginx-apply.sh <domain>
#   cho ra một candidate dựng từ ảnh CŨ: healthcheck xanh, cả sáu phép kiểm của
#   `nginx-verify.sh` xanh (ảnh cũ phục vụ tốt — ĐÓ CHÍNH LÀ VẤN ĐỀ), rồi script
#   in "cấu hình mới đã được áp". Đường deploy chính build ở `scripts/deploy.sh`
#   Step 7 nên không dính; `scripts/setup-ssl.sh` và mọi lần gõ tay theo runbook
#   thì có.
#
# Phép đo HÀNH VI không thể thấy ca này — nên cổng phải so NỘI DUNG, và phải so
# ở tầng mà `COPY` đặt tệp xuống (trước render). `envsubst` của entrypoint biến
# `/etc/nginx/templates/*.template` thành `/etc/nginx/conf.d/*`, nên so byte ở
# tầng `conf.d` là không thể; ở tầng `/etc/nginx/templates/` thì `COPY` là phép
# chép NGUYÊN BYTE.


def test_cong_noi_dung_chay_TRUOC_phep_do_hanh_vi():
    ma = _ma_lenh(_APPLY)
    assert "_cong_noi_dung" in ma, (
        "scripts/nginx-apply.sh không có cổng đối chiếu nội dung — sửa template "
        "mà quên build thì script vẫn in 'cấu hình mới đã được áp'"
    )
    vt_cong = ma.index('_cong_noi_dung "$_CID_CANDIDATE"')
    vt_do = ma.index("nginx-verify.sh")
    assert vt_cong < vt_do, (
        "cổng nội dung phải chạy TRƯỚC nginx-verify.sh: ca 'chưa build' là ca mà "
        "phép đo hành vi luôn xanh, nên để sau là đốt phép đo rồi mới báo sai chỗ"
    )


def test_cong_dong_nhat_ghim_image_id_bat_bien():
    """`{{.Config.Image}}` là TÊN:TAG — hai service dùng chung một tag."""
    ma = _ma_lenh(_APPLY)
    assert "{{.Image}}" in ma, (
        "cổng đồng nhất phải đọc `docker inspect -f '{{.Image}}'` (sha256 bất biến)"
    )
    assert "{{.Config.Image}}" not in ma, (
        "`{{.Config.Image}}` trả về `qlts-nginx:local` cho CẢ HAI service, nên "
        "phép so luôn khớp kể cả khi `up -d` không recreate gì"
    )
    assert re.search(r"_ANH_DANG_PHUC_VU.*!=.*_ANH_DA_CHUNG_MINH|"
                     r"_ANH_DA_CHUNG_MINH.*!=.*_ANH_DANG_PHUC_VU", ma), (
        "không thấy phép so image id của nginx sau cutover với image id của "
        "candidate đã được chứng minh"
    )


def test_bang_doi_chieu_suy_tu_dockerfile_chu_khong_chep_tay():
    """Chép tay một bảng thứ hai là mở đường cho nó trôi (CLAUDE.md §6)."""
    ma = _ma_lenh(_APPLY)
    assert "nginx/Dockerfile" in ma, (
        "cổng nội dung phải suy danh sách tệp TỪ `nginx/Dockerfile`; một bảng "
        "chép tay sẽ canh hụt đúng tệp mà `COPY` mới thêm"
    )


def test_tap_anh_nen_suy_tu_FROM_chu_khong_chep_tay():
    """Danh sách script của ảnh nền KHÔNG được đóng cứng trong script.

    Bốn script ấy đổi theo mỗi lần nâng `nginx:<ver>`-alpine; một danh sách chép
    tay sẽ im lặng sai ngay lần nâng đầu tiên. Cách duy nhất còn đúng về sau là
    hỏi CHÍNH ảnh nền, và suy tên ảnh nền từ dòng `FROM` của cùng Dockerfile.
    """
    ma = _ma_lenh(_APPLY)
    assert "_anh_nen" in ma and "FROM" in ma, (
        "cổng chiều ngược phải suy ảnh nền từ dòng `FROM` của nginx/Dockerfile"
    )
    assert "docker image inspect" in ma, (
        "phải hỏi `docker image inspect` trước khi `docker run` ảnh nền — nếu "
        "không, một tag vắng mặt sẽ khiến cổng đi KÉO TỪ MẠNG giữa lúc deploy"
    )
    for ten in ("10-listen-on-ipv6", "15-local-resolvers", "20-envsubst", "30-tune-worker"):
        assert ten not in ma, (
            f"script đóng cứng tên tệp của ảnh nền ('{ten}') — danh sách ấy sẽ "
            "trôi ngay lần nâng nginx kế tiếp"
        )


def test_cong_noi_dung_di_CA_HAI_CHIEU():
    """Chiều xuôi chỉ duyệt tệp CÒN tồn tại ở nguồn ⇒ mù với tệp đã bị xoá."""
    ma = _ma_lenh(_APPLY)
    assert "MỒ CÔI" in ma, (
        "không thấy nhánh chiều ngược (ảnh → nguồn): một template bị xoá khỏi "
        "cây mà còn trong ảnh vẫn được envsubst render và nginx include"
    )
    assert "_MOC_LIET_KE" in ma, (
        "phép liệt kê phải kết bằng một mốc — đầu ra cụt mà rc=0 trông y hệt "
        "một danh sách sạch"
    )


def test_tap_thu_muc_soi_KHONG_CO_LAI_khi_mot_COPY_bien_mat():
    """Suy tập thư mục CHỈ từ Dockerfile hiện tại là một điểm mù.

    Xoá hẳn một dòng `COPY` thì thư mục đích của nó rơi khỏi tập soi, và tệp cũ
    trong ảnh (chưa dựng lại) vẫn được entrypoint render/thi hành. Tập phải là
    HỢP với thư mục đọc từ lịch sử build của chính ảnh đang chạy.
    """
    ma = _ma_lenh(_APPLY)
    assert "docker history" in ma, (
        "cổng không đọc lịch sử build của ảnh ⇒ không lấy lại được tập thư mục "
        "của một `COPY` vừa bị xoá khỏi Dockerfile"
    )
    assert "_dich_copy_trong_lich_su" in ma
    for duong in ("/etc/nginx/templates", "/docker-entrypoint.d"):
        assert f'"{duong}"' not in ma and f"'{duong}'" not in ma, (
            f"đóng cứng thư mục runtime '{duong}' trong script — tập thư mục "
            "phải suy ra, không chép tay"
        )


def test_ADD_bi_tu_choi_vi_cong_khong_mo_hinh_hoa_duoc():
    """`ADD` ghi vào ảnh y như `COPY`; bỏ qua im lặng là một đường vòng."""
    ma = _ma_lenh(_APPLY)
    assert re.search(r"ADD\[\[:space:\]\]|ADD\[\[:space:", ma) or "lệnh ADD" in ma, (
        "cổng không từ chối `ADD` — một `ADD templates/ …` sẽ đi vòng qua toàn "
        "bộ phép đối chiếu mà không ai thấy"
    )


# --- Ba ca kiểm chạy thật, với `docker` GIẢ --------------------------------
# Không đụng nginx thật, không build gì: stub chỉ hiểu đúng những lệnh mà
# `nginx-apply.sh` + `nginx-verify.sh` gọi, và mọi hành vi được lái bằng biến
# môi trường — nên MỖI CA VI PHẠM ĐÚNG MỘT BẤT BIẾN (CLAUDE.md §3).

# Mốc kết của phép liệt kê. ĐỌC TỪ chính `scripts/nginx-apply.sh`: chép tay một
# bản thứ hai ở đây thì ngày script đổi mốc, stub sẽ lặng lẽ trả một danh sách
# mà script coi là CỤT — và mọi ca full-run đỏ vì một lý do không ai đoán ra.
_m_moc = re.search(r"^_MOC_LIET_KE='([^']+)'", _ma_lenh(_APPLY), re.M)
assert _m_moc, "không đọc được `_MOC_LIET_KE` từ scripts/nginx-apply.sh"
_MOC_LIET_KE_STUB = _m_moc.group(1)


# --- LÕI dùng chung của hai `docker` GIẢ -----------------------------------
# Đoạn bash dưới đây mô hình hoá ĐÚNG những lệnh mà cổng NỘI DUNG (G1) và cổng
# ĐỒNG NHẤT (G2) của `scripts/nginx-apply.sh` gọi: `inspect -f {{.Image}}`,
# `image inspect`, `history`, `exec … sha256sum`, `exec … sh -c 'find …'`, và
# `run … __QLTS_HET__` trên ảnh nền.
#
# Vì sao MỘT bản: `nginx-apply.sh` nay có HAI người gọi được kiểm ở tệp này —
# các ca chạy thẳng script (`_chay_apply`) và các ca chạy trọn `setup-ssl.sh`
# (`_chay_setup_ssl`, Step 5 gọi thật sang nginx-apply). Hai bản mô phỏng sẽ
# trôi khỏi nhau, và bản KHÔNG có ca đối chứng sẽ trôi trước (CLAUDE.md §7).
#
# Hàm chỉ `exit` khi nó thật sự mô hình hoá được lệnh; mọi thứ khác rơi xuống
# phần THÂN riêng của từng sân khấu (ngữ nghĩa `compose ps`, các cần gạt
# build/pull/certbot) — những thứ vốn khác nhau và phải khác nhau.
_LOI_STUB_ANH = r"""
_qlts_mo_hinh_anh() {
  local _cid_ngx="${STUB_CID_NGINX:-ngx22222}"
  local _fmt _cid _a _last _p _f _d _t
  case "${1:-}" in
  inspect)
    shift
    _fmt=""; _cid=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -f|--format) _fmt="$2"; shift 2 ;;
        *) _cid="$1"; shift ;;
      esac
    done
    case "$_fmt" in
      *index*IPAddress*)  echo "172.30.0.9" ;;
      *Networks*)         echo "qltsstub_default" ;;
      *State.Status*)     echo "${STUB_STATUS:-running}" ;;
      *State.Health*)     echo "${STUB_HEALTH:-healthy}" ;;
      *State.Running*)    echo "${STUB_RUNNING:-true}" ;;
      *State.ExitCode*)   echo "0" ;;
      *Config.Image*)     echo "qlts-nginx:local" ;;
      *.Image*)
        if [ "$_cid" = "$_cid_ngx" ]; then
          [ -n "${STUB_ANH_NGINX+x}" ] || exit "${STUB_INSPECT_ANH_RC:-0}"
          printf '%s\n' "$STUB_ANH_NGINX"
        else
          [ -n "${STUB_ANH_CANDIDATE+x}" ] || exit "${STUB_INSPECT_ANH_RC:-0}"
          printf '%s\n' "$STUB_ANH_CANDIDATE"
        fi
        ;;
    esac
    exit 0 ;;
  image)
    exit "${STUB_NEN_CO_RC:-0}" ;;
  history)
    # history --no-trunc --format '{{.CreatedBy}}' <ảnh>
    for _a in "$@"; do _last="$_a"; done
    if [ "$_last" = "${STUB_NEN_REF:?stub thiếu STUB_NEN_REF}" ]; then
      [ "${STUB_LS_NEN_RC:-0}" = "0" ] || exit "${STUB_LS_NEN_RC}"
      cat "${STUB_LS_NEN:?}"
    else
      [ "${STUB_LS_ANH_RC:-0}" = "0" ] || exit "${STUB_LS_ANH_RC}"
      cat "${STUB_LS_ANH:?}"
    fi
    exit 0 ;;
  exec)
    shift
    _cid="$1"; shift
    case "${1:-}" in
      sha256sum)
        _p="$2"
        [ "${STUB_EXEC_RC:-0}" = "0" ] || exit "${STUB_EXEC_RC}"
        _f="${STUB_ANH_TREE:?stub thiếu STUB_ANH_TREE}$_p"
        [ -f "$_f" ] || exit 1
        printf '%s  %s\n' "$(sha256sum "$_f" | cut -d' ' -f1)" "$_p"
        exit 0 ;;
      sh)
        [ "${STUB_LIET_KE_RC:-0}" = "0" ] || exit "${STUB_LIET_KE_RC}"
        shift 3
        shift
        for _d in "$@"; do
          find "${STUB_ANH_TREE:?}$_d" -type f 2>/dev/null | sed "s#^${STUB_ANH_TREE}##"
        done
        [ "${STUB_LIET_KE_KHONG_MOC:-0}" = "1" ] || echo "@MOC@"
        exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  run)
    if printf '%s' "$*" | grep -q '@MOC@'; then
      [ "${STUB_NEN_RC:-0}" = "0" ] || exit "${STUB_NEN_RC}"
      for _t in ${STUB_NEN_TEP:-}; do echo "$_t"; done
      [ "${STUB_NEN_KHONG_MOC:-0}" = "1" ] || echo "@MOC@"
      exit 0
    fi
    exit "${STUB_RUN_RC:-0}" ;;
  esac
}
"""

# Đầu tệp chung: MỘT dòng nhật ký, tiền tố cấu hình được.
#
# Hai sân khấu đọc nhật ký theo hai định dạng đã có sẵn assertion bám vào —
# `_chay_apply` đọc các dòng `docker …`, còn `_lat_lenh_compose`/`_vt_lenh` của
# nhóm setup-ssl đọc các dòng KHÔNG tiền tố (`compose …`). Nên tiền tố là tham
# số, chứ không phải cái cớ để đi sửa hàng loạt assertion cho khớp stub.
#
# Xuống dòng trong argv bị ÉP thành khoảng trắng: `nginx-verify.sh` truyền cả
# một script `sh -c '...'` nhiều dòng làm tham số, và nếu ghi nguyên văn thì
# MỘT lệnh hoá ra ba chục dòng nhật ký — mọi phép so VỊ TRÍ sẽ lệch theo.
_DAU_STUB_DOCKER = r"""#!/usr/bin/env bash
_L="${QLTS_STUB_LOG:-/dev/null}"
printf '%s\n' "@TIEN_TO@${*//$'\n'/ }" >> "$_L"
"""


def _ma_stub_docker(tien_to: str, than: str) -> str:
    """Ghép một `docker` giả: nhật ký + LÕI G1/G2 dùng chung + thân riêng."""
    return (
        _DAU_STUB_DOCKER.replace("@TIEN_TO@", tien_to)
        + _LOI_STUB_ANH.replace("@MOC@", _MOC_LIET_KE_STUB)
        + '_qlts_mo_hinh_anh "$@"\n'
        + than
    )


# Thân RIÊNG của sân khấu `nginx-apply.sh` chạy thẳng: ngữ nghĩa `compose ps`
# đơn giản (candidate và nginx luôn tồn tại), mọi lệnh compose khác lái bằng
# `STUB_COMPOSE_RC`.
_THAN_STUB_NGX = r"""
_cid_cand="${STUB_CID_CANDIDATE:-cand1111}"
_cid_ngx="${STUB_CID_NGINX:-ngx22222}"
case "${1:-}" in
  compose)
    shift
    _sub=""; _args=()
    while [ $# -gt 0 ]; do
      case "$1" in
        -f|--env-file|-p|--profile) shift 2; continue ;;
        -*) shift; continue ;;
        *) _sub="$1"; shift; _args=("$@"); break ;;
      esac
    done
    case "$_sub" in
      ps)
        _svc=""
        for _a in "${_args[@]}"; do case "$_a" in -*) ;; *) _svc="$_a" ;; esac; done
        case "$_svc" in
          nginx-candidate) echo "$_cid_cand" ;;
          nginx)           echo "$_cid_ngx" ;;
        esac
        exit 0 ;;
      *) exit "${STUB_COMPOSE_RC:-0}" ;;
    esac
    ;;
esac
exit 0
"""

_STUB_DOCKER_NGX = _ma_stub_docker("docker ", _THAN_STUB_NGX)

# Ảnh sha256 giả — chỉ cần ĐÚNG DẠNG, vì đó chính là thứ cổng đồng nhất thẩm định.
_ANH_A = "sha256:" + "1" * 64
_ANH_B = "sha256:" + "2" * 64

# Bảng COPY KỲ VỌNG, khai tường minh ở đây để đối chiếu với bảng mà
# `nginx-apply.sh` TỰ SUY từ `nginx/Dockerfile`. Hai bản này CỐ Ý độc lập: bản
# trong script là thứ chạy thật, bản ở đây là thứ ta khẳng định nó phải ra.
_DUONG_TRONG_ANH = {
    "nginx.conf": "/etc/nginx/nginx.conf",
    "templates/default.conf.template": "/etc/nginx/templates/default.conf.template",
    "bootstrap/nginx.conf": "/etc/nginx/nginx-bootstrap.conf",
    "bootstrap/default.conf.template":
        "/etc/nginx/templates-bootstrap/default.conf.template",
    "docker-entrypoint.d/10-qlts-kiem-bien.sh":
        "/docker-entrypoint.d/10-qlts-kiem-bien.sh",
    "docker-entrypoint.d/25-qlts-kiem-ban-render.sh":
        "/docker-entrypoint.d/25-qlts-kiem-ban-render.sh",
}

# Tệp của ẢNH NỀN `nginx:1.27-alpine` trong các thư mục đích — ĐO THẬT
# (`docker run --rm --entrypoint sh nginx:1.27-alpine -c 'find …'`, 22-09-2026),
# không đoán theo tên: hai trong bốn cái tên không phải thứ người ta hay đoán
# (`15-local-resolvers.envsh` chứ không phải `.sh`; `10-listen-on-ipv6-by-default.sh`
# chứ không phải `10-listen-on-ipv6-on-ipv4.sh`). `/etc/nginx/templates` và
# `/etc/nginx/templates-bootstrap` KHÔNG tồn tại trong ảnh nền — cũng đã đo.
_TEP_ANH_NEN = [
    "/docker-entrypoint.d/10-listen-on-ipv6-by-default.sh",
    "/docker-entrypoint.d/15-local-resolvers.envsh",
    "/docker-entrypoint.d/20-envsubst-on-templates.sh",
    "/docker-entrypoint.d/30-tune-worker-processes.sh",
]

# Đuôi lịch sử của ảnh nền. Không cần giống `nginx:1.27-alpine` từng dòng — thứ
# ca kiểm đo là HỢP ĐỒNG: đuôi phải trùng khít, phần đầu là của QLTS. Cố ý có một
# `COPY … /` để chứng minh cổng không đi quét cả gốc hệ tệp.
_LICH_SU_NEN = [
    'CMD ["nginx" "-g" "daemon off;"]',
    'ENTRYPOINT ["/docker-entrypoint.sh"]',
    "COPY 20-envsubst-on-templates.sh /docker-entrypoint.d # buildkit",
    "COPY docker-entrypoint.sh / # buildkit",
    "ADD alpine-minirootfs.tar.gz / # buildkit",
]

_bo_qua_neu_khong_chay_duoc_bash = pytest.mark.skipif(
    _BASH is None or shutil.which("sha256sum") is None,
    reason="cần bash chạy được và `sha256sum` để thi hành thật scripts/nginx-apply.sh",
)


def _from_cua(dockerfile: Path) -> str:
    dong = [
        d.strip() for d in _doc(dockerfile).splitlines()
        if d.strip().upper().startswith("FROM ")
    ]
    assert len(dong) == 1, f"{dockerfile} phải có đúng MỘT dòng FROM; thấy {len(dong)}"
    return dong[0].split()[1]


def _dung_cay_anh(
    goc_nginx: Path, san: Path, them: dict[str, str] | None = None
) -> Path:
    """Cây "ảnh" phản chiếu đường dẫn TUYỆT ĐỐI trong container, dựng từ
    `goc_nginx` theo đúng bảng `_DUONG_TRONG_ANH`.

    ``them``: các tệp PHỤ được tạo ở NGUỒN rồi chụp vào ảnh — để ca "xoá khỏi
    nguồn, giữ trong ảnh" có thứ để xoá mà không phải đụng template thật. Chỉ
    sân khấu sao chép cây nguồn mới được truyền tham số này.

    Cây ảnh CỐ Ý mang cả bốn tệp của ảnh nền: thiếu chúng thì phép trừ tập nền
    không bao giờ được thi hành, và ca đối chứng sẽ xanh vì một lý do sai.
    """
    anh = san / "anh"
    ban_do = dict(_DUONG_TRONG_ANH)
    for rel, dich in (them or {}).items():
        (goc_nginx / rel).parent.mkdir(parents=True, exist_ok=True)
        (goc_nginx / rel).write_text(
            f"# tệp phụ của ca kiểm: {rel}\n", encoding="utf-8", newline="\n"
        )
        ban_do[rel] = dich
    for nguon, dich in ban_do.items():
        d = anh / dich.lstrip("/")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(goc_nginx / nguon, d)
    for dich in _TEP_ANH_NEN:
        d = anh / dich.lstrip("/")
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text("# script cua anh nen\n", encoding="utf-8", newline="\n")
    return anh


def _ghi_lich_su_anh(goc_nginx: Path, san: Path) -> None:
    """Lịch sử build giả, đúng hình dạng `docker history --format '{{.CreatedBy}}'`
    (mới nhất TRƯỚC, phần của ảnh nền nằm ở ĐUÔI).

    Sinh từ chính Dockerfile của sân khấu, nên nó phản ánh "ảnh đã được dựng từ
    Dockerfile lúc này" — ca kiểm nào sửa Dockerfile SAU khi dựng sân khấu sẽ
    tạo đúng độ lệch cần đo.
    """
    (san / "lichsu-nen.txt").write_text(
        "\n".join(_LICH_SU_NEN) + "\n", encoding="utf-8", newline="\n"
    )
    dong_copy = [
        d.strip()
        for d in (goc_nginx / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if d.strip().startswith("COPY ")
    ]
    rieng = (
        ["RUN /bin/sh -c chmod +x /docker-entrypoint.d/*.sh # buildkit"]
        + [f"{d} # buildkit" for d in reversed(dong_copy)]
        + ["RUN /bin/sh -c rm -f /etc/nginx/conf.d/*.conf # buildkit"]
    )
    (san / "lichsu-anh.txt").write_text(
        "\n".join(rieng + _LICH_SU_NEN) + "\n", encoding="utf-8", newline="\n"
    )


def _bien_mo_hinh_anh(goc_nginx: Path, san: Path) -> dict[str, str]:
    """Biến môi trường mà LÕI stub cần để mô hình hoá G1/G2.

    `STUB_NEN_REF` suy từ chính Dockerfile của sân khấu: đóng cứng
    `nginx:1.27-alpine` ở đây thì lần nâng nginx kế tiếp sẽ làm stub trả nhầm
    lịch sử mà không ai thấy.
    """
    return {
        "STUB_ANH_TREE": str(san / "anh").replace("\\", "/"),
        "STUB_NEN_TEP": " ".join(_TEP_ANH_NEN),
        "STUB_NEN_REF": _from_cua(goc_nginx / "Dockerfile"),
        "STUB_LS_NEN": str(san / "lichsu-nen.txt").replace("\\", "/"),
        "STUB_LS_ANH": str(san / "lichsu-anh.txt").replace("\\", "/"),
    }


def _san_khau_ngx(
    tmp_path: Path, them: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """Sân khấu cô lập: bản sao `scripts/` + `nginx/`, `docker` giả, và một
    cây "ảnh" phản chiếu đường dẫn tuyệt đối trong container.
    """
    san = tmp_path / "san"
    repo = san / "repo"
    (san / "bin").mkdir(parents=True)
    shutil.copytree(_GOC / "scripts", repo / "scripts")
    shutil.copytree(_THU_MUC_NGINX, repo / "nginx")

    stub = san / "bin" / "docker"
    stub.write_text(_STUB_DOCKER_NGX, encoding="utf-8", newline="\n")
    stub.chmod(0o755)

    anh = _dung_cay_anh(repo / "nginx", san, them)
    _ghi_lich_su_anh(repo / "nginx", san)
    return repo, anh


def _chay_apply(repo: Path, anh: Path, **bien: str) -> subprocess.CompletedProcess:
    nhat_ky = repo.parent / "lenh.log"
    nhat_ky.write_text("", encoding="utf-8")
    moi_truong = {
        **os.environ,
        "MSYS_NO_PATHCONV": "1",
        "PATH": str(repo.parent / "bin") + os.pathsep + os.environ.get("PATH", ""),
        **_bien_mo_hinh_anh(repo / "nginx", anh.parent),
        "QLTS_STUB_LOG": str(nhat_ky).replace("\\", "/"),
        "QLTS_COMPOSE_ENV_FILE": "khong-ton-tai.env",
        **bien,
    }
    return subprocess.run(
        [_BASH, str(repo / "scripts" / "nginx-apply.sh"), "nginx-test.local"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=moi_truong, cwd=str(repo),
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca2_anh_da_chua_template_moi_thi_XANH(tmp_path):
    """Ca ĐỐI CHỨNG. Thiếu nó thì mọi ca đỏ dưới đây có thể đỏ vì lý do khác.

    Khẳng định thêm: cổng đã soi ĐÚNG SÁU tệp mà `nginx/Dockerfile` COPY, ở
    đúng đường dẫn trong container — tức bảng script tự suy khớp bảng kỳ vọng.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    assert kq.returncode == 0, f"ca đối chứng phải XANH:\n{kq.stdout}\n{kq.stderr}"

    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    da_soi = {
        d.split("sha256sum ", 1)[1].strip()
        for d in nhat_ky.splitlines()
        if " exec " in d and "sha256sum " in d
    }
    assert da_soi == set(_DUONG_TRONG_ANH.values()), (
        "bảng mà nginx-apply.sh suy từ nginx/Dockerfile KHÔNG khớp bảng kỳ vọng.\n"
        f"  script soi : {sorted(da_soi)}\n"
        f"  kỳ vọng    : {sorted(_DUONG_TRONG_ANH.values())}"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca1_template_sua_ma_chua_build_thi_DO(tmp_path):
    """Bất biến: bản trong container PHẢI khớp nguồn sẽ được áp.

    Ảnh được chụp TRƯỚC, rồi nguồn trôi đi — đúng chuỗi "sửa template rồi chạy
    thẳng nginx-apply.sh". Mọi phép đo hành vi ở đây đều xanh (stub `docker run`
    trả 0), nên ca này CHỈ có thể đỏ vì cổng nội dung.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    t = repo / "nginx" / "templates" / "default.conf.template"
    t.write_text(_doc(t) + "\n# dòng mới chưa vào ảnh\n", encoding="utf-8", newline="")

    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"template đã trôi mà cổng vẫn XANH:\n{ra}"
    assert "LỆCH" in ra, f"không nói ra tệp nào lệch:\n{ra}"
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca3_khong_doc_duoc_checksum_thi_DO_chu_khong_phai_DAT(tmp_path):
    """Bất biến: lỗi ĐỌC không bao giờ được tính là "đạt" (fail-closed).

    `docker exec sha256sum` hỏng ⇒ phía container không có giá trị. Bản fail-open
    tự nhiên ("không đọc được thì không có gì để so") làm ca này xanh trong khi
    KHÔNG một tệp nào được đối chiếu.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(
        repo, anh, STUB_EXEC_RC="1",
        STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A,
    )
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"không đọc được checksum mà cổng vẫn XANH:\n{ra}"
    assert "không đọc được checksum" in ra, f"thông điệp không nói đúng ca:\n{ra}"
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca6_template_xoa_khoi_nguon_ma_con_trong_anh_thi_DO(tmp_path):
    """Bất biến CHIỀU NGƯỢC: ảnh không được giữ tệp cấu hình QLTS đã bị xoá.

    Đây là ca mà chiều xuôi KHÔNG THỂ thấy: vòng duyệt đi qua các tệp còn tồn
    tại ở nguồn, nên một tệp đã xoá thì đơn giản là không được hỏi tới. Trong
    khi đó entrypoint vẫn envsubst nó thành `/etc/nginx/conf.d/*` và nginx vẫn
    `include`. Mọi phép đo hành vi vẫn xanh.
    """
    them = {"templates/mo-coi.conf.template": "/etc/nginx/templates/mo-coi.conf.template"}
    repo, anh = _san_khau_ngx(tmp_path, them=them)
    # Chụp ảnh xong mới xoá khỏi nguồn — đúng chuỗi "gỡ template rồi chạy thẳng".
    (repo / "nginx" / "templates" / "mo-coi.conf.template").unlink()

    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"tệp mồ côi trong ảnh mà cổng vẫn XANH:\n{ra}"
    assert "MỒ CÔI" in ra and "mo-coi.conf.template" in ra, (
        f"không nói ra tệp mồ côi nào:\n{ra}"
    )
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca9_xoa_HAN_mot_lenh_COPY_khoi_Dockerfile_thi_DO(tmp_path):
    """Bất biến: tập thư mục cần soi KHÔNG ĐƯỢC CO LẠI khi một `COPY` biến mất.

    Khác hẳn ca6. Ca6 xoá TỆP NGUỒN trong khi dòng `COPY templates/ …` vẫn còn,
    nên thư mục đích vẫn nằm trong tập soi. Ở đây xoá HẲN dòng `COPY` — thư mục
    đích rơi khỏi tập suy từ Dockerfile, và một cổng chỉ nhìn Dockerfile hiện
    tại sẽ KHÔNG BAO GIỜ nhìn vào đó nữa, trong khi ảnh (chưa dựng lại) vẫn giữ
    template cũ và entrypoint vẫn render nó.

    Tập thư mục cũ được lấy lại từ lịch sử build của chính ảnh đang chạy.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    df = repo / "nginx" / "Dockerfile"
    than = _doc(df)
    moc = "COPY templates/ /etc/nginx/templates/"
    assert than.count(moc) == 1, "Dockerfile đã đổi — ca kiểm đang neo vào dòng không còn"
    # Ảnh KHÔNG dựng lại: `lichsu-anh.txt` giữ nguyên dòng COPY này.
    df.write_text(than.replace(moc + "\n", ""), encoding="utf-8", newline="")

    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"xoá hẳn một lệnh COPY mà cổng vẫn XANH:\n{ra}"
    assert "MỒ CÔI" in ra and "/etc/nginx/templates/default.conf.template" in ra, (
        f"không nhìn vào thư mục của lệnh COPY vừa bị xoá:\n{ra}"
    )
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca11_xoa_HAN_mot_COPY_dich_TEP_khoi_Dockerfile_thi_DO(tmp_path):
    """Nhánh ANH EM của ca9: đích dạng TỆP, không phải thư mục (CLAUDE.md §6).

    `COPY nginx.conf /etc/nginx/nginx.conf` không kết thúc bằng `/`, nên bản
    chỉ thu thập đích dạng thư mục bỏ nó lại — không thư mục nào để `find`, và
    không ai canh. Xoá HẲN dòng ấy mà dùng ảnh CŨ thì `nginx.conf` của ta vẫn
    nằm trong ảnh và vẫn là cấu hình nginx đang chạy.

    Lưu ý vì sao chiều xuôi KHÔNG bắt được: chiều xuôi chỉ duyệt các dòng COPY
    CÒN TRONG Dockerfile. Xoá dòng thì không còn gì để nó nhắc tới.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    df = repo / "nginx" / "Dockerfile"
    than = _doc(df)
    moc = "COPY nginx.conf /etc/nginx/nginx.conf"
    assert than.count(moc) == 1, "Dockerfile đã đổi — ca kiểm đang neo vào dòng không còn"
    # Ảnh KHÔNG dựng lại: `lichsu-anh.txt` giữ nguyên dòng COPY này.
    df.write_text(than.replace(moc + "\n", ""), encoding="utf-8", newline="")

    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"xoá hẳn một COPY đích-tệp mà cổng vẫn XANH:\n{ra}"
    assert "MỒ CÔI" in ra and "/etc/nginx/nginx.conf" in ra, (
        f"không nhận ra tệp do lệnh COPY vừa bị xoá sinh ra:\n{ra}"
    )
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca12_mot_dong_COPY_hong_XEN_GIUA_lich_su_thi_DO(tmp_path):
    """Bất biến: MỘT dòng COPY không đọc được cũng phải ĐỎ.

    Cố ý KHÔNG dựng ca "mọi dòng đều hỏng" — ca ấy đã bị phép kiểm
    `grep -q '^COPY '` bắt và không chứng minh gì mới. Ở đây các dòng khác vẫn
    hợp lệ, nên phép kiểm tổng thể vẫn qua; chỉ phép từ chối TỪNG DÒNG mới thấy.
    Bỏ qua dòng hỏng = đích của nó không bao giờ vào tập soi.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    ls = repo.parent / "lichsu-anh.txt"
    dong = _doc(ls).splitlines()
    vt = next(i for i, d in enumerate(dong) if d.startswith("COPY templates/"))
    # Dòng COPY CỤT: đúng tiền tố `COPY ` nên qua được grep, nhưng thiếu đích.
    dong.insert(vt, "COPY # buildkit")
    ls.write_text("\n".join(dong) + "\n", encoding="utf-8", newline="\n")

    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"một dòng COPY hỏng mà cổng vẫn XANH:\n{ra}"
    assert "không phân tích được" in ra, f"thông điệp không nói đúng ca:\n{ra}"
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "profile production up -d" not in nhat_ky, (
        "đã đụng tới container ĐANG PHỤC VỤ dù cổng nội dung đã đỏ"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca10_khong_doc_duoc_lich_su_build_thi_DO(tmp_path):
    """Bất biến: KHÔNG xác định được tập thư mục cũ ⇒ ĐỎ, không đoán là rỗng.

    Trả về tập rỗng khi không đọc được lịch sử trông y hệt "ảnh này không COPY
    vào thư mục nào" — và ca sau chính là điểm mù ca9 mô tả.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(
        repo, anh, STUB_LS_ANH_RC="1",
        STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A,
    )
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"không đọc được lịch sử build mà cổng vẫn XANH:\n{ra}"
    assert "lịch sử build" in ra, f"thông điệp không nói đúng ca:\n{ra}"


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca7_danh_sach_tep_CUT_thi_DO_chu_khong_phai_DAT(tmp_path):
    """Bất biến: đầu ra CỤT không được coi là "không có tệp thừa nào".

    `docker run`/`docker exec` có thể trả 0 với đầu ra bị cắt. Một danh sách cụt
    trông y hệt một danh sách sạch — nên phép liệt kê phải kết bằng MỘT MỐC, và
    thiếu mốc là ĐỎ.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(
        repo, anh, STUB_NEN_KHONG_MOC="1",
        STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A,
    )
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"danh sách cụt mà cổng vẫn XANH:\n{ra}"
    assert "CỤT" in ra, f"thông điệp không nói đúng ca:\n{ra}"


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca8_anh_nen_vang_mat_cuc_bo_thi_DO_va_KHONG_keo_mang(tmp_path):
    """Bất biến: không đo được tập nền ⇒ ĐỎ, và không đi kéo ảnh từ mạng.

    `docker run` trên một tag vắng mặt sẽ tự pull — biến cổng thành phụ thuộc
    mạng giữa lúc deploy. Nên phải hỏi `docker image inspect` TRƯỚC và từ chối.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(
        repo, anh, STUB_NEN_CO_RC="1",
        STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_A,
    )
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"ảnh nền vắng mặt mà cổng vẫn XANH:\n{ra}"
    assert "ảnh nền" in ra, f"thông điệp không nói đúng ca:\n{ra}"
    nhat_ky = (repo.parent / "lenh.log").read_text(encoding="utf-8")
    assert "image inspect" in nhat_ky, (
        "cổng không hỏi `docker image inspect` trước — `docker run` sẽ tự pull"
    )
    assert not re.search(r"^docker run .*__QLTS_HET__", nhat_ky, re.M), (
        "đã gọi `docker run` trên ảnh nền dù nó vắng mặt cục bộ (⇒ pull từ mạng)"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca4_nginx_sau_cutover_chay_anh_KHAC_candidate_thi_DO(tmp_path):
    """Bất biến: container đang phục vụ phải chạy ĐÚNG bản ảnh đã chứng minh.

    Đây là ca mà `{{.Config.Image}}` không thể thấy: hai service dùng chung tag
    `qlts-nginx:local`, nên so theo tên:tag là so một hằng số với chính nó.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(repo, anh, STUB_ANH_CANDIDATE=_ANH_A, STUB_ANH_NGINX=_ANH_B)
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"nginx chạy ảnh khác mà script vẫn tuyên bố đạt:\n{ra}"
    assert _ANH_A in ra and _ANH_B in ra, (
        f"thông điệp không nêu cả hai image id để đối chiếu:\n{ra}"
    )


@_bo_qua_neu_khong_chay_duoc_bash
def test_ca5_image_id_khong_phai_ID_bat_bien_thi_DO(tmp_path):
    """Bất biến: giá trị đọc được phải ĐÚNG DẠNG image id, không chỉ khác rỗng.

    `docker inspect` trả `qlts-nginx:local` (dạng của `{{.Config.Image}}`) cho
    CẢ HAI container. Bản không thẩm định dạng sẽ thấy hai giá trị BẰNG NHAU và
    tuyên bố đạt — một giá trị gộp hai ca ngược nhau.
    """
    repo, anh = _san_khau_ngx(tmp_path)
    kq = _chay_apply(
        repo, anh,
        STUB_ANH_CANDIDATE="qlts-nginx:local", STUB_ANH_NGINX="qlts-nginx:local",
    )
    ra = kq.stdout + kq.stderr
    assert kq.returncode != 0, f"image id không phải ID bất biến mà vẫn XANH:\n{ra}"
    assert "image id bất biến" in ra, f"thông điệp không nói đúng ca:\n{ra}"


# ---------------------------------------------------------------------------
# Consumer: không đường/lệnh cũ nào còn sót
# ---------------------------------------------------------------------------

_DUONG_CU = "nginx/conf.d/default.conf.template"


def _cac_script() -> list[Path]:
    thu_muc = _GOC / "scripts"
    return sorted(thu_muc.glob("*.sh")) if thu_muc.is_dir() else []


def test_khong_script_nao_doc_duong_template_cu():
    """Rename template mà quên consumer thì deploy kế tiếp dừng giữa chừng."""
    assert _cac_script(), "không thấy scripts/*.sh — guard này đang xanh vô nghĩa"
    pham = []
    for sh in _cac_script():
        for so, dong in enumerate(_doc(sh).splitlines(), 1):
            if _DUONG_CU in dong and not dong.lstrip().startswith("#"):
                pham.append(f"{sh.relative_to(_GOC)}:{so}")
    assert not pham, f"còn script đọc `{_DUONG_CU}` (đường đã bị rename): {pham}"


def test_deploy_khong_con_render_template_tren_host():
    """Render trên host chính là thứ đẻ ra `default.conf` nằm ngoài git."""
    dong_pham = [
        f"{so}: {d.strip()}"
        for so, d in enumerate(_doc(_DEPLOY).splitlines(), 1)
        if "envsubst" in d and not d.lstrip().startswith("#")
    ]
    assert not dong_pham, (
        "deploy.sh còn `envsubst` render template trên host; entrypoint nginx "
        f"phải là nơi duy nhất render. Dòng: {dong_pham}"
    )


def test_khong_con_nginx_s_reload_o_bat_ky_dau():
    """`nginx -s reload` nạp lại đúng bản render CŨ của chính tiến trình đó."""
    pham = []
    for sh in _cac_script():
        for so, d in enumerate(_doc(sh).splitlines(), 1):
            if "nginx -s reload" in d and not d.lstrip().startswith("#"):
                pham.append(f"{sh.relative_to(_GOC)}:{so}")
    assert not pham, f"còn `nginx -s reload`: {pham}"


# ---------------------------------------------------------------------------
# Lệnh vận hành ĐÃ CHẾT — cấm quay lại, kể cả trong TÀI LIỆU
# ---------------------------------------------------------------------------
#
# Guard cũ chỉ quét `scripts/*.sh`. Nhưng ba cần gạt hỏng nặng nhất của sự cố
# 12-08 không nằm trong script nào cả — chúng nằm trong RUNBOOK, dưới dạng lệnh
# mà người trực gõ tay lúc 2 giờ sáng. Thêm runbook vào `paths:` chỉ khiến CI
# CHẠY; nó không khiến CI BẮT được một lệnh đã chết quay lại.
#
# Quy ước để guard đọc được tài liệu mà không tự bắn vào chân: chỉ soi các dòng
# NẰM TRONG khối ``` và KHÔNG bắt đầu bằng `#`. Muốn nhắc "đừng dùng X" thì viết
# nó thành dòng chú thích hoặc để ngoài khối lệnh.
#
# Van thoát DUY NHẤT: dán `CO-Y-LENH-CHET` ngay trên dòng đó. Nó dành cho các ca
# ĐỐI CHỨNG — bài kiểm cố tình chạy lệnh đã chết để chứng minh nó không làm gì
# (E2E chạy `nginx -s reload` rồi cho thấy `POST /api/admissions/` vẫn 200).
# Van hẹp và ồn ào là có chủ đích: gõ được nó nghĩa là đã phải dừng lại và nghĩ.
_VAN_THOAT = "CO-Y-LENH-CHET"

_LENH_DA_CHET = [
    (
        r"nginx/conf\.d/default\.conf\.template",
        "đường template CŨ — đã chuyển sang nginx/templates/ và nay nằm trong image",
    ),
    (
        r"nginx -s reload",
        "nạp lại đúng bản render CŨ của chính tiến trình đó; `nginx -t` vẫn xanh",
    ),
    (
        r"restart\s+(-\S+\s+)*nginx\b",
        "`restart` tái dùng biến môi trường đã nướng vào container — cần gạt câm",
    ),
    (
        r"restart\s+(-\S+\s+)*backend\b",
        "`env_file` chỉ đọc lúc TẠO container; `restart` giữ ADMISSION_FROZEN cũ. "
        "Dùng `up -d --no-deps --wait backend`",
    ),
    (
        r"envsubst[^\n]*>\s*nginx/",
        "render trên host chính là thứ đẻ ra tệp ngoài git đã làm site chết",
    ),
    (
        r"cp\s+-r\s+nginx_conf_backup",
        "khôi phục vào một thư mục không còn được mount — im lặng không làm gì",
    ),
]

_TAI_LIEU_VAN_HANH = [
    "Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md",
    "Documents/PRODUCTION_DEPLOY_GUIDE.md",
    "tests-e2e/nginx-packaging/README.md",
]


def _dong_lenh_trong_tai_lieu(duong: Path) -> list[tuple[int, str]]:
    """Các dòng NẰM TRONG khối ``` và không phải chú thích."""
    ra: list[tuple[int, str]] = []
    trong_khoi = False
    for so, dong in enumerate(_doc(duong).splitlines(), 1):
        if dong.lstrip().startswith("```"):
            trong_khoi = not trong_khoi
            continue
        if trong_khoi and dong.strip() and not dong.lstrip().startswith("#"):
            if _VAN_THOAT in dong:
                continue
            ra.append((so, dong))
    return ra


def test_tai_lieu_van_hanh_khong_con_lenh_da_chet():
    """Ba cần gạt hỏng nặng nhất của 12-08 nằm trong RUNBOOK, không trong script.

    Chúng đều "thành công": `nginx -t` in *syntax is ok*, `reload` và `restart`
    trả 0 — trong khi `POST /api/admissions/` vẫn 200. Đã tái hiện đúng như vậy.
    Nên tài liệu vận hành phải bị canh y như mã nguồn.
    """
    da_soi = 0
    pham = []
    for ten in _TAI_LIEU_VAN_HANH:
        d = _GOC / ten
        if not d.is_file():
            continue
        da_soi += 1
        for so, dong in _dong_lenh_trong_tai_lieu(d):
            for mau, ly_do in _LENH_DA_CHET:
                if re.search(mau, dong):
                    pham.append(f"{ten}:{so}: {dong.strip()[:90]}  ← {ly_do}")
    assert da_soi, "không soi được tài liệu vận hành nào — guard đang xanh vô nghĩa"
    assert not pham, "còn lệnh vận hành đã chết trong tài liệu:\n  " + "\n  ".join(pham)


# Script chạm PRODUCTION. Luật ghim `-f` chỉ áp cho nhóm này.
#
# CỐ Ý loại `import-prod-to-dev.sh` và `fe-check.sh`: chúng làm việc trên stack
# DEV và *cần* `docker-compose.override.yml` được nạp — ghim `-f` vào đó là bẻ
# gãy chúng. Một luật áp bừa lên mọi script sẽ hoặc bị tắt đi, hoặc bị lách
# bằng ngoại lệ rải rác; danh sách tường minh thì đọc được và cãi được.
_SCRIPT_PRODUCTION = [
    "deploy.sh",
    "setup-ssl.sh",
    "nginx-apply.sh",
    "nginx-verify.sh",
    "phase3-pre-deploy-snapshot.sh",
    "rollback-preflight.sh",
]


def _co_lenh_compose(dong: str) -> bool:
    """Dòng TÀI LIỆU có gọi `docker compose` trực tiếp.

    Chỉ dùng cho tài liệu vận hành (.md), nơi mỗi dòng đã là một lệnh trần.
    Mã shell thật đi qua `_lenh_compose_trong_script` — xem hợp đồng ở đó.
    """
    if "docker compose" not in dong:
        return False
    # `command -v docker compose` là phép kiểm cài đặt, không phải lời gọi.
    if "command -v docker compose" in dong:
        return False
    return True


# ===========================================================================
# Bộ phân loại ngữ cảnh cho MÃ SHELL — hợp đồng tường minh
# ===========================================================================
# Bản trước hỏi `"docker compose" in dong` rồi thôi. Nó soi cả dòng THÔNG BÁO,
# và chưa đỏ lần nào chỉ vì văn bản của những dòng ấy TÌNH CỜ có sẵn
# `-f docker-compose.yml` — tức guard đã luôn soi nhầm, chỉ là chưa gặp dòng
# thông báo nào thiếu cờ.
#
# CỐ Ý KHÔNG ghi số lượng hay danh sách số dòng ở đây: `deploy.sh` còn đổi, mà
# một con số trong chú thích thì âm thầm cũ đi không ai biết. Bất biến được
# neo bằng TEST (xem `test_guard_compose_van_thay_du_hai_loai_o_deploy_sh`),
# không bằng câu chữ.
#
# HỢP ĐỒNG (dựa trên HÌNH DẠNG cú pháp, không dựa trên số dòng / tên hàm /
# câu chữ tiếng Việt cụ thể):
#
#   A. Ngữ cảnh MÃ (ngoài mọi trích dẫn, ngoài chú thích) ⇒ LÀ LỆNH.
#      Bao gồm: gọi trực tiếp · sau `if !` · trong `$( )` (kể cả khi `$( )`
#      nằm bên trong nháy kép) · gán mảng `X=(docker compose …)`.
#      Ngoại lệ duy nhất: `command -v docker compose` — phép kiểm cài đặt.
#
#   B. Trong CHUỖI TRÍCH DẪN — nháy kép HOẶC NHÁY ĐƠN, cùng một luật ⇒ chỉ
#      tính là "lệnh in cho operator / gán vào biến" khi có hình dạng
#      nhãn-rồi-lệnh mà người ta copy-paste được:
#        B1. KHÔNG nằm trong ngoặc đơn còn mở bên trong chuỗi ấy
#            (dấu ngoặc = lời chú thích phụ, không phải lệnh để chạy);
#        B2. đứng ở ĐẦU chuỗi (bỏ qua khoảng trắng) HOẶC ngay sau `": "`.
#      `error "… (docker compose ps -aq thất bại)"` trượt CẢ HAI: nó nằm trong
#      ngoặc, và không ở đầu chuỗi cũng không sau dấu hai chấm.
#
#      🔴 NHÁY ĐƠN PHẢI ĐI CHUNG LUẬT VỚI NHÁY KÉP. Bản trước bỏ qua toàn bộ
#      nháy đơn và vì thế FAIL-OPEN với cả wrapper lẫn gợi ý operator:
#      `DC='docker compose up -d'`, `COMPOSE='docker compose ps'`,
#      `log 'docker compose up -d'`, `echo 'docker compose ps'` đều lọt sạch.
#      Với shell thì `'…'` và `"…'` chỉ khác ở phép bung biến — khác biệt đó
#      KHÔNG liên quan gì tới việc chuỗi ấy có phải một lệnh hay không, nên
#      lấy nó làm cớ để miễn kiểm là tự mở một đường vòng.
#
#   C. Chú thích ⇒ bỏ qua.
#
#   D. FAIL-CLOSED: cú pháp mà bộ phân loại KHÔNG mô hình hoá (heredoc,
#      ANSI-C `$'…'`) mà lại chứa `docker compose` ⇒ trả về dạng UNSUPPORTED
#      để guard ĐỎ, tuyệt đối không im lặng coi là prose an toàn.
#
# Nếu ai đó cần nới hợp đồng, sửa ở đây và thêm ca hồi quy — đừng thêm ngoại lệ
# theo số dòng.
_NGU_CANH_MA = "ma"
_NGU_CANH_NHAY_KEP = "nhay_kep"
_NGU_CANH_NHAY_DON = "nhay_don"
_NGU_CANH_CHU_THICH = "chu_thich"


def _ngu_canh_tung_ky_tu(noi_dung: str) -> list[str]:
    """Gắn nhãn ngữ cảnh cho TỪNG ký tự của toàn bộ nội dung script.

    Nhận cả tệp chứ không nhận từng dòng: chuỗi và `$( )` đều có thể trải nhiều
    dòng, mà một regex "giả vờ hiểu nháy" chỉ đúng với dòng hiện tại là đúng cái
    bẫy đã cắn kho này.
    """
    n = len(noi_dung)
    nhan = [_NGU_CANH_MA] * n
    ngan_xep: list[str] = []          # ngữ cảnh cha khi bước vào `$( )`
    tt = _NGU_CANH_MA
    i = 0
    while i < n:
        c = noi_dung[i]

        if tt == _NGU_CANH_CHU_THICH:
            if c == "\n":
                tt = _NGU_CANH_MA
                nhan[i] = _NGU_CANH_MA
            else:
                nhan[i] = _NGU_CANH_CHU_THICH
            i += 1
            continue

        if tt == _NGU_CANH_NHAY_DON:
            nhan[i] = _NGU_CANH_NHAY_DON
            if c == "'":
                tt = _NGU_CANH_MA
            i += 1
            continue

        # Còn lại: ngữ cảnh MÃ hoặc NHÁY KÉP (hai chỗ duy nhất `$( )` mở được).
        if c == "\\" and i + 1 < n:
            nhan[i] = tt
            nhan[i + 1] = tt
            i += 2
            continue

        if c == "$" and i + 1 < n and noi_dung[i + 1] == "(":
            nhan[i] = nhan[i + 1] = _NGU_CANH_MA
            ngan_xep.append(tt)
            tt = _NGU_CANH_MA
            i += 2
            continue

        if c == ")" and ngan_xep:
            nhan[i] = _NGU_CANH_MA
            tt = ngan_xep.pop()
            i += 1
            continue

        if tt == _NGU_CANH_NHAY_KEP:
            nhan[i] = _NGU_CANH_NHAY_KEP
            if c == '"':
                tt = _NGU_CANH_MA
            i += 1
            continue

        nhan[i] = _NGU_CANH_MA
        if c == '"':
            tt = _NGU_CANH_NHAY_KEP
        elif c == "'":
            tt = _NGU_CANH_NHAY_DON
        elif c == "#" and (i == 0 or noi_dung[i - 1] in " \t\n;&|("):
            tt = _NGU_CANH_CHU_THICH
            nhan[i] = _NGU_CANH_CHU_THICH
        i += 1
    return nhan


def _lat_lenh_ma(noi_dung: str, vt: int) -> str:
    """Lấy nguyên một lệnh từ vị trí `vt`, NỐI các dòng tiếp nối `\\`."""
    ra: list[str] = []
    j, n = vt, len(noi_dung)
    while j < n:
        c = noi_dung[j]
        if c == "\\" and j + 1 < n and noi_dung[j + 1] == "\n":
            ra.append(" ")
            j += 2
            continue
        if c in "\n;":
            break
        ra.append(c)
        j += 1
    return "".join(ra)


def _lat_chuoi(noi_dung: str, nhan: list[str], vt: int) -> tuple[str, int]:
    """Nội dung chuỗi trích dẫn bao quanh `vt`, kèm độ lệch của `vt` trong đó.

    Dùng chung cho nháy kép LẪN nháy đơn: hai loại chỉ khác ở phép bung biến,
    còn câu hỏi "chuỗi này có phải một lệnh không" thì y hệt nhau.
    """
    loai = nhan[vt]
    d = vt
    while d > 0 and nhan[d - 1] == loai:
        d -= 1
    c = vt
    n = len(noi_dung)
    while c < n and nhan[c] == loai:
        c += 1
    return noi_dung[d:c], vt - d


def _la_goi_y_operator(chuoi: str, lech: int) -> bool:
    """Hợp đồng B: chuỗi này có đang IN MỘT LỆNH cho người trực không?"""
    truoc = chuoi[:lech]
    # B1 — nằm trong ngoặc đơn còn mở ⇒ là lời chú thích phụ, không phải lệnh.
    if truoc.count("(") > truoc.count(")"):
        return False
    # B2 — đầu chuỗi (bỏ khoảng trắng) hoặc ngay sau `": "`.
    if truoc.strip() == "":
        return True
    return truoc.endswith(": ")


def _cu_phap_khong_mo_hinh_hoa(noi_dung: str, vt: int) -> str | None:
    """Hợp đồng D: `docker compose` có đang nằm trong cú pháp CHƯA mô hình hoá?

    Trả về tên cú pháp (⇒ UNSUPPORTED, guard phải ĐỎ) hoặc None.
    """
    truoc = noi_dung[:vt]
    # heredoc: `<<EOF` / `<<-'EOF'` mở trước đó mà chưa thấy dấu đóng.
    for m in re.finditer(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", truoc):
        dau = m.group(2)
        # Dấu đóng đứng riêng một dòng.
        if not re.search(rf"^\s*{re.escape(dau)}\s*$", truoc[m.end():], re.M):
            return f"heredoc <<{dau}"
    # ANSI-C quoting `$'…'` — bộ quét coi `'` sau `$` như nháy đơn thường.
    if re.search(r"\$'[^']*$", truoc):
        return "ANSI-C $'…'"
    return None


def _lenh_compose_trong_script(noi_dung: str):
    """Sinh `(so_dong, doan_lenh)` cho MỌI lần `docker compose` là LỆNH thật.

    Chuỗi trả về của ca UNSUPPORTED cố ý KHÔNG chứa `-f docker-compose.yml`
    nên nó luôn làm guard đỏ — fail-closed theo hợp đồng D.
    """
    nhan = _ngu_canh_tung_ky_tu(noi_dung)
    moc = "docker compose"
    vt = noi_dung.find(moc)
    while vt != -1:
        loai = nhan[vt]
        so_dong = noi_dung.count("\n", 0, vt) + 1
        chua_ho_tro = _cu_phap_khong_mo_hinh_hoa(noi_dung, vt)
        if chua_ho_tro is not None:
            yield so_dong, f"UNSUPPORTED ({chua_ho_tro}) — bộ phân loại không đọc được ngữ cảnh này"
        elif loai == _NGU_CANH_MA:
            lenh = _lat_lenh_ma(noi_dung, vt)
            # Phép kiểm cài đặt, không phải lời gọi.
            if not noi_dung[:vt].rstrip().endswith("command -v"):
                yield so_dong, lenh
        elif loai in (_NGU_CANH_NHAY_KEP, _NGU_CANH_NHAY_DON):
            # Nháy đơn đi CHUNG luật với nháy kép — xem hợp đồng B.
            chuoi, lech = _lat_chuoi(noi_dung, nhan, vt)
            if _la_goi_y_operator(chuoi, lech):
                yield so_dong, chuoi.strip()
        vt = noi_dung.find(moc, vt + 1)


def test_lenh_compose_phai_ghim_docker_compose_yml():
    """Thiếu `-f docker-compose.yml` là Compose TỰ NẠP override DEV.

    Đo thật trong worktree này: cùng một lệnh
    `docker compose --env-file .env.production --profile production config`
      * KHÔNG `-f`: backend `command = uvicorn app.main:app --reload`,
        `APP_ENV = development`, và `docker-compose.override.yml` kéo theo
        `env_file: ./Backend_FastAPI/.env` + bind-mount mã nguồn;
      * CÓ `-f`:   `command = None`, `APP_ENV = None` (đúng ảnh production).
    Trên một máy chưa có `Backend_FastAPI/.env` thì lệnh đổ — ồn ào nhưng vô
    hại. Trên máy CÓ tệp đó, nó dựng cấu hình development trên production mà
    không báo gì cả. Đó mới là ca đáng sợ.

    Bao gồm cả `down`/`up -d` trần: trên prod, cặp ấy gỡ stack production rồi
    dựng stack dev lên thay.
    """
    pham = []
    for ten in _TAI_LIEU_VAN_HANH:
        d = _GOC / ten
        if not d.is_file():
            continue
        for so, dong in _dong_lenh_trong_tai_lieu(d):
            if _co_lenh_compose(dong) and "-f docker-compose.yml" not in dong:
                pham.append(f"{ten}:{so}: {dong.strip()[:90]}")
    da_soi_script = 0
    for sh in _cac_script():
        if sh.name not in _SCRIPT_PRODUCTION:
            continue
        da_soi_script += 1
        for so, lenh in _lenh_compose_trong_script(_doc(sh)):
            if "-f docker-compose.yml" not in lenh:
                pham.append(f"{sh.relative_to(_GOC)}:{so}: {lenh.strip()[:90]}")
    assert da_soi_script == len(_SCRIPT_PRODUCTION), (
        f"chỉ soi được {da_soi_script}/{len(_SCRIPT_PRODUCTION)} script production — "
        "một tên trong _SCRIPT_PRODUCTION đã bị đổi/xoá và guard đang canh hụt"
    )
    assert not pham, (
        "lệnh `docker compose` thiếu `-f docker-compose.yml` (Compose sẽ tự nạp "
        "docker-compose.override.yml của DEV):\n  " + "\n  ".join(pham)
    )


# ---------------------------------------------------------------------------
# Hồi quy cho bộ phân loại ngữ cảnh (hợp đồng A/B/C ở trên)
# ---------------------------------------------------------------------------
# Mỗi ca nuôi một mẩu shell tổng hợp vào `_lenh_compose_trong_script` và hỏi
# ĐÚNG MỘT câu. Không ca nào dựa vào số dòng, tên hàm, hay câu chữ hiện tại của
# `deploy.sh` — nếu guard chỉ đúng nhờ những thứ đó thì nó chưa hiểu ngữ cảnh.

def _bat(noi_dung: str) -> list[str]:
    """Các đoạn bị coi là LỆNH và THIẾU `-f docker-compose.yml`."""
    return [
        lenh
        for _, lenh in _lenh_compose_trong_script(noi_dung)
        if "-f docker-compose.yml" not in lenh
    ]


@pytest.mark.parametrize(
    "ten_ca,manh",
    [
        # (1) chẩn đoán trong ngoặc — chính là deploy.sh:515, KHÔNG được bắt.
        ("chẩn đoán trong ngoặc đơn",
         '''error "không liệt kê được container của service '$ten' (docker compose ps -aq thất bại)"'''),
        # (2) chú thích.
        ("chú thích", '# docker compose up -d rồi chờ healthy'),
        ("chú thích thụt lề", '    # dùng docker compose ps để xem trạng thái'),
        # (3) phép kiểm cài đặt.
        ("command -v", 'command -v docker compose >/dev/null 2>&1 || error "thiếu"'),
        # (4) văn xuôi có nhắc tên công cụ nhưng không phải lệnh in ra.
        ("văn xuôi giữa câu", 'log "nhớ rằng docker compose sẽ nạp override nếu thiếu cờ"'),
        ("văn xuôi trong ngoặc sau dấu hai chấm",
         'warn "Cảnh báo: bước này (docker compose sẽ tự nạp override) rất dễ sai"'),
        # Nháy đơn CHỈ sạch khi thật sự là văn xuôi — cùng luật với nháy kép.
        ("nháy đơn văn xuôi giữa câu",
         "echo 'hãy nhớ rằng docker compose có thể nạp override'"),
        ("nháy đơn văn xuôi trong ngoặc",
         "warn 'Cảnh báo: bước này (docker compose sẽ tự nạp override) rất dễ sai'"),
    ],
)
def test_guard_compose_khong_bat_nham_van_ban(ten_ca: str, manh: str) -> None:
    assert _bat(manh) == [], f"{ten_ca}: bắt nhầm văn bản không phải lệnh"


@pytest.mark.parametrize(
    "ten_ca,manh",
    [
        # (5) gọi trực tiếp.
        ("gọi trực tiếp", 'docker compose --profile production ps'),
        # (6) sau `if !`.
        ("sau if !", 'if ! docker compose exec -T postgres pg_isready; then\n  exit 1\nfi'),
        # (7) command substitution.
        ("command substitution", 'ds=$(docker compose ps -aq backend)'),
        ("command substitution trong nháy kép", 'echo "kết quả: $(docker compose ps -aq backend)"'),
        # (8) gán mảng / gán chuỗi.
        ("gán mảng", 'COMPOSE=(docker compose --env-file "$_ENV_FILE")'),
        ("gán mảng có gạch dưới", '_COMPOSE=(docker compose --env-file "$_ENV_FILE")'),
        # (9) gợi ý operator bắt đầu bằng `docker compose`.
        ("gợi ý đầu chuỗi", 'log "  docker compose --profile production logs -f"'),
        ("gợi ý đầu chuỗi qua cutover", 'cutover "  docker compose --profile production exec backend alembic upgrade head"'),
        ("gợi ý đầu chuỗi qua echo", 'echo "  docker compose exec postgres pg_restore -U qlts"'),
        # (10) gợi ý operator sau dấu hai chấm.
        ("gợi ý sau dấu hai chấm",
         'error "PostgreSQL không sẵn sàng.\n       Kiểm tra: docker compose --profile production ps postgres"'),
        ("gợi ý sau dấu hai chấm, câu dài",
         'error "mơ hồ.\n       Dọn container thừa rồi deploy lại: docker compose ps -a $ten"'),
        # 🔴 NHÁY ĐƠN — đường fail-open của bản trước. Bốn dạng chủ sở hữu nêu.
        ("wrapper nháy đơn DC=", "DC='docker compose up -d'"),
        ("wrapper nháy đơn COMPOSE=", "COMPOSE='docker compose ps'"),
        ("gợi ý nháy đơn qua log", "log 'docker compose up -d'"),
        ("gợi ý nháy đơn qua echo", "echo 'docker compose ps'"),
        ("gợi ý nháy đơn sau dấu hai chấm",
         "error 'PostgreSQL hỏng. Kiểm tra: docker compose ps postgres'"),
        ("nháy đơn thụt lề đầu chuỗi", "log '  docker compose --profile production ps'"),
    ],
)
def test_guard_compose_bat_khi_thieu_co(ten_ca: str, manh: str) -> None:
    assert _bat(manh), f"{ten_ca}: LỌT — thiếu `-f docker-compose.yml` mà guard im lặng"


@pytest.mark.parametrize(
    "ten_ca,manh",
    [
        ("heredoc không dấu nháy", "cat <<EOF\ndocker compose up -d\nEOF\n"),
        ("heredoc có dấu nháy", "cat <<'EOF'\ndocker compose ps\nEOF\n"),
        ("heredoc thụt lề", "cat <<-EOF\n\tdocker compose ps\nEOF\n"),
        ("ANSI-C quoting", "DC=$'docker compose ps\\n'"),
    ],
)
def test_guard_compose_cu_phap_la_thi_fail_closed(ten_ca: str, manh: str) -> None:
    """Hợp đồng D: cú pháp chưa mô hình hoá ⇒ ĐỎ, không im lặng cho qua.

    Đây là chỗ dễ sa vào bẫy nhất: "bộ quét không hiểu" và "chuỗi này an toàn"
    là HAI kết luận khác nhau, gộp chúng lại là tự mở một đường vòng.
    """
    ra = _bat(manh)
    assert ra, f"{ten_ca}: cú pháp lạ mà guard im lặng"
    assert any("UNSUPPORTED" in r for r in ra), (
        f"{ten_ca}: phải nói rõ là UNSUPPORTED chứ không đoán bừa, nhận: {ra}"
    )


@pytest.mark.parametrize(
    "ten_ca,manh",
    [
        ("gọi trực tiếp", 'docker compose -f docker-compose.yml --profile production ps'),
        ("sau if !", 'if ! docker compose -f docker-compose.yml exec -T postgres pg_isready; then\n  exit 1\nfi'),
        ("command substitution", 'ds=$(docker compose -f docker-compose.yml ps -aq backend)'),
        ("gán mảng", 'COMPOSE=(docker compose -f docker-compose.yml --env-file "$_ENV_FILE")'),
        ("gợi ý đầu chuỗi", 'log "  docker compose -f docker-compose.yml ps"'),
        ("gợi ý sau dấu hai chấm", 'error "hỏng.\n       Kiểm tra: docker compose -f docker-compose.yml ps postgres"'),
        ("nối dòng, cờ ở dòng đầu",
         'docker compose -f docker-compose.yml --profile production \\\n    up -d backend'),
        # Nháy đơn có cờ ⇒ phải XANH, nếu không luật mới thành "chặn tất".
        ("wrapper nháy đơn có cờ", "DC='docker compose -f docker-compose.yml up -d'"),
        ("gợi ý nháy đơn có cờ", "log '  docker compose -f docker-compose.yml ps'"),
        ("gợi ý nháy đơn sau hai chấm có cờ",
         "error 'hỏng. Kiểm tra: docker compose -f docker-compose.yml ps postgres'"),
    ],
)
def test_guard_compose_doi_chung_co_co_thi_xanh(ten_ca: str, manh: str) -> None:
    """Đối chứng: có `-f` thì KHÔNG được kêu.

    Thiếu nhóm ca này thì một bản vá "bắt tất" vẫn làm mọi ca ở trên xanh.
    """
    assert _bat(manh) == [], f"{ten_ca}: kêu oan một lệnh đã ghim đúng cờ"


def test_guard_compose_van_thay_du_hai_loai_o_deploy_sh():
    """Tripwire thay cho con số trong chú thích.

    Chú thích ghi "bốn dòng string" đã lỗi thời trong im lặng (thật ra là bảy).
    Nên bất biến được neo bằng PHÉP ĐO, không bằng câu chữ: guard phải còn nhìn
    thấy CẢ HAI loại trong `deploy.sh` — lệnh trong ngữ cảnh mã, VÀ gợi ý
    operator nằm trong chuỗi. Mất một loại nghĩa là bộ phân loại vừa câm đi một
    nửa, dù mọi ca tổng hợp vẫn xanh.
    """
    d = _GOC / "scripts" / "deploy.sh"
    if not d.is_file():
        pytest.skip("không có scripts/deploy.sh")
    noi_dung = _doc(d)
    nhan = _ngu_canh_tung_ky_tu(noi_dung)
    so_dong_thay = {so for so, _ in _lenh_compose_trong_script(noi_dung)}
    assert so_dong_thay, "guard không thấy lệnh `docker compose` nào — chắc chắn đã câm"

    trong_ma, trong_chuoi = 0, 0
    for so in so_dong_thay:
        vt = 0
        for _ in range(so - 1):
            vt = noi_dung.index("\n", vt) + 1
        het = noi_dung.find("\n", vt)
        het = len(noi_dung) if het == -1 else het
        k = noi_dung.find("docker compose", vt, het)
        if k == -1:
            continue
        if nhan[k] == _NGU_CANH_MA:
            trong_ma += 1
        else:
            trong_chuoi += 1

    assert trong_ma > 0, "không còn thấy lệnh nào trong ngữ cảnh MÃ"
    assert trong_chuoi > 0, (
        "không còn thấy gợi ý operator nào trong chuỗi — nhánh B của hợp đồng "
        "đã chết mà các ca tổng hợp không phát hiện ra"
    )
    # Mọi thứ guard thấy trong tệp thật đều PHẢI đã ghim cờ (nếu không, ca đích
    # `test_lenh_compose_phai_ghim_docker_compose_yml` đang đỏ).
    assert _bat(noi_dung) == [], f"deploy.sh có lệnh thiếu cờ: {_bat(noi_dung)}"


def test_guard_compose_van_thay_dong_515_la_khong_phai_lenh():
    """Neo vào tệp THẬT: dòng chẩn đoán của `deploy.sh` không được tính là lệnh.

    Ca này cố ý đọc `scripts/deploy.sh` thật thay vì một mẩu tổng hợp — nếu ai
    đó sửa wording của dòng ấy để né guard thay vì sửa guard, ca tổng hợp vẫn
    xanh còn ca này sẽ đổi nghĩa và bắt phải đọc lại.
    """
    d = _GOC / "scripts" / "deploy.sh"
    if not d.is_file():
        pytest.skip("không có scripts/deploy.sh")
    noi_dung = _doc(d)
    assert "(docker compose ps -aq thất bại)" in noi_dung, (
        "dòng chẩn đoán đã bị đổi wording — guard phải được kiểm lại theo HÌNH "
        "DẠNG, không phải theo câu chữ này"
    )
    so_dong = [so for so, _ in _lenh_compose_trong_script(noi_dung)]
    dong_chan_doan = noi_dung[: noi_dung.index("(docker compose ps -aq thất bại)")].count("\n") + 1
    assert dong_chan_doan not in so_dong, (
        f"dòng {dong_chan_doan} là câu chẩn đoán trong ngoặc, không phải lệnh"
    )


def test_tai_lieu_khong_bao_dat_bien_ma_khong_ai_doc():
    """Một `export` mà không ai đọc là một quy trình xanh nhưng không làm gì.

    Ca thật: §8.1 Step 3 bảo người trực
        export BACKEND_IMAGE_TAG=pre-admission-cutover-${DATE}
        export FRONTEND_IMAGE_TAG=...
        docker compose ... down && docker compose ... up -d
    nhưng `docker-compose.yml` KHÔNG hề đọc hai biến ấy — bốn service ứng dụng
    chỉ khai `build:`, không khai `image:`. Đo thật: render compose với hai tag
    giả cho `services.backend.image` = None, và `grep -c IMAGE_TAG` = 0. Nên
    rollback "recommended" chỉ dựng lại đúng ảnh hiện hành. Ba lệnh, ba lần
    exit 0, và phiên bản cũ không hề quay lại.

    Luật: biến được `export` trong khối lệnh của tài liệu vận hành phải hoặc
    được `docker-compose.yml` nội suy, hoặc được chính tài liệu ấy dùng lại ở
    một dòng lệnh khác.
    """
    compose_tho = _doc(_COMPOSE)
    pham = []
    for ten in _TAI_LIEU_VAN_HANH:
        d = _GOC / ten
        if not d.is_file():
            continue
        dong_lenh = _dong_lenh_trong_tai_lieu(d)
        for so, dong in dong_lenh:
            m = re.match(r"\s*export\s+([A-Z_][A-Z0-9_]*)=", dong)
            if not m:
                continue
            bien = m.group(1)
            if f"${{{bien}" in compose_tho:
                continue
            dung_lai = any(
                s2 != so and re.search(r"\$\{?" + bien + r"\b", d2)
                for s2, d2 in dong_lenh
            )
            if not dung_lai:
                pham.append(f"{ten}:{so}: export {bien} — không ai đọc biến này")
    assert not pham, (
        "tài liệu bảo đặt biến mà không cơ chế nào tiêu thụ:\n  " + "\n  ".join(pham)
    )


def test_script_khong_con_lenh_da_chet():
    """Cùng bộ luật, áp lên `scripts/*.sh`."""
    assert _cac_script(), "không thấy scripts/*.sh — guard đang xanh vô nghĩa"
    pham = []
    for sh in _cac_script():
        for so, dong in enumerate(_doc(sh).splitlines(), 1):
            if dong.lstrip().startswith("#") or _VAN_THOAT in dong:
                continue
            for mau, ly_do in _LENH_DA_CHET:
                if re.search(mau, dong):
                    pham.append(f"{sh.relative_to(_GOC)}:{so}: {dong.strip()[:90]}  ← {ly_do}")
    assert not pham, "còn lệnh đã chết trong scripts:\n  " + "\n  ".join(pham)


# ---------------------------------------------------------------------------
# setup-ssl.sh: bốn tính chất, mỗi cái từng là một ca hỏng thật
# ---------------------------------------------------------------------------

_SETUP_SSL = _GOC / "scripts" / "setup-ssl.sh"


@pytest.fixture(scope="module")
def ma_setup_ssl() -> str:
    if not _SETUP_SSL.is_file():
        pytest.skip("không có scripts/setup-ssl.sh")
    return _ma_lenh(_SETUP_SSL)


def test_setup_ssl_certbot_khong_keo_nginx_production_len(ma_setup_ssl: str):
    """`certbot` khai `depends_on: nginx` — thiếu `--no-deps` là tranh cổng 80.

    Ở bước bootstrap, chứng thư chưa tồn tại nên nginx production còn chưa khởi
    động nổi; đồng thời container bootstrap đang giữ cổng 80.

    Và `--entrypoint certbot` là bắt buộc: service này override entrypoint thành
    vòng lặp `certbot renew … sleep 12h`. `run` chỉ thay COMMAND chứ không thay
    ENTRYPOINT, nên thiếu cờ ấy thì `certonly …` chỉ là đối số không được thực
    thi — chứng thư không bao giờ được cấp, mà lệnh vẫn "chạy xong".
    """
    lenh = [d for d in ma_setup_ssl.splitlines() if "run --rm" in d and "certbot" in d]
    assert lenh, "setup-ssl.sh không còn lệnh `run --rm ... certbot`"
    for d in lenh:
        assert "--no-deps" in d, f"thiếu `--no-deps`: {d.strip()}"
        assert "--entrypoint certbot" in d, f"thiếu `--entrypoint certbot`: {d.strip()}"


def test_setup_ssl_chay_lai_duoc_khi_chung_thu_da_ton_tai(ma_setup_ssl: str):
    """Không có `--keep-until-expiring` thì lần chạy thứ hai tự khoá mình.

    `certonly --non-interactive` gặp một lineage trùng khít và chưa gần hết hạn
    sẽ rơi vào lời nhắc tương tác, `NoninteractiveDisplay` biến nó thành
    `MissingCommandlineFlag`, và người vận hành đọc thông điệp lỗi rồi đi mò DNS.
    Ca này rất dễ gặp vì Step 5 là một cổng CỨNG: hỏng ở đó thì phản xạ đầu tiên
    là chạy lại script.
    """
    assert "--keep-until-expiring" in ma_setup_ssl, (
        "certbot thiếu `--keep-until-expiring` — chạy lại script sẽ chết ở Step 3 "
        "với một thông điệp chỉ sai hướng"
    )


def test_setup_ssl_khoi_dong_nginx_KEM_theo_upstream(ma_setup_ssl: str):
    """Trên VPS mới, `--no-deps` cho `up nginx` là `[emerg] host not found`.

    `nginx/nginx.conf` khai `upstream backend { server backend:8000; }` và nginx
    phân giải hostname upstream NGAY LÚC NẠP CONFIG, vô điều kiện.
    """
    assert "QLTS_NGINX_NO_DEPS=0" in ma_setup_ssl, (
        "setup-ssl.sh phải gọi nginx-apply.sh với QLTS_NGINX_NO_DEPS=0 — trên VPS "
        "mới thì backend/frontend chưa chạy, và nginx không nạp nổi config"
    )
    for d in ma_setup_ssl.splitlines():
        if "up -d" in d and re.search(r"[^-]\bnginx\b", d) and "bootstrap" not in d:
            assert "--no-deps" not in d, f"`up nginx` không được mang --no-deps: {d.strip()}"


def test_setup_ssl_bat_lai_container_last_good_khi_hong(ma_setup_ssl: str):
    """Script này dừng nginx — nên mọi đường thoát khác 0 phải bật lại nó.

    Bản trước chỉ trap dọn bootstrap: bootstrap hỏng, certbot hỏng, candidate
    hỏng hay bàn giao hỏng đều để lại một máy chủ KHÔNG có nginx nào chạy, mà
    người vận hành không được báo là mình cần bật lại.
    """
    assert re.search(r"trap\s+\S*khoi_phuc\S*\s+EXIT", ma_setup_ssl), (
        "trap EXIT phải gọi hàm khôi phục last-good, không chỉ dọn bootstrap"
    )
    # Neo vào ĐẦU DÒNG: script còn một dòng `echo "... docker start $_CID..."`
    # để chỉ cho người vận hành cách chạy tay. Một biểu thức không neo sẽ khớp
    # đúng dòng thông báo ấy và xanh cả khi lệnh thật đã bị thay bằng `up -d`.
    # Chính bài đột biến đã lộ ra chỗ này — cùng lớp lỗi mà đợt review tìm thấy
    # ở guard `_vi_tri("scripts/deploy.sh")` của bản trước.
    assert re.search(
        r"^\s*(if\s+!\s+)?docker start\s+\"\$_CID_NGINX_CU\"", ma_setup_ssl, re.M
    ), (
        "phải `docker start` ĐÚNG container cũ theo ID đã ghi lại — `up -d` có "
        "thể dựng một container khác từ một cấu hình khác, đó không phải last-good"
    )
    assert "_DA_BAN_GIAO=1" in ma_setup_ssl, (
        "phải có cờ đánh dấu đã bàn giao xong, nếu không trap sẽ bật lại container "
        "cũ ngay cả trên đường thoát THÀNH CÔNG"
    )
    # Cờ chỉ được bật SAU khi nginx-apply.sh đạt.
    vt_apply = ma_setup_ssl.index("nginx-apply.sh")
    vt_co = ma_setup_ssl.index("_DA_BAN_GIAO=1")
    assert vt_apply < vt_co, (
        "cờ bàn giao được bật TRƯỚC khi nginx-apply.sh chứng minh container mới "
        "phục vụ được — trap sẽ im lặng ở đúng lúc cần nó nhất"
    )


# ---------------------------------------------------------------------------
# setup-ssl.sh Step 0: ẢNH phải dựng được TRƯỚC cổng 80 và TRƯỚC ACME
# ---------------------------------------------------------------------------
# Đo thật trên bản trước: `grep -c build scripts/setup-ssl.sh` = 0 — script chưa
# bao giờ dựng ảnh nginx. Thiệt hại KHÔNG phải hạn mức Let's Encrypt
# (`--keep-until-expiring` đã lo), mà là đường lùi: chứng thư đã cấp ở Step 3,
# bootstrap đã gỡ ở Step 4, Step 5 đỏ vì ảnh cũ/không có, `_DA_BAN_GIAO` còn 0 ⇒
# trap bật lại container nginx CŨ — mà trên VPS mới thì KHÔNG CÓ container cũ
# nào, nên trap lặng lẽ không làm gì và máy chủ ở lại KHÔNG có nginx.
#
# Guard TĨNH không đủ cho nhóm này: câu hỏi là "build có xảy ra TRƯỚC lệnh chạm
# nginx đang chạy không", tức một câu hỏi về THỨ TỰ THỰC THI. Nên các ca dưới
# đây CHẠY THẬT `setup-ssl.sh` với `docker` và `git` GIẢ trên PATH, rồi so VỊ
# TRÍ trong nhật ký argv — không so sự có mặt (một guard chỉ hỏi "có dòng build
# không" vẫn xanh khi dòng ấy nằm ở Step 5).
#
# Không certbot thật, không build/recreate nginx thật, không `docker compose up`
# thật: mọi lời gọi `docker` đều dừng ở stub.

# Thân RIÊNG của sân khấu `setup-ssl.sh`: các cần gạt build/pull/certbot và ngữ
# nghĩa `compose ps` của riêng nó (có `nginx-bootstrap`, và `nginx` CÓ THỂ vắng
# mặt — đó là kịch bản VPS mới).
#
# LÕI dùng chung đã `exit` trước khi tới đây cho `inspect`/`image`/`history`/
# `exec`/`run` — tức đúng những lệnh mà G1/G2 của `nginx-apply.sh` gọi ở Step 5.
# `setup-ssl.sh` không gọi `docker run` trần (certbot đi qua `docker compose
# run`, nên `$1` là `compose` và rơi xuống đây), nên LÕI không nuốt cần gạt nào.
_THAN_STUB_SSL = r"""
_a="$*"
case "$_a" in
    *" build "*|*" build")
        exit "${STUB_BUILD_RC:-0}" ;;
    *" pull "*|*" pull")
        exit "${STUB_PULL_RC:-0}" ;;
    *certonly*)
        exit "${STUB_CERTBOT_RC:-0}" ;;
    # Nhánh riêng phải đứng TRƯỚC nhánh chung: `*"ps -q nginx"*` có dấu sao hai
    # đầu nên nó khớp luôn cả `ps -q nginx-candidate`.
    *"ps -aq nginx-bootstrap"*|*"ps -q nginx-bootstrap"*)
        echo "cid-bootstrap-0001"; exit 0 ;;
    *"ps -aq nginx-candidate"*|*"ps -q nginx-candidate"*)
        echo "cid-candidate-0001"; exit 0 ;;
    *"ps -aq nginx"*|*"ps -q nginx"*)
        if [ -n "${STUB_CID_NGINX:-}" ]; then echo "$STUB_CID_NGINX"; fi
        exit 0 ;;
esac
exit 0
"""

_STUB_DOCKER = _ma_stub_docker("", _THAN_STUB_SSL)

# Container id mà `compose ps` của sân khấu setup-ssl trả về — khai ở đây để ca
# kiểm neo được vào ĐÚNG hai container mà cổng đồng nhất (G2) phải đọc.
_CID_CANDIDATE_SSL = "cid-candidate-0001"
_CID_NGINX_SSL = "cid-nginx-0001"

_STUB_GIT = r"""#!/usr/bin/env bash
# `git` GIẢ: trạng thái cây nguồn do biến môi trường quyết định.
printf 'git %s\n' "${*//$'\n'/ }" >> "$QLTS_STUB_LOG"
case "${1:-}" in
    rev-parse)
        if [ "${STUB_GIT_REV_RC:-0}" != "0" ]; then exit "${STUB_GIT_REV_RC}"; fi
        echo "${STUB_GIT_SHA:-1111111111111111111111111111111111111111}"
        exit 0 ;;
    status)
        if [ -n "${STUB_GIT_BAN:-}" ]; then printf '%s\n' "$STUB_GIT_BAN"; fi
        exit "${STUB_GIT_STATUS_RC:-0}" ;;
esac
exit 0
"""


def _moi_truong_gia(tmp_path: Path, **bien: str) -> tuple[dict, Path]:
    """PATH có `docker`/`git` giả, `.env` giả, và một nhật ký argv rỗng.

    Step 5 của `setup-ssl.sh` gọi THẬT sang `scripts/nginx-apply.sh`, và script
    ấy mang cổng NỘI DUNG (G1) + cổng ĐỒNG NHẤT (G2). Nên sân khấu này phải
    dựng đủ thứ để một lượt chạy ĐẠT là đạt vì đúng lý do:
      * cây "ảnh" chụp byte-nguyên từ `nginx/` THẬT của kho — G1 chiều xuôi so
        sha256 từng tệp, nên một bản "gần đúng" là đỏ;
      * cùng cây ấy KHÔNG có tệp nào ngoài bảng COPY + bốn tệp của ảnh nền —
        G1 chiều ngược gọi là mồ côi ngay nếu có;
      * lịch sử build có đuôi TRÙNG KHÍT lịch sử ảnh nền — `_dich_copy_trong_lich_su`
        fail-closed khi đuôi lệch;
      * `STUB_ANH_CANDIDATE` = `STUB_ANH_NGINX` = MỘT image id `sha256:` +
        64 hex — G2 từ chối cả khi hai bên lệch lẫn khi giá trị không đúng dạng.
    Mọi giá trị đều đi qua `**bien`, nên ca kiểm ngược nào muốn phá đúng MỘT
    trong bốn thứ trên vẫn phá được bằng một biến duy nhất.
    """
    shim = tmp_path / "shim"
    shim.mkdir(parents=True, exist_ok=True)
    for ten, ma in (("docker", _STUB_DOCKER), ("git", _STUB_GIT)):
        p = shim / ten
        p.write_text(ma, encoding="utf-8", newline="\n")
        p.chmod(0o755)
    nhat_ky = tmp_path / "argv.log"
    nhat_ky.write_text("", encoding="utf-8", newline="\n")
    env_gia = tmp_path / "gia.env"
    env_gia.write_text(
        "DOMAIN=vi-du.test\nCERTBOT_EMAIL=ops@vi-du.test\n",
        encoding="utf-8",
        newline="\n",
    )
    # Sân khấu ảnh dùng CHUNG bộ dựng với nhóm `_chay_apply` — một bản thứ hai
    # sẽ trôi khỏi bản đầu, và bản ở đây (không có ca đột biến riêng) trôi trước.
    san = tmp_path / "san-anh"
    san.mkdir(parents=True, exist_ok=True)
    _dung_cay_anh(_THU_MUC_NGINX, san)
    _ghi_lich_su_anh(_THU_MUC_NGINX, san)
    moi = {
        **os.environ,
        # PATH ở dạng BẢN ĐỊA (Windows dùng `;`), còn hai biến dưới đi thẳng
        # vào bash nên phải ở dạng POSIX.
        "PATH": str(shim) + os.pathsep + os.environ.get("PATH", ""),
        "MSYS_NO_PATHCONV": "1",
        "QLTS_STUB_LOG": nhat_ky.as_posix(),
        "QLTS_COMPOSE_ENV_FILE": env_gia.as_posix(),
        **_bien_mo_hinh_anh(_THU_MUC_NGINX, san),
        "STUB_ANH_CANDIDATE": _ANH_A,
        "STUB_ANH_NGINX": _ANH_A,
    }
    for thua in ("QLTS_COMPOSE_EXTRA", "QLTS_SSL_KIEM_CAY_NGUON"):
        moi.pop(thua, None)
    moi.update({k: str(v) for k, v in bien.items()})
    return moi, nhat_ky


def _chay_setup_ssl(
    tmp_path: Path, duong: Path | None = None, **bien: str
) -> tuple[int, str, list[str]]:
    """CHẠY THẬT `setup-ssl.sh`; trả `(rc, log người đọc, nhật ký argv)`."""
    moi, nhat_ky = _moi_truong_gia(tmp_path, **bien)
    kb = duong or _SETUP_SSL
    r = subprocess.run(
        [_BASH, kb.as_posix()],
        cwd=str(_GOC),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=moi,
    )
    lenh = [d for d in nhat_ky.read_text(encoding="utf-8").splitlines() if d.strip()]
    return r.returncode, r.stdout + r.stderr, lenh


def _vt_lenh(lenh: list[str], moc: str) -> int:
    """Vị trí lệnh ĐẦU TIÊN khớp `moc` trong nhật ký; -1 nếu không có."""
    for i, d in enumerate(lenh):
        if moc in d:
            return i
    return -1


def _ghi_ban_sao(tmp_path: Path, dong: list[str]) -> Path:
    """Bản đột biến nằm ở thư mục TẠM, giữ nguyên layout `<goc>/scripts/…`.

    CẤM ghi đè tệp trong worktree để đổi phiên bản: chết giữa chừng là mất việc.
    """
    thu_muc = tmp_path / "ban-dot-bien" / "scripts"
    thu_muc.mkdir(parents=True, exist_ok=True)
    p = thu_muc / "setup-ssl.sh"
    p.write_text("\n".join(dong) + "\n", encoding="utf-8", newline="\n")
    return p


def _vt_lenh_ma(dong: list[str], moc: str) -> int:
    """Vị trí dòng MÃ (không phải chú thích) đầu tiên chứa `moc`."""
    for i, d in enumerate(dong):
        if moc in d and not d.lstrip().startswith("#"):
            return i
    raise AssertionError(f"không thấy dòng mã nào chứa `{moc}` trong setup-ssl.sh")


def _khoi_lenh(dong: list[str], bd: int) -> int:
    """Chỉ số dòng CUỐI của lệnh bắt đầu ở `bd` (đi hết các dòng nối `\\`)."""
    kt = bd
    while dong[kt].rstrip().endswith("\\"):
        kt += 1
    return kt


def _ban_go_step0(tmp_path: Path) -> Path:
    """Bản `setup-ssl.sh` ĐÃ GỠ trọn Step 0 — dùng cho kiểm ngược.

    Vòng 2: Step 0 không còn MỘT lệnh mà là hai (`build …` rồi `pull …`). Cắt
    tới hết lệnh muộn hơn trong hai lệnh ấy, chứ không đóng cứng vào `build` —
    cắt hụt thì bản đột biến vẫn còn `pull` và ca kiểm ngược đo nhầm thứ.
    """
    dong = _doc(_SETUP_SSL).splitlines()
    bd = next(
        i for i, d in enumerate(dong) if d.lstrip().startswith("log ") and "Step 0:" in d
    )
    kt = max(
        _khoi_lenh(dong, _vt_lenh_ma(dong, "--profile production build ")),
        _khoi_lenh(dong, _vt_lenh_ma(dong, "--profile production pull ")),
    )
    assert bd < kt, "mốc cắt Step 0 đảo ngược — đột biến sẽ cắt nhầm chỗ"
    return _ghi_ban_sao(tmp_path, dong[:bd] + dong[kt + 1 :])


def _ban_doi_build_xuong_sau_stop(tmp_path: Path) -> Path:
    """Đột biến TINH VI nhất của nhóm này: DỜI lệnh build xuống sau `stop nginx`.

    Không xoá gì, không đổi một ký tự nào của lệnh — nên mọi guard hỏi "script
    có gọi `compose build` không", "lệnh build có ghim `-f` không", "cây nguồn
    có được xác minh không" đều VẪN XANH. Thứ duy nhất đổi là VỊ TRÍ, và đó
    đúng là thứ quyết định thiệt hại: tới đó thì nginx đang phục vụ đã bị dừng.
    Đặt ngay sau `stop nginx` (tức vẫn TRƯỚC certbot) để đột biến khó bị bắt
    nhất — một guard chỉ so `build < certonly` sẽ không thấy gì.
    """
    dong = _doc(_SETUP_SSL).splitlines()
    bd = _vt_lenh_ma(dong, "--profile production build ")
    kt = _khoi_lenh(dong, bd)
    khoi = dong[bd : kt + 1]
    con_lai = dong[:bd] + dong[kt + 1 :]
    vt_stop = _vt_lenh_ma(con_lai, "--profile production stop nginx")
    return _ghi_ban_sao(
        tmp_path, con_lai[: vt_stop + 1] + khoi + con_lai[vt_stop + 1 :]
    )


# --- Đọc nhật ký argv thành (lệnh compose, có --no-deps, các toán hạng) ------
# Cờ MANG GIÁ TRỊ: token ngay sau chúng là giá trị chứ không phải tên service.
# Thiếu một cái ở đây là đọc nhầm giá trị thành service — `--entrypoint certbot
# certbot` là đúng cái bẫy ấy.
_CO_MANG_GIA_TRI = {
    "-f", "--file", "-p", "--project-name", "--env-file", "--profile",
    "--entrypoint", "-e", "--env", "--name", "--policy", "--tail", "-v",
    "--volume", "-w", "--workdir", "-u", "--user", "--network",
}


def _lat_lenh_compose(dong: str) -> tuple[str, bool, list[str]] | None:
    """`(lệnh, có --no-deps, toán hạng)` cho một dòng nhật ký `docker compose`.

    Trả `None` cho mọi thứ không phải lời gọi `docker compose` — đặc biệt là
    `docker run --rm --network …` của `nginx-verify.sh`, vốn KHÔNG khởi động
    service nào của stack và không được lẫn vào phép đếm.
    """
    tok = dong.split()
    if not tok or tok[0] != "compose":
        return None
    i = 1
    while i < len(tok):
        if tok[i] in _CO_MANG_GIA_TRI:
            i += 2
            continue
        if tok[i].startswith("-"):
            i += 1
            continue
        break
    if i >= len(tok):
        return None
    lenh = tok[i]
    i += 1
    toan_hang: list[str] = []
    no_deps = "--no-deps" in tok
    while i < len(tok):
        if tok[i] in _CO_MANG_GIA_TRI:
            i += 2
            continue
        if tok[i].startswith("-"):
            i += 1
            continue
        toan_hang.append(tok[i])
        i += 1
        # `run <service> <command> …`: chỉ token đầu là service, phần còn lại
        # là lệnh chạy TRONG container (`certonly --non-interactive …`).
        if lenh == "run":
            break
    return lenh, no_deps, toan_hang


def _dich_vu_khoi_dong(lenh: list[str], compose: dict) -> set[str]:
    """Mọi service được `up`/`run` trong đoạn nhật ký, ĐÃ đóng theo `depends_on`.

    Đóng bao là bắt buộc: `up -d nginx` không mang `--no-deps` sẽ kéo cả
    `frontend` + `backend` (rồi `postgres` + `redis`) lên theo, và những ảnh ấy
    cũng phải có mặt từ trước. Lệnh nào có `--no-deps` thì KHÔNG đóng bao.
    """
    dv = compose.get("services", {})
    ra: set[str] = set()
    for d in lenh:
        lat = _lat_lenh_compose(d)
        if lat is None or lat[0] not in ("up", "run"):
            continue
        _, no_deps, ten = lat
        hang_doi = [t for t in ten if t in dv]
        while hang_doi:
            t = hang_doi.pop()
            if t in ra:
                continue
            ra.add(t)
            if no_deps:
                continue
            hang_doi.extend(
                p for p in (dv[t].get("depends_on") or []) if p in dv and p not in ra
            )
    return ra


def _anh_cua(compose: dict, ten: str) -> str:
    """Định danh ẢNH mà service `ten` chạy.

    Ba service nginx (`nginx`, `nginx-candidate`, `nginx-bootstrap`) khai CÙNG
    `image: qlts-nginx:local`, nên build MỘT trong ba là đủ cho cả ba — đó
    chính là lý do phép so phải theo ẢNH chứ không theo tên service.
    """
    dv = compose["services"][ten]
    anh = dv.get("image")
    return anh if anh else f"<ảnh build riêng của {ten}>"


def _build_hay_pull_sau(lenh: list[str], moc: int) -> list[str]:
    """Các lệnh `build`/`pull` nằm SAU vị trí `moc` trong nhật ký."""
    pham = []
    for i, d in enumerate(lenh):
        if i <= moc:
            continue
        lat = _lat_lenh_compose(d)
        if lat is not None and lat[0] in ("build", "pull"):
            pham.append(f"#{i}: {d}")
    return pham


def _ban_go_kiem_cay(tmp_path: Path) -> Path:
    """Bản GỠ riêng khối xác minh cây nguồn, GIỮ nguyên lệnh build."""
    dong = _doc(_SETUP_SSL).splitlines()
    bd = next(
        i for i, d in enumerate(dong) if d.startswith('if [ "${QLTS_SSL_KIEM_CAY_NGUON')
    )
    # `fi` đóng khối NGOÀI nằm ở cột 0; mọi `fi` bên trong đều thụt lề, nên so
    # nguyên văn (không `strip`) là phép cắt chính xác.
    kt = next(i for i in range(bd + 1, len(dong)) if dong[i] == "fi")
    return _ghi_ban_sao(tmp_path, dong[:bd] + dong[kt + 1 :])


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_build_hong_thi_DUNG_truoc_cong_80_va_truoc_acme(tmp_path):
    """Build hỏng ⇒ script dừng khi CHƯA chạm gì — không có gì phải khôi phục.

    Ca hỏng thật mà nhóm này canh: ảnh nginx không dựng được (template thiếu,
    Dockerfile hỏng, đĩa đầy). Nếu phát hiện ấy rơi xuống sau Step 3 thì chứng
    thư đã cấp, nginx đang phục vụ đã bị dừng, cổng 80 đã bị lấy — và trên VPS
    mới thì trap không có container cũ nào để bật lại.
    """
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_BUILD_RC="1")
    assert rc != 0, f"`compose build` trả 1 mà script vẫn trả 0:\n{ra}"
    assert _vt_lenh(lenh, " build nginx") >= 0, (
        "script không hề gọi `compose build nginx` — Step 0 đã biến mất:\n"
        + "\n".join(lenh)
    )
    for cam, vi_sao in (
        ("stop nginx", "đã dừng nginx đang phục vụ"),
        ("nginx-bootstrap", "đã đụng tới cổng 80"),
        ("certonly", "đã gọi ACME"),
    ):
        assert _vt_lenh(lenh, cam) < 0, (
            f"build hỏng mà script vẫn {vi_sao} — phát hiện tới quá muộn "
            f"(`{cam}` trong nhật ký lệnh):\n" + "\n".join(lenh)
        )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_khong_co_step0_thi_di_thang_toi_certbot(tmp_path):
    """KIỂM NGƯỢC: gỡ Step 0 ⇒ script chạy thẳng tới certbot.

    Không có ca này thì ca nền ở trên có thể đang xanh vì một lý do khác hẳn
    (env giả thiếu biến, stub trả sai, script chết ở một dòng vô can) — và một
    guard đỏ vì lý do khác là một guard không canh gì cả.
    """
    ban = _ban_go_step0(tmp_path)
    rc, ra, lenh = _chay_setup_ssl(
        tmp_path, duong=ban, STUB_BUILD_RC="1", STUB_CERTBOT_RC="1"
    )
    assert not _build_hay_pull_sau(lenh, -1), (
        "bản đột biến vẫn còn lệnh build/pull — phép cắt Step 0 đã trượt "
        "(vòng 2: Step 0 có HAI lệnh, cắt hụt một cái là đo nhầm thứ):\n"
        + "\n".join(lenh)
    )
    assert _vt_lenh(lenh, "stop nginx") >= 0 and _vt_lenh(lenh, "certonly") >= 0, (
        "gỡ Step 0 mà script KHÔNG tới được cổng 80 và certbot ⇒ ca nền đỏ vì "
        f"lý do khác chứ không phải vì Step 0 (rc={rc}):\n{ra}\n" + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_build_dung_TRUOC_moi_lenh_cham_nginx(tmp_path):
    """So VỊ TRÍ trong nhật ký lệnh, không so sự có mặt.

    Một lệnh build đặt ở Step 5 vẫn làm mọi guard "có gọi build không" xanh,
    trong khi nó chữa đúng con số không: tới đó thì cổng 80 đã bị lấy và chứng
    thư đã cấp.
    """
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_CERTBOT_RC="1")
    vt_build = _vt_lenh(lenh, " build nginx")
    vt_stop = _vt_lenh(lenh, "stop nginx")
    vt_acme = _vt_lenh(lenh, "certonly")
    assert min(vt_build, vt_stop, vt_acme) >= 0, (
        f"thiếu mốc trong nhật ký lệnh (build={vt_build} stop={vt_stop} "
        f"certbot={vt_acme}), rc={rc}:\n{ra}\n" + "\n".join(lenh)
    )
    assert vt_build < vt_stop < vt_acme, (
        "thứ tự thực thi SAI — build phải đứng trước mọi lệnh chạm nginx đang "
        f"phục vụ và trước ACME: build={vt_build} stop={vt_stop} "
        f"certbot={vt_acme}\n" + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_tu_choi_build_tu_cay_da_troi(tmp_path):
    """`build` dựng từ CÂY LÀM VIỆC — cây trôi thì ảnh không khớp commit nào.

    Không có cổng này, Step 0 chữa được ca "chưa có ảnh" nhưng lại mở một ca
    mới: nó đưa lặng lẽ mọi sửa đổi đang nằm trên đĩa của VPS lên production.
    """
    rc, ra, lenh = _chay_setup_ssl(
        tmp_path, STUB_GIT_BAN=" M nginx/templates/default.conf.template"
    )
    assert rc != 0, f"cây nguồn đã trôi mà script vẫn trả 0:\n{ra}"
    for cam in (" build nginx", "stop nginx", "certonly"):
        assert _vt_lenh(lenh, cam) < 0, (
            f"cây nguồn đã trôi mà script vẫn chạy `{cam}`:\n" + "\n".join(lenh)
        )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_go_kiem_cay_thi_cay_troi_van_build(tmp_path):
    """KIỂM NGƯỢC cho cổng cây nguồn: gỡ đúng khối ấy ⇒ build chạy trở lại."""
    ban = _ban_go_kiem_cay(tmp_path)
    rc, ra, lenh = _chay_setup_ssl(
        tmp_path, duong=ban, STUB_GIT_BAN=" M nginx/x", STUB_CERTBOT_RC="1"
    )
    assert _vt_lenh(lenh, " build nginx") >= 0, (
        "gỡ khối xác minh cây nguồn mà build vẫn không chạy ⇒ ca nền đỏ vì một "
        f"lý do khác (rc={rc}):\n{ra}\n" + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_khong_doc_duoc_HEAD_thi_tu_choi_build(tmp_path):
    """Không biết cây đang ở đâu thì không build — fail-closed, không đoán."""
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_GIT_REV_RC="128")
    assert rc != 0, f"`git rev-parse HEAD` hỏng mà script vẫn trả 0:\n{ra}"
    assert _vt_lenh(lenh, " build nginx") < 0, (
        "không đọc được HEAD mà vẫn build:\n" + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_khong_doc_duoc_git_status_thi_tu_choi_build(tmp_path):
    """`git status` hỏng ⇒ từ chối build. Nhánh ANH EM của ca ngay trên.

    Vá một nhánh thì còn bốn nhánh: cổng cây nguồn hỏi git HAI lần
    (`rev-parse HEAD` rồi `status --porcelain`), và chỉ nhánh thứ nhất từng có
    ca canh. Đo bằng đột biến: đổi `if ! _CAY_BAN=$(git status …); then error`
    thành `_CAY_BAN=$(git status … || true)` là biến một cổng fail-closed thành
    một cổng LUÔN XANH — `_CAY_BAN` rỗng thì cây nào cũng "sạch" — và trước ca
    này thì KHÔNG một ca nào trong 169 ca bắt được.
    """
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_GIT_STATUS_RC="128")
    assert rc != 0, f"`git status` trả 128 mà script vẫn trả 0:\n{ra}"
    assert not _build_hay_pull_sau(lenh, -1), (
        "không đọc được trạng thái cây nguồn mà vẫn build/pull:\n" + "\n".join(lenh)
    )
    assert _vt_lenh(lenh, "stop nginx") < 0 and _vt_lenh(lenh, "certonly") < 0, (
        "cổng cây nguồn đỏ mà script vẫn dừng nginx / gọi ACME:\n" + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_co_thoat_hiem_cay_nguon_chay_duoc(tmp_path):
    """Lối thoát ghi trong thông điệp lỗi phải MỞ ĐƯỢC cổng thật.

    Một `QLTS_SSL_KIEM_CAY_NGUON=0` được quảng cáo mà không ai đọc còn tệ hơn
    không có: người trực gõ nó lúc 2 giờ sáng, cổng vẫn đỏ, và họ đi sửa nhầm
    chỗ.
    """
    rc, ra, lenh = _chay_setup_ssl(
        tmp_path,
        STUB_GIT_BAN=" M nginx/x",
        QLTS_SSL_KIEM_CAY_NGUON="0",
        STUB_CERTBOT_RC="1",
    )
    assert _vt_lenh(lenh, " build nginx") >= 0, (
        "đặt QLTS_SSL_KIEM_CAY_NGUON=0 mà cổng vẫn chặn build "
        f"(rc={rc}):\n{ra}\n" + "\n".join(lenh)
    )


def test_setup_ssl_build_di_qua_mang_COMPOSE_da_ghim(ma_setup_ssl: str):
    """Lệnh build mới phải đi qua mảng `COMPOSE` đã ghim `-f docker-compose.yml`.

    `_lenh_compose_trong_script` tìm chuỗi `docker compose`, nên một dòng viết
    `"${COMPOSE[@]}" … build nginx` là VÔ HÌNH với nó: guard không đỏ, mà cũng
    không xác nhận gì. Cái giữ cho dòng ấy được ghim là khai báo mảng ở đầu tệp
    — và điều đó chỉ đúng chừng nào lệnh build thật sự dùng mảng ấy.
    """
    dong_build = [
        d for d in ma_setup_ssl.splitlines() if re.search(r"\bbuild\s+nginx\b", d)
    ]
    assert dong_build, (
        "setup-ssl.sh không còn lệnh `build nginx` — Step 0 đã biến mất, và với "
        "nó là toàn bộ đường lùi trên VPS mới"
    )
    for d in dong_build:
        assert '"${COMPOSE[@]}"' in d or "-f docker-compose.yml" in d, (
            "lệnh build không ghim `-f docker-compose.yml` và cũng không đi qua "
            f"mảng COMPOSE: {d.strip()[:120]}"
        )


def test_mang_compose_trong_script_production_ghim_va_gan_DUNG_MOT_LAN():
    """Mảng giữ `docker compose` phải ghim `-f`, và chỉ được gán MỘT lần.

    Bộ phân loại ngữ cảnh nhìn thấy `X=(docker compose …)` vì chuỗi ấy có mặt ở
    đó. Nó KHÔNG nhìn thấy `X+=(--profile …)` hay một lần gán lại `X=("${X[@]}"
    -f khac.yml)`: hai dòng ấy không chứa `docker compose` nên không lần nào
    được hỏi tới, mà chúng lại đổi được chính lệnh mà mọi `"${X[@]}"` sau đó
    chạy. Đóng khe ấy ở đây thay vì nới hợp đồng của bộ phân loại.
    """
    re_gan = re.compile(r"^(\w+)=\(\s*docker compose\b(.*)$", re.M)
    pham: list[str] = []
    da_soi = 0
    for sh in _cac_script():
        if sh.name not in _SCRIPT_PRODUCTION:
            continue
        da_soi += 1
        ma = _ma_lenh(sh)
        for m in re_gan.finditer(ma):
            ten, than = m.group(1), m.group(2)
            if "-f docker-compose.yml" not in than:
                pham.append(f"{sh.name}: mảng `{ten}` không ghim -f docker-compose.yml")
            so_lan = len(re.findall(rf"^\s*{re.escape(ten)}\+?=\(", ma, re.M))
            if so_lan != 1:
                pham.append(
                    f"{sh.name}: mảng `{ten}` được gán {so_lan} lần — lần gán "
                    "thứ hai không chứa `docker compose` nên bộ phân loại không "
                    "nhìn thấy nó"
                )
    assert da_soi == len(_SCRIPT_PRODUCTION), (
        f"chỉ soi được {da_soi}/{len(_SCRIPT_PRODUCTION)} script production — "
        "một tên trong _SCRIPT_PRODUCTION đã bị đổi/xoá"
    )
    assert not pham, "mảng lệnh compose không an toàn:\n  " + "\n  ".join(pham)


# ---------------------------------------------------------------------------
# setup-ssl.sh Step 0 — VÒNG 2: phạm vi là MỌI ảnh cần sau điểm dừng nginx
# ---------------------------------------------------------------------------
# Vòng 1 chỉ build `nginx`. Nhưng sau điểm dừng, Step 3 chạy `certbot` và Step 5
# gọi `nginx-apply.sh` với `QLTS_NGINX_NO_DEPS=0`, mà Nhịp 0 của nó là
# `up -d --wait postgres redis backend frontend`. Ảnh backend/frontend thiếu ⇒
# Compose TỰ build ngay tại đó; ảnh certbot/postgres/redis thiếu ⇒ một
# `docker pull` phát sinh — cả hai đều rơi vào đúng khoảng thời gian mà Step 0
# sinh ra để dọn trống: cổng 80 đã nhường, nginx đang phục vụ đã bị dừng, và
# (với certbot trở đi) chứng thư đã cấp.
#
# Nhóm ca dưới đây đo bằng NHẬT KÝ LỆNH của một lượt chạy đầy đủ, và so theo VỊ
# TRÍ. Một guard hỏi "có gọi build không" vẫn xanh khi lệnh ấy nằm ở Step 5 —
# `_ban_doi_build_xuong_sau_stop` là đột biến dựng riêng để chứng minh điều đó.


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_setup_ssl_sau_khi_dung_nginx_khong_con_build_hay_pull(tmp_path):
    """SAU `stop nginx`, nhật ký lệnh phải có ĐÚNG 0 lệnh `build` và 0 `pull`.

    Đây là tính chất mà toàn bộ Step 0 tồn tại để bảo đảm. Nó được phát biểu
    trên nhật ký argv của MỘT lượt chạy đi tới cùng (rc=0), chứ không trên văn
    bản script: một lệnh build nằm trong nhánh `if` chẳng bao giờ chạy cũng làm
    guard tĩnh xanh, còn một lệnh build do `nginx-apply.sh` (script KHÁC) phát
    ra thì guard tĩnh trên `setup-ssl.sh` không bao giờ thấy.
    """
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_CID_NGINX="cid-nginx-0001")
    assert rc == 0, f"lượt chạy đầy đủ không tới đích (rc={rc}):\n{ra}\n" + "\n".join(
        lenh
    )
    vt_stop = _vt_lenh(lenh, "stop nginx")
    assert vt_stop >= 0, "không thấy `stop nginx` — mốc đo biến mất:\n" + "\n".join(lenh)

    # CHỐNG XANH RỖNG: nếu script chết ngay sau `stop nginx` thì "0 lệnh build
    # phía sau" đúng một cách vô nghĩa. Bắt buộc phải thấy các mốc muộn nhất.
    for moc, o_dau in (
        ("nginx-bootstrap", "Step 2"),
        ("certonly", "Step 3"),
        ("nginx-candidate", "Step 5 / Nhịp 1"),
    ):
        assert any(moc in d for d in lenh[vt_stop + 1 :]), (
            f"nhật ký sau `stop nginx` không có mốc `{moc}` ({o_dau}) ⇒ lượt "
            "chạy chưa đi hết, ca này đang xanh rỗng:\n" + "\n".join(lenh)
        )
    assert "nginx" in _dich_vu_khoi_dong(lenh[vt_stop + 1 :], _tai_compose(_COMPOSE)), (
        "không thấy service `nginx` được khởi động lại sau điểm dừng ⇒ Step 5 "
        "chưa chạy hết:\n" + "\n".join(lenh)
    )

    # CHỐNG XANH RỖNG, phần hai: Step 5 gọi THẬT sang `nginx-apply.sh`, nên rc=0
    # ở đây cũng là lời khẳng định rằng hai cổng của script ấy đã ĐI QUA chứ
    # không phải được đi vòng. Nếu sân khấu tụt xuống thành "mọi lệnh đều thành
    # công" thì rc vẫn 0 và cả nhóm ca này xanh mà không đo gì — nên đòi đúng
    # dấu vết mà G1/G2 để lại.
    #
    # G1 (cổng NỘI DUNG): thông báo đối chiếu THÀNH CÔNG, và đủ số tệp.
    khop = re.search(r"cổng nội dung: (\d+)/\1 tệp khớp nguồn", ra)
    assert khop, (
        "không thấy cổng NỘI DUNG (G1) của nginx-apply.sh báo đối chiếu thành "
        f"công — lượt chạy này chưa đi qua nó:\n{ra}"
    )
    assert int(khop.group(1)) == len(_DUONG_TRONG_ANH), (
        f"G1 chỉ đối chiếu {khop.group(1)} tệp, bảng COPY của nginx/Dockerfile "
        f"có {len(_DUONG_TRONG_ANH)} — sân khấu đang che bớt tệp cho cổng"
    )
    # …và đúng ba phép đo mà G1 dựa vào, trên nhật ký argv (không phải trên log
    # người đọc): lịch sử build, checksum trong container, và mốc kết của phép
    # liệt kê. Thiếu mốc thì một đầu ra CỤT trông y hệt một danh sách sạch.
    for moc, vi_sao in (
        ("history ", "đọc lịch sử build của ảnh"),
        (" sha256sum ", "đối chiếu checksum trong container"),
        (_MOC_LIET_KE_STUB, "mốc kết của phép liệt kê thư mục đích"),
    ):
        assert any(moc in d for d in lenh), (
            f"nhật ký không có dấu vết `{moc}` ({vi_sao}) ⇒ G1 chưa thật sự "
            "chạy:\n" + "\n".join(lenh)
        )

    # G2 (cổng ĐỒNG NHẤT): image id BẤT BIẾN được đọc ở CẢ HAI container và
    # khớp nhau. `{{.Config.Image}}` không đủ — nó là tên:tag dùng chung.
    cid_doc = {
        d.split()[-1]
        for d in lenh
        if d.startswith("inspect ") and "{{.Image}}" in d
    }
    assert {_CID_CANDIDATE_SSL, _CID_NGINX_SSL} <= cid_doc, (
        "G2 không đọc `{{.Image}}` của CẢ candidate lẫn nginx đang phục vụ "
        f"(thấy: {sorted(cid_doc)}):\n" + "\n".join(lenh)
    )
    assert re.search(r"chạy đúng ảnh đã chứng minh \(sha256:[0-9a-f]{64}\)", ra), (
        "không thấy nginx-apply.sh tuyên bố nginx đang chạy ĐÚNG bản ảnh đã "
        f"được chứng minh (image id bất biến) ⇒ G2 chưa đi qua:\n{ra}"
    )

    pham = _build_hay_pull_sau(lenh, vt_stop)
    assert not pham, (
        "còn lệnh build/pull phát sinh SAU khi nginx đang phục vụ đã bị dừng — "
        "đúng hình dạng thất bại mà Step 0 sinh ra để chặn:\n  "
        + "\n  ".join(pham)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_doi_build_xuong_sau_stop_nginx_thi_ca_tren_DO(tmp_path):
    """KIỂM NGƯỢC cho ca ngay trên: dời build xuống sau `stop nginx` ⇒ ĐỎ.

    Bản đột biến vi phạm ĐÚNG MỘT bất biến (vị trí của lệnh build) và không
    đụng gì khác — nên nếu ca trên vẫn xanh với nó thì ca trên không canh gì.
    Ca này khẳng định hai điều, và cần cả hai: (1) bản đột biến VẪN chạy được
    tới certbot — tức nó tinh vi, không phải một script gãy; (2) phép đo vị trí
    bắt được nó.
    """
    ban = _ban_doi_build_xuong_sau_stop(tmp_path)
    rc, ra, lenh = _chay_setup_ssl(
        tmp_path, duong=ban, STUB_CID_NGINX="cid-nginx-0001"
    )
    vt_stop = _vt_lenh(lenh, "stop nginx")
    assert vt_stop >= 0, f"đột biến làm hỏng cả mốc `stop nginx` (rc={rc}):\n{ra}"
    assert _vt_lenh(lenh, "certonly") > vt_stop, (
        "bản đột biến không còn chạy tới certbot ⇒ nó THÔ chứ không tinh vi, "
        f"và ca trên có thể đang đỏ vì lý do khác (rc={rc}):\n{ra}\n"
        + "\n".join(lenh)
    )
    pham = _build_hay_pull_sau(lenh, vt_stop)
    assert pham, (
        "dời hẳn lệnh build xuống sau `stop nginx` mà phép đo KHÔNG thấy gì ⇒ "
        "ca `sau khi dừng nginx không còn build/pull` đang xanh vô nghĩa:\n"
        + "\n".join(lenh)
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_moi_anh_can_sau_diem_dung_deu_do_step0_lo_lieu(tmp_path):
    """Phạm vi Step 0 = ĐÚNG tập ảnh của các service khởi động sau điểm dừng.

    Suy cả hai chiều từ chính nhật ký chạy + `docker-compose.yml`, không từ một
    danh sách chép tay:
      * THIẾU  — một service lên sau điểm dừng mà ảnh của nó không được Step 0
                 lo (build hoặc pull) ⇒ đỏ. Đây là khe hở vòng 1.
      * THỪA   — Step 0 build/pull một ảnh mà không service nào sau điểm dừng
                 dùng ⇒ cũng đỏ. Đây là khe hở ngược lại: mở rộng máy móc sang
                 `celery-worker`/`celery-beat` (không lệnh nào khởi động chúng)
                 bắt một VPS mới trả tiền cho hai ảnh vô dụng.
    So theo ẢNH chứ không theo tên service: ba service nginx dùng chung
    `qlts-nginx:local`, build một là đủ cho cả ba.
    """
    compose = _tai_compose(_COMPOSE)
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_CID_NGINX="cid-nginx-0001")
    assert rc == 0, f"lượt chạy đầy đủ không tới đích (rc={rc}):\n{ra}"
    vt_stop = _vt_lenh(lenh, "stop nginx")
    assert vt_stop >= 0

    ds_build: list[str] = []
    ds_pull: list[str] = []
    for d in lenh[:vt_stop]:
        lat = _lat_lenh_compose(d)
        if lat is None:
            continue
        if lat[0] == "build":
            ds_build += lat[2]
        elif lat[0] == "pull":
            ds_pull += lat[2]
    assert ds_build, "Step 0 không build gì cả:\n" + "\n".join(lenh)
    assert ds_pull, "Step 0 không bảo đảm ảnh mượn nào cả:\n" + "\n".join(lenh)

    dv = compose["services"]
    for t in ds_build:
        assert t in dv and dv[t].get("build"), (
            f"Step 0 build `{t}` nhưng docker-compose.yml không khai `build:` "
            "cho nó — lệnh ấy không dựng được gì"
        )
    for t in ds_pull:
        assert t in dv and not dv[t].get("build"), (
            f"Step 0 `pull {t}` nhưng service ấy có `build:` — ảnh của nó phải "
            "được DỰNG, `pull` sẽ đi tìm một ảnh không ai đẩy lên registry"
        )

    anh_lo = {_anh_cua(compose, t) for t in ds_build + ds_pull}
    khoi_dong = _dich_vu_khoi_dong(lenh[vt_stop + 1 :], compose)
    assert khoi_dong, "không service nào được khởi động sau điểm dừng — xanh rỗng"
    anh_can = {_anh_cua(compose, t) for t in khoi_dong}

    thieu = {
        f"{t} → {_anh_cua(compose, t)}"
        for t in khoi_dong
        if _anh_cua(compose, t) not in anh_lo
    }
    assert not thieu, (
        "service lên SAU điểm dừng nginx mà Step 0 không lo ảnh cho nó — "
        "Compose sẽ tự build/pull đúng lúc cổng 80 đã nhường:\n  "
        + "\n  ".join(sorted(thieu))
    )
    thua = anh_lo - anh_can
    assert not thua, (
        "Step 0 lo những ảnh mà KHÔNG lệnh nào sau điểm dừng dùng tới:\n  "
        + "\n  ".join(sorted(thua))
        + "\n(các service thật sự khởi động: "
        + ", ".join(sorted(khoi_dong))
        + ")"
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_cong_cay_nguon_phu_dung_cac_build_context(tmp_path, ma_setup_ssl: str):
    """Cổng cây nguồn phải soi ĐÚNG các `build.context` của ảnh sắp build.

    Hai chiều, và cả hai đều đã hỏng thật ở đâu đó:
      * soi HỤT  — vòng 1 chỉ gác `nginx` + `docker-compose.yml`; nay Step 0
                   còn build backend + frontend, nên một `Backend_FastAPI/`
                   đang trôi sẽ lặng lẽ lên production;
      * soi THỪA — gác cả cây thì mọi sửa đổi vô can cũng làm cổng đỏ, và một
                   cổng đỏ oan là một cổng sẽ bị tắt.
    Danh sách được suy từ `docker-compose.yml`, nên đổi `build.context` của một
    service mà quên cổng là ca này đỏ.
    """
    m = re.search(r"^_DUONG_CAY_NGUON=\(([^)]*)\)", ma_setup_ssl, re.M)
    assert m, "không thấy khai báo `_DUONG_CAY_NGUON=(…)` trong setup-ssl.sh"
    duong_gac = set(m.group(1).split())

    # Khai báo mà không ai DÙNG là một cổng xanh giả. Buộc chính mảng ấy phải
    # là thứ được truyền cho `git status`.
    assert 'git status --porcelain -- "${_DUONG_CAY_NGUON[@]}"' in ma_setup_ssl, (
        "`_DUONG_CAY_NGUON` được khai nhưng `git status` không dùng nó — cổng "
        "đang gác một danh sách khác với danh sách được kiểm ở đây"
    )

    compose = _tai_compose(_COMPOSE)
    rc, ra, lenh = _chay_setup_ssl(tmp_path, STUB_CID_NGINX="cid-nginx-0001")
    assert rc == 0, f"lượt chạy đầy đủ không tới đích (rc={rc}):\n{ra}"
    ds_build: list[str] = []
    for d in lenh:
        lat = _lat_lenh_compose(d)
        if lat is not None and lat[0] == "build":
            ds_build += lat[2]
    assert ds_build, "Step 0 không build gì cả"

    def _chuan(p: str) -> str:
        return p[2:] if p.startswith("./") else p

    mong = {"docker-compose.yml"}
    for t in ds_build:
        b = compose["services"][t]["build"]
        mong.add(_chuan(b if isinstance(b, str) else b["context"]))

    assert duong_gac == mong, (
        "cổng cây nguồn lệch khỏi các `build.context` thật:\n"
        f"  script gác : {sorted(duong_gac)}\n"
        f"  compose đòi: {sorted(mong)}\n"
        f"  (service sắp build: {ds_build})"
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_break_glass_cay_nguon_la_bien_rieng_va_canh_bao_to(
    tmp_path, ma_setup_ssl: str
):
    """Lối thoát phải là BIẾN RIÊNG và phải hét lên khi được dùng.

    Một cờ dùng chung cho hai hàng rào là cách một hàng rào bị gỡ mà không ai
    định gỡ nó. Một lối thoát im lặng thì tệ hơn nữa: nó biến "owner cố ý bỏ
    qua" thành "không ai biết cổng đã tắt" — và bản ghi vận hành duy nhất về
    việc ảnh production không khớp commit nào sẽ không tồn tại.
    """
    # BIẾN RIÊNG: được ĐỌC đúng một lần, và lần đọc ấy là điều kiện của cổng.
    doc_bien = re.findall(r"\$\{QLTS_SSL_KIEM_CAY_NGUON[:\-]", ma_setup_ssl)
    assert len(doc_bien) == 1, (
        f"`QLTS_SSL_KIEM_CAY_NGUON` được đọc {len(doc_bien)} lần — lối thoát "
        "đang điều khiển nhiều hơn một thứ"
    )
    dong_dk = [
        d for d in ma_setup_ssl.splitlines() if "${QLTS_SSL_KIEM_CAY_NGUON" in d
    ][0]
    assert len(re.findall(r"\$\{", dong_dk)) == 1, (
        "điều kiện của cổng cây nguồn còn đọc biến khác ngoài "
        f"QLTS_SSL_KIEM_CAY_NGUON — lối thoát không còn là của riêng nó: {dong_dk.strip()}"
    )

    rc, ra, lenh = _chay_setup_ssl(
        tmp_path,
        STUB_GIT_BAN=" M nginx/x\n M Backend_FastAPI/y\n?? frontend/z",
        QLTS_SSL_KIEM_CAY_NGUON="0",
        STUB_CID_NGINX="cid-nginx-0001",
    )
    assert rc == 0, f"break-glass mà lượt chạy vẫn hỏng (rc={rc}):\n{ra}"
    assert ra.count("[WARN]") >= 5, (
        "break-glass chỉ cảnh báo lí nhí — một dòng warn lẫn trong log build là "
        f"thứ không ai đọc:\n{ra}"
    )
    assert "BREAK-GLASS" in ra and "THAO TÁC CÓ CHỦ ĐÍCH" in ra, (
        "văn bản cảnh báo không nói rõ đây là thao tác owner có chủ đích chứ "
        f"không phải đường đi thường:\n{ra}"
    )
    assert _vt_lenh(lenh, " build ") >= 0, (
        "break-glass được bật mà cổng vẫn chặn build — lối thoát chỉ là quảng "
        "cáo:\n" + "\n".join(lenh)
    )


# ---------------------------------------------------------------------------
# Đường vận hành: workflow deploy
# ---------------------------------------------------------------------------


def _dong_khong_comment(duong: Path) -> list[str]:
    return [d for d in _doc(duong).splitlines() if not d.lstrip().startswith("#")]


def test_workflow_pull_TRUOC_khi_chay_deploy_script():
    """Bash nạp script vào bộ nhớ lúc gọi — phải cập nhật cây TRƯỚC."""
    wf = _GOC / ".github" / "workflows" / "deploy.yml"
    if not wf.is_file():
        pytest.skip("không có .github/workflows/deploy.yml")
    dong = _dong_khong_comment(wf)

    def _vi_tri(mau: str) -> int:
        for i, d in enumerate(dong):
            if mau in d:
                return i
        return -1

    # Cây được cập nhật bằng `git pull --ff-only origin main` (bản cũ) HOẶC
    # `git fetch` + `git merge --ff-only "$SHA_MONG_DOI"` (bản ghim SHA — xem
    # tests/unit/test_deploy_ghim_sha.py). Bất biến cần canh là THỨ TỰ, không
    # phải tên lệnh; neo cứng vào chữ `git pull` làm guard đỏ oan ngay khi đường
    # ghim SHA thay nó, dù cây vẫn được cập nhật trước.
    #
    # `max` chứ không phải `min`: nếu có nhiều lệnh cập nhật cây thì lệnh CUỐI
    # CÙNG vẫn phải đứng trước lời gọi script.
    vt_pull = max(_vi_tri("git pull"), _vi_tri("git merge --ff-only"))
    # Neo vào LỜI GỌI, không vào chuỗi con `scripts/deploy.sh`: bản guard trước
    # lấy `max(_vi_tri("scripts/deploy.sh"), _vi_tri("deploy.sh"))`, mà chuỗi
    # thứ nhất là superset của chuỗi thứ hai nên CẢ HAI cùng trỏ về dòng
    # `test -f scripts/deploy.sh` — tức nó sắp thứ tự với phép kiểm tiền đề chứ
    # không phải với lời gọi. Dời lời gọi lên trên `git pull` mà test vẫn xanh.
    vt_chay = _vi_tri("bash scripts/deploy.sh")
    assert vt_pull != -1, "workflow deploy không cập nhật cây trước khi chạy script"
    assert vt_chay != -1, "workflow deploy không gọi `bash scripts/deploy.sh`"
    assert vt_pull < vt_chay, (
        "workflow chạy deploy.sh TRƯỚC khi pull — lần deploy đầu sau merge sẽ "
        "chạy bản script cũ"
    )
    assert "--ff-only" in "\n".join(dong), (
        "dùng `git pull --ff-only` để merge lạ không âm thầm xảy ra trên prod"
    )


def test_workflow_khong_chay_script_tu_tmp():
    """Chép script sang /tmp làm PROJECT_DIR suy từ BASH_SOURCE thành `/`."""
    wf = _GOC / ".github" / "workflows" / "deploy.yml"
    if not wf.is_file():
        pytest.skip("không có deploy.yml")
    assert "/tmp/deploy" not in "\n".join(_dong_khong_comment(wf)), (
        "workflow chạy deploy.sh từ /tmp — script suy PROJECT_DIR từ BASH_SOURCE "
        "nên project root sẽ thành `/`"
    )


# ---------------------------------------------------------------------------
# Cổng CI: gate phải NHÌN THẤY thứ nó canh
# ---------------------------------------------------------------------------

# Mọi đường dẫn mà chính tệp test này đọc. Sửa bất kỳ đường nào trong số đó đều
# có thể phá hợp đồng đóng gói — nên cả bộ phải nằm trong `paths:` của gate.
_DUONG_GUARD_DOC = [
    "docker-compose.yml",
    "docker-compose.rollback.yml",
    "nginx/Dockerfile",
    "nginx/templates/default.conf.template",
    "nginx/docker-entrypoint.d/10-qlts-kiem-bien.sh",
    "scripts/nginx-apply.sh",
    "scripts/nginx-verify.sh",
    "scripts/deploy.sh",
    "scripts/setup-ssl.sh",
    ".github/workflows/deploy.yml",
    "tests-e2e/nginx-packaging/docker-compose.nginx-test.yml",
]


def _khop_glob(duong: str, mau: str) -> bool:
    """Khớp kiểu `paths:` của GitHub Actions, đủ dùng cho các mẫu ta khai."""
    if mau.endswith("/**"):
        return duong.startswith(mau[:-2])
    if mau.endswith("/*"):
        return duong.startswith(mau[:-1]) and "/" not in duong[len(mau) - 1 :]
    return duong == mau


def test_bo_loc_paths_cua_gate_phu_moi_duong_ma_guard_doc():
    """Gate không nhìn thấy thứ nó canh thì nó không canh gì cả.

    `paths:` của `backend-test.yml` trước 13-08-2026 không có `docker-compose.yml`
    lẫn `nginx/**` — mà bộ guard này gần như CHỈ khẳng định về hai thứ đó. Nghĩa
    là đúng những sửa đổi nó sinh ra để chặn (mount lại `conf.d`, bỏ `DOMAIN`,
    dời template) lại là những sửa đổi khiến workflow không chạy: required check
    treo ở "expected, not run", và lối thoát tự nhiên là chạm bừa một tệp trong
    `Backend_FastAPI/`. Memory `ci-allowlist-tep-khong-duoc-gac`.
    """
    wf = _GOC / ".github" / "workflows" / "backend-test.yml"
    if not wf.is_file():
        pytest.skip("không có backend-test.yml")
    noi_dung = yaml.safe_load(_doc(wf))
    # `on:` là hằng `True` của YAML 1.1 khi safe_load — tra cả hai khoá.
    kich_hoat = noi_dung.get("on", noi_dung.get(True, {}))
    mau = kich_hoat.get("pull_request", {}).get("paths") or []
    assert mau, "backend-test.yml không có bộ lọc `paths:`"
    # `_TAI_LIEU_VAN_HANH` cũng phải nằm trong danh sách: guard tài liệu ĐỌC
    # từng tệp trong đó, nên một tệp không có mặt ở `paths:` là một tệp mà guard
    # canh trên giấy còn CI thì không bao giờ chạy để canh. `PRODUCTION_DEPLOY_
    # GUIDE.md` đã đúng vào ca đó.
    can_phu = _DUONG_GUARD_DOC + _TAI_LIEU_VAN_HANH
    thieu = [d for d in can_phu if not any(_khop_glob(d, m) for m in mau)]
    assert not thieu, (
        f"gate `pytest` KHÔNG chạy khi các đường sau đổi: {thieu}. "
        f"Bộ lọc hiện có: {mau}"
    )


# ---------------------------------------------------------------------------
# Override E2E: phải hỏi MODEL COMPOSE SAU KHI GỘP, không đọc YAML thô
# ---------------------------------------------------------------------------

_E2E = _GOC / "tests-e2e" / "nginx-packaging"
_E2E_OVERRIDE = _E2E / "docker-compose.nginx-test.yml"
_E2E_README = _E2E / "README.md"


def test_override_e2e_dung_override_cho_ports_va_profiles():
    """Lớp tĩnh — luôn chạy, kể cả khi không có Docker.

    Compose GỘP danh sách: `ports: []` không xoá cổng nào, và `profiles: [x]`
    NỐI vào chứ không thay, nên giá trị gộp thành `["production","x"]` và
    service vẫn khớp `--profile production`. Chỉ `!override` mới thay thật.
    """
    if not _E2E_OVERRIDE.is_file():
        pytest.skip("không có override E2E")
    tho = _doc(_E2E_OVERRIDE)
    assert not re.search(r"^\s*ports:\s*\[\]\s*$", tho, re.M), (
        "còn `ports: []` trần — nó KHÔNG gỡ cổng nào; Compose gộp danh sách"
    )
    assert re.search(r"profiles:\s*!override", tho), (
        "`profiles:` của certbot thiếu `!override` — giá trị gộp vẫn chứa "
        "`production`, nên `up -d` khởi động một certbot thật với vòng gia hạn "
        "12h sống qua cả lần khởi động lại máy"
    )


def _co_docker() -> bool:
    import shutil

    return shutil.which("docker") is not None


@pytest.mark.skipif(not _co_docker(), reason="cần Docker CLI để hỏi model Compose")
def test_model_compose_sau_khi_gop_dung_nhu_override_tuyen_bo(tmp_path):
    """Lớp hành vi — hỏi CHÍNH Compose, vì luật gộp không đọc được từ YAML thô.

    Bản trước khai `profiles: - khong-dung` và `ports: []` rồi coi như xong;
    một phép kiểm parse YAML cũng sẽ "thấy" đúng như thế và báo xanh. Chỉ khi
    hỏi `docker compose config` mới lộ ra giá trị gộp thật.

    Chỉ SKIP khi thật sự không nói chuyện được với Docker daemon. Mọi lỗi khác
    của `docker compose config` là FAIL: một bài kiểm biến lỗi thành skip thì
    nó chỉ còn là một dòng xanh, và đó đúng là lớp sai mà cả PR này đang vá.
    """
    import json
    import os
    import subprocess

    if not _E2E_OVERRIDE.is_file():
        pytest.skip("không có override E2E")

    # Tệp env rỗng, có thật, nằm ngoài repo — KHÔNG dùng `/dev/null` (trên
    # Windows nó bị hiểu thành một đường dẫn tương đối không tồn tại, và cả bài
    # kiểm rơi vào nhánh skip).
    env_rong = tmp_path / "rong.env"
    env_rong.write_text("", encoding="utf-8")

    moi_truong = {
        **os.environ,
        "MSYS_NO_PATHCONV": "1",
        "DOMAIN": "nginx-test.local",
        "POSTGRES_PASSWORD": "x",
        "NEXT_PUBLIC_API_URL": "http://x",
        "TEST_BACKEND_IMAGE": "busybox",
        "TEST_FRONTEND_IMAGE": "busybox",
        "QLTS_ENV_FILE": str(env_rong),
    }
    ket_qua = subprocess.run(
        [
            "docker", "compose",
            "-f", str(_COMPOSE),
            "-f", str(_E2E_OVERRIDE),
            "--profile", "production",
            "config", "--format", "json",
        ],
        cwd=str(_GOC),
        capture_output=True,
        text=True,
        env=moi_truong,
    )
    if ket_qua.returncode != 0:
        loi = ket_qua.stderr.lower()
        khong_co_daemon = any(
            d in loi
            for d in (
                "cannot connect to the docker daemon",
                "docker daemon is not running",
                "is not a docker command",
                "permission denied while trying to connect",
            )
        )
        if khong_co_daemon:
            pytest.skip(f"không nói chuyện được với Docker daemon: {ket_qua.stderr[:160]}")
        pytest.fail(f"`docker compose config` lỗi: {ket_qua.stderr[:600]}")

    dich_vu = json.loads(ket_qua.stdout)["services"]
    assert "certbot" not in dich_vu, (
        "certbot VẪN nằm trong stack kiểm sau khi gộp — `profiles` bị NỐI chứ "
        "không bị thay. Lệnh `up -d` trong README sẽ khởi động một certbot thật."
    )
    # KHÔNG khẳng định "postgres không publish cổng": trong `docker-compose.yml`
    # production, postgres vốn đã không publish gì (cổng 5433 chỉ có ở
    # `docker-compose.override.yml` của dev). Một khẳng định như thế đúng kể cả
    # khi `!override` bị gỡ sạch — tức nó không canh gì cả.
    # Khẳng định CÓ NỘI DUNG: sau khi gộp, không service nào được mở ra ngoài
    # loopback. Nó đúng cho hôm nay (chỉ nginx publish) và vẫn còn răng vào ngày
    # ai đó thêm cổng cho một service khác.
    lo_ra_ngoai = {
        ten: [p for p in dv.get("ports", []) if p.get("host_ip") not in ("127.0.0.1",)]
        for ten, dv in dich_vu.items()
        if any(p.get("host_ip") not in ("127.0.0.1",) for p in dv.get("ports", []))
    }
    assert not lo_ra_ngoai, (
        f"stack KIỂM đang mở cổng ra ngoài loopback sau khi gộp: {lo_ra_ngoai}. "
        "Nó chạy trên máy người phát triển và trên cùng host với stack thật."
    )
    cong_nginx = dich_vu["nginx"].get("ports", [])
    assert cong_nginx, "nginx của stack kiểm không publish cổng nào — E2E sẽ không gọi được"
    assert {str(p.get("published")) for p in cong_nginx} != {"80", "443"}, (
        "nginx của stack kiểm vẫn giữ 80/443 của production — `ports` bị GỘP "
        "chứ không bị thay"
    )


_ROLLBACK = _GOC / "docker-compose.rollback.yml"

# Bốn service ứng dụng có ảnh RIÊNG (`<project>-<service>`), nên rollback phải
# ghim đủ bốn. Lùi backend mà quên celery là chạy worker phiên bản MỚI trên lược
# đồ CSDL đã lùi.
_SERVICE_PHAI_LUI = ["backend", "celery-worker", "celery-beat", "frontend"]


def test_co_tep_rollback_ghim_anh_cu():
    assert _ROLLBACK.is_file(), (
        "thiếu docker-compose.rollback.yml — không có nó thì rollback phải sinh "
        "ad-hoc giữa lúc sự cố, đúng thứ runbook cấm"
    )
    noi_dung = _tai_compose(_ROLLBACK)["services"]
    assert sorted(noi_dung) == sorted(_SERVICE_PHAI_LUI), (
        f"rollback phải ghim ĐÚNG {sorted(_SERVICE_PHAI_LUI)}; hiện: {sorted(noi_dung)}"
    )


@pytest.mark.skipif(not _co_docker(), reason="cần Docker CLI để hỏi model Compose")
def test_model_compose_rollback_chon_dung_bon_anh_cu(tmp_path):
    """Bằng chứng hành vi, không phải bằng chứng chữ.

    Quy trình rollback cũ đọc trên giấy thì hợp lý và chạy thì exit 0 — chỉ có
    model Compose mới nói ra rằng không ảnh cũ nào được chọn.
    """
    import json
    import os
    import subprocess

    if not _ROLLBACK.is_file():
        pytest.skip("chưa có docker-compose.rollback.yml")
    env_rong = tmp_path / "rong.env"
    env_rong.write_text("", encoding="utf-8")
    moi_truong = {
        **os.environ,
        "MSYS_NO_PATHCONV": "1",
        "DOMAIN": "nginx-test.local",
        "POSTGRES_PASSWORD": "x",
        "NEXT_PUBLIC_API_URL": "http://x",
        "QLTS_ENV_FILE": str(env_rong),
        "QLTS_ROLLBACK_TAG": "tag-cu-kiem-thu",
    }

    def _config(moi_truong_chay):
        return subprocess.run(
            [
                "docker", "compose",
                "-f", str(_COMPOSE), "-f", str(_ROLLBACK),
                "--profile", "production", "config", "--format", "json",
            ],
            cwd=str(_GOC), capture_output=True, text=True, env=moi_truong_chay,
        )

    kq = _config(moi_truong)
    if kq.returncode != 0:
        loi = kq.stderr.lower()
        if "cannot connect to the docker daemon" in loi or "is not a docker command" in loi:
            pytest.skip(f"không nói chuyện được với Docker daemon: {kq.stderr[:160]}")
        pytest.fail(f"`docker compose config` lỗi: {kq.stderr[:600]}")

    dich_vu = json.loads(kq.stdout)["services"]
    for ten in _SERVICE_PHAI_LUI:
        s = dich_vu[ten]
        assert s.get("image") == f"qlts-{ten}:tag-cu-kiem-thu", (
            f"`{ten}` không được ghim về ảnh cũ; hiện image={s.get('image')!r}"
        )
        assert not s.get("build"), (
            f"`{ten}` vẫn còn `build:` — `up -d` sẽ dựng lại từ mã MỚI, tức "
            "không rollback gì cả"
        )
    assert dich_vu["nginx"].get("build"), (
        "nginx CỐ Ý vẫn build từ cây git (cấu hình của nó đi theo image); ghim "
        "thêm một tag ảnh là tạo nguồn chuẩn thứ hai"
    )

    # Quên tag phải ĐỔ, không được lặng lẽ dựng lại ảnh hiện hành.
    thieu_tag = {k: v for k, v in moi_truong.items() if k != "QLTS_ROLLBACK_TAG"}
    assert _config(thieu_tag).returncode != 0, (
        "thiếu QLTS_ROLLBACK_TAG mà lệnh vẫn xanh — đúng cái bẫy của quy trình cũ"
    )


_RUNBOOK = _GOC / "Documents" / "ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md"
_PREFLIGHT = _GOC / "scripts" / "rollback-preflight.sh"


def _khoi_rollback() -> list[tuple[int, str]]:
    r"""Các LỆNH trong §8.1 (khối rollback), kèm số dòng của dòng đầu lệnh.

    Dòng nối tiếp `\` được NỐI LẠI. Không nối thì guard mù: lệnh
        docker compose -f docker-compose.yml -f docker-compose.rollback.yml \
            --env-file .env.production --profile production up -d --wait \
            backend celery-worker celery-beat frontend
    có `docker compose` ở dòng 1 và tên service ở dòng 3, nên một phép kiểm
    theo từng dòng thấy "lệnh compose không chạm service nào" rồi bỏ qua. Bản
    nháp đầu của chính guard này đã xanh vô nghĩa đúng như vậy — 0/3 đột biến
    bị bắt — cho tới khi mỗi lệnh được đột biến riêng lẻ mới lộ ra.
    """
    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 8.1")
    j = noi_dung.index("### 8.2", i)
    truoc = noi_dung[:i].count("\n")
    ra: list[tuple[int, str]] = []
    trong = False
    dang_noi: tuple[int, str] | None = None
    for k, dong in enumerate(noi_dung[i:j].splitlines(), start=truoc + 1):
        if dong.lstrip().startswith("```"):
            trong = not trong
            continue
        if not trong or not dong.strip() or dong.lstrip().startswith("#"):
            continue
        if dang_noi is not None:
            so_dau, truoc_do = dang_noi
            gop = truoc_do + " " + dong.strip()
        else:
            so_dau, gop = k, dong
        if gop.rstrip().endswith("\\"):
            dang_noi = (so_dau, gop.rstrip()[:-1].rstrip())
        else:
            dang_noi = None
            ra.append((so_dau, gop))
    if dang_noi is not None:
        ra.append(dang_noi)
    return ra


def test_kiem_tai_san_rollback_chay_TRUOC_khi_cham_CSDL():
    """Đảo thứ tự này là tự đưa mình vào trạng thái không tiến không lùi.

    Bản trước khôi phục CSDL rồi mới đi tìm ảnh cũ. Ảnh không còn (registry đã
    dọn, tag đã trôi, máy đã prune) thì lúc phát hiện, `pg_restore --clean` đã
    nạp lại lược đồ CŨ trong khi mã đang chạy vẫn là mã MỚI.
    """
    assert _PREFLIGHT.is_file(), "thiếu scripts/rollback-preflight.sh"
    dong = _khoi_rollback()
    vt_kiem = next((i for i, (_, d) in enumerate(dong) if "rollback-preflight.sh" in d), -1)
    vt_db = next((i for i, (_, d) in enumerate(dong) if "pg_restore" in d), -1)
    assert vt_kiem != -1, "§8.1 không gọi scripts/rollback-preflight.sh"
    assert vt_db != -1, "§8.1 không còn bước khôi phục CSDL?"
    assert vt_kiem < vt_db, (
        "kiểm tài sản rollback nằm SAU `pg_restore` — CSDL bị đụng trước khi biết "
        "có đường lùi hay không"
    )


def test_rollback_khong_nuot_loi():
    """`docker pull ... || echo "DUNG LAI"` trả exit 0 rồi chạy tiếp."""
    pham = [
        f"{so}: {d.strip()[:80]}"
        for so, d in _khoi_rollback()
        if re.search(r"\|\|\s*echo", d)
    ]
    assert not pham, (
        "§8.1 còn nuốt lỗi bằng `|| echo` — trong cửa sổ rollback thì một lệnh "
        f"hỏng phải DỪNG, không phải in ra một câu rồi đi tiếp: {pham}"
    )


def test_moi_lenh_sau_khi_lui_deu_giu_tep_rollback():
    """Thiếu một `-f` ở bước sau là tự hoàn tác rollback, im lặng.

    Đo model: có tệp rollback thì `backend image=qlts-backend:<cũ> build=false`;
    thiếu nó thì `image=None build=true` — tức `up` dựng lại từ mã MỚI. Bản
    trước đúng vào bẫy ấy ở Step "restore env/config" và Step "unlock".
    """
    dong = _khoi_rollback()
    bat_dau = next(
        (i for i, (_, d) in enumerate(dong)
         if "rollback-preflight.sh" in d or "docker-compose.rollback.yml" in d),
        None,
    )
    assert bat_dau is not None, "§8.1 không hề nhắc tới tài sản rollback"
    pham = []
    for so, d in dong[bat_dau:]:
        if "docker compose" not in d:
            continue
        if not any(s in d for s in _SERVICE_PHAI_LUI):
            continue  # nginx build từ cây git là đúng, không cần tệp rollback
        if "-f docker-compose.rollback.yml" not in d:
            pham.append(f"{so}: {d.strip()[:90]}")
    assert not pham, (
        "lệnh compose chạm service đã lùi mà THIẾU `-f docker-compose.rollback.yml`:\n  "
        + "\n  ".join(pham)
    )


def test_tag_rollback_lay_tu_container_dang_chay_khong_tu_latest():
    """`qlts-<service>:latest` là tag DI ĐỘNG.

    Nó có thể đã trôi sang một bản build khác từ trước khi ta chạm vào, nên tag
    từ nó là tạo ra tài sản rollback SAI ngay lúc tạo — và không gì phát hiện
    được về sau. `.Image` của container đang chạy mới là "phiên bản đang phục vụ".
    """
    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 5.4")
    j = noi_dung.index("### 5.5", i)
    khoi = noi_dung[i:j]
    assert not re.search(r"docker tag\s+\"?qlts-\$?\{?S?\}?[^\"\s]*:latest", khoi), (
        "§5.4 còn tag từ `:latest` — phải lấy `.Image` của container đang chạy"
    )
    assert "ps -q" in khoi and "{{.Image}}" in khoi, (
        "§5.4 phải suy ảnh từ container đang chạy (`ps -q` → `inspect .Image`)"
    )
    assert "MANIFEST" in khoi, (
        "§5.4 phải ghi manifest (service · container ID · image ID · reference) — "
        "đó là thứ `rollback-preflight.sh` đối chiếu để phát hiện tag đã trôi"
    )


_GUIDE = _GOC / "Documents" / "PRODUCTION_DEPLOY_GUIDE.md"


def test_runbook_push_registry_khong_bi_nuot_loi():
    """`set +e` trước vòng `docker push` biến "đẩy hỏng" thành im lặng.

    Hậu quả không dừng ở đó: tag khi ấy chỉ tồn tại TRÊN MÁY, mà preflight lại
    `docker image inspect` trước — thấy tag cục bộ nên không bao giờ `pull`.
    Cổng T-1d vì thế ĐẠT cho một tài sản rollback sẽ bốc hơi ngay khi máy chủ
    mất hoặc bị prune.
    """
    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 5.4")
    j = noi_dung.index("### 5.5", i)
    # Chỉ giữ dòng LỆNH: chú thích của chính khối này có nhắc cả `set -e` lẫn
    # `docker push`, nên neo vào chuỗi thô sẽ khớp trúng câu văn và guard xanh
    # vô nghĩa — bản nháp đầu đã đúng như vậy (0/1 đột biến bị bắt).
    lenh = [d for d in noi_dung[i:j].splitlines() if d.strip() and not d.lstrip().startswith("#")]
    vt_push = next((k for k, d in enumerate(lenh) if re.match(r"\s*docker push\b", d)), -1)
    assert vt_push != -1, "§5.4 không còn dòng LỆNH `docker push`?"
    truoc = "\n".join(lenh[:vt_push])
    vt_bat = max(k for k, d in enumerate(lenh[:vt_push]) if d.strip() == "set -e")
    vt_tat = max((k for k, d in enumerate(lenh[:vt_push]) if d.strip() == "set +e"), default=-1)
    assert "set -e" in truoc, "vòng push không nằm trong phạm vi `set -e`"
    assert vt_bat > vt_tat, (
        "`set +e` được bật lại TRƯỚC vòng `docker push` — lỗi đẩy ảnh sẽ bị nuốt, "
        "và preflight vẫn ĐẠT vì tag cục bộ khiến nó không bao giờ `pull`"
    )


def test_preflight_kiem_anh_co_that_NGOAI_may():
    """Ảnh có trên máy này không chứng minh còn rollback được sau khi mất máy."""
    ma = _ma_lenh(_PREFLIGHT)
    assert "docker manifest inspect" in ma, (
        "preflight chỉ kiểm ảnh cục bộ — phải hỏi registry bằng "
        "`docker manifest inspect` (không tải ảnh) mới biết tài sản có ở ngoài máy"
    )
    assert "QLTS_ROLLBACK_LOCAL_ONLY" in ma, (
        "phải có đường chấp nhận rủi ro TƯỜNG MINH cho ca không dùng registry — "
        "im lặng bỏ qua thì lại thành cổng xanh giả"
    )


def test_rollback_khoi_phuc_cay_nginx_chinh_xac():
    """`cp -r backup/* nginx/` để lại tệp mà bản LỖI thêm vào.

    Image dựng ra là bản LAI giữa cấu hình cũ và chính cấu hình vừa gây sự cố,
    nên rollback có thể tái tạo lại đúng sự cố.
    """
    khoi = "\n".join(d for _, d in _khoi_rollback())
    assert not re.search(r"cp\s+-r\s+\S*nginx_backup\S*\s+nginx/", khoi), (
        "còn `cp -r … nginx/` — chép chồng KHÔNG xoá tệp chỉ có ở bản lỗi"
    )
    assert re.search(r"git checkout\s+\"?\$\w+\"?\s+--\s+nginx/", khoi), (
        "phải `git checkout <pre-cutover-sha> -- nginx/` để cây khớp CHÍNH XÁC"
    )
    assert "git clean -fd nginx/" in khoi, (
        "thiếu `git clean -fd nginx/` — tệp bản lỗi thêm vào vẫn ở lại"
    )
    # Neo vào LỆNH GHI, không vào chuỗi "git-rev" — chuỗi ấy còn xuất hiện ở
    # dòng `awk` đọc lại và ở chú thích mô tả cột manifest, nên một phép kiểm
    # `"git-rev" in ...` vẫn xanh sau khi lệnh ghi đã bị gỡ.
    assert re.search(r"printf[^\n]*git-rev[^\n]*>>\s*\"?\$MANIFEST", _doc(_RUNBOOK)), (
        "§5.4 phải GHI revision git vào manifest; không có nó thì Step 5 không "
        "biết `git checkout` về đâu"
    )


def test_deploy_guide_build_ca_nginx():
    """nginx nay có `build:` + tag cố định — bỏ nó ra là dùng lại ảnh CŨ.

    `up -d` không tự dựng lại khi tag `qlts-nginx:local` đã tồn tại, nên thay
    đổi template/entrypoint lặng lẽ không được deploy. Đường `scripts/deploy.sh`
    build `--parallel` toàn bộ nên miễn nhiễm; chỉ đường deploy TAY mới hở.
    """
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    pham = []
    for so, dong in _dong_lenh_trong_tai_lieu(_GUIDE):
        if "docker compose" not in dong or " build " not in dong:
            continue
        if "..." in dong:
            continue
        # Chỉ bắt lần build ĐẦY ĐỦ (cả backend lẫn frontend). Build một service
        # là chủ ý — "chỉ deploy backend" thì dựng lại nginx là thừa; ca đụng
        # `nginx/` đã có khối riêng chỉ sang `scripts/nginx-apply.sh`.
        day_du = "backend" in dong and "frontend" in dong
        if day_du and "nginx" not in dong:
            pham.append(f"{so}: {dong.strip()[:95]}")
    assert not pham, (
        "lệnh build ĐẦY ĐỦ trong hướng dẫn deploy tay bỏ sót `nginx` — máy đã có "
        "tag `qlts-nginx:local` sẽ dùng lại ảnh CŨ:\n  " + "\n  ".join(pham)
    )
    assert "nginx-apply.sh" in _doc(_GUIDE), (
        "hướng dẫn deploy tay phải chỉ đường cho ca đụng `nginx/` sang "
        "scripts/nginx-apply.sh (dựng candidate + đo request thật)"
    )


def test_preflight_dinh_nghia_moi_ham_no_goi():
    """Hàm gọi mà chưa định nghĩa = `exit 127` dưới `set -e`.

    `warn` từng được gọi ở nhánh `QLTS_ROLLBACK_LOCAL_ONLY=1` mà không hề được
    định nghĩa. Nhánh ấy chưa từng được chạy nên không ai thấy — đúng loại đường
    thoát hiểm chỉ hỏng đúng lúc cần tới.
    """
    ma = _ma_lenh(_PREFLIGHT)
    dinh_nghia = set(re.findall(r"^\s*(\w+)\s*\(\)\s*\{", ma, re.M))
    goi = set(re.findall(r"^\s*(log|warn|error)\b", ma, re.M))
    thieu = sorted(goi - dinh_nghia)
    assert not thieu, f"gọi hàm chưa định nghĩa (exit 127 dưới `set -e`): {thieu}"


def test_preflight_kiem_git_sha_TRUOC_khi_cham_csdl():
    """Manifest hỏng / commit biến mất chỉ lộ ra SAU `pg_restore` là quá muộn."""
    ma = _ma_lenh(_PREFLIGHT)
    # Neo vào ĐÚNG phép kiểm commit (`^{commit}`), không vào chuỗi `git cat-file`
    # chung: script còn một `cat-file -e …:nginx` nữa, nên phép kiểm lỏng vẫn
    # xanh sau khi phép kiểm commit đã bị gỡ.
    assert re.search(r"git cat-file -e[^\n]*\^\{commit\}", ma), (
        "preflight phải xác nhận commit pre-cutover CÒN TỒN TẠI; §8.1 Step 5 mới "
        "`git checkout` thì lúc đó CSDL đã bị `pg_restore --clean` phá"
    )
    assert re.search(r"\[0-9a-f\]\{40\}", ma), (
        "phải kiểm git-rev là SHA ĐẦY ĐỦ 40 ký tự — SHA rút gọn có thể mơ hồ"
    )
    assert re.search(r"cat-file -e[^\n]*:nginx", ma), (
        "phải xác nhận commit đó CÓ thư mục nginx/"
    )


def test_preflight_doi_chieu_DIGEST_chu_khong_chi_ton_tai_tag():
    """Tag ở registry có thể đã bị đẩy đè bởi một ảnh KHÁC.

    `docker manifest inspect <tag>` chỉ chứng minh "có gì đó ở đó", không chứng
    minh đó là ảnh cũ. Digest thì bất biến.
    """
    ma = _ma_lenh(_PREFLIGHT)
    assert re.search(r"docker manifest inspect\s+\"?\$DIGEST", ma), (
        "phải hỏi registry BẰNG DIGEST đã ghi, không bằng tag"
    )
    # Neo vào lệnh ĐỌC trường offsite, không vào chuỗi `# offsite` — chuỗi ấy
    # còn nằm trong chính thông điệp lỗi, nên phép kiểm lỏng vẫn xanh sau khi
    # lệnh đọc đã bị gỡ.
    assert re.search(r'awk[^\n]*\$1=="# offsite"[^\n]*\$MANIFEST', ma), (
        "phải ĐỌC trường offsite từ manifest — mất host thì còn ảnh trên registry "
        "nhưng không biết digest nào là ảnh cũ"
    )
    assert "RepoDigests" in _doc(_RUNBOOK), (
        "§5.4 phải ghi digest (`docker inspect --format '{{index .RepoDigests 0}}'`) "
        "vào manifest sau mỗi lần push"
    )


def _lenh_ghep_trong_tai_lieu(duong: Path) -> list[tuple[int, str]]:
    r"""Như `_dong_lenh_trong_tai_lieu` nhưng NỐI các dòng nối tiếp `\`.

    Không nối thì mọi guard đọc theo dòng đều né được bằng đúng một lần xuống
    dòng: `--profile production \` + `    up -d` là cùng MỘT lệnh mà phép kiểm
    từng dòng không thấy gì cả. Đã vấp đúng lỗi này (0/3 đột biến bị bắt) nên
    nó thành helper chung thay vì mỗi nơi tự chống một kiểu.

    Chú thích cuối dòng cũng bị cắt: `up -d --wait backend  # KHÔNG restart`
    không được tính chữ trong lời nhắc là một tên service.
    """
    ra: list[tuple[int, str]] = []
    for so, dong in _dong_lenh_trong_tai_lieu(duong):
        if ra and ra[-1][1].rstrip().endswith("\\"):
            ra[-1] = (ra[-1][0], ra[-1][1].rstrip()[:-1].rstrip() + " " + dong.strip())
        else:
            ra.append((so, dong))
    return [(so, re.split(r"\s+#", d, maxsplit=1)[0]) for so, d in ra]


def _up_d_cham_nginx(duong: Path, chi_production: bool = False) -> list[str]:
    """Các lệnh `up -d` hoặc TRẦN, hoặc gọi thẳng tên nginx."""
    pham = []
    for so, dong in _lenh_ghep_trong_tai_lieu(duong):
        if chi_production and not (
            "--profile production" in dong or ".env.production" in dong
        ):
            continue  # mục DEV cố ý dùng override — áp luật production vào là sai
        if not re.search(r"\bup -d\b", dong):
            continue
        # Bỏ CỜ, không bỏ tham số theo sau: `--\S+(\s+\S+)?` sẽ nuốt luôn
        # `nginx` trong `up -d --wait nginx` và guard mất đúng thứ nó canh.
        sau = re.sub(r"--\S+", "", dong.split("up -d", 1)[1]).strip()
        if not sau:
            pham.append(f"{so}: `up -d` trần — {dong.strip()[:80]}")
        elif re.search(r"\bnginx\b", sau):
            pham.append(f"{so}: `up -d` liệt kê nginx — {dong.strip()[:80]}")
    return pham


def test_deploy_guide_khong_up_d_TRAN_cham_nginx():
    """`up -d` trần thay thẳng nginx đang phục vụ, bỏ qua cổng candidate."""
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    pham = _up_d_cham_nginx(_GUIDE)
    assert not pham, (
        "nginx phải được áp qua `scripts/nginx-apply.sh`, không qua `up -d`:\n  "
        + "\n  ".join(pham)
    )
    assert "nginx-apply.sh" in _doc(_GUIDE)


def test_preflight_doi_chieu_image_id_chu_khong_chi_ton_tai():
    """Ảnh "có mặt" không chứng minh nó là ảnh CŨ."""
    ma = _ma_lenh(_PREFLIGHT)
    assert "{{.Id}}" in ma, "preflight không đọc image ID thật để đối chiếu"
    assert "config --images" in ma, (
        "preflight phải hỏi model Compose xem ảnh nào SẼ được dùng, không chỉ "
        "kiểm ảnh có tồn tại"
    )
    assert re.search(r"grep\s+-qxF", ma), (
        "so khớp ảnh phải KHỚP CẢ DÒNG (`grep -qxF`): một `grep -E` lỏng sẽ xanh "
        "khi chỉ một trong bốn ảnh khớp"
    )


def test_ca_hoi_quy_e2e_dung_no_deps():
    """Thiếu `--no-deps`, một ca chưa hề chạy vẫn báo lại trạng thái của ca trước.

    `up -d --force-recreate nginx-candidate` mà không `--no-deps` thì tập `up`
    là {postgres, redis, backend, frontend, nginx-candidate} và `--force-recreate`
    đụng tất: `backend` chạy lại `alembic upgrade head` + nạp Casbin, và nếu nó
    không kịp `service_healthy` thì lệnh `up` BỎ DỞ trước khi chạm candidate —
    container của ca trước còn đứng nguyên, và người chạy đọc trạng thái của nó
    rồi đánh dấu ca này PASS.
    """
    # Lớp 1 — nơi lệnh THẬT SỰ chạy.
    ma_apply = _ma_lenh(_APPLY)
    lenh_candidate = re.search(r"[^\n]*up -d[^\n]*nginx-candidate[^\n]*", ma_apply)
    assert lenh_candidate, "nginx-apply.sh không dựng nginx-candidate"
    assert "--no-deps" in lenh_candidate.group(0), (
        f"lệnh dựng candidate thiếu `--no-deps`: {lenh_candidate.group(0).strip()}"
    )

    # Lớp 2 — tài liệu E2E phải gọi ĐÚNG script đó, không chép tay vòng lặp.
    if not _E2E_README.is_file():
        pytest.skip("không có README E2E")
    tho = _doc(_E2E_README)
    assert "nginx-apply.sh" in tho, (
        "README E2E tự chép một vòng `up -d` thay vì gọi scripts/nginx-apply.sh — "
        "bản chép chỉ chứng minh giả định của người viết tài liệu"
    )
    for dong in tho.splitlines():
        if "up -d" in dong and "nginx-candidate" in dong:
            assert "--no-deps" in dong, f"ca hồi quy thiếu `--no-deps`: {dong.strip()}"


def test_readme_e2e_khong_chep_de_env_production():
    """`cp fixture .env.production` phá tệp bí mật không khôi phục được."""
    if not _E2E_README.is_file():
        pytest.skip("không có README E2E")
    pham = [
        d.strip()
        for d in _doc(_E2E_README).splitlines()
        if re.search(r"^\s*cp\s+\S+\s+\.env\.production", d)
    ]
    assert not pham, (
        f"README E2E hướng dẫn ghi đè .env.production: {pham}. Dùng "
        "`QLTS_ENV_FILE` — docker-compose.yml đã khai "
        "`env_file: ${QLTS_ENV_FILE:-.env.production}` chính vì việc này."
    )


# ---------------------------------------------------------------------------
# Đường OFF-HOST của rollback: registry · digest · bản kê ngoài máy
#
# Ba guard dưới đây canh cùng một sự thật: tài sản rollback chỉ có giá trị khi
# nó còn dùng được SAU KHI mất chính máy chủ này. Mọi phép kiểm "có trên máy"
# đều ĐẠT ở T-1d và vô dụng ở T+0.
# ---------------------------------------------------------------------------

_CLAUDE_MD = _GOC / "CLAUDE.md"


def _lenh_5_4() -> str:
    r"""Chỉ DÒNG LỆNH của §5.4, đã nối `\`, đã bỏ chú thích.

    Bỏ chú thích là bắt buộc: khối này giải thích khá dài về `docker push`,
    `# offsite`, `set -e`… nên guard neo vào chuỗi thô sẽ khớp trúng câu văn và
    xanh cả sau khi lệnh thật đã bị gỡ. Đã đúng như vậy hai lần.
    """
    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 5.4")
    j = noi_dung.index("### 5.5", i)
    tho = "\n".join(
        d for d in noi_dung[i:j].splitlines()
        if d.strip() and not d.lstrip().startswith("#")
    )
    return re.sub(r"\\\n\s*", " ", tho)


def test_runbook_push_ref_phai_co_namespace():
    """`docker push qlts-backend:<tag>` KHÔNG đẩy vào kho của dự án.

    Ref không có namespace được Docker phân giải thành
    `docker.io/library/qlts-backend` — không gian tên của ảnh thư viện chính
    thức, ta không sở hữu, nên push bị từ chối. Cả đường off-host của bản nháp
    trước vì thế chưa từng chạy nổi một lần, mà preflight vẫn ĐẠT vì tag cục bộ
    có mặt: đúng hình dạng "cổng xanh cho tài sản không tồn tại".
    """
    lenh = _lenh_5_4()
    assert re.search(r"QLTS_ROLLBACK_REGISTRY:\?", lenh), (
        "§5.4 phải ĐỔ NGAY khi chưa khai registry (`${QLTS_ROLLBACK_REGISTRY:?…}`); "
        "thiếu nó thì `docker push` nhắm vào docker.io/library"
    )
    assert re.search(r'REMOTE="\$\{QLTS_ROLLBACK_REGISTRY\}/qlts-', lenh), (
        "ref đem push phải mang namespace của kho dự án"
    )
    pham = [
        d.strip()[:90]
        for d in lenh.splitlines()
        if re.match(r"\s*docker push\b", d) and "$REMOTE" not in d
    ]
    assert not pham, (
        "còn `docker push` một ref không mang registry của dự án:\n  "
        + "\n  ".join(pham)
    )


def test_runbook_5_4_chay_duoc_o_che_do_local_only():
    """`${QLTS_ROLLBACK_REGISTRY:?…}` ở MỨC KHỐI thì local-only chết ngay tại đó.

    Tài liệu bảo "máy không có registry thì khai QLTS_ROLLBACK_LOCAL_ONLY=1",
    nhưng dòng `:?` lại chạy vô điều kiện — nên người trực phải tự hiểu mà bỏ
    qua một đoạn giữa. Đã đo bằng cách chạy nguyên khối §5.4 của bản trước ở chế
    độ local-only: đổ đúng tại dòng ấy, chưa kịp ghi được gì. Một quy trình cứu
    hộ đòi đọc-hiểu-rồi-chọn-tay là quy trình sẽ sai vào lúc 3 giờ sáng.

    Guard neo vào CẤU TRÚC (`if` … `else` … dòng `:?` … `fi`), không neo vào thụt
    lề: thụt lề không đổi ngữ nghĩa bash nên một guard theo cột sẽ báo đỏ cho
    bản viết đúng và bỏ lọt bản viết sai.
    """
    dong = _lenh_5_4().splitlines()
    vt_if = next(
        (k for k, d in enumerate(dong)
         if re.match(r'\s*if \[ "\$QLTS_ROLLBACK_LOCAL_ONLY" = "1" \]', d)), -1)
    vt_reg = next(
        (k for k, d in enumerate(dong) if "QLTS_ROLLBACK_REGISTRY:?" in d), -1)
    assert vt_if != -1, "§5.4 không rẽ nhánh theo QLTS_ROLLBACK_LOCAL_ONLY"
    assert vt_reg != -1, "§5.4 không còn đòi registry ở nhánh dùng registry"
    assert vt_if < vt_reg, (
        "dòng đòi registry chạy TRƯỚC nhánh local-only — chế độ local-only sẽ "
        "chết tại đó dù tài liệu bảo nó dùng được"
    )
    giua = dong[vt_if:vt_reg]
    assert any(d.strip() == "else" for d in giua), (
        "giữa `if local-only` và dòng đòi registry không có `else` — dòng ấy "
        "không nằm trong nhánh nào cả"
    )
    assert not any(d.strip() == "fi" for d in giua), (
        "nhánh đã đóng bằng `fi` TRƯỚC dòng đòi registry — nó lại về mức khối"
    )


def test_runbook_truyen_co_local_only_xuong_preflight():
    """"Nhớ tự export" không phải một cơ chế.

    §5.4 diễn tập bằng `rollback-preflight.sh` ngay tại T-1d. Nếu lời gọi ấy chỉ
    truyền tag thì ở chế độ local-only preflight vẫn đi hỏi registry và đỏ —
    trong khi khối vừa CỐ Ý không push gì cả.
    """
    dong = [d for d in _lenh_5_4().splitlines() if "rollback-preflight.sh" in d]
    assert dong, "§5.4 không còn diễn tập bằng rollback-preflight.sh"
    thieu = [d.strip()[:90] for d in dong if "QLTS_ROLLBACK_LOCAL_ONLY" not in d]
    assert not thieu, (
        "lời gọi preflight không truyền QLTS_ROLLBACK_LOCAL_ONLY:\n  "
        + "\n  ".join(thieu)
    )


def test_runbook_ghi_digest_cua_DUNG_repo_vua_push():
    """`{{index .RepoDigests 0}}` lấy phần tử ĐẦU, không phải phần tử ĐÚNG.

    Một ảnh từng được push vào nhiều repo mang nhiều RepoDigests; phần tử 0 khi
    ấy có thể là digest của repo KHÁC — preflight sẽ kéo về một ảnh không phải
    ảnh cũ, và mọi phép so ID sau đó đều nói dối theo cùng một hướng.
    """
    lenh = _lenh_5_4()
    assert "{{range .RepoDigests}}" in lenh, (
        "phải duyệt HẾT RepoDigests rồi lọc, không lấy `index … 0`"
    )
    assert re.search(r"grep\s+\"\^\$\{QLTS_ROLLBACK_REGISTRY\}/qlts-", lenh), (
        "phải lọc digest theo đúng repo vừa push"
    )


def test_runbook_upload_ban_ke_HOAN_CHINH():
    """Bản kê đưa ra ngoài phải TỰ ĐỦ, nếu không nó tự làm mình đỏ.

    Bản nháp trước `cp` TRƯỚC rồi mới `printf '# offsite'` vào bản local, nên
    tệp lên S3 thiếu đúng cái dòng mà preflight bắt buộc phải có. Khôi phục bản
    kê từ S3 về một máy trắng rồi chạy preflight = đỏ ngay. Đường cứu hộ hỏng
    đúng vào lúc dùng tới nó.
    """
    lenh = _lenh_5_4()
    dong = lenh.splitlines()
    vt_offsite = next(
        (k for k, d in enumerate(dong)
         if re.search(r'printf[^\n]*# offsite[^\n]*>>\s*"\$MANIFEST"', d)), -1)
    vt_cp = next(
        (k for k, d in enumerate(dong) if re.match(r'\s*cp\s+"\$MANIFEST"', d)), -1)
    assert vt_offsite != -1, "§5.4 không còn GHI dòng '# offsite' vào manifest"
    assert vt_cp != -1, "§5.4 không còn copy manifest ra tệp đem đi offsite"
    assert vt_offsite < vt_cp, (
        "`cp` chạy TRƯỚC khi manifest hoàn chỉnh — bản đưa lên S3 sẽ thiếu dòng "
        "'# offsite' mà chính preflight bắt buộc phải có"
    )
    # Neo vào HÀNH VI (đẩy checksum đi kèm), không vào TÊN CÔNG CỤ: đích offsite
    # nay có thể là S3 hoặc một remote rclone, và guard khoá vào `aws` sẽ đỏ khi
    # đổi provider dù bất biến vẫn được giữ nguyên.
    assert re.search(r"day_offsite[^\n]*\.sha256", lenh), (
        "phải upload checksum đi kèm — không có nó thì bản tải về không kiểm được"
    )
    assert re.search(r"cmp -s[^\n]*offsite-check", lenh), (
        "phải tải NGƯỢC bản kê về và so nội dung: lệnh upload trả 0 không chứng "
        "minh object đọc lại được (quyền, KMS, lifecycle, sai bucket/remote)"
    )


def test_preflight_keo_anh_bang_DIGEST_khong_bang_TAG():
    """Host bị prune + tag registry đã trôi = pull theo tag kéo về ảnh MỚI.

    Script khi ấy dừng vì ID lệch, trong khi ảnh cũ vẫn nằm nguyên ở registry
    dưới digest cũ. Câu "tag trôi thành không liên quan" chỉ đúng khi KHÔNG còn
    chỗ nào hỏi registry bằng tag nữa.
    """
    ma = _ma_lenh(_PREFLIGHT)
    # Neo vào THAM SỐ của `pull`, không vào cả dòng: dòng ấy còn mang thông điệp
    # lỗi có nhắc `$DIGEST`, nên phép kiểm `"$DIGEST" not in d` vẫn xanh sau khi
    # lệnh đã bị đổi sang `pull "$REF"`. Bản nháp đầu đúng như vậy — lỗi này tái
    # phát lần thứ ba trong cùng đợt, và lần nào cũng chỉ ma trận đột biến bắt được.
    pham = []
    for d in ma.splitlines():
        m = re.search(r"\bdocker pull\s+(\S+)", d)
        if m and "$DIGEST" not in m.group(1):
            pham.append(f"{d.strip()[:70]}  ← kéo `{m.group(1)}`")
    assert not pham, (
        "còn `docker pull` theo TAG — phải kéo bằng digest đã ghi:\n  "
        + "\n  ".join(pham)
    )
    assert re.search(r'docker tag "\$DIGEST" "\$REF"', ma), (
        "kéo bằng digest xong phải tự đóng lại tag mà docker-compose.rollback.yml ghim"
    )


def test_preflight_tu_choi_digest_khong_co_namespace():
    """Manifest ghi `qlts-backend@sha256:…` nghĩa là ảnh KHÔNG ở ngoài máy.

    Ref ấy phân giải thành `docker.io/library/qlts-backend`. Nó tồn tại trong
    manifest chỉ khi §5.4 chạy bằng bản cũ — tức đường off-host chưa từng có.
    """
    ma = _ma_lenh(_PREFLIGHT)
    assert 'REPO="${DIGEST%%@*}"' in ma, (
        "preflight không tách phần repo ra khỏi digest thì không kiểm được namespace"
    )
    assert "docker.io/library/*" in ma, (
        "phải từ chối tường minh kho thư viện chính thức"
    )


def test_preflight_chung_minh_ban_ke_offsite_DOC_DUOC():
    """Chuỗi đường dẫn không rỗng không chứng minh gì cả.

    Object có thể chưa bao giờ được upload, đã bị lifecycle dọn, hoặc không đọc
    lại được (thiếu quyền, sai KMS key, sai bucket). Phải TẢI VỀ và so nội dung.
    """
    ma = _ma_lenh(_PREFLIGHT)
    assert re.search(r'_offsite_lay "\$OFFSITE"', ma), (
        "preflight chỉ kiểm chuỗi không rỗng — phải tải object về mới biết nó còn"
    )
    assert "sha256sum" in ma, "phải đối chiếu checksum của bản tải về"
    assert re.search(r'cmp -s "\$TMP_OFFSITE/manifest\.txt" "\$MANIFEST"', ma), (
        "phải chứng minh bản offsite khớp bản local; nếu không thì khôi phục từ "
        "nó rồi chạy chính script này sẽ tự đỏ"
    )


def _service_co_build() -> set[str]:
    dv = _tai_compose(_COMPOSE).get("services", {})
    return {t for t, c in dv.items() if isinstance(c, dict) and c.get("build")}


def test_deploy_guide_build_du_moi_anh_ma_up_se_dung():
    """Bốn service ứng dụng có ảnh RIÊNG — Compose đặt tên `<project>-<service>`.

    Không service nào khai `image:` chung, nên build mỗi `backend` rồi `up` cả
    ba là chạy worker phiên bản CŨ trên mã backend mới; ở nhánh rollback thì
    ngược lại — worker ở lại bản MỚI trên lược đồ CSDL vừa lùi. Cả hai đều là
    lệch âm thầm: không log, không healthcheck nào bắt được.
    """
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    co_build = _service_co_build()
    assert {"backend", "celery-worker", "celery-beat", "frontend"} <= co_build, (
        f"model compose đã đổi (service có build: {sorted(co_build)}) — đếm lại "
        "trước khi tin guard này"
    )
    pham = []
    da_build: set[str] = set()
    for so, dong in _lenh_ghep_trong_tai_lieu(_GUIDE):
        if "docker compose" not in dong or "..." in dong:
            continue
        if " build " in dong:
            da_build = {
                t for t in re.split(r"\s+", dong.split(" build ", 1)[1]) if t in co_build
            }
            continue
        if re.search(r"\bup -d\b", dong):
            can = {
                t for t in re.split(r"\s+", re.sub(r"--\S+", "", dong.split("up -d", 1)[1]))
                if t in co_build
            }
            thieu = can - da_build
            if thieu:
                pham.append(
                    f"{so}: `up -d` dựng {sorted(thieu)} mà lệnh build ngay trước "
                    f"đó chỉ có {sorted(da_build) or 'không gì'}"
                )
    assert not pham, (
        "hướng dẫn deploy tay dựng service bằng ảnh CŨ vì không build nó:\n  "
        + "\n  ".join(pham)
    )


# ---------------------------------------------------------------------------
# `build nginx` phải đứng TRƯỚC `nginx-apply.sh`
# ---------------------------------------------------------------------------
# `scripts/nginx-apply.sh` KHÔNG build. Service nginx ghim tag cố định
# `qlts-nginx:local`, nên `up -d` dùng lại ảnh đã có tag ấy mà không dựng lại.
# Cấu hình thì đi theo IMAGE (`nginx/Dockerfile` COPY `templates/`). Ba vế ấy
# cộng lại cho đúng một kết cục: cây `nginx/` khác ảnh đang chạy ⇒ candidate đo
# ảnh CŨ, `up -d` áp ảnh CŨ, và script in ra "cấu hình mới đã được áp".
#
# Đó là ca fail-OPEN, nên không healthcheck nào bắt. Thứ duy nhất chặn được là
# thứ tự lệnh trong tài liệu vận hành — mà trước guard này không ai canh nó.
#
# CỐ Ý loại `tests-e2e/nginx-packaging/README.md` khỏi phạm vi, cùng lý lẽ với
# `_SCRIPT_PRODUCTION`: nó chạy trên một stack CÔ LẬP (`-p qltsngx`) và phần
# lớn lời gọi `nginx-apply.sh` ở đó CỐ TÌNH nạp một cấu hình hỏng qua override
# `kn*.yml` để chứng minh cổng candidate từ chối. Bắt nó build trước mỗi ca là
# đòi dựng lại ảnh cho một đột biến không nằm trong cây — vừa thừa vừa sai
# nghĩa. Danh sách tường minh thì đọc được và cãi được; một luật áp bừa sẽ bị
# tắt đi hoặc bị lách bằng ngoại lệ rải rác.
_TAI_LIEU_CHAM_PRODUCTION = [
    "Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md",
    "Documents/PRODUCTION_DEPLOY_GUIDE.md",
]


def _chi_so_khoi(duong: Path) -> dict[int, int]:
    """Số hiệu dòng ➜ chỉ số khối ``` chứa nó.

    Cùng luật mở/đóng khối với `_dong_lenh_trong_tai_lieu` (ở đó khối được đếm
    ngầm): chỉ `lstrip().startswith("```")` mới lật trạng thái, nên fence nằm
    trong trích dẫn `> ```bash` KHÔNG tính — đúng như bộ đọc lệnh đang làm.

    Vì sao cần chỉ số khối: một khối ``` là đơn vị người trực CHÉP ra chạy.
    Cho phép `build` ở khối này phủ cho `apply` ở khối khác tức là giả định
    người ta chạy tuần tự cả tài liệu — giả định đó chính là chỗ hở.
    """
    ra: dict[int, int] = {}
    trong_khoi = False
    khoi = 0
    for so, dong in enumerate(_doc(duong).splitlines(), 1):
        if dong.lstrip().startswith("```"):
            if not trong_khoi:
                khoi += 1
            trong_khoi = not trong_khoi
            continue
        if trong_khoi:
            ra[so] = khoi
    return ra


_CHUOI_NHAY = re.compile(r"\"[^\"]*\"|'[^']*'")


def _bo_chuoi(dong: str) -> str:
    """Bỏ phần nằm trong nháy — chỉ giữ lại phần thật sự là LỆNH.

    CLAUDE.md §3 ghi đúng cái bẫy này: biểu thức khớp trúng **dòng thông báo**
    thay vì dòng lệnh. Đã vấp thật ở chính guard này: dòng
    `… || { echo "nginx/ còn tệp UNTRACKED sau git clean — DỪNG"; … }`
    làm `_GIT_VIET_LAI_CAY` tưởng vừa có một `git clean` chạy, nên nó xoá hiệu
    lực của cổng đứng ngay TRÊN nó và guard đỏ ở một tài liệu ĐÚNG.

    Chỉ dùng cho câu hỏi "dòng này CÓ PHẢI lệnh X không". KHÔNG dùng cho các mẫu
    cổng: `git diff --quiet "$PRE_SHA" -- nginx/` mất `"$PRE_SHA"` thì không còn
    phân biệt được với phép so `HEAD` — mà phân biệt ấy chính là hai luồng.
    """
    return _CHUOI_NHAY.sub(" ", dong)


# Lệnh git VIẾT LẠI CÂY LÀM VIỆC. Sau một trong số này, mọi lần build trước đó
# hết giá trị: ảnh `qlts-nginx:local` đang mang cấu hình của cây CŨ.
#
# LUÔN hỏi qua `_bo_chuoi` — xem lý do ở đó.
#
# Đây đúng là hình dạng của Step 5 phần rollback (`git checkout "$PRE_SHA" --
# nginx/` + `git clean -fd nginx/`), và nếu không có vế này thì lần build ở
# Step 1 sẽ "phủ" luôn cho Step 5 — đã đo: đột biến đổi `build nginx` của Step 5
# thành `build backend` KHÔNG bị bắt. `fetch`/`push`/`log`/`status` không đổi
# cây nên cố ý không nằm trong danh sách.
_GIT_VIET_LAI_CAY = re.compile(
    r"\bgit\s+(checkout|switch|clean|pull|reset|restore|stash|apply|merge|rebase|worktree)\b"
)


def _la_build_nginx(dong: str) -> bool:
    """Lệnh `docker compose ... build ... nginx`.

    Đòi `nginx` là MỘT THAM SỐ sau `build`, không phải chữ `nginx` ở bất kỳ đâu
    trong dòng: `... --env-file .env.production build backend` nằm cạnh một
    đường dẫn có chữ nginx vẫn phải bị coi là KHÔNG build nginx.
    """
    if not _co_lenh_compose(dong) or " build " not in dong:
        return False
    sau = re.split(r"\s+", dong.split(" build ", 1)[1].strip())
    return "nginx" in sau


def test_moi_loi_goi_nginx_apply_deu_co_build_nginx_dung_truoc():
    """Bỏ `build nginx` = áp ảnh CŨ mà vẫn báo ĐẠT.

    Một lần build được coi là còn hiệu lực cho tới khi gặp MỘT trong hai mốc:
      * hết khối ``` — khối là đơn vị người trực chép ra chạy, nên cho build ở
        khối này phủ cho apply ở khối khác là giả định người ta chạy tuần tự cả
        tài liệu, mà đó chính là chỗ hở;
      * một lệnh git viết lại cây làm việc (`_GIT_VIET_LAI_CAY`) — sau nó, ảnh
        đang có mang cấu hình của cây CŨ.

    Hệ quả đã biết và CHẤP NHẬN: trong phần rollback, Step 7 (mở băng) nằm cùng
    khối với Step 5 và không có lệnh git nào xen giữa, nên nó được lần build ở
    Step 5 phủ. Điều đó ĐÚNG khi chạy tuần tự — giữa hai bước chỉ có curl/psql
    và một lần sửa `.env.production`, không gì chạm `nginx/`, mà đổi env thì
    `up -d` tự recreate vì model lệch, không cần ảnh mới. Guard này vì thế
    KHÔNG mô hình hoá ca người trực NHẢY THẲNG vào Step 7; đó là một quyết định
    còn mở của tài liệu, không phải chỗ guard quên.
    """
    assert set(_TAI_LIEU_CHAM_PRODUCTION) <= set(_TAI_LIEU_VAN_HANH), (
        "_TAI_LIEU_CHAM_PRODUCTION đã trôi khỏi _TAI_LIEU_VAN_HANH — một tên bị "
        "đổi/xoá ở một danh sách mà không ở danh sách kia"
    )
    pham = []
    da_soi = 0
    for ten in _TAI_LIEU_CHAM_PRODUCTION:
        d = _GOC / ten
        if not d.is_file():
            continue
        if "scripts/nginx-apply.sh" not in _doc(d):
            continue
        khoi_cua = _chi_so_khoi(d)
        da_build: set[int] = set()
        thay_apply = 0
        for so, dong in _lenh_ghep_trong_tai_lieu(d):
            khoi = khoi_cua.get(so)
            if _GIT_VIET_LAI_CAY.search(_bo_chuoi(dong)):
                da_build.clear()
            if _la_build_nginx(dong):
                da_build.add(khoi)
            if "scripts/nginx-apply.sh" not in dong:
                continue
            thay_apply += 1
            if khoi not in da_build:
                pham.append(
                    f"{ten}:{so}: `nginx-apply.sh` chạy mà chưa có "
                    f"`docker compose ... build nginx` nào còn hiệu lực đứng "
                    f"trước (cùng khối ```, sau mốc git gần nhất) — "
                    f"{dong.strip()[:70]}"
                )
        # §11: cổng phải NHÌN THẤY thứ nó canh. Văn bản có lời gọi mà bộ đọc
        # lệnh không thấy dòng nào nghĩa là lệnh đã rơi ra ngoài khối ```, hoặc
        # bị ngắt dòng kiểu mà bộ nối không hiểu — guard xanh vô nghĩa.
        assert thay_apply, (
            f"{ten}: văn bản có `scripts/nginx-apply.sh` mà bộ đọc lệnh không "
            "thấy lời gọi nào — guard đang canh hụt, không phải tài liệu đã sạch"
        )
        da_soi += 1
    assert da_soi == len(_TAI_LIEU_CHAM_PRODUCTION), (
        f"chỉ soi được {da_soi}/{len(_TAI_LIEU_CHAM_PRODUCTION)} tài liệu chạm "
        "production — một tên trong _TAI_LIEU_CHAM_PRODUCTION đã bị đổi/xoá, "
        "hoặc lời gọi `nginx-apply.sh` đã biến mất khỏi tệp; guard đang canh hụt"
    )
    assert not pham, (
        "lời gọi `nginx-apply.sh` không có `build nginx` đứng trước: apply sẽ "
        "dựng candidate từ ảnh CŨ, đo ảnh CŨ, áp ảnh CŨ và báo ĐẠT:\n  "
        + "\n  ".join(pham)
    )


# ---------------------------------------------------------------------------
# Cổng phải là LỆNH CHẶN, không phải một dòng chữ
# ---------------------------------------------------------------------------
_THOAT_SAU_HOAC = re.compile(r"\bexit\b\s*(?P<ma>[^\s;}\"']*)")


def _la_lenh_chan(dong: str) -> bool:
    """Nhánh THẤT BẠI của dòng này có thoát KHÁC 0 không.

    Bốn hình dạng đều trượt, và cả bốn đều đã gặp ngoài đời:

      * `A && echo "…"` — chỉ chạy khi A THÀNH CÔNG. A hỏng thì im lặng hoàn
        toàn. Đây đúng là ca `valid-until-phai-la-lenh-chan`: cổng in đủ chữ để
        người đọc tin là đã chặn, trong khi nó chưa chặn lần nào (approval trễ
        17 giây vì thế).
      * `A || echo "…"` — có nhánh hỏng, nhưng nhánh đó IN RỒI ĐI TIẾP. Tinh vi
        hơn hẳn ca `&&` vì nó *trông* như một cổng.
      * `A` trần — chỉ đặt mã thoát cho dòng CUỐI của script.
      * `A || { …; exit 0; }` — dừng và báo THÀNH CÔNG. Tệ hơn không có cổng,
        vì nó dừng đúng lúc rồi in ra màu xanh.

    Cố ý KHÔNG nhận `git status --porcelain` làm cổng dù nó là dòng người ta hay
    viết ra: nó chỉ in. Toàn bộ quyết định ② của owner nằm ở chỗ ấy.
    """
    if "||" not in dong:
        return False
    sau = dong.split("||", 1)[1]
    m = _THOAT_SAU_HOAC.search(sau)
    if m is None:
        return False
    return m.group("ma") != "0"


# Những phép hỏi TRẠNG THÁI mà tài liệu dùng làm cổng. Mỗi mẫu ở đây là một câu
# hỏi mà câu trả lời "không đạt" PHẢI dừng quy trình.
#
# `git rev-parse` cố ý hẹp lại thành `--verify`: `git rev-parse HEAD` ở §5.4 là
# một phép ĐỌC để ghi manifest, không phải cổng, và bắt nó `|| exit 1` là vô
# nghĩa. `git status` KHÔNG có mặt — nó chỉ in, và đó là cả vấn đề.
_CONG_TRANG_THAI_CAY = [
    (
        re.compile(r"\bgit\s+diff\s+--quiet\b"),
        "so cây làm việc với một mốc git",
    ),
    (
        re.compile(r"\bgit\s+ls-files\s+--others\b"),
        "hỏi tệp untracked (thứ `git diff` KHÔNG BAO GIỜ thấy)",
    ),
    (
        re.compile(r"\bgit\s+rev-parse\s+--verify\b"),
        "kiểm một ref còn phân giải được",
    ),
    (
        re.compile(r"\bdocker\s+image\s+inspect\b[^\n]*\{\{\.Id\}\}"),
        "đối chiếu image ID thật",
    ),
]

# Sàn §11: guard phải NHÌN THẤY thứ nó canh. Xoá sạch cổng rồi guard xanh vì
# "không có dòng nào vi phạm" là đúng cái bẫy mà mục này tồn tại để chặn.
_SAN_CONG_TRANG_THAI = 10


def test_moi_cong_trang_thai_deu_la_lenh_chan_khong_phai_dong_chu():
    """Đổi `|| { … exit 1; }` thành `&& echo …` (hoặc `|| echo …`) phải ĐỎ.

    Owner chốt vòng 2: điều kiện trước Step 7 và cổng git-status phải là **lệnh
    chặn thật**, không phải chú thích và không phải một dòng in. Test này canh
    đúng HÌNH DẠNG ấy, tách khỏi câu hỏi "cổng có tồn tại không" (test kế bên)
    để mỗi bất biến có một đột biến giết riêng.
    """
    pham = []
    da_thay = 0
    for ten in _TAI_LIEU_CHAM_PRODUCTION:
        d = _GOC / ten
        if not d.is_file():
            continue
        for so, dong in _lenh_ghep_trong_tai_lieu(d):
            for mau, mo_ta in _CONG_TRANG_THAI_CAY:
                if not mau.search(dong):
                    continue
                da_thay += 1
                if not _la_lenh_chan(dong):
                    pham.append(
                        f"{ten}:{so}: cổng «{mo_ta}» KHÔNG chặn — nhánh thất "
                        f"bại không `exit` khác 0: {dong.strip()[:100]}"
                    )
    assert da_thay >= _SAN_CONG_TRANG_THAI, (
        f"chỉ thấy {da_thay} cổng trạng thái trong tài liệu chạm production "
        f"(sàn {_SAN_CONG_TRANG_THAI}) — cổng đã bị xoá bớt, hoặc bộ đọc lệnh "
        "không còn nhìn thấy chúng. Guard xanh ở đây là xanh vô nghĩa."
    )
    assert not pham, (
        "cổng chỉ IN ra chứ không chặn — quy trình chạy tiếp như thể đã đạt:\n  "
        + "\n  ".join(pham)
    )


# `build nginx` dựng từ CÂY LÀM VIỆC. Cây bẩn ⇒ phần trôi lên thẳng production.
# Nên mọi `build nginx` phải có CẢ HAI cổng đứng trước, vì chúng mù ở hai chỗ
# khác nhau: `git diff` không thấy untracked, `git ls-files --others` không thấy
# tệp được theo dõi đã bị sửa.
_CAP_CONG_TRUOC_BUILD = [
    (
        re.compile(r"\bgit\s+diff\s+--quiet\b"),
        "`git diff --quiet <mốc> -- nginx/ …` (tệp được theo dõi bị sửa/xoá)",
    ),
    (
        re.compile(r"\bgit\s+ls-files\s+--others\b[^\n]*nginx/"),
        "`git ls-files --others -- nginx/` (tệp untracked — `COPY` nhặt, "
        "`git diff` không thấy)",
    ),
]

# CỐ Ý chỉ một tệp. `PRODUCTION_DEPLOY_GUIDE.md:149` cũng có `build nginx` +
# `nginx-apply.sh` mà KHÔNG có cổng cây sạch — đã đo. Nó nằm ngoài phạm vi sửa
# của đợt này (một lát khác đang giữ tệp), nên thay vì nới luật cho vừa hiện
# trạng, nợ được ghim bằng một phép kiểm NGƯỢC ở cuối test: ngày cổng được thêm
# vào guide, CI đỏ và bảo đưa tên nó sang danh sách trên.
_TAI_LIEU_BAT_BUOC_CONG_CAY_SACH = [
    "Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md",
]
_TAI_LIEU_CON_NO_CONG_CAY_SACH = [
    "Documents/PRODUCTION_DEPLOY_GUIDE.md",
]


def test_moi_build_nginx_deu_co_cong_cay_sach_chan_truoc():
    """Xoá cổng mà giữ `build nginx` = dựng cây bẩn lên production, im lặng.

    Hiệu lực của một cổng hết khi gặp MỘT trong hai mốc — cùng luật với
    `test_moi_loi_goi_nginx_apply_deu_co_build_nginx_dung_truoc`:
      * hết khối ``` (khối là đơn vị người trực chép ra chạy);
      * một lệnh git VIẾT LẠI CÂY (`_GIT_VIET_LAI_CAY`) — sau `git checkout
        "$PRE_SHA" -- nginx/` thì phép so cũ nói về một cây không còn tồn tại.

    Vế thứ hai chính là chỗ HAI LUỒNG tách nhau, và guard cố ý KHÔNG ép chúng
    dùng chung một lệnh: luồng bình thường so với `HEAD`, luồng rollback (sau
    `git checkout`) so với `$PRE_SHA`. Ép `HEAD` vào Step 5 sẽ đỏ ở đúng ca đang
    làm đúng, và người trực sẽ học cách bỏ qua cổng.
    """
    pham = []
    da_soi = 0
    for ten in _TAI_LIEU_BAT_BUOC_CONG_CAY_SACH:
        d = _GOC / ten
        assert d.is_file(), f"{ten}: không còn tệp — guard mất đối tượng"
        khoi_cua = _chi_so_khoi(d)
        # (chỉ số cổng) ➜ {khối đã có cổng ấy còn hiệu lực}
        con_hieu_luc: dict[int, set[int]] = {i: set() for i in range(len(_CAP_CONG_TRUOC_BUILD))}
        thay_build = 0
        for so, dong in _lenh_ghep_trong_tai_lieu(d):
            khoi = khoi_cua.get(so)
            if _GIT_VIET_LAI_CAY.search(_bo_chuoi(dong)):
                for tap in con_hieu_luc.values():
                    tap.clear()
            for i, (mau, _) in enumerate(_CAP_CONG_TRUOC_BUILD):
                if mau.search(dong) and _la_lenh_chan(dong):
                    con_hieu_luc[i].add(khoi)
            if not _la_build_nginx(dong):
                continue
            thay_build += 1
            for i, (_, ten_cong) in enumerate(_CAP_CONG_TRUOC_BUILD):
                if khoi not in con_hieu_luc[i]:
                    pham.append(
                        f"{ten}:{so}: `build nginx` chạy mà chưa có cổng CHẶN "
                        f"{ten_cong} nào còn hiệu lực đứng trước (cùng khối "
                        f"```, sau mốc git gần nhất)"
                    )
        assert thay_build, (
            f"{ten}: không thấy `build nginx` nào — guard đang canh hụt, không "
            "phải tài liệu đã sạch"
        )
        da_soi += 1
    assert da_soi == len(_TAI_LIEU_BAT_BUOC_CONG_CAY_SACH)
    assert not pham, (
        "`build nginx` dựng từ CÂY LÀM VIỆC; thiếu cổng là đưa phần trôi lên "
        "production giữa cửa sổ đóng băng:\n  " + "\n  ".join(pham)
    )

    # Ratchet cho món nợ đã đo, không phải một ngoại lệ vĩnh viễn.
    for ten in _TAI_LIEU_CON_NO_CONG_CAY_SACH:
        d = _GOC / ten
        if not d.is_file():
            continue
        co_cong = any(
            mau.search(dong) and _la_lenh_chan(dong)
            for so, dong in _lenh_ghep_trong_tai_lieu(d)
            for mau, _ in _CAP_CONG_TRUOC_BUILD
        )
        assert not co_cong, (
            f"{ten} nay ĐÃ có cổng cây sạch dạng lệnh chặn — chuyển tên nó từ "
            "_TAI_LIEU_CON_NO_CONG_CAY_SACH sang _TAI_LIEU_BAT_BUOC_CONG_CAY_SACH "
            "để luật áp thật. Đây là tin tốt, không phải hồi quy."
        )


# ---------------------------------------------------------------------------
# Step 7 (mở băng trong rollback): KHÔNG build lại ⇒ phải chứng minh đủ NĂM điều
# ---------------------------------------------------------------------------
# Owner chốt phương án B: không build lần hai giữa cửa sổ rollback. Giá của
# quyết định ấy là năm tiền đề phải còn đúng, và chúng phải được kiểm bằng LỆNH
# THOÁT. Danh sách dưới đây là đúng năm điều owner nêu, giữ nguyên số hiệu để
# đọc chéo được với chú thích trong runbook.
_NAM_PHEP_KIEM_STEP7 = [
    (
        "①",
        re.compile(r"\bgit\s+rev-parse\s+--verify\b[^\n]*PRE_SHA"),
        "$PRE_SHA còn phân giải được thành commit",
    ),
    (
        "②",
        re.compile(r"\bgit\s+diff\s+--quiet\s+\"?\$\{?PRE_SHA\}?[^\n]*nginx/"),
        "nginx/ vẫn khớp $PRE_SHA (phép so của LUỒNG ROLLBACK — không phải HEAD)",
    ),
    (
        "③",
        re.compile(r"\bgit\s+ls-files\s+--others\b[^\n]*nginx/"),
        "không có tệp untracked dưới nginx/",
    ),
    (
        "④",
        re.compile(r"\bgit\s+diff\s+--quiet\s+HEAD\b[^\n]*docker-compose\.yml"),
        "docker-compose.yml không trôi (phép so của LUỒNG BÌNH THƯỜNG — HEAD)",
    ),
    (
        "⑤",
        re.compile(r"\bdocker\s+image\s+inspect\b[^\n]*\{\{\.Id\}\}"),
        "ảnh qlts-nginx:local vẫn ĐÚNG ID đã ghi ở Step 5",
    ),
]

# Dòng GHI LẠI image ID ở Step 5. Không có nó thì điều ⑤ không có gì để đối
# chiếu, và một phép so với biến rỗng sẽ... vẫn xanh nếu viết ẩu.
_GHI_IMAGE_ID = re.compile(
    r"^(?P<bien>[A-Za-z_][A-Za-z0-9_]*)=\$\(\s*docker\s+image\s+inspect\b[^)]*\{\{\.Id\}\}"
)


def test_step7_khong_build_lai_thi_phai_chung_minh_du_nam_dieu():
    """Phương án B chỉ đúng khi năm tiền đề của nó được KIỂM, không được TIN.

    Vùng được soi là đoạn giữa lời gọi `nginx-apply.sh` của Step 5 và lời gọi
    của Step 7 — cố ý neo vào HAI lời gọi cuối chứ không vào số dòng: một đột
    biến dời nguyên cụm năm phép kiểm lên ngay sau `build nginx` của Step 5
    (giữ nguyên từng ký tự, tổng số dòng không đổi) sẽ làm chúng vô nghĩa với
    Step 7, và cách neo này bắt được đúng ca ấy.

    Vòng 1 đã ghi rằng ca "người trực nhảy thẳng vào Step 7" nằm NGOÀI phạm vi
    guard. Nay nó có điều kiện chặn thật nên được đưa VÀO: điều ⑤ chính là thứ
    bắt được ca đó — shell mới thì `$NGINX_IMG_SAU_BUILD` rỗng và cổng đỏ.
    """
    d = _RUNBOOK
    assert d.is_file(), "không còn RUNBOOK — guard mất đối tượng"
    khoi_cua = _chi_so_khoi(d)
    lenh = _lenh_ghep_trong_tai_lieu(d)

    # Neo vào `docker-compose.rollback.yml`, KHÔNG vào `rollback-preflight.sh`:
    # preflight còn được nhắc ở §5.4 (khối khác) nên nó nhận diện ra HAI khối —
    # đã đo, guard đỏ ngay lần chạy đầu. Tệp override rollback thì chỉ xuất hiện
    # như một LỆNH ở đúng §8.1.
    khoi_81 = {
        khoi_cua.get(so)
        for so, dong in lenh
        if "docker-compose.rollback.yml" in dong
    }
    assert len(khoi_81) == 1, (
        "không xác định được DUY NHẤT khối §8.1 (khối có lệnh dùng "
        f"`docker-compose.rollback.yml`): {sorted(khoi_81)} — guard đang canh hụt"
    )
    khoi = khoi_81.pop()
    trong_khoi = [(so, dong) for so, dong in lenh if khoi_cua.get(so) == khoi]

    apply_o = [so for so, dong in trong_khoi if "scripts/nginx-apply.sh" in dong]
    assert len(apply_o) >= 2, (
        f"khối §8.1 chỉ có {len(apply_o)} lời gọi `nginx-apply.sh` — không neo "
        "được vùng Step 5 ➜ Step 7; guard đang canh hụt"
    )
    dau, cuoi = apply_o[-2], apply_o[-1]
    vung = [(so, dong) for so, dong in trong_khoi if dau < so < cuoi]
    assert vung, f"vùng Step 5 ➜ Step 7 (dòng {dau}..{cuoi}) rỗng — canh hụt"

    thieu = []

    # Phương án B: KHÔNG build lần hai. Đổi sang A là một quyết định của owner,
    # và khi đó chính test này phải đổi cùng lúc với chú thích Step 7.
    build_lai = [so for so, dong in vung if _la_build_nginx(dong)]
    if build_lai:
        thieu.append(
            f"vùng Step 5 ➜ Step 7 có `build nginx` ở dòng {build_lai} — owner "
            "chốt phương án B (KHÔNG build lần hai). Đổi phương án thì sửa cả "
            "chú thích Step 7 và test này, đừng sửa một bên"
        )

    for nhan, mau, mo_ta in _NAM_PHEP_KIEM_STEP7:
        khop = [(so, dong) for so, dong in vung if mau.search(dong)]
        if not khop:
            thieu.append(f"{nhan} VẮNG MẶT: {mo_ta}")
        elif not any(_la_lenh_chan(dong) for _, dong in khop):
            thieu.append(
                f"{nhan} có mặt nhưng KHÔNG CHẶN (chỉ in ra rồi đi tiếp): "
                f"{mo_ta} — {khop[0][1].strip()[:90]}"
            )

    # Điều ① còn một vế: biến rỗng nghĩa là shell này KHÔNG phải shell đã chạy
    # Step 5. `git diff --quiet "" -- nginx/` khi ấy so với cây làm việc và
    # KHÔNG đỏ — một cổng xanh giả đúng lúc cần nó nhất.
    if not any(
        re.search(r"\[\s*-n\s+\"\$\{?PRE_SHA", dong) and _la_lenh_chan(dong)
        for _, dong in vung
    ):
        thieu.append(
            "① thiếu vế `[ -n \"$PRE_SHA\" ] || … exit`: mở shell mới giữa "
            "Step 5 và Step 7 thì biến rỗng và mọi phép so sau đó xanh giả"
        )

    # Cross-link: điều ⑤ phải đối chiếu với ĐÚNG biến mà Step 5 đã ghi.
    ghi = [
        (so, m)
        for so, dong in trong_khoi
        if so < dau
        for m in [_GHI_IMAGE_ID.match(dong.strip())]
        if m
    ]
    if not ghi:
        thieu.append(
            "Step 5 KHÔNG ghi lại image ID sau `build nginx` "
            "(`VAR=$(docker image inspect --format '{{.Id}}' …)`) — điều ⑤ "
            "không còn gì để đối chiếu"
        )
    else:
        so_ghi, m = ghi[-1]
        bien = m.group("bien")
        dong_ghi = dict(trong_khoi)[so_ghi]
        if not _la_lenh_chan(dong_ghi):
            thieu.append(
                f"Step 5:{so_ghi}: dòng ghi image ID không chặn — `docker image "
                "inspect` hỏng thì biến rỗng và Step 7 so với rỗng"
            )
        if not any(
            mau.search(dong) and bien in dong and _la_lenh_chan(dong)
            for _, mau, _ in _NAM_PHEP_KIEM_STEP7[-1:]
            for _, dong in vung
        ):
            thieu.append(
                f"điều ⑤ không đối chiếu với biến `{bien}` mà Step 5 ghi — một "
                "phép `docker image inspect` không so với gì thì chỉ là một "
                "dòng log"
            )

    assert not thieu, (
        "Step 7 bỏ `build nginx` (phương án B) mà KHÔNG chứng minh đủ tiền đề — "
        "ảnh được áp có thể không còn là ảnh Step 5 đã dựng và đã đo:\n  "
        + "\n  ".join(thieu)
    )


def test_claude_md_khong_day_lenh_production_cham_nginx():
    """CLAUDE.md tự mâu thuẫn thì phần đọc trước sẽ thắng.

    Mục Docker ở đầu tệp dạy `--profile production up -d` trần, trong khi mục
    "Nginx & Deploy" ở cuối nói nginx chỉ được áp qua `nginx-apply.sh`. Phần
    được đọc trước là phần đầu — và nó cuốn nginx vào, thay thẳng container
    đang phục vụ bằng một cấu hình chưa đo lần nào.

    Chỉ soi dòng CHẠM PRODUCTION: mục dev cố ý dùng `docker compose up -d` với
    override, áp luật production lên đó là bẻ gãy hướng dẫn đúng.
    """
    if not _CLAUDE_MD.is_file():
        pytest.skip("không có CLAUDE.md")
    pham = _up_d_cham_nginx(_CLAUDE_MD, chi_production=True)
    assert not pham, (
        "CLAUDE.md dạy lệnh production chạm thẳng nginx:\n  " + "\n  ".join(pham)
    )
    assert "nginx-apply.sh" in _doc(_CLAUDE_MD), (
        "CLAUDE.md phải chỉ đường áp nginx qua cổng candidate"
    )


def test_claude_md_lenh_production_ghim_docker_compose_yml():
    """Thiếu `-f docker-compose.yml` là Compose tự nạp override DEV lên production."""
    if not _CLAUDE_MD.is_file():
        pytest.skip("không có CLAUDE.md")
    pham = [
        f"{so}: {d.strip()[:90]}"
        for so, d in _lenh_ghep_trong_tai_lieu(_CLAUDE_MD)
        if ("--profile production" in d or ".env.production" in d)
        and _co_lenh_compose(d)
        and "-f docker-compose.yml" not in d
    ]
    assert not pham, (
        "lệnh production trong CLAUDE.md thiếu `-f docker-compose.yml`:\n  "
        + "\n  ".join(pham)
    )


# =============================================================================
# Offsite provider — bản kê phải ra được khỏi máy KHÔNG phụ thuộc `aws`
# =============================================================================
#
# Đo trên prod 25-08-2026: máy chủ KHÔNG có `aws` CLI, nhưng CÓ `rclone` với
# remote `gdrive-crypt:` mà cron backup CSDL đã dùng và đã đo end-to-end. Bản
# trước của cả §5.4 lẫn preflight đóng cứng vào `aws s3 cp`, nên đường off-host
# **chưa từng chạy nổi một lần** trên chính máy nó sinh ra để phục vụ — và điều
# đó không lộ ra, vì nhánh `QLTS_ROLLBACK_LOCAL_ONLY=1` vẫn ĐẠT.

def _khoi_offsite_loai() -> list[str]:
    """Các nhánh `case` của `_offsite_loai`, theo ĐÚNG thứ tự trong script.

    Kiểm tĩnh chứ không `subprocess bash`: trên Windows, `bash` mà Python tìm
    thấy có thể là launcher WSL, và nó treo thay vì chạy — guard khi ấy đỏ vì
    môi trường chứ không vì mã. Thứ tự nhánh là thứ duy nhất cần khẳng định, và
    nó đọc được tất định từ chính script.
    """
    ma = _doc(_PREFLIGHT)
    i = ma.index("_offsite_loai() {")
    j = ma.index("esac", i)
    return [d.strip() for d in ma[i:j].splitlines() if ")" in d and ";;" in d]


def test_preflight_nhan_dien_provider_dung_thu_tu():
    """`s3://x` cũng khớp mẫu `?*:*` — thứ tự `case` là bản chất, không phải khẩu vị.

    Để nhánh rclone lên trước thì MỌI đường S3 bị gọi bằng rclone. Và `https://`
    phải rơi vào "không nhận ra" chứ không được đoán bừa là rclone: đoán sai
    provider chỉ làm thông báo lỗi trỏ sai hướng đúng vào lúc cần nó nhất.
    """
    nhanh = _khoi_offsite_loai()
    assert nhanh, "không đọc được các nhánh `case` của _offsite_loai"

    def vi_tri(mau: str) -> int:
        return next((k for k, d in enumerate(nhanh) if d.startswith(mau)), -1)

    vt_s3 = vi_tri("s3://*)")
    vt_scheme = vi_tri("*://*)")
    vt_rclone = vi_tri("?*:*)")
    assert vt_s3 != -1, "thiếu nhánh nhận diện `s3://`"
    assert vt_scheme != -1, (
        "thiếu nhánh chặn URL có scheme khác — `https://…` sẽ bị coi là rclone"
    )
    assert vt_rclone != -1, "thiếu nhánh nhận diện remote rclone `<remote>:<path>`"
    assert vt_s3 < vt_rclone, (
        "nhánh `?*:*` (rclone) đứng TRƯỚC `s3://*` — mọi đường S3 sẽ bị gọi bằng rclone"
    )
    assert vt_scheme < vt_rclone, (
        "nhánh `*://*` đứng SAU `?*:*` — `https://…` sẽ bị nhận nhầm là remote rclone"
    )
    assert "aws" in nhanh[vt_s3] and "rclone" in nhanh[vt_rclone], (
        "nhánh nhận diện không trả đúng tên provider"
    )


def test_preflight_ho_tro_rclone_khong_doi_aws_cho_moi_dich():
    """Máy prod không có `aws`. Đòi nó cho một đích rclone là chặn nhầm.

    Bản trước gọi `command -v aws || error` NGAY khi vào nhánh offsite, trước cả
    khi biết đường dẫn thuộc provider nào — nên trên chính máy production, cổng
    rollback không thể ĐẠT bằng bất kỳ cách nào ngoài LOCAL_ONLY.
    """
    ma = _ma_lenh(_PREFLIGHT)
    assert "rclone copyto" in ma, (
        "preflight chưa hỗ trợ rclone — trên máy không có `aws` thì bản kê "
        "offsite KHÔNG kiểm được, và cổng rollback thành vô dụng đúng lúc cần"
    )
    assert "_offsite_lay" in ma, "không có hàm điều phối provider"
    # `command -v aws` chỉ được phép nằm SAU khi đã nhận diện provider.
    for dong in ma.splitlines():
        if "command -v aws" in dong:
            assert "aws)" in ma, (
                "còn kiểm `aws` mà không có nhánh provider — nghĩa là vẫn đòi "
                "aws cho mọi đích offsite, kể cả rclone"
            )


def test_offsite_dung_copyto_khong_dung_copy():
    """`rclone copy` coi đích là THƯ MỤC và giữ nguyên tên nguồn.

    Tệp khi ấy nằm ở `$2/<tên gốc>`, mọi phép đọc sau đó trượt — trong khi lệnh
    vẫn trả 0. Đúng loại lỗi "exit 0 mà việc không xảy ra".
    """
    for ten, ma in (("preflight", _ma_lenh(_PREFLIGHT)), ("§5.4", _lenh_5_4())):
        pham = [
            d.strip()[:80]
            for d in ma.splitlines()
            if re.search(r"\brclone\s+copy\s", d)
        ]
        assert not pham, (
            ten + " dùng `rclone copy` cho một tệp — phải `copyto`, nếu không "
            "tệp rơi vào thư mục con và mọi phép so sau đó trượt: " + str(pham)
        )


def test_preflight_tu_choi_trang_thai_nua_voi_offsite_ma_thieu_digest():
    """"Đã lưu bản kê nhưng chưa push đủ ảnh" KHÔNG được coi là ĐẠT.

    Hai nửa của tài sản rollback phải đi cùng nhau. Có `# offsite` mà thiếu
    digest nghĩa là bản kê đã ra ngoài máy trong khi ta không chứng minh được
    những ảnh ấy đã lên registry.
    """
    ma = _ma_lenh(_PREFLIGHT)
    # Neo vào CẤU TRÚC + VỊ TRÍ, không vào tên biến: bản đầu của guard này chỉ
    # kiểm `"thieu_digest" in ma`, mà tên ấy xuất hiện ở BỐN dòng — đổi tên ở
    # dòng khai báo thì ba dòng còn lại vẫn giữ chuỗi, guard xanh trong khi
    # script đã vỡ. Đo được: mutation đổi tên cho 83/83 XANH.
    i = ma.index('QLTS_ROLLBACK_LOCAL_ONLY:-0}" != "1"')
    j = ma.index('_offsite_lay "$OFFSITE"', i)
    khoi = ma[i:j]
    assert re.search(r"\$1==s \{print \$5\}", khoi), (
        "trước khi tải bản kê offsite, preflight phải đọc cột digest (cột 5) của "
        "từng service — thiếu nó thì 'đã lưu bản kê nhưng chưa push đủ ảnh' vẫn ĐẠT"
    )
    assert re.search(r"for S in \"\$\{DICH_VU\[@\]\}\"", khoi), (
        "phải duyệt ĐỦ bốn service, không kiểm mẫu một cái"
    )
    assert "error" in khoi, (
        "phát hiện thiếu digest mà không `error` thì chỉ là một dòng log"
    )


def test_5_4_khong_dong_cung_dich_offsite_vao_s3():
    """Đích offsite phải khai qua biến — máy này không có `aws`."""
    lenh = _lenh_5_4()
    assert "QLTS_OFFSITE_URL" in lenh, (
        "§5.4 còn đóng cứng đích offsite; phải cho khai qua QLTS_OFFSITE_URL"
    )
    assert "gdrive-crypt:" in lenh, (
        "mặc định nên trỏ remote rclone đã có sẵn và đã đo (gdrive-crypt), thay "
        "vì đòi cài thêm một CLI chỉ để chạy được đường cứu hộ"
    )


# =============================================================================
# Runbook Pha B — bật writer v2
# =============================================================================


def _khoi_pha_b(noi_dung: str) -> str:
    """Khối lệnh của "### Pha B", cắt theo MỐC chứ không theo độ dài cố định.

    Bản trước cắt `[i:i+4000]`. Khối dài thêm vài dòng chú thích là truy vấn
    BASELINE SAU rơi ra ngoài cửa sổ, và guard đỏ vì lý do không liên quan tới
    thứ nó canh — một guard mong manh theo đúng nghĩa đen.
    """
    i = noi_dung.index("### Pha B")
    j = noi_dung.index("### Sau khi pha B", i)
    return noi_dung[i:j]


def test_pha_b_kiem_co_tren_CA_BA_container():
    """`up -d` trả 0 không chứng minh cả ba service đã nhận cờ mới.

    Compose chỉ recreate service nào có model lệch. Một service không recreate
    giữ `writer=false` trong khi hai service kia đã bật ⇒ ghi legacy hay v2 tuỳ
    tiến trình nào phục vụ. Lệch âm thầm, không log nào báo.
    """
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    noi_dung = _doc(_GUIDE)
    khoi = _khoi_pha_b(noi_dung)
    for c in ("qlts-backend-1", "qlts-celery-worker-1", "qlts-celery-beat-1"):
        assert c in khoi, "Pha B không kiểm cờ trên " + c
    assert "docker inspect" in khoi and "MFA_BACKUP_CODE_V2_WRITER_ENABLED" in khoi, (
        "phải đọc cờ ĐÃ NƯỚNG vào container, không suy từ tệp .env"
    )
    # Ba điều dưới đây là thứ biến "lời nhắc" thành CỔNG. Bản trước chỉ
    # `grep '^VAR='` — khớp cả `=false` — rồi `|| echo 'DUNG LAI'`, mà `echo`
    # trả 0 nên quy trình đi tiếp. Guard cũng chỉ đòi có mặt tên biến, nên nó
    # xanh cho một cổng fail-OPEN.
    assert re.search(r'!=\s*"true"|=\s*"true"|-eq\s+1', khoi), (
        "cổng chỉ tìm TÊN biến chứ không so GIÁ TRỊ — `grep '^VAR='` khớp cả "
        "`=false`, nên một container chưa recreate vẫn lọt"
    )
    assert re.search(r"\bexit 1\b", khoi), (
        "cổng không `exit 1` — dòng chữ 'DỪNG LẠI' không dừng được gì khi người "
        "trực dán cả khối vào terminal; lệnh sau vẫn chạy"
    )
    assert re.search(r"so_khai|-ne 1", khoi), (
        "không bắt ca biến khai TRÙNG: >1 dòng thì giá trị nào thắng là tuỳ thứ "
        "tự nạp — phải coi là hỏng, không đoán"
    )
    # Đếm phải làm trên output THÔ, TRƯỚC khi tách giá trị. Đếm sau khi tách là
    # sai: command substitution xoá newline cuối và `grep -c .` bỏ dòng rỗng,
    # nên `VAR=true` + `VAR=` cho ra `so_dong=1` và LỌT. Đã đo đúng cặp ấy.
    assert re.search(r"grep -c '\^MFA_BACKUP_CODE_V2_WRITER_ENABLED='", khoi), (
        "đếm số dòng khai báo phải grep trên output THÔ của `docker inspect`; "
        "đếm sau khi `sed` tách giá trị thì `VAR=true` + `VAR=` vẫn cho 1 và lọt"
    )
    # `up --wait` hỏng phải DỪNG, và "dừng" nghĩa là `exit`, không phải `echo`.
    #
    # ⚠️ Bản trước chỉ hỏi "có `||` gần lệnh Compose không". Đổi guard thật
    # thành `|| echo "DUNG LAI"` — ĐÚNG cái lỗi fail-open đang vá — mà test vẫn
    # xanh. Neo phải vào NHÁNH LỖI: phần ngay sau `||` phải chứa `exit`.
    vt_up = khoi.find("up -d")
    assert vt_up != -1, "Pha B không còn bước dựng lại service?"
    cua_so = khoi[vt_up:vt_up + 320]
    vt_or = cua_so.find("||")
    assert vt_or != -1, (
        "`docker compose up --wait` không có `||` chặn lỗi — một lượt dựng hỏng "
        "vẫn để khối đọc cờ trên container CŨ còn sống, thấy true, rồi đi tiếp"
    )
    nhanh_loi = cua_so[vt_or:vt_or + 160]
    assert re.search(r"\bexit\b", nhanh_loi), (
        "nhánh lỗi của `up --wait` không `exit` — `|| echo 'DUNG LAI'` trả 0 nên "
        f"khối vẫn chạy tiếp. Nhánh hiện tại: {nhanh_loi.strip()[:90]!r}"
    )


def test_pha_b_co_baseline_DB_truoc_va_sau():
    """"Có 1 bản ghi v2" không phân biệt được "vừa sinh" với "đã có từ trước"."""
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    noi_dung = _doc(_GUIDE)
    khoi = _khoi_pha_b(noi_dung)
    assert "v2_truoc" in khoi, "Pha B thiếu baseline DB TRƯỚC khi bật cờ"
    # "BASELINE SAU" là CHỮ, không phải phép đo. Bản trước guard xanh chỉ vì tìm
    # thấy chuỗi ấy trong một dòng chú thích — trong khi không có truy vấn thứ
    # hai nào để so, nên "v2 +1, legacy −1" không thể chứng minh được.
    assert khoi.count('FROM "user"') >= 2, (
        "chỉ có MỘT truy vấn — không có số liệu SAU thì không tính được delta; "
        "'BASELINE SAU' đang là chú thích chứ không phải phép đo"
    )
    assert re.search(r"v2_sau|d_v2", khoi), "không đọc số liệu SAU vào biến"

    # Trích RIÊNG nhánh so delta rồi mới khẳng định — không quét cả khối.
    #
    # ⚠️ Bản trước tìm `exit 1` trên TOÀN khối Pha B. Khối ấy có sẵn ba `exit 1`
    # khác (baseline không đọc được, `up --wait` hỏng, cờ writer sai), nên xoá
    # riêng `exit 1` của nhánh delta vẫn xanh — guard canh hụt đúng chỗ nó sinh
    # ra để canh.
    vt_if = khoi.find('if [ "$d_v2"')
    assert vt_if != -1, (
        "không tìm thấy nhánh `if` so delta — delta phải được KIỂM bằng máy, "
        "không phải in ra cho người đọc"
    )
    vt_fi = khoi.find("\nfi", vt_if)
    assert vt_fi != -1, "nhánh so delta không đóng bằng `fi`?"
    nhanh_delta = khoi[vt_if:vt_fi]
    assert re.search(r"-ne 1\b", nhanh_delta) and re.search(r"-ne -1\b", nhanh_delta), (
        "nhánh delta không so đủ (+1 / −1) — đọc hai bảng số bằng mắt là chỗ "
        "sai sót vào lúc 3 giờ sáng"
    )
    assert re.search(r"\bexit 1\b", nhanh_delta), (
        "delta lệch mà nhánh ấy không `exit 1` thì chỉ là một dòng cảnh báo — "
        f"nhánh hiện tại: {nhanh_delta.strip()[:110]!r}"
    )


def test_pha_b_uu_tien_rollback_moi_hon_e84e0cd8():
    """"Đọc được v2" KHÔNG còn là tiêu chí đủ để chọn ảnh lùi.

    `e84e0cd8` đọc được v2 nhưng là bản TRƯỚC #576, nên lùi về đó mở lại hai
    race MFA đã vá (TOTP replay + mfa_token reuse, cả hai fail-open).
    """
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    noi_dung = _doc(_GUIDE)
    i = noi_dung.index("### Sau khi pha B đã phát mã")
    khoi = noi_dung[i:i + 3000]
    assert "811cdf17" in khoi, (
        "runbook chưa nêu ảnh ưu tiên sau #576; người trực sẽ lùi về ảnh pha A "
        "và mở lại hai race vừa vá"
    )
    vt_moi = khoi.index("811cdf17")
    vt_cu = khoi.index("e84e0cd8")
    assert vt_moi < vt_cu, (
        "e84e0cd8 được nêu TRƯỚC 811cdf17 — thứ tự đọc dẫn người trực chọn nhầm"
    )


def test_pha_b_co_ke_hoach_cap_lai_ma_khi_doi_pepper():
    """Đổi pepper = vô hiệu MỌI mã v2 đã phát, không tính lại được từ hash."""
    if not _GUIDE.is_file():
        pytest.skip("không có PRODUCTION_DEPLOY_GUIDE.md")
    noi_dung = _doc(_GUIDE)
    assert "Nếu buộc phải đổi pepper" in noi_dung, (
        "chỉ cảnh báo 'đổi pepper là vô hiệu mã' mà không có KẾ HOẠCH thì lúc "
        "buộc phải đổi vẫn không ai biết làm gì"
    )
    i = noi_dung.index("Nếu buộc phải đổi pepper")
    khoi = noi_dung[i:i + 2000]
    assert "count(*)" in khoi, "thiếu bước đếm phạm vi người dùng đang giữ mã v2"
    assert re.search(r"[Cc]ấp lại mã", khoi), "thiếu bước cấp lại mã"


# ---------------------------------------------------------------------------
# GHCR: đăng nhập TRƯỚC preflight, logout SAU CÙNG, và KHÔNG kết luận quá tay
#
# Vì sao nhóm guard này tồn tại: package rollback là PRIVATE. Đo thật 25-08-2026 —
# sau `docker logout ghcr.io`, preflight non-local trả RC=1 với "KHÔNG phân giải
# được <digest> trên registry", tức CÙNG thông báo dùng cho ca "ảnh đã bị dọn
# mất". Người trực lúc 3 giờ sáng rất dễ đọc cái đỏ đó thành "mất đường lùi".
#
# ⚠️ Guard TĨNH (tìm chuỗi trong mã) KHÔNG đủ cho nhóm này. Bản nháp đầu chỉ tìm
# tên helper và tên thông báo, nên ba lỗi fail-open lọt qua nguyên vẹn:
#   1. lệnh cứu hộ render ra `echo "\$PAT"` — copy vào chạy sẽ gửi CHUỖI `$PAT`;
#   2. "có khoá trong config.json" bị coi là "đã đăng nhập hợp lệ";
#   3. verifier logout bắt mọi Exception rồi coi config hỏng là "auths rỗng".
# Nên bên dưới có cả guard RENDER: chạy thật đoạn mã rồi đọc kết quả.
# ---------------------------------------------------------------------------


def _khoi_ba_trang_thai() -> str:
    """Đoạn xử lý `docker manifest inspect` thất bại trong preflight."""
    ma = _doc(_PREFLIGHT)
    i = ma.index('if ! docker manifest inspect "$DIGEST"')
    # Phải lấy CẢ `fi` đóng khối: cắt trước nó thì đoạn trích mất cân bằng và
    # bash chết bằng "unexpected end of file" — guard khi ấy đỏ vì đoạn trích
    # hỏng chứ không phải vì mã sai. Đã vấp.
    moc = "\n        fi"
    j = ma.index(moc, i) + len(moc)
    return ma[i:j]


def _render_nhanh(ma_tra_ve: int) -> str:
    """CHẠY THẬT khối ba-trạng-thái, với helper được ép trả `ma_tra_ve`.

    Guard tĩnh không thấy được lỗi escape: chuỗi trong mã nguồn trông hợp lý,
    chỉ khi bash render mới lộ ra `\\$PAT` thay vì `$PAT`. Phải chạy mới biết.
    """
    # ⚠️ PHẢI bật `set -euo pipefail` y như script thật. Bản nháp của chính guard
    # này KHÔNG bật, nên nó XANH trong khi script thật im lặng chết trước khi tới
    # `case`: dưới `set -e`, một lời gọi hàm trần trả khác 0 giết shell ngay, và
    # hai thông báo quan trọng nhất không bao giờ in ra. Guard render mà chạy
    # trong môi trường dễ dãi hơn bản thật thì nó canh một thứ không tồn tại.
    kich_ban = (
        "set -euo pipefail\n"
        "RED=''; NC=''\n"
        'error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }\n'
        "REPO=ghcr.io/favouritekid/qlts-backend\n"
        "DIGEST=ghcr.io/favouritekid/qlts-backend@sha256:abc\n"
        "S=backend\n"
        "_co_cau_hinh_credential() { return " + str(ma_tra_ve) + "; }\n"
        + _khoi_ba_trang_thai()
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write(kich_ban)
        duong = f.name
    try:
        r = subprocess.run(
            [_BASH, duong], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        return r.stdout + r.stderr
    finally:
        os.unlink(duong)


@pytest.mark.skipif(_BASH is None, reason="cần bash để render thật")
def test_lenh_cuu_ho_in_ra_phai_chay_duoc():
    """Lệnh gợi ý trong thông báo lỗi phải COPY VÀO CHẠY ĐƯỢC.

    Đã đo: bản nháp đầu render ra `echo "\\$PAT"`. Người trực copy sẽ gửi chuỗi
    `$PAT` làm mật khẩu — thất bại theo kiểu trông như đã làm đúng.
    """
    ra = _render_nhanh(1)
    dong = [d.strip() for d in ra.split("\n") if "docker login" in d]
    assert dong, "thông báo không in ra lệnh đăng nhập nào"
    lenh = dong[0]

    assert "\\$PAT" not in lenh, (
        "lệnh render ra còn escape thừa — copy vào chạy sẽ gửi chuỗi $PAT "
        "thay vì token: " + lenh
    )
    assert "--password-stdin" in lenh, "token phải qua stdin, không qua argv"
    assert "printf" in lenh, (
        "dùng `printf %s` chứ không `echo`: echo của một số shell diễn giải dấu "
        "gạch chéo ngược và làm hỏng token"
    )
    assert "unset PAT" in lenh, "không xoá PAT khỏi môi trường sau khi dùng"
    assert "rc=$?" in lenh, (
        "`; unset PAT` nuốt mã thoát của login (unset luôn trả 0) — phải bắt "
        "`rc=$?` ngay sau login thì người trực mới biết login hỏng"
    )
    assert "<" not in lenh, (
        "placeholder dạng <user> KHÔNG copy-paste được: bash đọc `<` là chuyển "
        "hướng nhập và báo 'No such file or directory': " + lenh
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để render thật")
@pytest.mark.parametrize(
    "ma, phai_co",
    [
        # Không có credential ⇒ kết luận CHẮC CHẮN: chưa cấu hình đăng nhập.
        (1, ["CHƯA CẤU HÌNH ĐĂNG NHẬP", "KHÔNG PHẢI"]),
        # Config không đọc được ⇒ KHÔNG biết gì, không đoán về phía nào.
        (2, ["KHÔNG ĐỌC ĐƯỢC"]),
        # CÓ credential mà inspect vẫn hỏng ⇒ token hết hạn / thiếu scope /
        # mạng lỗi / ảnh mất. KHÔNG được tuyên bố ảnh đã mất.
        (0, ["KHÔNG XÁC ĐỊNH", "hết hạn", "thiếu scope"]),
    ],
)
def test_ba_trang_thai_khong_ket_luan_qua_tay(ma, phai_co):
    """Mỗi trạng thái phải nói ĐÚNG mức chắc chắn mà bằng chứng cho phép."""
    ra = _render_nhanh(ma)
    for s in phai_co:
        assert s in ra, "nhánh mã %d thiếu '%s'; ra: %s" % (ma, s, ra[:400])

    if ma == 0:
        # Ca nguy hiểm nhất: CÓ credential nhưng inspect hỏng. Trước khi loại
        # trừ token/mạng thì KHÔNG được nói ảnh không còn.
        assert "không còn ở ngoài máy" not in ra, (
            "có credential mà inspect hỏng vẫn tuyên bố ảnh mất — đúng kết luận "
            "sai mà nhóm guard này sinh ra để loại bỏ"
        )
        assert "KHÔNG kết luận" in ra, "không cảnh báo người trực đừng kết luận vội"


def test_helper_khong_tu_nhan_la_chung_minh_dang_nhap():
    """Helper chỉ đọc config.json ⇒ tên và ngữ nghĩa phải nói đúng chừng ấy."""
    ma = _doc(_PREFLIGHT)

    assert "_co_cau_hinh_credential()" in ma, "thiếu helper kiểm cấu hình credential"
    assert "_da_dang_nhap()" not in ma, (
        "tên `_da_dang_nhap` hứa nhiều hơn thứ hàm chứng minh được: token hết "
        "hạn / thiếu scope / bị thu hồi vẫn để nguyên khoá trong `auths`"
    )

    i = ma.index("_co_cau_hinh_credential()")
    j = ma.index("\n}", i)
    than = ma[i:j]

    # Trích RIÊNG nhánh `except`. Kiểm `"sys.exit(2)" in than` là chưa đủ: thân
    # hàm còn một `sys.exit(2)` khác (nhánh `not isinstance`), nên đổi riêng
    # nhánh except sang `sys.exit(1)` vẫn XANH. Đã đo bằng mutation.
    k = than.index("except Exception:")
    nhanh_except = than[k:than.index("host = sys.argv", k)]
    assert "sys.exit(2)" in nhanh_except, (
        "config không đọc được phải có mã thoát RIÊNG (2 = không biết); gộp vào "
        "1 = 'chắc chắn không có credential' là fail-open — một config.json "
        "hỏng sẽ được đọc thành 'chưa đăng nhập' và che mất chính lỗi cần sửa"
    )
    assert 'd.get("credsStore")' in than or "d.get('credsStore')" in than, (
        "bỏ sót `credsStore`: credential khi ấy nằm NGOÀI config.json. Kiểm "
        "bằng chuỗi 'credsStore' thôi là chưa đủ — nó còn xuất hiện ở chú thích"
    )

    lenh = "\n".join(d for d in than.split("\n") if not d.lstrip().startswith("#"))
    assert 'python3 -c "pass"' in lenh, "phải THỬ CHẠY python3 rồi mới tin"
    assert "command -v python3" not in lenh, (
        "`command -v python3` chỉ chứng minh tệp có mặt — trên Windows nó là "
        "stub Microsoft Store, in 'Python was not found' rồi exit 0"
    )


def _lenh_khoi_rollback() -> list:
    """Các LỆNH trong §8.1, đã bỏ dòng chú thích.

    Bỏ comment là bản chất: `docker login` và `rollback-preflight.sh` còn xuất
    hiện trong chú thích giải thích, nên phép đo thứ tự trên văn bản thô cho
    kết quả SAI. Đã đo: login=134 preflight=151 logout=140 trên bản thô, trong
    khi thứ tự lệnh thật là 8 < 10 < 51.
    """
    return [(n, d) for n, d in _khoi_rollback() if not d.lstrip().startswith("#")]


def test_runbook_dang_nhap_registry_truoc_khi_chay_preflight():
    """§8.1 phải `docker login` TRƯỚC lời gọi preflight, không phải sau."""
    lenh = _lenh_khoi_rollback()

    vt_login = next((i for i, (_, d) in enumerate(lenh) if "docker login" in d), -1)
    vt_pf = next(
        (i for i, (_, d) in enumerate(lenh) if "rollback-preflight.sh" in d), -1
    )
    assert vt_pf != -1, "§8.1 không gọi rollback-preflight.sh"
    assert vt_login != -1, (
        "§8.1 không có bước `docker login` — package rollback là PRIVATE và quy "
        "trình CỐ Ý logout sau mỗi lần dùng, nên trạng thái bình thường của máy "
        "chủ là chưa đăng nhập; preflight sẽ đỏ ngay"
    )
    assert vt_login < vt_pf, (
        "`docker login` nằm SAU preflight thì vô dụng: preflight đã đỏ và dừng"
    )

    dl = lenh[vt_login][1]
    assert "--password-stdin" in dl, "token qua argv sẽ lộ trong `ps` và history"
    assert "read -rs" in dl, "phải đọc token bằng `read -rs`"
    # `unset PAT` KHÔNG kiểm ở đây: lệnh an toàn trải nhiều dòng
    # (`if … then / unset PAT / else … fi`) nên phép kiểm theo TỪNG DÒNG không
    # thấy nó — đúng lớp lỗi "lệnh nhiều dòng làm guard mù". Việc đó thuộc
    # `test_lenh_login_trong_runbook_giong_lenh_preflight_in_ra`, guard ấy xét
    # cả khối và còn đòi `unset PAT` xuất hiện ở CẢ HAI nhánh.


def test_runbook_logout_o_buoc_cuoi_va_nghiem_thu_fail_closed():
    """§8.1 phải logout sau cùng, và verifier phải ĐỎ khi không đọc được config."""
    lenh = _lenh_khoi_rollback()

    vt_logout = next((i for i, (_, d) in enumerate(lenh) if "docker logout" in d), -1)
    vt_pf = next(
        (i for i, (_, d) in enumerate(lenh) if "rollback-preflight.sh" in d), -1
    )
    assert vt_logout != -1, (
        "§8.1 không logout — token nằm base64 KHÔNG mã hoá trong config.json"
    )
    assert vt_logout > vt_pf, (
        "logout TRƯỚC preflight là tự làm đỏ chính phép kiểm mình vừa cần"
    )

    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 8.1")
    khoi_tho = noi_dung[i:noi_dung.index("### 8.2", i)]
    # CHỈ xét dòng lệnh: chính chú thích giải thích vì sao KHÔNG được dùng
    # `a = []` lại chứa đúng chuỗi ấy, nên bản nháp của guard này đỏ trên mã
    # ĐÚNG. Lần thứ hai vấp cùng một lỗi trong PR này — quét mã thì phải bỏ
    # comment trước, không có ngoại lệ.
    khoi = "\n".join(
        d for d in khoi_tho.split("\n") if not d.lstrip().startswith("#")
    )

    assert "sys.exit(" in khoi, (
        "verifier logout phải THOÁT KHÁC 0 khi có vấn đề; bản nháp đầu bắt mọi "
        "Exception rồi gán danh sách rỗng nên config.json HỎNG cho XANH GIẢ"
    )
    assert "a = []" not in khoi, (
        "gán danh sách rỗng khi đọc lỗi = coi config hỏng là 'đã sạch'"
    )
    # Phải neo vào phép ĐỌC THẬT (`d.get(...)`), không vào tên xuất hiện đâu đó.
    # Mutation `store = d.get("credsStore")` → `store = None` giữ nguyên chuỗi
    # "credsStore" ở thông báo lỗi nên guard theo tên vẫn XANH. Đã đo.
    for k in ("credHelpers", "credsStore"):
        assert ('d.get("%s")' % k) in khoi or ("d.get('%s')" % k) in khoi, (
            "verifier bỏ sót phép đọc `%s`: credential có thể không nằm trong "
            "`auths`, và một tên chỉ xuất hiện trong thông báo lỗi thì không "
            "chứng minh nó được kiểm" % k
        )


def _chay_lenh_login(lenh: str, docker_rc: int) -> tuple:
    """CHẠY THẬT lệnh login đã render, với `docker` giả trả `docker_rc`.

    Trả (mã thoát của cả khối, PAT còn sót hay không).

    Guard tĩnh "có `rc=$?` trong lệnh" là chưa đủ: bản trước kết thúc bằng
    `echo "docker login rc=$rc"`, mà `echo` trả 0 nên CẢ DÒNG vẫn thành công khi
    login hỏng. Chỉ chạy mới thấy.
    """
    # ⚠️ Phải đo bằng `trap … EXIT`, không phải bằng một dòng `echo` đặt SAU lệnh.
    # Nhánh thất bại kết thúc bằng `exit "$rc"`, nên dòng đặt sau KHÔNG BAO GIỜ
    # chạy: guard khi ấy đọc được "PAT không còn sót" cho mọi bản, kể cả bản đã
    # gỡ hẳn `unset PAT` khỏi nhánh lỗi. Đã đo — mutation đó lọt qua nguyên vẹn.
    # `trap … EXIT` chạy kể cả khi script thoát bằng `exit`.
    kich_ban = (
        'trap \'echo "PAT_CON_SOT=${PAT+co}"\' EXIT\n'
        "docker() { cat >/dev/null; return " + str(docker_rc) + "; }\n"
        + lenh
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write(kich_ban)
        duong = f.name
    try:
        r = subprocess.run(
            [_BASH, duong], input="TOKEN-GIA\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        return r.returncode, ("PAT_CON_SOT=co" in r.stdout)
    finally:
        os.unlink(duong)


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
@pytest.mark.parametrize("docker_rc", [0, 1])
def test_lenh_login_fail_closed_va_luon_unset_pat(docker_rc):
    """Lệnh login phải trả ĐÚNG mã lỗi của `docker login`, và luôn xoá PAT.

    `…; unset PAT` và `…; echo "rc=$rc"` đều trả 0 dù login hỏng — người trực
    chạy trong script sẽ đi tiếp như thể đã đăng nhập. Đã đo cả hai bản.
    """
    ra = _render_nhanh(1)
    dong = [d.strip() for d in ra.split("\n") if "docker login" in d]
    assert dong, "thông báo không in ra lệnh đăng nhập nào"

    rc, con_sot = _chay_lenh_login(dong[0], docker_rc)
    assert rc == docker_rc, (
        f"docker login trả {docker_rc} mà cả khối trả {rc} — lệnh KHÔNG "
        f"fail-closed, mã lỗi bị nuốt: {dong[0]}"
    )
    assert not con_sot, (
        f"PAT còn trong môi trường sau khi login trả {docker_rc} — token phải "
        f"được unset ở CẢ HAI nhánh"
    )


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_lenh_login_trong_runbook_giong_lenh_preflight_in_ra():
    """§8.1 và thông báo preflight phải dùng CÙNG một lệnh an toàn.

    Hai nơi lệch nhau thì một trong hai sẽ hỏng, và nơi hỏng là nơi ít được
    đọc. Bản trước sửa lệnh trong preflight nhưng để nguyên §8.1 với `echo
    "$PAT"`, `-u <user>` và mã lỗi bị nuốt.
    """
    noi_dung = _doc(_RUNBOOK)
    i = noi_dung.index("### 8.1")
    khoi_tho = noi_dung[i:noi_dung.index("### 8.2", i)]
    lenh_rb = "\n".join(
        d for d in khoi_tho.split("\n") if not d.lstrip().startswith("#")
    )

    assert 'echo "$PAT"' not in lenh_rb, (
        "§8.1 còn dùng `echo \"$PAT\"`: echo của một số shell diễn giải dấu "
        "gạch chéo ngược và làm hỏng token"
    )
    assert "-u <" not in lenh_rb, (
        "§8.1 còn placeholder `-u <user>`: bash đọc `<` là chuyển hướng nhập, "
        "lệnh copy vào chạy sẽ báo 'No such file or directory'"
    )
    assert "printf %s" in lenh_rb, "§8.1 phải dùng `printf %s` để đưa token qua stdin"
    assert re.search(r"rc=\$\?;\s*unset PAT;\s*exit", lenh_rb), (
        "§8.1 phải trả đúng mã lỗi của login: `; unset PAT` nuốt mã thoát vì "
        "unset luôn trả 0"
    )
    assert lenh_rb.count("unset PAT") >= 2, (
        "`unset PAT` phải có ở CẢ HAI nhánh (login thành công và thất bại)"
    )


def test_helper_goi_trong_ngu_canh_dieu_kien_vi_set_e():
    """Dưới `set -euo pipefail`, gọi helper trần rồi đọc `$?` là chết im lặng."""
    ma = _doc(_PREFLIGHT)
    assert "set -euo pipefail" in ma, "script không còn bật set -euo pipefail?"

    khoi = _khoi_ba_trang_thai()
    lenh = "\n".join(d for d in khoi.split("\n") if not d.lstrip().startswith("#"))

    assert not re.search(
        r"^\s*_co_cau_hinh_credential\s+\"\$_REG\"\s*$", lenh, re.M
    ), (
        "gọi helper TRẦN dưới `set -e`: mã thoát khác 0 giết shell NGAY, `case` "
        "không bao giờ chạy và hai thông báo 'CHƯA CẤU HÌNH' / 'KHÔNG ĐỌC ĐƯỢC' "
        "không tới được người trực. Đặt vào `if …; then`"
    )
    assert re.search(r"if\s+_co_cau_hinh_credential\s+\"\$_REG\"\s*;\s*then", lenh), (
        "helper phải được gọi trong ngữ cảnh điều kiện — `set -e` không can "
        "thiệp ở đó"
    )
    assert "_CRED_RC" in lenh, "phải giữ mã thoát vào biến rồi mới `case`"


def test_fallback_grep_khong_nhan_vo_chac_chan():
    """Không có python3 thì `grep` KHÔNG chứng minh được JSON hợp lệ."""
    ma = _doc(_PREFLIGHT)
    i = ma.index("_co_cau_hinh_credential()")
    j = ma.index("\n}", i)
    than = ma[i:j]

    k = than.index("grep -q")
    duoi = than[k:]
    lenh = "\n".join(d for d in duoi.split("\n") if not d.lstrip().startswith("#"))
    assert re.search(r"return\s+2\s*$", lenh.strip()), (
        "nhánh fallback grep không tìm thấy credential phải trả 2 ('không "
        "biết'), không phải 1 ('chắc chắn chưa cấu hình'): grep không phân biệt "
        "được 'JSON hợp lệ và không có credential' với 'JSON hỏng nên không khớp'"
    )


# ---------------------------------------------------------------------------
# Retention offsite: chỉ được xoá DB dump ở TẦNG GỐC remote
# ---------------------------------------------------------------------------
#
# Sự cố 11-09-2026: `rclone delete gdrive-crypt: --min-age 14d` không mang bộ
# lọc nào nên nó quét TOÀN BỘ remote. Nó đã xoá thật hai bản kê rollback thế hệ
# 27-08 lúc 03:00 — thứ duy nhất ánh xạ tag rollback → digest ảnh trên GHCR.
# Ảnh vẫn còn nguyên trên registry, nhưng không còn gì nói ảnh nào ứng với tag
# nào, nên đường lùi coi như mất.

_BACKUP = _GOC / "scripts" / "backup-with-offsite.sh"


def _lenh_rclone_delete() -> list[str]:
    r"""Các dòng LỆNH `rclone delete` — không phải mọi dòng NHẮC TỚI nó.

    Hai lớp lọc, vì mỗi lớp một mình đều hụt:

    1. `_ma_lenh` bỏ DÒNG chú thích — script có ba câu chú thích nhắc lại nguyên
       văn lệnh cũ để giải thích sự cố.
    2. `re.match` neo vào ĐẦU dòng, vì `_ma_lenh` **không** bỏ chuỗi nằm trong
       lệnh. Khối hậu kiểm có một dòng `log "… kiểm '--include' của lệnh rclone
       delete."`, và bản nháp đầu của chính guard này đã đếm nó thành lệnh thứ
       hai — đo được: nó báo 2 ≠ 1. Đúng cái bẫy "khớp trúng dòng thông báo thay
       vì dòng lệnh".

    Lệnh viết khác đi (`sudo rclone delete`, `rclone --config x delete`) sẽ cho
    danh sách rỗng và làm guard ĐỎ, chứ không lọt — fail-closed.
    """
    return [
        d.strip()
        for d in _ma_lenh(_BACKUP).splitlines()
        if re.match(r"\s*rclone\s+delete\b", d)
    ]


def _khoi_hau_kiem() -> str:
    """Khối hậu kiểm sau lệnh xoá, trích NGUYÊN VĂN từ script.

    Phải lấy CẢ HAI `fi` đóng khối: cắt trước chúng thì đoạn trích mất cân bằng
    và bash chết bằng "unexpected end of file" — guard khi ấy đỏ vì đoạn trích
    hỏng chứ không phải vì mã sai.
    """
    ma = _doc(_BACKUP)
    i = ma.index("RESIDUE_RC=0")
    moc = "\n    fi\nfi\n"
    j = ma.index(moc, i) + len(moc)
    return ma[i:j]


def test_retention_co_dung_mot_lenh_xoa():
    """Nhiều lệnh xoá thì mỗi guard dưới đây chỉ canh được một cái."""
    assert _BACKUP.is_file(), f"thiếu {_BACKUP.relative_to(_GOC)}"
    lenh = _lenh_rclone_delete()
    assert len(lenh) == 1, (
        f"kỳ vọng đúng một lệnh `rclone delete`, thấy {len(lenh)}: {lenh}"
    )


def test_retention_neo_vao_tang_goc_va_dung_duoi_sql_gz():
    """Mẫu lọc phải neo `/` vào gốc remote và khớp đúng đuôi `.sql.gz`.

    Thiếu dấu `/` đầu mẫu thì rclone khớp ở MỌI độ sâu — đã đo trên cả 1.60.1
    lẫn 1.74.4, kể cả qua remote crypt: `qlts-rollback/qlts_old.sql.gz` bị xoá
    theo. Sai đuôi (`.sql` thay vì `.sql.gz`) thì không khớp gì, `rclone delete`
    trả 0 IM LẶNG và retention chết mà không ai biết.
    """
    lenh = _lenh_rclone_delete()[0]

    assert not re.search(r"--include\s+[^'\"\s]", lenh), (
        "mẫu `--include` phải nằm trong dấu nháy: để trần thì bash bung glob "
        "theo thư mục làm việc của cron TRƯỚC khi rclone nhìn thấy nó, và "
        f"rclone nhận một tên tệp cục bộ làm bộ lọc: {lenh}"
    )
    m = re.search(r"--include\s+(?P<q>['\"])(?P<mau>[^'\"]+)(?P=q)", lenh)
    assert m, f"lệnh retention KHÔNG có `--include` — nó đang quét cả remote: {lenh}"

    mau = m.group("mau")
    assert mau.startswith("/"), (
        f"mẫu {mau!r} không neo vào gốc remote: thiếu dấu `/` đầu mẫu thì nó "
        "khớp ở mọi độ sâu và xoá cả bản kê rollback trong thư mục con"
    )
    assert mau.endswith(".sql.gz"), (
        f"mẫu {mau!r} không kết thúc bằng `.sql.gz`: bản dump thật tên là "
        "`qlts_<ngày>.sql.gz`, sai đuôi thì lệnh xoá thành công RỖNG và im"
    )
    assert mau.startswith("/qlts_"), (
        f"mẫu {mau!r} không giới hạn vào tiền tố `qlts_` của DB dump"
    )


def test_retention_gioi_han_do_sau_mot_tang():
    """`--max-depth 1` là hàng rào THỨ HAI, độc lập với dấu `/` đầu mẫu.

    Dư thừa có chủ ý: mỗi hàng rào một mình đã đủ giữ thư mục con an toàn, nên
    một lần lỡ tay gỡ dấu `/` vẫn không thành sự cố mất bản kê.
    """
    lenh = _lenh_rclone_delete()[0]
    assert re.search(r"--max-depth\s+1\b", lenh), (
        f"thiếu `--max-depth 1` — mất hàng rào thứ hai chặn thư mục con: {lenh}"
    )


def test_retention_giu_nguong_14_ngay_va_khong_dung_rmdirs():
    lenh = _lenh_rclone_delete()[0]
    assert re.search(r"--min-age\s+14d\b", lenh), (
        f"mất ngưỡng `--min-age 14d`: lệnh sẽ xoá cả bản vừa upload xong: {lenh}"
    )
    assert "--rmdirs" not in lenh, (
        "KHÔNG dùng `--rmdirs`: đo trực tiếp thấy rclone 1.60.1 và 1.74.4 hành "
        "xử khác nhau với cờ này, mà phiên bản rclone trên máy chủ không được "
        f"ghim ở đâu cả: {lenh}"
    )


def test_retention_khong_co_co_thu_hai_am_tham_noi_rong():
    """Một cờ THỨ HAI nới phạm vi trong khi cờ thứ nhất vẫn còn nguyên vẹn.

    Đây là lớp đột biến mà guard đọc "lần xuất hiện đầu tiên" hoàn toàn mù. Hậu
    quả đo được thật với rclone 1.74.4:

      · `--min-age 14d … --min-age 0s`      xoá luôn bản vừa upload HÔM NAY
      · `--include '/qlts_*.sql.gz' --include '/**'`
                                            xoá lại bản kê rollback, tức TÁI
                                            HIỆN ĐÚNG sự cố tệp này chặn
      · `--max-depth 1 … --max-depth 9`     gỡ im lặng hàng rào thứ hai

    rclone CỘNG DỒN `--include` và lấy cờ CUỐI cho `--min-age`/`--max-depth`.
    `_ma_lenh` đã nối các dòng nối tiếp `\\`, nên viết cờ thứ hai xuống dòng
    cũng không né được phép đếm này.
    """
    lenh = _lenh_rclone_delete()[0]
    for co in ("--include", "--min-age", "--max-depth"):
        n = len(re.findall(re.escape(co) + r"(?![\w-])", lenh))
        assert n == 1, (
            f"`{co}` xuất hiện {n} lần: rclone cộng dồn `--include` và lấy cờ "
            f"CUỐI cho `--min-age`/`--max-depth`, nên cờ thứ hai nới phạm vi "
            f"trong khi cờ đầu vẫn trông hoàn toàn đúng: {lenh}"
        )
    for co in ("--filter", "--exclude", "--files-from", "--include-from",
               "--filter-from", "--exclude-from"):
        assert not re.search(re.escape(co) + r"(?![\w-])", lenh), (
            f"`{co}` đổi hẳn ngữ nghĩa lọc và có thể nới lại phạm vi mà phép "
            f"đếm `--include` không thấy: {lenh}"
        )


def test_retention_tro_dung_goc_remote():
    """Đổi đối số remote nới phạm vi mà mọi guard về CỜ đều mù.

    `gdrive-crypt:qlts-rollback` giữ nguyên từng cờ một mà vẫn xoá đúng thư mục
    đang cần bảo vệ.
    """
    lenh = _lenh_rclone_delete()[0]
    m = re.match(r"rclone\s+delete\s+(\S+)", lenh)
    assert m, f"không đọc được đối số remote của lệnh xoá: {lenh}"
    assert m.group(1) == "gdrive-crypt:", (
        f"lệnh xoá trỏ vào {m.group(1)!r} chứ không phải GỐC remote "
        f"`gdrive-crypt:`: {lenh}"
    )


def test_script_khong_dung_cu_phap_rieng_cua_bash():
    """Kho KHÔNG chứa crontab máy chủ ⇒ không có gì chứng minh cron gọi `bash`.

    Nếu cron gọi `sh` (dash trên Debian/Ubuntu) thì một bashism giết script ngay
    ở thì PHÂN TÍCH CÚ PHÁP — `bash scripts/backup-cron.sh` ở dòng 19 không bao
    giờ chạy, và mất luôn backup CỤC BỘ chứ không riêng offsite.

    ⚠️ Đừng tin `set -o pipefail` ở dòng 12 là đã ghim bash: đã đo, dash hiện
    đại CHẤP NHẬN cờ này và chạy tiếp bình thường.

    Đọc qua `_ma_lenh` chứ không phải nội dung thô: chú thích trong script có
    nhắc tới `<<<` để giải thích vì sao không dùng nó, và bản nháp đầu của guard
    này đã báo đỏ vì chính câu chú thích ấy.
    """
    ma = _ma_lenh(_BACKUP)
    assert "<<<" not in ma, (
        "here-string `<<<` là cú pháp riêng của bash: dash báo `Syntax error: "
        "redirection unexpected` ngay lúc phân tích, trước cả lệnh đầu tiên"
    )
    assert "[[" not in ma, "`[[ ]]` là cú pháp riêng của bash — dùng `[ ]`"


def test_retention_hong_van_lam_script_thoat_khac_0():
    """Dọn dẹp hỏng phải đẩy ra mã thoát, nếu không cron hiểu là thành công."""
    ma = _ma_lenh(_BACKUP)
    assert re.search(r'RETENTION_RC"?\s*-eq\s*0\s*\]\s*\|\|\s*exit\s+1', ma), (
        'mất dòng `[ "$RETENTION_RC" -eq 0 ] || exit 1` — lớp offsite có thể '
        "chết hàng tháng mà cron vẫn ghi nhận thành công"
    )
    assert re.search(r"rclone\s+delete[^\n]*\|\|\s*RETENTION_RC=\$\?", ma), (
        "mã thoát của `rclone delete` không được bắt vào `RETENTION_RC` — dưới "
        "`set -e` thì hoặc script chết câm, hoặc lỗi bị nuốt"
    )


def test_hau_kiem_khong_dung_lai_chinh_bo_loc_cua_rclone():
    """Hậu kiểm phải dùng CƠ CHẾ KHÁC, nếu không nó mù đúng lúc cần thấy.

    Đây là bất biến dễ bị "dọn cho gọn" nhất: dùng lại `--include` của lệnh xoá
    thì khi mẫu ấy sai, phép liệt kê cũng trả rỗng và hậu kiểm báo SẠCH. Một
    phép kiểm không bao giờ đỏ được thì không canh gì cả.
    """
    khoi = _khoi_hau_kiem()
    dong_lsf = [d for d in khoi.splitlines() if "rclone lsf" in d]
    assert len(dong_lsf) == 1, f"kỳ vọng đúng một lệnh `rclone lsf`: {dong_lsf}"
    assert "--include" not in dong_lsf[0], (
        "hậu kiểm dùng lại `--include` của lệnh xoá ⇒ mẫu sai thì cả hai cùng "
        f"trả rỗng và nó báo SẠCH cho một retention đã chết: {dong_lsf[0]}"
    )
    m = re.search(r"grep -E '([^']+)'", khoi)
    assert m, (
        "hậu kiểm phải tự khớp tên bằng `grep -E` — đó chính là cơ chế độc lập "
        "với bộ lọc của rclone"
    )
    mau = m.group(1)
    assert mau.startswith("^") and mau.endswith("$"), (
        f"mẫu hậu kiểm {mau!r} không neo hai đầu: `grep` không neo thì một tên "
        "như `xxqlts_1.sql.gzyy` cũng khớp"
    )
    assert "[^/]" in mau, (
        f"mẫu hậu kiểm {mau!r} không loại ký tự `/`: một tên có đường dẫn (tức "
        "nằm trong thư mục con) sẽ bị tính nhầm thành bản dump ở tầng gốc và "
        "gây báo động giả mỗi đêm nếu `--max-depth 1` của lệnh liệt kê bị gỡ"
    )


def _chay_lenh_xoa(lenh: str) -> list[str]:
    """CHẠY THẬT lệnh xoá với `rclone` giả, trả về argv mà nó NHẬN ĐƯỢC.

    Guard tĩnh đọc mã nguồn; bash đọc mã nguồn RỒI BUNG GLOB. Hai thứ đó khác
    nhau đúng ở chỗ nguy hiểm nhất, nên phải chạy mới biết. Thư mục làm việc
    được gieo sẵn tệp mồi tên `qlts_*.sql.gz`: mẫu nào không được bảo vệ bằng
    dấu nháy sẽ TỰ LỘ bằng cách biến thành tên tệp mồi trong argv.
    """
    with tempfile.TemporaryDirectory() as thu_muc:
        for moi in ("qlts_moi_nhu.sql.gz", "qlts_moi_khac.sql.gz"):
            Path(thu_muc, moi).write_text("moi", encoding="utf-8")
        kich_ban = (
            "set -euo pipefail\n"
            "log() { :; }\n"
            "RETENTION_RC=0\n"
            "rclone() { printf '%s\\n' \"$@\" > argv.txt; return 0; }\n"
            + lenh
            + "\n"
        )
        kb = Path(thu_muc, "chay.sh")
        kb.write_text(kich_ban, encoding="utf-8", newline="\n")
        r = subprocess.run(
            [_BASH, str(kb)], cwd=thu_muc, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        assert r.returncode == 0, f"kịch bản đổ: {r.stdout}{r.stderr}"
        return Path(thu_muc, "argv.txt").read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_bash_truyen_dung_mau_cho_rclone_khong_bung_glob():
    """Thứ rclone NHẬN ĐƯỢC mới là bộ lọc thật, không phải thứ ta viết ra."""
    argv = _chay_lenh_xoa(_lenh_rclone_delete()[0])

    assert "--include" in argv, f"argv không có `--include`: {argv}"
    mau = argv[argv.index("--include") + 1]
    assert mau.startswith("/qlts_") and mau.endswith(".sql.gz"), (
        f"rclone nhận bộ lọc {mau!r} — không phải mẫu neo gốc mà script viết ra; "
        f"nhiều khả năng bash đã bung glob: {argv}"
    )
    assert not any(d.endswith("moi_nhu.sql.gz") for d in argv), (
        f"bash đã bung mẫu thành tên tệp trong thư mục làm việc: {argv}"
    )
    assert "--max-depth" in argv and argv[argv.index("--max-depth") + 1] == "1", (
        f"rclone không nhận được `--max-depth 1`: {argv}"
    )
    assert "--min-age" in argv and argv[argv.index("--min-age") + 1] == "14d", (
        f"rclone không nhận được `--min-age 14d`: {argv}"
    )


def _chay_hau_kiem(danh_sach: str, lsf_rc: int = 0) -> tuple:
    """CHẠY THẬT khối hậu kiểm với `rclone lsf` giả.

    Trả `(RETENTION_RC, log, argv mà rclone nhận được)`.

    Danh sách giả đi qua BIẾN MÔI TRƯỜNG chứ không nhúng vào kịch bản, để một
    tên tệp có ký tự lạ không bao giờ đổi được cấu trúc kịch bản.

    ⚠️ Bản nháp đầu của stub này BỎ QUA argv, nên mọi tham số của chính lệnh
    `lsf` — remote, `--min-age` — không hề được canh. Đo được: đổi `--min-age
    14d` thành `400d` làm hậu kiểm MÙ HOÀN TOÀN mà cả bộ test vẫn xanh. Hậu
    kiểm là lưới đỡ CUỐI CÙNG, nên tham số của nó phải được canh chặt như tham
    số của lệnh xoá.
    """
    with tempfile.TemporaryDirectory() as thu_muc:
        kich_ban = (
            "set -euo pipefail\n"
            'log() { echo "LOG $*"; }\n'
            "RETENTION_RC=0\n"
            "rclone() {\n"
            "  printf '%s\\n' \"$@\" > argv.txt\n"
            '  if [ "${1:-}" != "lsf" ]; then echo "STUB GOI SAI: $*" >&2; return 9; fi\n'
            '  printf %s "${DS_GIA:-}"\n'
            "  return " + str(lsf_rc) + "\n"
            "}\n"
            + _khoi_hau_kiem()
            + '\necho "RETENTION_RC=$RETENTION_RC"\n'
        )
        kb = Path(thu_muc, "chay.sh")
        kb.write_text(kich_ban, encoding="utf-8", newline="\n")
        r = subprocess.run(
            [_BASH, str(kb)], cwd=thu_muc, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
            env={**os.environ, "DS_GIA": danh_sach},
        )
        ra = r.stdout + r.stderr
        m = re.search(r"RETENTION_RC=(\d+)", ra)
        assert m, f"khối hậu kiểm không chạy tới cuối: {ra}"
        p = Path(thu_muc, "argv.txt")
        argv = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
        return int(m.group(1)), ra, argv


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_hau_kiem_goi_lsf_dung_pham_vi():
    """Tham số của CHÍNH lệnh hậu kiểm cũng phải được canh.

    Đo được: `--min-age 400d`, hay đổi remote sang `gdrive-crypt:qlts-rollback`,
    làm hậu kiểm mù hoàn toàn — nó báo SẠCH cho một retention đã chết. Bỏ hẳn
    `--min-age` thì hỏng theo chiều ngược lại: báo động giả mỗi đêm, rồi người
    trực tắt cảnh báo đi.
    """
    _, _, argv = _chay_hau_kiem("")
    assert argv and argv[0] == "lsf", f"khối hậu kiểm không gọi `rclone lsf`: {argv}"
    assert "gdrive-crypt:" in argv, (
        f"hậu kiểm không liệt kê GỐC remote — nó đang soi chỗ khác: {argv}"
    )
    assert argv.count("--min-age") == 1 and argv[argv.index("--min-age") + 1] == "14d", (
        f"hậu kiểm phải soi đúng ngưỡng 14d: lớn hơn thì mù, không có thì báo "
        f"động giả mỗi đêm: {argv}"
    )
    assert argv.count("--max-depth") == 1 and argv[argv.index("--max-depth") + 1] == "1", (
        f"hậu kiểm phải giới hạn ở tầng gốc: {argv}"
    )
    for co in ("--include", "--filter", "--exclude"):
        assert co not in argv, (
            f"hậu kiểm dùng `{co}` là dùng lại bộ lọc của rclone ⇒ mẫu sai thì "
            f"cả hai cùng trả rỗng và nó báo SẠCH: {argv}"
        )


_BAN_KE = "rollback_manifest_pre-24ec658b-from-a4dab746-20260910T151546Z.offsite.txt"


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_hau_kiem_bat_duoc_retention_chet_lang():
    """Mẫu sai ⇒ `rclone delete` trả 0 và xoá rỗng. Hậu kiểm phải kêu.

    Đây là lý do tồn tại của cả khối: mã thoát 0 KHÔNG phân biệt được "mẫu sai"
    với "không có gì để xoá".
    """
    rc, ra, _ = _chay_hau_kiem("qlts_20260820_030000.sql.gz\n" + _BAN_KE + "\n")
    assert rc != 0, (
        "còn bản dump quá hạn ở gốc remote mà hậu kiểm vẫn để RETENTION_RC=0 — "
        f"một retention chết lặng vẫn được báo là thành công:\n{ra}"
    )
    assert "VẪN CÒN" in ra, f"hậu kiểm không in cảnh báo nào:\n{ra}"


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
@pytest.mark.parametrize(
    "danh_sach",
    [
        "",
        _BAN_KE + "\n",
        _BAN_KE + "\nconfig_backup_20260820_manifest.txt\n",
        "qlts_20260820_030000.sql.gz.sha256\n",
        "ghi_chu_van_hanh.txt\n",
        # Bản dump nằm trong thư mục con: nếu `--max-depth 1` của lệnh liệt kê
        # bị gỡ thì tên này sẽ xuất hiện kèm đường dẫn, và một mẫu không loại
        # `/` sẽ tính nhầm nó thành bản sót ở gốc rồi kêu mỗi đêm.
        "qlts-rollback/qlts_20260820_030000.sql.gz\n",
    ],
)
def test_hau_kiem_khong_bao_dong_gia(danh_sach):
    """Bản kê, checksum và object lạ ở gốc KHÔNG được tính là bản dump sót.

    Guard này khoá đúng phạm vi: nới `case` thành `qlts*` hay `*.gz` thì đêm nào
    retention cũng bị coi là hỏng, cảnh báo thành tiếng ồn, rồi người trực tắt.
    """
    rc, ra, _ = _chay_hau_kiem(danh_sach)
    assert rc == 0, f"báo động giả cho danh sách {danh_sach!r}:\n{ra}"
    assert "VẪN CÒN" not in ra, f"cảnh báo sai cho {danh_sach!r}:\n{ra}"


@pytest.mark.skipif(_BASH is None, reason="cần bash để chạy thật")
def test_hau_kiem_khong_liet_ke_duoc_thi_cung_phai_keu():
    """Không liệt kê được nghĩa là KHÔNG BIẾT, không phải là SẠCH."""
    rc, ra, _ = _chay_hau_kiem("", lsf_rc=7)
    assert rc == 7, (
        f"`rclone lsf` hỏng (mã 7) mà RETENTION_RC={rc} — script sẽ thoát 0 và "
        f"báo HOÀN TẤT cho một lượt dọn dẹp chưa hề được xác minh:\n{ra}"
    )
