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
    ``chi_thi``."""
    return [khoi for khoi, _ in _chi_thi_theo_khoi(conf, chi_thi)]


def _chi_thi_theo_khoi(conf: str, chi_thi: str) -> list[tuple[str, str]]:
    """``(đầu khối bao quanh, dòng chỉ thị đã gọn)`` cho mỗi dòng bắt đầu bằng
    ``chi_thi``. Bỏ chuỗi trong ngoặc trước khi đếm ``{`` ``}`` (thân `return 503
    '{"detail":…}'` có ngoặc nhọn)."""
    ngan_xep: list[str] = []
    ket_qua: list[tuple[str, str]] = []
    for dong in conf.splitlines():
        sach = re.sub(r"'[^']*'|\"[^\"]*\"", "''", dong).split("#", 1)[0]
        if " ".join(sach.split()).startswith(chi_thi):
            ket_qua.append((ngan_xep[-1] if ngan_xep else "<ngoai-cung>",
                            " ".join(_bo_chu_thich(dong).split())))
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
    """Tập DẤU HIỆU của hai map = ``nginx_token_marker_alternation()`` (nguồn chuẩn
    Python: ``TOKEN_PATH_PREFIXES`` + tham số query chứa ``token``) — CLAUDE.md §7."""
    from app.core.log_redaction import nginx_token_marker_alternation

    alt = nginx_token_marker_alternation()
    mong_doi = {
        ("$request", "$qlts_request_log"):
            '"~*^(.*?(?:%s))(.*?)( HTTP/[0-9.]+)?$" "$1<redacted>$3";' % alt,
        ("$http_referer", "$qlts_referer_log"):
            '"~*^(.*?(?:%s))(.*)$" "$1<redacted>";' % alt,
    }
    conf = _doc(NGINX_CONF)
    lech = [
        dich for (nguon, dich), dong in mong_doi.items()
        if dong not in _khoi_map(conf, nguon, dich)
    ]
    assert lech == [], (
        "map %s không phủ ĐÚNG tập dấu hiệu của log_redaction.py; mong đợi:\n%s"
        % (lech, "\n".join(mong_doi.values())))


def _ap_map(khoi: str, gia_tri: str) -> str | None:
    """Mô phỏng ``map`` nginx trên một giá trị: regex ĐẦU TIÊN khớp thắng (``~``
    phân biệt hoa thường, ``~*`` không), ``$n`` trong đích = nhóm bắt. Không regex
    nào khớp ⇒ ``None`` (đi ``default`` = giá trị THÔ)."""
    for m in re.finditer(r'^\s*"([^"]*)"\s+"([^"]*)"\s*;', khoi, re.M):
        khoa, dich = m.group(1), m.group(2)
        if not khoa.startswith("~"):
            continue
        hoa_thuong = khoa.startswith("~*")
        k = re.search(khoa[2:] if hoa_thuong else khoa[1:], gia_tri, re.I if hoa_thuong else 0)
        if k:
            return re.sub(r"\$(\d)", lambda g: k.group(int(g.group(1))) or "", dich)
    return None


def test_map_nginx_che_gia_tri_tham_so_query_chua_token():
    """``/reset-password?token=…`` (``user_service``) vào cột request lẫn referer của
    access log ⇒ CẢ HAI map phải che giá trị tham số query có tên chứa ``token``.
    Tiền tố đường dẫn đã có test riêng; ca này canh nhánh query."""
    conf = _doc(NGINX_CONF)
    mau = {
        ("$request", "$qlts_request_log"):
            "GET /reset-password?token=GIAV6QTOKEN01&x=1 HTTP/1.1",
        ("$http_referer", "$qlts_referer_log"):
            "https://example.invalid/reset-password?reset_token=GIAV6QTOKEN01",
    }
    lo = {}
    for (nguon, dich), gia_tri in mau.items():
        ra = _ap_map(_khoi_map(conf, nguon, dich), gia_tri)
        if ra is None or "GIAV6QTOKEN01" in ra:
            lo[dich] = ra if ra is not None else "<không regex nào khớp ⇒ ghi THÔ>"
    assert lo == {}, "map nginx để lọt token trong tham số query: %s" % lo


# URI mang NHIỀU token / token ở dạng khó (F31). Mỗi giá trị giả bắt đầu ``GIA``.
_URI_NHIEU_TOKEN = [
    "/confirm/GIAV6A?token=GIAV6B",
    "/reset-password?token=GIAV6A&refresh_token=GIAV6B",
    "/x?a=1&refresh_token=GIAV6A&token=GIAV6B",
    "/magic-link/withdraw/GIAV6A/confirm/GIAV6B",
    "/api/admissions/confirm/GIAV6A?Token=GIAV6B&x=1",
    "/login?next=%2Fconfirm%2FGIAV6A&access-token=GIAV6B",
    "/r/GIAV6A?lp=1&id_token=GIAV6B",
]


def _gia_tri_mau() -> list[tuple[tuple[str, str], str]]:
    mau = []
    for uri in _URI_NHIEU_TOKEN:
        for ban in ("HTTP/1.1", "HTTP/2.0"):
            mau.append((("$request", "$qlts_request_log"), "GET %s %s" % (uri, ban)))
        mau.append((("$http_referer", "$qlts_referer_log"), "https://example.invalid" + uri))
    return mau


def test_map_nginx_che_het_khi_mot_gia_tri_co_nhieu_token():
    """F31: ``map`` chỉ áp MỘT regex (khớp đầu tiên thắng). Kiểu "thay một token,
    giữ đuôi" để lọt token thứ hai ⇒ thiết kế cắt từ DẤU HIỆU ĐẦU TIÊN. Canh: không
    giá trị giả nào sống sót, ở CẢ ``$request`` lẫn ``$http_referer``."""
    conf = _doc(NGINX_CONF)
    lo = {}
    for (nguon, dich), gia_tri in _gia_tri_mau():
        ra = _ap_map(_khoi_map(conf, nguon, dich), gia_tri)
        if ra is None or "GIAV6" in ra:
            lo[gia_tri] = ra if ra is not None else "<không regex nào khớp ⇒ ghi THÔ>"
    assert lo == {}, "map nginx để lọt token khi một giá trị có nhiều token:\n%s" % "\n".join(
        "  %s  →  %s" % kv for kv in lo.items())


def test_map_nginx_van_giu_phan_truoc_dau_hieu_va_giao_thuc():
    """Dòng log vẫn CÓ ÍCH: giữ phương thức + đường dẫn tới dấu hiệu đầu tiên + giao
    thức (``$request``) / gốc URL (``$http_referer``); chỉ phần sau bị thay."""
    conf = _doc(NGINX_CONF)
    thuc = (
        _ap_map(_khoi_map(conf, "$request", "$qlts_request_log"),
                "GET /confirm/GIAV6A?token=GIAV6B HTTP/1.1"),
        _ap_map(_khoi_map(conf, "$http_referer", "$qlts_referer_log"),
                "https://example.invalid/reset-password?token=GIAV6A&refresh_token=GIAV6B"),
    )
    assert thuc == (
        "GET /confirm/<redacted> HTTP/1.1",
        "https://example.invalid/reset-password?token=<redacted>",
    ), "map nginx không giữ phần trước dấu hiệu / giao thức: %s" % (thuc,)


#: Biến DUY NHẤT được phép trong ``log_format main`` (V6 vòng 5: danh sách CHO PHÉP thay
#: danh sách cấm — đột biến thêm ``$uri`` thô làm lộ token mà ca cũ chỉ cấm
#: ``$request``/``$http_referer`` vẫn xanh; E2E thật bắt được, ca tĩnh thì không).
_BIEN_LOG_FORMAT_CHO_PHEP = {
    "remote_addr", "remote_user", "time_local", "qlts_request_log", "status",
    "body_bytes_sent", "qlts_referer_log", "http_user_agent", "http_x_forwarded_for",
}


def test_log_format_main_chi_dung_bien_da_che():
    lf = [c for c in _cau_lenh(_doc(NGINX_CONF), "log_format") if c.startswith("log_format main ")]
    assert len(lf) == 1, "HẠ TẦNG: không thấy đúng một log_format main"
    bien = set(re.findall(r"\$\{?([A-Za-z0-9_]+)", lf[0]))
    la = sorted(bien - _BIEN_LOG_FORMAT_CHO_PHEP)
    assert la == [] and "$qlts_request_log" in lf[0] and "$qlts_referer_log" in lf[0], (
        "log_format main ghi biến NGOÀI danh sách cho phép %s (URL/Referer phải qua "
        "$qlts_request_log/$qlts_referer_log đã che): %s" % (la, lf[0]))


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
# nginx — error_log (N17.10 B): location phục vụ URL token KHÔNG ghi error_log
# ---------------------------------------------------------------------------
#
# `error_log` in nguyên `request: "…"` khi upstream lỗi / `limit_req` từ chối —
# `log_format` không chạm tới. Ở đây khoá TĨNH: location mà nginx THỰC SỰ chọn
# cho mỗi URL token có `error_log /dev/null;`, còn location thường vẫn giữ mức
# `warn` của nginx.conf. Bằng chứng HÀNH VI (502 thật, `limit_req` thật) ở E2E
# `tests-e2e/nginx-packaging/kiem-log-che-token.sh` (mã E1–E4).

#: URI (nginx chọn location theo URI ĐÃ giải mã, không có query) của MỌI dạng URL
#: token ứng dụng phát ra — rà 24-10: trang FE ``app/confirm/[token]``,
#: ``app/magic-link/[action]/[token]``, ``app/(auth)/reset-password`` (``?token=``
#: do ``user_service.py`` dựng), ``app/lp/[code]``; backend ``/r/{code}``,
#: ``/api/public/sms/landing/{code}``, ``/api/admissions/confirm/{token}``,
#: ``/api/v2/admissions/magic-link/{action}/{token}``. Kèm biến thể hoa/thường và
#: dấu ``/`` cuối.
_URI_TOKEN = (
    "/confirm/GIA", "/Confirm/GIA", "/magic-link/withdraw/GIA",
    "/reset-password", "/reset-password/", "/lp/GIA", "/lp/GIA/nganh", "/r/GIA",
    "/api/public/sms/landing/GIA", "/api/admissions/confirm/GIA",
    "/api/v2/admissions/magic-link/confirm/GIA",
)
#: Đối chứng: tắt error_log toàn cục (lựa chọn C) là mất chẩn đoán 502/504 cả site.
_URI_THUONG = (
    "/", "/login", "/dashboard", "/reset-password-cu", "/confirmation", "/api/payments/1",
    "/api/auth/login", "/socket.io/", "/_next/static/a.js", "/health",
)
#: Đánh đổi ĐỀ XUẤT, CHỜ OWNER CHỐT — khoá để không ai tưởng là lỗi: API tuyển sinh không
#: token cũng mất error_log vì dùng chung location có cổng đóng băng.
_URI_TUYEN_SINH_KHONG_TOKEN = ("/api/admissions/123", "/api/v2/admin/rounds")
_DEV_NULL = "error_log /dev/null;"
_MUC_MAIN = "error_log /var/log/nginx/error.log warn;"


def _cac_khoi(text: str) -> list[tuple[str, int, int, int]]:
    """Mọi khối ``đầu { thân }``: ``(đầu đã gọn, vị trí đầu thân, vị trí cuối thân,
    độ sâu)``. ``text`` đã bỏ chú thích và chuỗi ngoặc."""
    ra, ngan, moc = [], [], 0
    for i, c in enumerate(text):
        if c == "{":
            ngan.append((" ".join(text[moc:i].split()), i + 1))
        elif c == "}":
            dau, bat_dau = ngan.pop()
            ra.append((dau, bat_dau, i, len(ngan)))
        if c in ";{}":
            moc = i + 1
    assert not ngan, "HẠ TẦNG: ngoặc nhọn không cân"
    return ra


def _sach(text: str) -> str:
    return "\n".join(
        re.sub(r"'[^']*'|\"[^\"]*\"", "''", d).split("#", 1)[0] for d in text.splitlines()
    )


def _cap_dau(than: str) -> str:
    """Chỉ thị cấp đầu của một thân khối (bỏ khối con lồng bên trong)."""
    while re.search(r"\{[^{}]*\}", than):
        than = re.sub(r"[^;{}]*\{[^{}]*\}", "", than)
    return than


def _error_log(than: str) -> str | None:
    el = [" ".join(m.group(0).split()) for m in re.finditer(r"\berror_log\b[^;]*;", _cap_dau(than))]
    assert len(el) <= 1, "HẠ TẦNG: nhiều error_log cùng cấp: %s" % el
    return el[0] if el else None


def _https_locations() -> tuple[str, list[tuple[str, str, str]]]:
    """``(thân server HTTPS có tên, [(bổ ngữ, mẫu, thân location)] theo thứ tự)``."""
    sach = _sach(_doc(TEMPLATE))
    khoi = _cac_khoi(sach)
    server = [
        (b, e, d) for dau, b, e, d in khoi
        if dau == "server" and re.search(r"\blisten\s+443\s+ssl\s*;", _cap_dau(sach[b:e]))
        and "default_server" not in _cap_dau(sach[b:e])
    ]
    assert len(server) == 1, "HẠ TẦNG: không thấy đúng MỘT server 443 có tên"
    sb, se, sd = server[0]
    locs = []
    for dau, b, e, d in sorted(khoi, key=lambda k: k[1]):
        if d == sd + 1 and sb <= b < se and dau.startswith("location "):
            phan = dau.split(None, 2)
            if phan[1] in ("=", "~", "~*", "^~"):
                locs.append((phan[1], phan[2], sach[b:e]))
            else:
                locs.append(("", phan[1], sach[b:e]))
    return sach[sb:se], locs


def _location_chon(uri: str) -> tuple[str, str, str]:
    """Thuật toán chọn location của nginx: ``=`` khớp đúng → tiền tố dài nhất (``^~``
    dừng ở đó) → regex THEO THỨ TỰ, khớp đầu tiên thắng → tiền tố dài nhất."""
    _, locs = _https_locations()
    for l in locs:
        if l[0] == "=" and l[1] == uri:
            return l
    tien_to = [l for l in locs if l[0] in ("", "^~") and uri.startswith(l[1])]
    dai_nhat = max(tien_to, key=lambda l: len(l[1])) if tien_to else None
    if dai_nhat and dai_nhat[0] == "^~":
        return dai_nhat
    for l in locs:
        if l[0] in ("~", "~*") and re.search(l[1], uri, re.I if l[0] == "~*" else 0):
            return l
    assert dai_nhat, "HẠ TẦNG: không location nào nhận %s" % uri
    return dai_nhat


def _error_log_hieu_luc(uri: str) -> tuple[str, str]:
    """``(location được chọn, error_log có hiệu lực)``: của location, không có thì
    của server, không có nữa thì cấp main của nginx.conf (kế thừa từ trên xuống)."""
    l = _location_chon(uri)
    server, _ = _https_locations()
    tren = _cau_lenh(_cap_dau(_sach(_doc(NGINX_CONF))), "error_log")
    el = _error_log(l[2]) or _error_log(server) or (tren[0] if len(tren) == 1 else None)
    return "location %s %s" % (l[0], l[1]) if l[0] else "location %s" % l[1], el or "<không có>"


def test_moi_tien_to_token_co_uri_mau():
    """Thêm tiền tố vào ``TOKEN_PATH_PREFIXES`` (nguồn chuẩn) mà không thêm URI mẫu
    ở đây ⇒ ĐỎ, nên tiền tố mới không lọt khỏi phép kiểm error_log bên dưới."""
    from app.core.log_redaction import TOKEN_PATH_PREFIXES

    thieu = [
        p for p in TOKEN_PATH_PREFIXES
        if not any(re.search(re.escape(p).replace(r"\*", "[^/]+"), u) for u in _URI_TOKEN)
    ]
    assert thieu == [], "tiền tố token chưa có URI mẫu trong _URI_TOKEN: %s" % thieu


def test_error_log_tat_o_moi_location_phuc_vu_uri_token():
    sai = {u: v for u in _URI_TOKEN for v in [_error_log_hieu_luc(u)] if v[1] != _DEV_NULL}
    assert sai == {}, "URL token rơi vào location VẪN ghi error_log (location, error_log): %s" % sai


def test_error_log_location_thuong_giu_muc_warn_cua_nginx_conf():
    sai = {u: v for u in _URI_THUONG for v in [_error_log_hieu_luc(u)] if v[1] != _MUC_MAIN}
    assert sai == {}, "location thường KHÔNG còn error_log mức warn (location, error_log): %s" % sai


def test_error_log_api_tuyen_sinh_khong_token_cung_tat_la_danh_doi_da_biet():
    """Tách API token ra location riêng thì ca này ĐỎ — có chủ đích: location riêng
    không chạy cổng đóng băng (rewrite không kế thừa), phải quyết lại có ý thức."""
    mong = _error_log_hieu_luc("/api/admissions/confirm/GIA")
    sai = {u: v for u in _URI_TUYEN_SINH_KHONG_TOKEN for v in [_error_log_hieu_luc(u)] if v != mong}
    assert mong[1] == _DEV_NULL and sai == {}, (
        "API tuyển sinh không token phải dùng CHUNG location (và error_log) với API "
        "token %s: %s" % (mong, sai))


def test_error_log_template_chi_dang_dev_null_va_chi_trong_location():
    """``error_log`` ở cấp server = tắt cả site (lựa chọn C); dạng khác ``/dev/null``
    (vd. ``/dev/stderr crit``) vẫn để lọt dòng ``crit`` mang ``request:``."""
    co = _chi_thi_theo_khoi(_doc(TEMPLATE), "error_log")
    sai = [(k, d) for k, d in co if d != _DEV_NULL or not k.startswith("location ")]
    assert co and sai == [], "error_log trong template sai dạng hoặc sai chỗ: %s" % sai


def test_error_log_cap_main_nginx_conf_giu_warn():
    assert _cau_lenh(_doc(NGINX_CONF), "error_log") == [_MUC_MAIN], (
        "nginx.conf phải giữ đúng một error_log cấp main mức warn (không crit, không /dev/null)")


# ---------------------------------------------------------------------------
# Referrer-Policy cho trang token — nginx + Next
# ---------------------------------------------------------------------------


#: Trang FE mang bí mật trên URL (route param hoặc ``?token=``) — rà V6 vòng 2:
#: ``app/confirm/[token]``, ``app/magic-link/[action]/[token]``,
#: ``app/(auth)/reset-password`` (``ResetPasswordForm`` đọc ``?token=``),
#: ``app/lp/[code]`` (mã SMS).
_TRANG_TOKEN = ("/confirm/GIA", "/magic-link/withdraw/GIA", "/reset-password", "/lp/GIA")
_TRANG_THUONG = ("/login", "/", "/dashboard", "/reset-password-cu")


def _referrer_nginx(duong: str) -> str | None:
    """Referrer-Policy nginx THỰC SỰ gửi cho trang FE ``duong`` ở khối HTTPS: location
    tiền tố dài nhất có ``add_header Referrer-Policy`` riêng thắng (add_header không
    kế thừa); không có thì giá trị cấp server — literal, hoặc biến map ``$uri``."""
    rieng, cap_server = {}, None
    for khoi, dong in _chi_thi_theo_khoi(_doc(TEMPLATE), "add_header Referrer-Policy"):
        gia_tri = dong.split()[2].strip('"')
        if khoi.startswith("location ") and len(khoi.split()) == 2:
            rieng[khoi.split()[1]] = gia_tri
        elif khoi == "server":
            cap_server = gia_tri
    khop = [p for p in rieng if duong.startswith(p)]
    if khop:
        return rieng[max(khop, key=len)]
    if cap_server == "$qlts_referrer_policy":
        khoi_map = _khoi_map(_doc(NGINX_CONF), "$uri", "$qlts_referrer_policy")
        ra = _ap_map(khoi_map, duong)
        if ra is not None:
            return ra
        m = re.search(r'^\s*default\s+"([^"]*)"\s*;', khoi_map, re.M)
        return m.group(1) if m else None
    return cap_server


def _referrer_next(duong: str) -> str | None:
    """Referrer-Policy Next gửi cho ``duong``: luật ``headers()`` khớp SAU CÙNG thắng
    (tài liệu Next: cùng khoá header thì khối sau ghi đè)."""
    src = _doc(NEXT_CONFIG)
    ra = None
    for m in re.finditer(r'source:\s*"([^"]+)",\s*headers:\s*\[(.*?)\]\s*,?\s*\}', src, re.S):
        nguon, than = m.group(1), m.group(2)
        rp = re.search(r'key:\s*"Referrer-Policy",\s*value:\s*"([^"]+)"', than)
        if not rp:
            continue
        assert ":" not in nguon.replace("/:path*", ""), "HẠ TẦNG: dạng source chưa hỗ trợ: %s" % nguon
        mau = re.escape(nguon).replace(r"/:path\*", r"(?:/.*)?").replace(r"\(\.\*\)", r"(.*)")
        if re.fullmatch(mau, duong):
            ra = rp.group(1)
    return ra


def test_referrer_policy_trang_token_ca_hai_tang_no_referrer():
    """Trang token: CẢ nginx lẫn Next phải gửi ``no-referrer`` — hai tầng cùng gửi
    header, lệch nhau thì trình duyệt lấy cái đứng sau."""
    sai = {
        trang: (_referrer_nginx(trang), _referrer_next(trang))
        for trang in _TRANG_TOKEN
        if (_referrer_nginx(trang), _referrer_next(trang)) != ("no-referrer", "no-referrer")
    }
    assert sai == {}, "trang token không đồng nhất no-referrer (nginx, Next): %s" % sai


def test_referrer_policy_trang_thuong_hai_tang_giu_strict_origin():
    """Đối chứng: trang thường vẫn ``strict-origin-when-cross-origin`` ở cả hai tầng
    (map/nguồn quá rộng sẽ làm hỏng chính sách chung)."""
    mong = "strict-origin-when-cross-origin"
    sai = {
        trang: (_referrer_nginx(trang), _referrer_next(trang))
        for trang in _TRANG_THUONG
        if (_referrer_nginx(trang), _referrer_next(trang)) != (mong, mong)
    }
    assert sai == {}, "trang thường lệch chính sách chung (nginx, Next): %s" % sai


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
