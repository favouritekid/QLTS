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

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")


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
    """Dòng có gọi `docker compose` trực tiếp (không qua biến đã gán sẵn)."""
    if "docker compose" not in dong:
        return False
    # `command -v docker compose` là phép kiểm cài đặt, không phải lời gọi.
    if "command -v docker compose" in dong:
        return False
    # `DC="docker compose -f ..."` / `_COMPOSE=(docker compose -f ...)` tự mang
    # cờ trong chính chuỗi gán nên vẫn được soi bình thường; các lời gọi QUA
    # biến (`$DC ...`) không chứa chuỗi "docker compose" nên tự bỏ qua.
    return True


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
        for so, dong in enumerate(_doc(sh).splitlines(), 1):
            if dong.lstrip().startswith("#"):
                continue
            if _co_lenh_compose(dong) and "-f docker-compose.yml" not in dong:
                pham.append(f"{sh.relative_to(_GOC)}:{so}: {dong.strip()[:90]}")
    assert da_soi_script == len(_SCRIPT_PRODUCTION), (
        f"chỉ soi được {da_soi_script}/{len(_SCRIPT_PRODUCTION)} script production — "
        "một tên trong _SCRIPT_PRODUCTION đã bị đổi/xoá và guard đang canh hụt"
    )
    assert not pham, (
        "lệnh `docker compose` thiếu `-f docker-compose.yml` (Compose sẽ tự nạp "
        "docker-compose.override.yml của DEV):\n  " + "\n  ".join(pham)
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
    assert re.search(r"aws s3 cp[^\n]*\.sha256", lenh), (
        "phải upload checksum đi kèm — không có nó thì bản tải về không kiểm được"
    )
    assert re.search(r"cmp -s[^\n]*offsite-check", lenh), (
        "phải tải NGƯỢC bản kê về và so nội dung: `aws s3 cp` trả 0 không chứng "
        "minh object đọc lại được (quyền, KMS, lifecycle, sai bucket)"
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
    assert re.search(r'aws s3 cp "\$OFFSITE"', ma), (
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
