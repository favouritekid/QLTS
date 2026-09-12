"""Cổng cho `scripts/celery-heartbeat-monitor.sh` — lớp giám sát NGOÀI Celery.

Script này là thứ duy nhất còn chạy khi Celery đã chết, nên mọi lối fail-open
của nó đều là "im lặng vĩnh viễn" chứ không phải "một cảnh báo bị trễ". Tệp này
canh đúng những lối đó:

* không đọc được Redis / mất khoá / giá trị rác  ⇒ vẫn phải ping `/fail`
  (coi "không biết" là "vẫn ổn" chính là định nghĩa fail-open);
* thiếu URL                                      ⇒ thoát KHÁC 0, và KHÔNG ping;
* URL không bao giờ vào argv / environment / output;
* hai check (Celery và backup) không dùng chung URL;
* chuỗi ngưỡng 300s → 900s → 1200s phải khớp nhau qua ba tệp khác nhau.

Phần phán định được gọi bằng MÃ THẬT (source script rồi gọi `phan_dinh`), và
phần ping được đo bằng cách ĐÈ HÀM `curl`/`docker` trong cùng shell — hàm shell
thắng lookup PATH, nên không cần shim khả thi hay sửa PATH, và chạy giống nhau
trên Linux lẫn Git Bash.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc backend-test.yml")


# ---------------------------------------------------------------------------
# Định vị
# ---------------------------------------------------------------------------

def _tim_bash() -> str | None:
    """Một `bash` THỰC SỰ chạy được — kiểm bằng cách CHẠY, không tin `which`.

    Trên Windows `shutil.which("bash")` thường trả bash của WSL, và gọi nó bằng
    đường dẫn kiểu Windows cho `execvpe(/bin/bash) failed`.
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
    """Đi ngược lên tìm gốc repo bằng MỐC, không đếm số tầng."""
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
_MONITOR = _GOC / "scripts" / "celery-heartbeat-monitor.sh"
_LIB = _GOC / "scripts" / "lib" / "healthchecks.sh"
_BACKUP = _GOC / "scripts" / "backup-with-offsite.sh"
_MAU_ENV = _GOC / "ops" / "healthchecks.env.example"
_TASK_PY = _GOC / "Backend_FastAPI" / "app" / "tasks" / "heartbeat_tasks.py"
_COMPOSE = _GOC / "docker-compose.yml"
_WF = _GOC / ".github" / "workflows" / "backend-test.yml"

_BA_TEP = {"monitor": _MONITOR, "lib": _LIB, "backup": _BACKUP}

SENTINEL = "https://hc-ping.test/SENTINEL-9f3a7c"
SENTINEL_BACKUP = "https://hc-ping.test/SENTINEL-backup-1122"

TEP_TEST_TASK = "tests/integration/test_celery_heartbeat.py"
TEP_TEST_SCRIPT = "tests/unit/test_celery_heartbeat_monitor_script.py"


def _doc(p: Path) -> str:
    """Chuẩn hoá CRLF → LF trước khi khẳng định bất cứ điều gì.

    `.gitattributes` chỉ ép `eol=lf` cho `*.sh`, nên `ops/healthchecks.env.example`
    được checkout thành CRLF trên Windows. Khi ấy một biểu thức `^TEN=$` KHÔNG
    khớp `TEN=\\r\\n` — guard sẽ xanh trên runner Linux và đỏ trên máy dev, tức
    đúng kiểu "xanh ở chỗ khác" mà nó sinh ra để chặn.
    """
    assert p.is_file(), f"không thấy {p}"
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _noi_dong_tiep(than: str) -> str:
    """Nối các dòng kết thúc bằng `\\` thành MỘT dòng lệnh logic.

    Một lệnh trải nhiều dòng làm phép kiểm theo-từng-dòng không thấy gì cả —
    đã có lần 0/3 đột biến bị bắt vì đúng lý do này.
    """
    return re.sub(r"\\\n\s*", " ", than)


def _than_lenh(than: str) -> str:
    """Bỏ comment để guard soi DÒNG LỆNH, không soi dòng giải thích.

    Một biểu thức khớp trúng chính đoạn comment đang mô tả điều cấm là kiểu
    guard xanh vô nghĩa đã vấp nhiều lần.
    """
    ra = []
    for dong in than.splitlines():
        if dong.lstrip().startswith("#"):
            continue
        ra.append(re.sub(r"\s#\s.*$", "", dong))
    return "\n".join(ra)


def _cac_lenh_curl() -> list[tuple[str, str]]:
    """Mọi dòng LỆNH (đã nối dòng tiếp) có gọi `curl`, ở cả ba script."""
    ra = []
    for p in (_MONITOR, _LIB, _BACKUP):
        for dong in _than_lenh(_noi_dong_tiep(_doc(p))).splitlines():
            if re.search(r"(^|\s|\|)curl\s", dong):
                ra.append((p.name, dong.strip()))
    return ra


def _so_shell(ten: str, than: str) -> int:
    """Đọc một hằng số nguyên gán ở cấp cao nhất của script."""
    khop = re.search(rf"^{ten}=([0-9]+)\s*$", than, re.M)
    assert khop, f"không thấy hằng `{ten}=<số>` trong script"
    return int(khop.group(1))


def _so_python(ten: str, than: str) -> int:
    khop = re.search(rf"^{ten}\s*=\s*([0-9_]+)\s*(?:#.*)?$", than, re.M)
    assert khop, f"không thấy `{ten} = <số>` dạng literal trong heartbeat_tasks.py"
    return int(khop.group(1).replace("_", ""))


# ---------------------------------------------------------------------------
# Bộ chạy: đè `docker` và `curl` bằng HÀM shell trong cùng tiến trình
# ---------------------------------------------------------------------------

_PRELUDE_CHAY = """set -uo pipefail
docker() { printf '%s' "$FAKE_RAW"; return "$FAKE_DOCKER_RC"; }
curl() {
    printf 'ARGV<<%s>>\\n' "$*" >> "$LOG_ARGV"
    env > "$LOG_ENV"
    cat >> "$LOG_STDIN"
    return "$FAKE_CURL_RC"
}
. "$MONITOR"
"""

_PRELUDE_PHAN_DINH = """set -uo pipefail
QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY=1 . "$MONITOR"
phan_dinh "$1" "$2" "$3"
"""


class Ket:
    def __init__(self, rc, out, argv, stdin, moi_truong):
        self.rc = rc
        self.out = out
        self.argv = argv
        self.stdin = stdin
        self.moi_truong = moi_truong


def _chay(
    tmp_path: Path,
    *,
    raw: str = "",
    docker_rc: int = 0,
    curl_rc: int = 0,
    dong_bi_mat: list[str] | None = None,
    mode_bi_mat: int = 0o600,
    symlink_bi_mat: bool = False,
) -> Ket:
    if _BASH is None:
        pytest.skip("không tìm thấy bash chạy được")

    log_argv = tmp_path / "argv.log"
    log_stdin = tmp_path / "stdin.log"
    log_env = tmp_path / "env.log"
    bi_mat = tmp_path / "healthchecks.env"
    if dong_bi_mat is not None:
        bi_mat.write_text("\n".join(dong_bi_mat) + "\n", encoding="utf-8", newline="\n")
        # Monitor fail-closed nếu quyền lỏng, nên mọi ca "đường bình thường"
        # phải dựng tệp ĐÚNG quyền — nếu không, chúng sẽ xanh/đỏ vì lý do khác
        # với thứ chúng định đo.
        os.chmod(bi_mat, mode_bi_mat)

    duong_bi_mat = bi_mat
    if symlink_bi_mat:
        lien_ket = tmp_path / "healthchecks.link.env"
        if not lien_ket.is_symlink():
            os.symlink(bi_mat, lien_ket)
        duong_bi_mat = lien_ket

    prelude = tmp_path / "prelude.sh"
    prelude.write_text(_PRELUDE_CHAY, encoding="utf-8", newline="\n")

    env = dict(os.environ)
    env.update(
        {
            "FAKE_RAW": raw,
            "FAKE_DOCKER_RC": str(docker_rc),
            "FAKE_CURL_RC": str(curl_rc),
            "LOG_ARGV": log_argv.as_posix(),
            "LOG_STDIN": log_stdin.as_posix(),
            "LOG_ENV": log_env.as_posix(),
            "MONITOR": _MONITOR.as_posix(),
            "QLTS_HEALTHCHECKS_FILE": duong_bi_mat.as_posix(),
            "QLTS_REDIS_CONTAINER": "fake-redis",
        }
    )
    env.pop("QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY", None)

    r = subprocess.run(
        [_BASH, prelude.as_posix()],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        encoding="utf-8",
        errors="replace",
    )

    def _oc(p: Path) -> str:
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""

    return Ket(
        rc=r.returncode,
        out=(r.stdout or "") + (r.stderr or ""),
        argv=_oc(log_argv),
        stdin=_oc(log_stdin),
        moi_truong=_oc(log_env),
    )


def _phan_dinh(tmp_path: Path, rc: int, raw: str, now: int) -> str:
    if _BASH is None:
        pytest.skip("không tìm thấy bash chạy được")
    prelude = tmp_path / "pd.sh"
    prelude.write_text(_PRELUDE_PHAN_DINH, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["MONITOR"] = _MONITOR.as_posix()
    r = subprocess.run(
        [_BASH, prelude.as_posix(), str(rc), raw, str(now)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, f"phan_dinh thoát {r.returncode}: {r.stderr}"
    return (r.stdout or "").strip()


_PRELUDE_GOI_HAM = """set -uo pipefail
QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY=1 . "$MONITOR"
HAM="$1"; shift
"$HAM" "$@"
"""


def _goi_ham(tmp_path: Path, ten_ham: str, *args: str) -> tuple[int, str]:
    """Gọi thẳng một hàm của lib bằng MÃ THẬT.

    Hàm thuần thì không cần Docker, không cần mạng, không đua với đồng hồ — và
    một test chép lại luật thay vì gọi nó sẽ vẫn xanh khi script trôi đi.
    """
    if _BASH is None:
        pytest.skip("không tìm thấy bash chạy được")
    prelude = tmp_path / f"goi_{ten_ham}.sh"
    prelude.write_text(_PRELUDE_GOI_HAM, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["MONITOR"] = _MONITOR.as_posix()
    env.pop("QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY", None)
    r = subprocess.run(
        [_BASH, prelude.as_posix(), ten_ham, *args],
        capture_output=True, text=True, timeout=120, env=env,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


@pytest.fixture
def bi_mat_day_du() -> list[str]:
    return [
        f"CELERY_HEARTBEAT_PING_URL={SENTINEL}",
        f"HEALTHCHECK_PING_URL={SENTINEL_BACKUP}",
    ]


# ---------------------------------------------------------------------------
# 1. Phán định — hàm thuần, mã thật, không đua với đồng hồ
# ---------------------------------------------------------------------------

NOW = 1_800_000_000


class TestPhanDinh:
    @pytest.mark.parametrize(
        "rc,raw,cho_doi",
        [
            (0, str(NOW), "fresh"),
            (0, str(NOW - 1), "fresh"),
            (0, str(NOW - 899), "fresh"),
            (0, str(NOW - 900), "fresh"),          # đúng ngưỡng: CHƯA cũ
            (0, str(NOW - 901), "stale"),          # vượt một giây: cũ
            (0, str(NOW - 100000), "stale"),
            (0, "", "missing"),
            (0, "   ", "missing"),
            (0, "\n", "missing"),
            (0, "abc", "malformed"),
            (0, "17e9", "malformed"),
            (0, "-1", "malformed"),
            (0, "1700000000.5", "malformed"),
            (0, "(nil)", "malformed"),
            (0, "ERR wrong number of arguments", "malformed"),
            (0, "0", "malformed"),
            (0, "12345", "malformed"),             # dưới mốc hợp lý
            (1, str(NOW), "read_error"),           # đọc lỗi thắng mọi thứ
            (2, "", "read_error"),
        ],
    )
    def test_bang_phan_dinh(self, tmp_path, rc, raw, cho_doi):
        assert _phan_dinh(tmp_path, rc, raw, NOW) == cho_doi

    def test_epoch_tuong_lai_xa_la_rac_khong_phai_tuoi_vinh_vien(self, tmp_path):
        """Một epoch ở tương lai làm `tuoi` thành ÂM.

        Không chặn thì `-99999 > 900` là sai ⇒ `fresh` mãi mãi: đúng một lối
        fail-open, và là lối mà lệch đồng hồ hoặc một lần ghi sai đơn vị (ms
        thay vì s) tạo ra rất tự nhiên.
        """
        ms = str(NOW * 1000)  # ghi bằng milligiây — lỗi thật, rất dễ xảy ra
        assert _phan_dinh(tmp_path, 0, ms, NOW) == "malformed"
        assert _phan_dinh(tmp_path, 0, str(NOW + 301), NOW) == "malformed"
        # Trong biên lệch đồng hồ cho phép thì vẫn coi là tươi.
        assert _phan_dinh(tmp_path, 0, str(NOW + 10), NOW) == "fresh"


# ---------------------------------------------------------------------------
# 2. Chạy trọn script — ping đi đâu, thoát bằng mã nào
# ---------------------------------------------------------------------------

class TestDuongPing:
    def test_tuoi_thi_ping_success(self, tmp_path, bi_mat_day_du):
        k = _chay(
            tmp_path, raw=str(int(time.time()) - 60), dong_bi_mat=bi_mat_day_du
        )
        assert k.rc == 0, f"rc={k.rc} out={k.out}"
        assert f'url = "{SENTINEL}"' in k.stdin
        assert "/fail" not in k.stdin

    @pytest.mark.parametrize(
        "nhan,raw,docker_rc",
        [
            ("cu", None, 0),
            ("mat_khoa", "", 0),
            ("rac", "khong-phai-so", 0),
            ("duoi_moc", "42", 0),
            ("doc_loi", "", 1),
        ],
    )
    def test_moi_ca_khong_tuoi_deu_ping_fail(
        self, tmp_path, bi_mat_day_du, nhan, raw, docker_rc
    ):
        """Kể cả KHÔNG ĐỌC ĐƯỢC.

        Redis chết hay docker chết thì Celery cũng không còn chạy được. Bỏ qua
        vì "không biết" là fail-open, và nó là ca dễ bỏ nhất vì trông giống lỗi
        của công cụ chứ không giống sự cố.
        """
        if raw is None:
            raw = str(int(time.time()) - 5000)
        k = _chay(tmp_path, raw=raw, docker_rc=docker_rc, dong_bi_mat=bi_mat_day_du)
        assert f'url = "{SENTINEL}/fail"' in k.stdin, (
            f"ca {nhan}: khong ping /fail. stdin={k.stdin!r} out={k.out}"
        )
        assert k.rc == 1, f"ca {nhan}: rc={k.rc}"

    def test_ping_that_bai_khong_bi_bao_thanh_cong(self, tmp_path, bi_mat_day_du):
        k = _chay(
            tmp_path,
            raw=str(int(time.time()) - 60),
            curl_rc=7,
            dong_bi_mat=bi_mat_day_du,
        )
        assert k.rc != 0, "ping thất bại mà script vẫn thoát 0"
        assert k.rc == 3


# ---------------------------------------------------------------------------
# 3. Thiếu cấu hình là FATAL, không phải "bỏ qua"
# ---------------------------------------------------------------------------

class TestThieuCauHinh:
    def test_khong_co_tep_bi_mat_thi_thoat_khac_0(self, tmp_path):
        k = _chay(tmp_path, raw=str(int(time.time())), dong_bi_mat=None)
        assert k.rc == 2, (
            f"rc={k.rc} — thoát 0 khi chưa cấu hình URL nghĩa là giám sát tự "
            "tắt trong im lặng, đúng trạng thái production đang mắc"
        )
        assert k.argv.strip() == "", "không có URL mà vẫn gọi curl"

    @pytest.mark.parametrize(
        "dong",
        [
            [],
            ["CELERY_HEARTBEAT_PING_URL="],
            ["CELERY_HEARTBEAT_PING_URL=   "],
            ['CELERY_HEARTBEAT_PING_URL=""'],
            ["# CELERY_HEARTBEAT_PING_URL=https://x/y"],
        ],
    )
    def test_bien_rong_hoac_bi_comment_cung_la_chua_cau_hinh(self, tmp_path, dong):
        k = _chay(tmp_path, raw=str(int(time.time())), dong_bi_mat=dong)
        assert k.rc == 2, f"dòng {dong!r} cho rc={k.rc}"
        assert k.argv.strip() == ""

    def test_KHONG_fallback_sang_URL_cua_backup(self, tmp_path):
        """Hai check phải độc lập.

        Dùng chung một URL thì một backup thành công lúc 03:00 sẽ ping success
        và XOÁ trạng thái "Celery đã chết từ 23:00"; ngược lại Celery khoẻ sẽ
        che việc backup không chạy. Hai sự cố che lấp nhau — thà TẮT hẳn và kêu.
        """
        k = _chay(
            tmp_path,
            raw=str(int(time.time())),
            dong_bi_mat=[f"HEALTHCHECK_PING_URL={SENTINEL_BACKUP}"],
        )
        assert k.rc == 2, f"rc={k.rc} — đã rơi sang biến của backup"
        assert SENTINEL_BACKUP not in k.stdin
        assert SENTINEL_BACKUP not in k.argv
        assert k.argv.strip() == ""


# ---------------------------------------------------------------------------
# 4. Bí mật: URL chỉ được ở hai chỗ
# ---------------------------------------------------------------------------

class TestChuaBiMat:
    def test_url_khong_bao_gio_o_argv(self, tmp_path, bi_mat_day_du):
        """`/proc/<pid>/cmdline` ai trên máy cũng đọc được qua `ps`.

        URL ping CHÍNH LÀ mật khẩu: có nó thì ping thay được, tức TẮT được
        cảnh báo mà không cần đăng nhập gì.
        """
        k = _chay(
            tmp_path, raw=str(int(time.time()) - 60), dong_bi_mat=bi_mat_day_du
        )
        assert k.argv.strip(), "curl chưa được gọi lần nào — test rỗng"
        assert SENTINEL not in k.argv, f"URL nằm trong argv: {k.argv!r}"
        assert "--config" in k.argv, (
            "curl không nhận `--config` ⇒ URL không thể đến từ stdin"
        )
        assert f'url = "{SENTINEL}"' in k.stdin, "URL phải đến qua STDIN"

    def test_url_khong_bao_gio_trong_environment_cua_tien_trinh_con(
        self, tmp_path, bi_mat_day_du
    ):
        k = _chay(
            tmp_path, raw=str(int(time.time()) - 60), dong_bi_mat=bi_mat_day_du
        )
        assert k.moi_truong.strip(), "chưa ghi được environment — test rỗng"
        assert SENTINEL not in k.moi_truong, (
            "URL bị export ⇒ mọi tiến trình con thừa hưởng và đọc được qua "
            "/proc/<pid>/environ"
        )

    @pytest.mark.parametrize("khong_tuoi", [False, True])
    def test_url_khong_bao_gio_ra_stdout_stderr(
        self, tmp_path, bi_mat_day_du, khong_tuoi
    ):
        """Log cron là tệp phẳng, giữ rất lâu — cả nhánh cảnh báo cũng phải sạch."""
        raw = str(int(time.time()) - (5000 if khong_tuoi else 60))
        k = _chay(tmp_path, raw=raw, dong_bi_mat=bi_mat_day_du)
        assert SENTINEL not in k.out, f"URL rò ra log: {k.out!r}"
        assert SENTINEL_BACKUP not in k.out

    @pytest.mark.parametrize(
        "url,hop_le",
        [
            ("https://hc-ping.test/abc-123", True),
            ("https://hc-ping.test/abc-123/fail", True),
            ("http://hc-ping.test/abc", False),          # không mã hoá
            ("HTTPS://hc-ping.test/abc", False),         # curl phân biệt hoa thường
            ("ftp://hc-ping.test/abc", False),
            ("file:///etc/passwd", False),
            ("hc-ping.test/abc", False),
            ("https://", False),
            ('https://x/a"b', False),                    # đóng chuỗi sớm
            ("https://x/a\\b", False),                   # escape của curl
            ("https://x/a b", False),
            ("https://x/a\tb", False),
            ("https://x/a\nproxy = http://kegian:8080", False),  # TIÊM chỉ thị
            ("https://x/a\rb", False),
            ("", False),
        ],
    )
    def test_URL_khong_an_toan_bi_tu_choi(self, tmp_path, url, hop_le):
        """Giá trị này bị ghim vào TỆP CẤU HÌNH của curl (`url = "…"`).

        Một ký tự xuống dòng không chỉ làm URL xấu — nó cho phép tiêm thẳng
        `proxy = …` hoặc `output = /etc/…`, tức chuyển hướng ping hoặc ghi tệp
        dưới quyền tiến trình đang chạy. Dấu nháy đóng chuỗi sớm, backslash là
        escape. Vì vậy đây là chặn TIÊM, không phải kiểm định dạng cho đẹp.
        """
        rc, out = _goi_ham(tmp_path, "hc_url_an_toan", url)
        assert (rc == 0) is hop_le, f"rc={rc} out={out!r}"
        if not hop_le:
            # Chỉ soi phần SAU lược đồ: thông báo từ chối có quyền nhắc chữ
            # "https://", nhưng không được nhắc phần bí mật (host + path).
            phan_bi_mat = url.split("//", 1)[-1]
            if len(phan_bi_mat) >= 4:
                assert phan_bi_mat not in out, (
                    "thông báo từ chối in ra phần bí mật của URL"
                )

    def test_hc_ping_tu_choi_URL_khong_an_toan_truoc_khi_goi_curl(self, tmp_path):
        """Chặn ở CẢ hai chỗ: lúc đọc và ngay trước khi ping.

        `hc_ping` dựng `${_URL}/fail`, và một caller về sau có thể truyền vào
        giá trị chưa qua `hc_doc_url`.
        """
        rc, _ = _goi_ham(tmp_path, "hc_ping", "http://hc-ping.test/abc")
        assert rc == 3

    def test_co_cua_sau_SOURCE_ONLY_nhung_khong_bao_gio_thoat_0(self, tmp_path):
        """Biến hook cho test không được biến thành công tắc tắt giám sát.

        Nếu nó lỡ có mặt trong môi trường cron, script phải thoát KHÁC 0 —
        thoát 0 nghĩa là cron xanh mỗi 5 phút trong khi không ai đo gì cả.
        """
        if _BASH is None:
            pytest.skip("không tìm thấy bash chạy được")
        env = dict(os.environ)
        env["QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY"] = "1"
        r = subprocess.run(
            [_BASH, _MONITOR.as_posix()],
            capture_output=True, text=True, timeout=120, env=env,
            encoding="utf-8", errors="replace",
        )
        assert r.returncode != 0, (
            "SOURCE_ONLY lọt vào cron mà script thoát 0 ⇒ giám sát bị tắt trong "
            "im lặng"
        )


_PRELUDE_CURLRC = """set -uo pipefail
QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY=1 . "$MONITOR"
# Script bật `set -e`, và cả hai lời gọi curl dưới đây CỐ Ý trả khác 0 (không có
# gì lắng nghe ở 127.0.0.1:9). Không tắt `-e` thì shell thoát ngay ở lệnh đầu và
# ca này im lặng không in mã nào — đúng chỗ nó vừa vấp.
set +e
export HOME="$FAKE_HOME"
printf 'url = "%s"\\n' "$URL_TEST" \\
  | curl --config - --fail --silent --max-time 5 --output /dev/null 2>/dev/null
echo "RC_KHONG_Q=$?"
hc_ping "$URL_TEST"
echo "RC_CO_Q=$?"
"""


class TestCurlKhongNgheCurlrc:
    """`-q` được đo bằng một `.curlrc` THẬT, không phải bằng hàm curl giả.

    Hàm giả trong các ca khác không mô phỏng được việc curl nạp tệp cấu hình
    mặc định, nên tự nó không chứng minh được gì về `-q`.
    """

    def test_curlrc_bi_bo_qua(self, tmp_path):
        if _BASH is None:
            pytest.skip("không tìm thấy bash chạy được")
        if shutil.which("curl") is None:
            pytest.skip("không có curl thật để đo")

        nha = tmp_path / "nha"
        nha.mkdir()
        # `interface = <không tồn tại>` cho mã thoát 45 (CURLE_INTERFACE_FAILED)
        # và KHÁC hẳn mã của lỗi mạng thường (7). Phải chọn đúng loại tuỳ chọn:
        # đã đo thì một tuỳ chọn KHÔNG TỒN TẠI chỉ sinh cảnh báo ở curl 8.14
        # (`is unknown`) mà mã thoát vẫn là 7, tức không phân biệt được gì; và
        # mọi tuỳ chọn đã có mặt trên dòng lệnh thì bị dòng lệnh ghi đè. Ở đây
        # `--interface` không có trên dòng lệnh nên giá trị trong .curlrc sống
        # sót — đúng cơ chế mà một `.curlrc` bị chạm dùng để chọn đường ra.
        (nha / ".curlrc").write_text(
            "interface = khong-co-giao-dien-nay-xyz\n", encoding="utf-8", newline="\n"
        )
        prelude = tmp_path / "curlrc.sh"
        prelude.write_text(_PRELUDE_CURLRC, encoding="utf-8", newline="\n")

        env = dict(os.environ)
        env.update({
            "MONITOR": _MONITOR.as_posix(),
            "FAKE_HOME": nha.as_posix(),
            # Cổng 9 (discard) trên loopback: từ chối kết nối ngay, không cần mạng.
            "URL_TEST": "https://127.0.0.1:9/khong-ton-tai",
        })
        env.pop("QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY", None)
        r = subprocess.run(
            [_BASH, prelude.as_posix()], capture_output=True, text=True,
            timeout=180, env=env, encoding="utf-8", errors="replace",
        )
        out = (r.stdout or "") + (r.stderr or "")
        khong_q = re.search(r"RC_KHONG_Q=(\d+)", out)
        co_q = re.search(r"RC_CO_Q=(\d+)", out)
        assert khong_q and co_q, out

        # Nửa đầu chứng minh `.curlrc` THỰC SỰ có hiệu lực — không có nó thì nửa
        # sau xanh vô nghĩa: một lệnh curl chỉ đơn giản không kết nối được cũng
        # cho kết quả "khác 2".
        assert khong_q.group(1) == "45", (
            f"thiếu `-q` mà .curlrc KHÔNG có hiệu lực (rc={khong_q.group(1)}, "
            f"chờ 45): ca này khi ấy không đo được gì. out={out!r}"
        )
        assert co_q.group(1) != "45", (
            f"hc_ping vẫn nạp .curlrc (rc={co_q.group(1)}) ⇒ `-q` không có tác dụng"
        )


# ---------------------------------------------------------------------------
# 4b. Quyền tệp bí mật: monitor FAIL-CLOSED, backup chỉ cảnh báo
# ---------------------------------------------------------------------------

class TestQuyenTepBiMat:
    @pytest.mark.parametrize(
        "mode,owner,group,nguoi_chay,hop_le",
        [
            ("600", "root", "root", "root", True),
            ("400", "root", "root", "root", True),
            # Mọi quyền của group/other đều bị loại: đọc được URL là ping
            # success thay được, tức VÔ HIỆU hoá cảnh báo.
            ("640", "root", "root", "root", False),
            ("604", "root", "root", "root", False),
            ("644", "root", "root", "root", False),
            ("660", "root", "root", "root", False),
            ("700", "root", "root", "root", False),
            ("777", "root", "root", "root", False),
            ("", "root", "root", "root", False),      # stat không đọc được
            # Tệp phải thuộc chính người đang chạy — nếu không, người khác ghi
            # được nội dung mà tiến trình này tin.
            ("600", "qlts", "root", "root", False),
            ("600", "root", "root", "runner", False),
            # Chạy bằng root (ca của cron production) thì group cũng phải root.
            ("600", "root", "adm", "root", False),
            # Ngoài root (runner CI) thì mode 600 đã cấm hết group/other rồi.
            ("600", "runner", "runner", "runner", True),
            ("600", "runner", "docker", "runner", True),
        ],
    )
    def test_luat_quyen_tep(self, tmp_path, mode, owner, group, nguoi_chay, hop_le):
        """Hàm THUẦN nên luật cho `root` được kiểm ở MỌI môi trường.

        Nếu chỉ đo bằng tệp thật thì nhánh `root` không bao giờ chạy: container
        backend chạy bằng `appuser`, runner CI chạy bằng `runner`. Một nhánh chỉ
        sống ở production mà không ca nào chạm tới là nhánh chưa được kiểm.
        """
        rc, out = _goi_ham(tmp_path, "hc_quyen_hop_le", mode, owner, group, nguoi_chay)
        assert (rc == 0) is hop_le, f"rc={rc} out={out!r}"

    def test_monitor_DUNG_HAN_khi_quyen_long_va_khong_ping_gi(
        self, tmp_path, bi_mat_day_du
    ):
        """Quyền lỏng ⇒ URL coi như đã lộ ⇒ KHÔNG dùng nó nữa, kể cả cho /fail.

        Người đọc được URL ping success thay được và cảnh báo bị vô hiệu. Im
        lặng ở đây là AN TOÀN: dead-man bên ngoài không nhận ping nào và sẽ kêu.
        """
        k = _chay(
            tmp_path,
            raw=str(int(time.time()) - 60),
            dong_bi_mat=bi_mat_day_du,
            mode_bi_mat=0o644,
        )
        assert k.rc == 4, f"rc={k.rc} out={k.out}"
        assert k.argv.strip() == "", "vẫn gọi curl dù tệp bí mật không an toàn"
        assert SENTINEL not in k.out

    def test_monitor_tu_choi_symlink_VA_dung_LY_DO_symlink(
        self, tmp_path, bi_mat_day_du
    ):
        """Khẳng định LÝ DO, không chỉ mã thoát — và đây là lý do phải thế.

        Phiên bản đầu của ca này chỉ kiểm `rc == 4`, và nó XANH cả khi nhánh
        symlink bị gỡ bỏ: `stat` của GNU KHÔNG deref symlink, nên mode đọc ra là
        777 (quyền cố định của symlink) và nhánh QUYỀN từ chối hộ. Guard canh
        hụt đúng kiểu "phép kiểm gộp vẫn xanh sau khi guard bị gỡ" — kiểm ngược
        causal đã bắt được.

        Nhánh này vẫn phải tồn tại: nó cho chẩn đoán ĐÚNG. Thông báo "quyền 777"
        đẩy người vận hành đi `chmod 600` chính symlink — việc trên Linux đổi
        quyền của ĐÍCH và không sửa gì cả.
        """
        k = _chay(
            tmp_path,
            raw=str(int(time.time()) - 60),
            dong_bi_mat=bi_mat_day_du,
            symlink_bi_mat=True,
        )
        assert k.rc == 4, f"rc={k.rc} out={k.out}"
        assert k.argv.strip() == ""
        assert "la symlink" in k.out, (
            "bị từ chối vì lý do KHÁC, nên ca này không chứng minh được nhánh "
            f"symlink còn tồn tại. out={k.out!r}"
        )

    def test_thieu_tep_van_la_ma_2_khong_phai_ma_4(self, tmp_path):
        """Hai nguyên nhân khác nhau, hai mã khác nhau.

        Gộp lại thì người đọc log cron không phân biệt được "chưa ai cài" với
        "ai đó đã chạm vào tệp bí mật".
        """
        k = _chay(tmp_path, raw=str(int(time.time())), dong_bi_mat=None)
        assert k.rc == 2

    def test_backup_chi_CANH_BAO_chu_khong_dung(self):
        """Hợp đồng khác nhau có chủ ý, và phải đọc ra được từ mã.

        Với monitor thì ping LÀ toàn bộ sản phẩm; với backup thì sản phẩm là bản
        sao lưu đã nằm ngoài máy chủ — từ chối ping không làm dữ liệu an toàn
        hơn, chỉ làm mất nốt tín hiệu cuối cùng.
        """
        than = _than_lenh(_doc(_BACKUP))
        assert "hc_kiem_quyen" in than, "backup không kiểm quyền tệp bí mật"
        dong = [d for d in than.splitlines() if "hc_kiem_quyen" in d]
        assert dong and all("log" in d and "WARN" in d for d in dong), (
            f"backup phải log WARN khi quyền lỏng, đang là: {dong}"
        )
        assert not any(re.search(r"\bexit\s+[1-9]", d) for d in dong), (
            "backup KHÔNG được thoát khác 0 chỉ vì quyền tệp bí mật"
        )


# ---------------------------------------------------------------------------
# 5. Bất biến tĩnh — những thứ không có ca chạy nào bắt được
# ---------------------------------------------------------------------------

class TestBatBienTinh:
    @pytest.mark.parametrize("tep", ["monitor", "lib", "backup"])
    def test_khong_dung_jq(self, tep):
        """VPS KHÔNG cài `jq`. Một lệnh `jq` sẽ chỉ đổ lúc 03:00 hoặc lúc sự cố."""
        than = _than_lenh(_doc(_BA_TEP[tep]))
        assert not re.search(r"\bjq\b", than), f"{tep} có dùng jq"

    @pytest.mark.parametrize("tep", ["monitor", "lib", "backup"])
    def test_khong_dung_here_string(self, tep):
        """`<<<` của bash ghi ra TỆP TẠM ⇒ bí mật rơi xuống đĩa."""
        than = _than_lenh(_doc(_BA_TEP[tep]))
        assert "<<<" not in than, f"{tep} dùng here-string"

    def test_monitor_va_backup_deu_fail_fast(self):
        for p in (_MONITOR, _BACKUP):
            assert re.search(r"^set -euo pipefail$", _doc(p), re.M), f"{p.name}"

    def test_dong_cron_duoc_tai_lieu_hoa_KHONG_phu_thuoc_bit_thuc_thi(self):
        """Cron gọi script này mỗi 5 phút, và một `Permission denied` ở đó là
        giám sát tắt trong im lặng — không khác gì không có script.

        Bit thực thi trong git thì KHÔNG kiểm được ở mọi môi trường: bind mount
        từ Windows bịa ra mode, và container backend không có `git`. Một phép
        kiểm `skip` khi thiếu công cụ là đúng cái lỗ mà repo này cấm. Nên thay vì
        canh cái bit, bản này LOẠI BỎ chế độ lỗi: dòng cron được tài liệu hoá gọi
        qua `bash`, chạy đúng bất kể mode. Mode 100755 vẫn được đặt, như lớp dư.
        """
        for than, nhan in ((_doc(_MAU_ENV), "ops/healthchecks.env.example"),
                           (_doc(_MONITOR), "celery-heartbeat-monitor.sh")):
            dong = [d for d in than.splitlines() if "*/5 * * * *" in d]
            assert dong, f"{nhan}: không có dòng cron `*/5 * * * *` nào"
            mau = re.compile(
                r"\*/5 \* \* \* \*\s+bash\s+\S*celery-heartbeat-monitor\.sh"
            )
            for d in dong:
                assert mau.search(d), (
                    f"{nhan}: dòng cron phải gọi qua `bash` để không phụ thuộc "
                    f"bit thực thi — đang là: {d.strip()!r}"
                )

    def test_khong_script_nao_SOURCE_tep_bi_mat(self):
        """Tệp bí mật là DỮ LIỆU.

        `source` biến một tệp cấu hình thành đường thực thi mã dưới quyền root,
        và `set -a` quanh nó còn export luôn bí mật sang mọi tiến trình con.
        """
        for p in (_MONITOR, _LIB, _BACKUP):
            than = _than_lenh(_doc(p))
            xau = [
                d for d in than.splitlines()
                if re.match(r"^\s*(\.|source)\s", d)
                and re.search(r"TEP_BI_MAT|healthchecks\.env|\.env\b", d)
            ]
            assert xau == [], f"{p.name} source tệp bí mật: {xau}"

    def test_moi_loi_goi_curl_deu_qua_config_stdin(self):
        """Không có `curl` nào mang URL trong argv, ở bất kỳ tệp nào."""
        bien_url = ("_URL", "PING_URL", "HEALTHCHECK_PING_URL", "url")
        lenh = _cac_lenh_curl()
        assert lenh, "không tìm thấy lời gọi curl nào — guard rỗng"
        for nhan, dong in lenh:
            assert "--config" in dong, f"{nhan}: curl không dùng --config: {dong}"
            # CHỈ phần sau từ `curl`: `printf 'url = "%s"' "$url" | curl …` là
            # đúng hình dạng cần có, nên soi cả dòng sẽ báo động giả vào chính
            # cái `printf` đang làm việc đúng.
            sau_curl = re.split(r"(?:^|\s|\|)curl\s", dong, maxsplit=1)[-1]
            for b in bien_url:
                assert f'"${b}"' not in sau_curl and f"${{{b}}}" not in sau_curl, (
                    f"{nhan}: URL vào argv của curl qua ${b}: {dong}"
                )

    def test_curl_luon_co_q_o_dau_de_bo_qua_curlrc(self):
        """`--config -` KHÔNG vô hiệu hoá cấu hình mặc định.

        Thiếu `-q` thì `~/.curlrc` (của root, dưới cron) vẫn được nạp TRƯỚC, và
        một dòng trong đó đủ để đổi `proxy`, thêm `output`, bật `trace` — tức
        chuyển hướng ping đi nơi khác hoặc ghi chính URL ra tệp. Tài liệu curl
        nói rõ `-q` phải là đối số ĐẦU TIÊN mới có tác dụng.
        """
        lenh = _cac_lenh_curl()
        assert lenh, "không tìm thấy lời gọi curl nào — guard rỗng"
        for nhan, dong in lenh:
            assert re.search(r"(^|\s|\|)\s*curl\s+-q(\s|$)", dong), (
                f"{nhan}: `-q` phải đứng NGAY SAU `curl`, đang là: {dong}"
            )

    def test_curl_ghim_giao_thuc_https_ca_khi_redirect(self):
        """Chốt ở TẦNG CURL, độc lập với phép kiểm chuỗi.

        Một redirect sang `http://` hoặc `file://` phải bị từ chối chứ không
        được đi theo.
        """
        lenh = _cac_lenh_curl()
        assert lenh, "không tìm thấy lời gọi curl nào — guard rỗng"
        for nhan, dong in lenh:
            assert "--proto '=https'" in dong, f"{nhan}: thiếu --proto: {dong}"
            assert "--proto-redir '=https'" in dong, (
                f"{nhan}: thiếu --proto-redir: {dong}"
            )

    def test_backup_dung_CHUNG_helper_khong_chep_doi(self):
        than = _than_lenh(_doc(_BACKUP))
        assert "hc_doc_url" in than and "hc_ping" in than, (
            "backup không dùng helper chung ⇒ hai bản xử lý bí mật sẽ trôi lệch"
        )
        assert "lib/healthchecks.sh" in than

    def test_backup_khong_doc_bien_cua_celery(self):
        than = _than_lenh(_doc(_BACKUP))
        assert "CELERY_HEARTBEAT_PING_URL" not in than

    def test_backup_khong_con_doc_URL_tu_environment(self):
        """Bản trước dùng `${HEALTHCHECK_PING_URL:-}` từ environment.

        Biến môi trường đi theo mọi tiến trình con; và nếu ai đặt nó vào
        `.env.production` cho tiện thì nó bị nướng vào container và lộ qua
        `docker inspect .Config.Env`.
        """
        than = _than_lenh(_doc(_BACKUP))
        assert "${HEALTHCHECK_PING_URL:-}" not in than
        assert "$HEALTHCHECK_PING_URL" not in than

    def test_monitor_doc_dung_DB_cua_app(self):
        than = _than_lenh(_doc(_MONITOR))
        assert _so_shell("REDIS_DB", than) == 1
        compose = yaml.safe_load(_doc(_COMPOSE))
        urls = set()
        for ten in ("backend", "celery-worker", "celery-beat"):
            dv = compose["services"].get(ten) or {}
            u = (dv.get("environment") or {}).get("REDIS_URL")
            if u:
                urls.add(str(u))
        assert urls, "không đọc được REDIS_URL nào từ compose"
        for u in urls:
            assert u.rstrip("/").endswith("/1"), (
                f"REDIS_URL={u} — monitor đọc `-n 1`, lệch DB là đọc một khoá "
                "không bao giờ tồn tại và báo `missing` mỗi 5 phút"
            )


# ---------------------------------------------------------------------------
# 6. Chuỗi ngưỡng: 300 → 900 → 1200, khớp qua ba tệp
# ---------------------------------------------------------------------------

class TestChuoiNguong:
    @pytest.fixture(scope="class")
    def so(self) -> dict:
        mon = _than_lenh(_doc(_MONITOR))
        py = _doc(_TASK_PY)
        return {
            "nhip": _so_python("HEARTBEAT_INTERVAL_SECONDS", py),
            "ttl": _so_python("HEARTBEAT_TTL_SECONDS", py),
            "moc_py": _so_python("MIN_PLAUSIBLE_EPOCH", py),
            "cu": _so_shell("NGUONG_CU_GIAY", mon),
            "moc_sh": _so_shell("EPOCH_TOI_THIEU", mon),
            "lech": _so_shell("LECH_TUONG_LAI_GIAY", mon),
        }

    def test_nguong_cu_dung_bang_ba_nhip_lo(self, so):
        assert so["cu"] == 3 * so["nhip"], (
            f"cũ={so['cu']}s nhưng nhịp={so['nhip']}s. Nhỏ hơn thì một lượt "
            "redeploy cũng kêu; lớn hơn thì cửa sổ mù rộng ra trong im lặng."
        )

    def test_TTL_lon_hon_nguong_cu(self, so):
        assert so["ttl"] > so["cu"], (
            f"TTL={so['ttl']}s <= cũ={so['cu']}s ⇒ nhánh `stale` là MÃ CHẾT: "
            "khoá luôn hết hạn trước khi bị coi là cũ, nên một worker im lặng "
            "chỉ còn hiện ra dạng `missing`."
        )

    def test_TTL_lon_hon_nhip_de_khong_tu_bao_dong(self, so):
        assert so["ttl"] > so["nhip"] * 2

    def test_moc_epoch_hop_ly_khop_nhau_hai_ben(self, so):
        assert so["moc_py"] == so["moc_sh"], (
            f"python={so['moc_py']} shell={so['moc_sh']} — hai bên hiểu khác "
            "nhau về 'giá trị này là rác' thì task ghi ra thứ monitor từ chối"
        )

    def test_lech_dong_ho_cho_phep_nho_hon_nguong_cu(self, so):
        assert 0 < so["lech"] < so["cu"]

    def test_khoa_redis_dung_mot_ten_o_ca_hai_ben(self):
        py = _doc(_TASK_PY)
        khop = re.search(r'^HEARTBEAT_KEY\s*=\s*"([^"]+)"', py, re.M)
        assert khop, "không thấy HEARTBEAT_KEY dạng literal trong task"
        mon = re.search(
            r'^HEARTBEAT_KEY="([^"]+)"', _than_lenh(_doc(_MONITOR)), re.M
        )
        assert mon, "không thấy HEARTBEAT_KEY trong monitor"
        assert khop.group(1) == mon.group(1), (
            f"task ghi `{khop.group(1)}`, monitor đọc `{mon.group(1)}` — hai "
            "khoá khác nhau thì monitor báo `missing` vĩnh viễn và không ai biết"
        )


# ---------------------------------------------------------------------------
# 7. Tệp mẫu: chỉ tên biến, tuyệt đối không giá trị
# ---------------------------------------------------------------------------

class TestTepMau:
    def test_khong_co_gia_tri_nao_trong_tep_mau(self):
        """Một URL thật lọt vào tệp mẫu là commit bí mật vào git công khai."""
        for dong in _doc(_MAU_ENV).splitlines():
            if dong.lstrip().startswith("#") or not dong.strip():
                continue
            assert re.fullmatch(r"[A-Z0-9_]+=", dong.strip()), (
                f"dòng mẫu có giá trị: {dong!r}"
            )

    def test_co_ca_hai_ten_bien(self):
        than = _doc(_MAU_ENV)
        for ten in ("CELERY_HEARTBEAT_PING_URL=", "HEALTHCHECK_PING_URL="):
            assert re.search(rf"^{re.escape(ten)}$", than, re.M), ten

    def test_ghi_ro_lich_cron_va_mui_gio(self):
        than = _doc(_MAU_ENV)
        assert "*/5" in than, "thiếu lịch cron của monitor"
        assert "0 3 * * *" in than, "thiếu lịch cron của backup"
        assert "Asia/Ho_Chi_Minh" in than, (
            "thiếu múi giờ — cron của VPS chạy theo giờ máy; để healthchecks ở "
            "UTC là lệch 7 tiếng"
        )

    def test_tep_THAT_van_bi_gitignore_chan(self):
        """Tệp mẫu được commit, tệp thật thì không bao giờ."""
        gi = _doc(_GOC / ".gitignore")
        assert re.search(r"^!ops/healthchecks\.env\.example$", gi, re.M), (
            "thiếu dòng gỡ ignore ⇒ `*.env.*` nuốt tệp mẫu và `git add` từ chối "
            "trong im lặng"
        )
        assert re.search(r"^\*\.env$", gi, re.M), (
            "thiếu `*.env` ⇒ tệp bí mật THẬT có thể bị commit"
        )


# ---------------------------------------------------------------------------
# 8. CI phải NHÌN THẤY hai tệp test này
# ---------------------------------------------------------------------------

class TestCINhinThay:
    @pytest.fixture(scope="class")
    def cac_leg(self) -> list[dict]:
        wf = yaml.safe_load(_doc(_WF))
        return wf["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]

    @pytest.mark.parametrize("tep", [TEP_TEST_TASK, TEP_TEST_SCRIPT])
    def test_tep_test_nam_trong_dung_MOT_leg(self, cac_leg, tep):
        """Tệp không có tên trong tier nào thì KHÔNG shard nào chạy nó mà
        required check VẪN XANH."""
        chua = [
            str(leg.get("tier", ""))
            for leg in cac_leg
            if tep in str(leg.get("tests", "")).split()
        ]
        assert len(chua) == 1, (
            f"{tep} nằm trong {len(chua)} leg: {chua!r}. 0 leg nghĩa là guard "
            "này không bao giờ chạy mà cổng vẫn xanh."
        )

    def test_bo_loc_paths_phu_MOI_duong_ma_guard_nay_doc(self):
        """Guard đọc một tệp mà `paths:` không liệt kê ⇒ canh trên giấy.

        Ca cụ thể, không phải giả định: một PR CHỈ dán URL thật vào
        `ops/healthchecks.env.example`, hoặc CHỈ gỡ dòng gỡ-ignore khỏi
        `.gitignore`, sẽ không kích hoạt `backend-test.yml` — nên hai guard
        tương ứng ở tệp này không chạy lần nào mà required check vẫn xanh.
        """
        wf = yaml.safe_load(_doc(_WF))
        kich_hoat = wf.get("on", wf.get(True, {}))
        mau = kich_hoat.get("pull_request", {}).get("paths") or []
        assert mau, "backend-test.yml không có bộ lọc `paths:`"

        can_phu = [
            "scripts/celery-heartbeat-monitor.sh",
            "scripts/lib/healthchecks.sh",
            "scripts/backup-with-offsite.sh",
            "ops/healthchecks.env.example",
            "Backend_FastAPI/app/tasks/heartbeat_tasks.py",
            "docker-compose.yml",
            ".github/workflows/backend-test.yml",
            ".gitignore",
        ]

        def _khop(duong: str, pat: str) -> bool:
            if pat.endswith("/**"):
                return duong.startswith(pat[:-2])
            return duong == pat

        thieu = [d for d in can_phu if not any(_khop(d, p) for p in mau)]
        assert not thieu, (
            f"gate `pytest` KHÔNG chạy khi các đường sau đổi: {thieu}. "
            f"Bộ lọc hiện có: {mau}"
        )
