"""V6 — hợp đồng TĨNH của bản vá che log: nginx, Next, một nguồn mẫu, lớp phụ.

Tệp này không chạy nginx; bằng chứng HÀNH VI (log thật không còn token mà VẪN
ghi dòng, header thật) là E2E chạy tay
``tests-e2e/nginx-packaging/kiem-log-che-token.sh``. Ở đây khoá những thứ mà
E2E không chạy mỗi PR:

* ``map`` của nginx phủ ĐÚNG tập tiền tố token của Python (nginx không đọc được
  hằng Python ⇒ hai bản, nên phải có test khoá chúng bằng nhau — CLAUDE.md §7);
* ``log_format main`` chỉ dùng biến đã che, ``access_log`` cấp ``http`` vẫn bật,
  và ``access_log off`` không lan sang location nào ngoài bốn chỗ sẵn có;
* trang token gửi ``Referrer-Policy: no-referrer`` ở CẢ nginx lẫn Next (hai tầng
  cùng gửi header ⇒ lệch giá trị là trình duyệt lấy cái đứng sau);
* mẫu che chỉ khai ở ``app/core/log_redaction.py``;
* lớp phụ: các lời gọi log ở ``admission_service`` không còn mang khoá CCCD.

Chạy không cần Docker/CSDL ⇒ nằm ở lát Tier 5.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
NGINX_CONF = REPO / "nginx" / "nginx.conf"
TEMPLATE = REPO / "nginx" / "templates" / "default.conf.template"
NEXT_CONFIG = REPO / "frontend" / "next.config.ts"


def _doc(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _bo_chu_thich(text: str) -> str:
    """Cắt chú thích ``#`` NGOÀI chuỗi ngoặc (regex trong ``map`` có ``[^/?#\\s]``)."""
    ra = []
    for line in text.splitlines():
        ngoac = None
        cat = len(line)
        for i, c in enumerate(line):
            if ngoac:
                if c == ngoac:
                    ngoac = None
            elif c in "'\"":
                ngoac = c
            elif c == "#":
                cat = i
                break
        ra.append(line[:cat])
    return "\n".join(ra)


def _khoi_map(conf: str, nguon: str, dich: str) -> str:
    m = re.search(
        r"map\s+%s\s+%s\s*\{(.*?)\n\s*\}" % (re.escape(nguon), re.escape(dich)),
        _bo_chu_thich(conf),
        re.S,
    )
    assert m, "nginx.conf THIẾU map %s %s" % (nguon, dich)
    return m.group(1)


def _cau_lenh(conf: str, ten: str) -> list[str]:
    """Các câu lệnh ``ten …;`` (có thể trải nhiều dòng), đã bỏ chú thích."""
    return [
        " ".join(m.group(0).split())
        for m in re.finditer(r"(?<![A-Za-z_])%s\b[^;]*;" % re.escape(ten), _bo_chu_thich(conf))
    ]


def _khoi_chua(conf: str, chi_thi: str) -> list[str]:
    """Đầu khối (``location …``/``server``/``http``) bao quanh mỗi lần xuất hiện
    ``chi_thi``. Bỏ chuỗi trong ngoặc trước khi đếm ``{`` ``}`` (thân `return 503
    '{"detail":…}'` có ngoặc nhọn)."""
    ngan_xep: list[str] = []
    ket_qua: list[str] = []
    for dong in conf.splitlines():
        sach = re.sub(r"'[^']*'|\"[^\"]*\"", "''", dong).split("#", 1)[0]
        if " ".join(sach.split()).startswith(chi_thi):
            ket_qua.append(ngan_xep[-1] if ngan_xep else "<ngoai-cung>")
        i = 0
        while i < len(sach):
            c = sach[i]
            if c == "{":
                dau = sach[:i].split(";")[-1].split("}")[-1]
                ngan_xep.append(" ".join(dau.split()))
            elif c == "}":
                if ngan_xep:
                    ngan_xep.pop()
            i += 1
    return ket_qua


# ---------------------------------------------------------------------------
# nginx — access log
# ---------------------------------------------------------------------------


def test_map_nginx_trung_tap_tien_to_token_cua_python():
    from app.core.log_redaction import nginx_token_path_alternation

    mong_doi = '"~^(.*?(?:%s))[^/?#\\s]+(.*)$" "$1<redacted>$2";' % nginx_token_path_alternation()
    conf = _doc(NGINX_CONF)
    lech = [
        dich for nguon, dich in (("$request", "$qlts_request_log"),
                                 ("$http_referer", "$qlts_referer_log"))
        if mong_doi not in _khoi_map(conf, nguon, dich)
    ]
    assert lech == [], (
        "map %s không phủ ĐÚNG TOKEN_PATH_PREFIXES của log_redaction.py; mong đợi dòng:\n%s"
        % (lech, mong_doi))


def test_log_format_main_chi_dung_bien_da_che():
    lf = [c for c in _cau_lenh(_doc(NGINX_CONF), "log_format") if c.startswith("log_format main ")]
    assert len(lf) == 1, "HẠ TẦNG: không thấy đúng một log_format main"
    tho = re.findall(r"\$(?:request|http_referer)(?![A-Za-z0-9_])", lf[0])
    assert tho == [] and "$qlts_request_log" in lf[0] and "$qlts_referer_log" in lf[0], (
        "log_format main còn ghi biến THÔ %s (phải là $qlts_request_log/$qlts_referer_log): %s"
        % (tho, lf[0]))


def test_access_log_cap_http_van_bat_bang_khuon_main():
    al = _cau_lenh(_doc(NGINX_CONF), "access_log")
    assert al == ["access_log /var/log/nginx/access.log main;"], (
        "access_log cấp http phải BẬT và dùng khuôn main đã che (không 'off', không "
        "khuôn khác): %s" % al)


def test_access_log_off_khong_lan_sang_location_token():
    """Chỉ bốn location sẵn có được tắt log. Tắt log ở location tuyển sinh hay
    ``location /`` là MẤT dấu vết điều tra mà KHÔNG đóng cửa Referer."""
    co = sorted(_khoi_chua(_doc(TEMPLATE), "access_log off"))
    assert co == sorted([
        "location = /nginx-alive",
        "location /r/",
        "location /api/public/sms/landing/",
        "location /lp/",
    ]), "access_log off xuất hiện ngoài bốn location cho phép: %s" % co


# ---------------------------------------------------------------------------
# Referrer-Policy cho trang token — nginx + Next
# ---------------------------------------------------------------------------


def test_nginx_trang_token_gui_no_referrer():
    khoi = _khoi_map(_doc(NGINX_CONF), "$uri", "$qlts_referrer_policy")
    dung_bien = [
        c for c in _cau_lenh(_doc(TEMPLATE), "add_header")
        if c.startswith("add_header Referrer-Policy ")
    ]
    assert ('"~/(?:confirm|magic-link)/" "no-referrer";' in khoi
            and 'default "strict-origin-when-cross-origin";' in khoi
            and "add_header Referrer-Policy $qlts_referrer_policy always;" in dung_bien), (
        "nginx: map $qlts_referrer_policy hoặc add_header cấp server sai: %s / %s"
        % (khoi.strip(), dung_bien))


def test_next_trang_token_gui_no_referrer_sau_khoi_chung():
    src = _doc(NEXT_CONFIG)
    vi_tri_chung = src.find('source: "/(.*)"')
    assert vi_tri_chung >= 0, "HẠ TẦNG: không thấy khối headers source /(.*)"
    thieu = []
    for trang in ("/confirm/:path*", "/magic-link/:path*"):
        m = re.search(
            r'source:\s*"%s",\s*headers:\s*\[\s*\{\s*key:\s*"Referrer-Policy",\s*value:\s*"no-referrer"'
            % re.escape(trang),
            src,
        )
        if not m or m.start() < vi_tri_chung:
            thieu.append(trang)
    assert thieu == [], (
        "next.config.ts: trang %s không có Referrer-Policy no-referrer ĐỨNG SAU khối /(.*)"
        % thieu)


# ---------------------------------------------------------------------------
# Một nguồn mẫu + lớp phụ
# ---------------------------------------------------------------------------


def test_mau_che_chi_khai_o_log_redaction():
    """Không module nào khác trong ``app/`` tự khai tiền tố token hay chuỗi che —
    bản chép thứ hai (như ``_SMS_BEARER_PREFIXES`` cũ ở ``exception_handlers``)
    là nơi sẽ bị sót khi thêm tiền tố mới."""
    from app.core.log_redaction import REDACTED, REDACTED_KEY, TOKEN_PATH_PREFIXES

    cam = set(TOKEN_PATH_PREFIXES) | {REDACTED, REDACTED_KEY}
    vi_pham = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        if p.as_posix().endswith("app/core/log_redaction.py"):
            continue
        cay = ast.parse(p.read_text(encoding="utf-8"))
        trong_f = {
            id(v) for n in ast.walk(cay) if isinstance(n, ast.JoinedStr) for v in n.values
        }
        for n in ast.walk(cay):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in trong_f and n.value in cam):
                vi_pham.append("%s:%d %r" % (p.relative_to(BACKEND).as_posix(), n.lineno, n.value))
    assert vi_pham == [], "mẫu che bị chép ngoài log_redaction.py: %s" % vi_pham


def test_lop_phu_admission_service_khong_log_khoa_cccd():
    from app.core.log_redaction import PII_KEYS

    khoa_cccd = {k for k in PII_KEYS if re.search(r"citizen|cccd|cmnd|id_number", k)}
    cay = ast.parse((BACKEND / "app/services/admission_service.py").read_text(encoding="utf-8"))
    vi_pham = []
    for n in ast.walk(cay):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr not in {"debug", "info", "warning", "warn", "error", "exception", "critical"}:
            continue
        nhan = n.func.value
        ten = nhan.id if isinstance(nhan, ast.Name) else getattr(nhan, "attr", "")
        if "log" not in ten.lower():
            continue
        vi_pham += ["%d:%s" % (n.lineno, k.arg) for k in n.keywords if k.arg in khoa_cccd]
    assert vi_pham == [], "lời gọi log ở admission_service còn mang khoá CCCD: %s" % vi_pham
