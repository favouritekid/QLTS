"""V6 — che dữ liệu cá nhân và token trong LOG, kiểm qua ĐÚNG cửa ra thật.

Bất biến (chủ sở hữu: ``app/core/log_redaction.py``): không dòng log nào rời
tiến trình web / gunicorn / celery worker / celery beat mang số CCCD, token trên
đường dẫn, giá trị khoá chứa ``token``, giá trị khoá PII đã biết (``phone``,
``email``, ``full_name``…), mật khẩu trong URL — và mã hồ sơ, mã lỗi, số tiền
vẫn GIỮ NGUYÊN.

Vì sao chạy trong TIẾN TRÌNH CON: cấu hình log là trạng thái toàn cục của tiến
trình (handler gốc, structlog). Trong pytest, mọi test khác đã nạp ``app.main``
và có thể đã chèn handler — đo trong tiến trình ấy là đo một cấu hình khác với
production. Mỗi tiến trình con nạp ĐÚNG thứ tiến trình thật nạp:

* web      — ``import app.main`` (uvicorn/gunicorn worker nạp đúng module này);
* gunicorn — ``gunicorn.conf.py::post_worker_init`` + ``gunicorn.glogging`` thật,
  KHÔNG nạp ``app.main`` (để lớp mức-logger được đo riêng);
* celery   — chỉ ``import app.celery_app`` (``celery -A app.celery_app``) rồi gọi
  đúng hàm worker/beat gọi để dựng log (``app.log.setup`` / ``Beat.setup_logging``).

Mỗi giá trị giả chỉ dùng ở ĐÚNG MỘT đầu dò, nên "giá trị vắng mặt" quy được về
một cửa ra. Điều kiện tiên quyết (tiến trình con chạy hết, dòng đầu dò có mặt)
nằm trong hàm phụ — hỏng ở đó là hạ tầng, không phải "bắt được đột biến".
Dữ liệu đều GIẢ: CCCD ``0999990…``, token ``GIAV6TOKEN…``, SĐT ``090000000x``,
email ``…@example.invalid``, họ tên ``Nguyen Van Gia``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Tiến trình con
# ---------------------------------------------------------------------------

_DRIVER_CHUNG = r'''
import asyncio, logging, sys
from sqlalchemy.exc import IntegrityError


def loi_sql(cccd):
    goc = Exception(
        'duplicate key value violates unique constraint "uq_v6_gia"\n'
        "DETAIL:  Key (citizen_id, academic_year)=(%s, 2026) already exists." % cccd
    )
    return IntegrityError(
        "INSERT INTO admission_profiles (full_name, citizen_id) VALUES ($1, $2)",
        ("Nguyen Van Gia", cccd),
        goc,
    )
'''

_DRIVER_WEB = _DRIVER_CHUNG + r'''
import app.main  # noqa: F401 — cấu hình log y như tiến trình web thật
import structlog
from starlette.requests import Request
from app.middleware.exception_handlers import (
    base_app_exception_handler,
    generic_exception_handler,
)
from app.utils.exceptions import DuplicateResourceError

# ---- (P) CHUỖI PROCESSOR structlog THẬT, tách khỏi handler: đo riêng tầng structlog
_procs = structlog.get_config()["processors"]
_lg = logging.getLogger("v6.chuoi")


def chuoi(ma, method, **ed):
    for p in _procs:
        ed = p(_lg, method, ed)
    sys.stdout.write("V6CHUOI|%s|%s\n" % (ma, ed))
    sys.stdout.flush()


chuoi("P1", "warning", event="v6_p1", citizen_id="099999000101",
      new_citizen_id="099999000102", cccd="099999000103", profile_id=4242)
chuoi("P2", "error", event="v6_p2", error=(
    'duplicate key value violates unique constraint "uq"\n'
    "DETAIL:  Key (citizen_id, academic_year)=(099999000104, 2026) already exists."))
chuoi("P3", "error", event="v6_p3", error=(
    "[SQL: INSERT INTO t (a, b) VALUES ($1, $2)]\n"
    "[parameters: ('Nguyen Van Gia', '099999000105')]\n"
    "(Background on this error at: https://sqlalche.me/e/20/gkpj)"))
try:
    raise loi_sql("099999000106")
except Exception:
    chuoi("P4", "error", event="v6_p4", exc_info=True)
chuoi("P5", "warning", event="DuplicateResourceError: CCCD 099999000107 da duoc su dung")
chuoi("P6", "info", event="v6_p6", path="/api/admissions/confirm/GIAV6TOKENP06",
      trang="https://example.invalid/magic-link/withdraw/GIAV6TOKENP16")
chuoi("P7", "info", event="v6_p7", confirm_token="GIAV6TOKENP07")
chuoi("P8", "info", event="v6_p8", phone="0900000001",
      email="gia@example.invalid", full_name="Nguyen Van Gia")
chuoi("P9", "info", event="v6_p9", profile_id=4242, error_code="V6_MA_LOI_GIA",
      amount=215100000, ghi_chu="thu 215100000 dong cho ho so 4242")
chuoi("P10", "info", event="v6_p10", redis_url="redis://:GIAMATKHAUP10@redis:6379/1")
chuoi("P11", "info", event="v6_p11",
      du_lieu={"api_key": "GIAV6KHOAP11A", "lop": {"authorization": "GIAV6KHOAP11B"}})

# ---- (E/L/A) CỬA RA THẬT: logger -> handler gốc -> stderr
slog = structlog.get_logger("v6.probe")
thuong = logging.getLogger("v6.thuong")
yeu_cau = Request({"type": "http", "method": "PUT", "path": "/api/admissions/4242",
                   "headers": [], "query_string": b""})

slog.warning("v6_e1_struct", citizen_id="099999000201", path="/confirm/GIAV6TOKENE01")
asyncio.run(base_app_exception_handler(yeu_cau, DuplicateResourceError(
    "CCCD 099999000202 da duoc su dung boi ho so khac trong nam 2026 (ID: 77)")))
asyncio.run(generic_exception_handler(yeu_cau, ValueError(
    "Cannot enroll: Citizen ID 099999000203 is already enrolled")))
asyncio.run(generic_exception_handler(yeu_cau, loi_sql("099999000204")))
try:
    raise loi_sql("099999000205")
except Exception:
    thuong.exception("v6_l4_traceback_thuong")
thuong.error("v6_l5_doi_so: %s", loi_sql("099999000206"))
thuong.info('v6_l6_escape {"path":"\\/api\\/v2\\/admissions\\/magic-link\\/confirm\\/GIAV6TOKENL06"}')
thuong.info("v6_l7_query GET /reset-password?token=GIAV6TOKENL07&lang=vi")
thuong.warning("v6_l8_giu: thu 215100000 dong, ho so 4242, ma loi V6_MA_LOI_GIA")
thuong.info("v6_l9_kv email=gia2@example.invalid phone=0900000002")
truy_cap = logging.getLogger("uvicorn.access")
truy_cap.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "GET",
              "/api/admissions/confirm/GIAV6TOKENA01", "1.1", 200)
truy_cap.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "POST",
              "/api/v2/admissions/magic-link/confirm/GIAV6TOKENA02", "1.1", 200)
sys.stderr.flush()
print("V6_XONG")
'''

_DRIVER_GUNICORN = r'''
import datetime, logging, runpy, sys
cau_hinh = runpy.run_path("gunicorn.conf.py")
from gunicorn.config import Config
from gunicorn.glogging import Logger

cfg = Config()
cfg.set("accesslog", "-")
cfg.set("errorlog", "-")
glog = Logger(cfg)
# Như UvicornWorker.__init__: uvicorn.access mượn handler access của gunicorn.
lg = logging.getLogger("uvicorn.access")
lg.handlers = glog.access_log.handlers
lg.setLevel(glog.access_log.level)
lg.propagate = False


class Tho:
    log = glog


cau_hinh["post_worker_init"](Tho())
print("V6_APP_MAIN=%s" % ("app.main" in sys.modules))
lg.info('%s - "%s %s HTTP/%s" %d', "10.0.0.1:5000", "GET",
        "/api/admissions/confirm/GIAV6TOKENG01", "1.1", 200)


class Resp:
    status = "200 OK"
    sent = 2
    response_length = 2
    headers = []


class Req:
    headers = []


moi_truong = {
    "REQUEST_METHOD": "GET",
    "RAW_URI": "/magic-link/withdraw/GIAV6TOKENG02?x=1",
    "PATH_INFO": "/magic-link/withdraw/GIAV6TOKENG02",
    "QUERY_STRING": "x=1",
    "SERVER_PROTOCOL": "HTTP/1.1",
    "HTTP_REFERER": "https://example.invalid/confirm/GIAV6TOKENG03",
    "HTTP_USER_AGENT": "v6-dau-do",
    "REMOTE_ADDR": "10.0.0.2",
}
glog.access(Resp(), Req(), moi_truong, datetime.timedelta(seconds=0, microseconds=1000))
sys.stdout.flush()
print("V6_XONG")
'''

_DRIVER_CELERY_WORKER = _DRIVER_CHUNG + r'''
from app.celery_app import celery_app
print("V6_APP_MAIN=%s" % ("app.main" in sys.modules))
# Đúng lời gọi của celery.apps.worker.Worker.setup_logging
celery_app.log.setup(logging.INFO, None, redirect_stdouts=False, hostname="v6@dau-do")
import structlog
from celery.utils.log import get_task_logger

structlog.get_logger("v6.celery").warning("v6_c1_struct", citizen_id="099999000301")
logging.getLogger("v6.celery.thuong").warning(
    "DuplicateResourceError: CCCD 099999000302 da duoc su dung")
get_task_logger("v6.celery.task").warning(
    "v6_c3_task GET /api/admissions/confirm/GIAV6TOKENC03")
structlog.get_logger("v6.celery").info(
    "v6_c4_redis", redis_url="redis://:GIAMATKHAUC04@redis:6379/2")
sys.stdout.flush()
sys.stderr.flush()
print("V6_XONG")
'''

_DRIVER_CELERY_BEAT = _DRIVER_CHUNG + r'''
from app.celery_app import celery_app
from celery.apps.beat import Beat
print("V6_APP_MAIN=%s" % ("app.main" in sys.modules))
Beat(app=celery_app, loglevel="INFO").setup_logging()
import structlog

structlog.get_logger("v6.beat").warning("v6_b1_struct", citizen_id="099999000401")
sys.stdout.flush()
sys.stderr.flush()
print("V6_XONG")
'''


def _chay(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONSTARTUP", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
    )


@pytest.fixture(scope="module")
def web() -> subprocess.CompletedProcess:
    return _chay(_DRIVER_WEB)


@pytest.fixture(scope="module")
def gunicorn() -> subprocess.CompletedProcess:
    return _chay(_DRIVER_GUNICORN)


@pytest.fixture(scope="module")
def celery_worker() -> subprocess.CompletedProcess:
    return _chay(_DRIVER_CELERY_WORKER)


@pytest.fixture(scope="module")
def celery_beat() -> subprocess.CompletedProcess:
    return _chay(_DRIVER_CELERY_BEAT)


def _tien_quyet(r: subprocess.CompletedProcess) -> str:
    """Tiến trình con chạy HẾT ⇒ trả toàn bộ đầu ra (stdout + stderr).

    Mốc ``V6_XONG`` tìm trên CẢ HAI luồng: khi Celery tự cấu hình log (không có
    receiver ``setup_logging``) nó chuyển hướng stdout sang logger, nên ``print``
    đi ra stderr — đó chính là trạng thái lỗi cần đo, không phải hạ tầng hỏng."""
    out = r.stdout + "\n" + r.stderr
    assert r.returncode == 0 and "V6_XONG" in out, (
        "HẠ TẦNG: tiến trình con không chạy hết (rc=%s)\n--- stderr (đuôi) ---\n%s"
        % (r.returncode, r.stderr[-3000:])
    )
    return out


def _dong_chuoi(r: subprocess.CompletedProcess, ma: str) -> str:
    """Dòng đầu ra của chuỗi processor structlog cho đầu dò ``ma``."""
    _tien_quyet(r)
    dong = [x for x in r.stdout.splitlines() if x.startswith("V6CHUOI|%s|" % ma)]
    assert len(dong) == 1, "HẠ TẦNG: không thấy đúng một dòng chuỗi %s" % ma
    return dong[0]


def _co_dau_do(r: subprocess.CompletedProcess, dau_do: str) -> str:
    """Toàn bộ đầu ra, sau khi xác nhận dòng của đầu dò có mặt (log VẪN ghi)."""
    out = _tien_quyet(r)
    assert dau_do in out, "HẠ TẦNG: dòng log của đầu dò %r không có mặt" % dau_do
    return out


def _khong_nap_app_main(r: subprocess.CompletedProcess, dau_do: str) -> str:
    """Như ``_co_dau_do`` + tiến trình con KHÔNG nạp ``app.main`` (để lớp cấu
    hình riêng của gunicorn/celery được đo độc lập với cấu hình web)."""
    out = _co_dau_do(r, dau_do)
    assert "V6_APP_MAIN=False" in out, (
        "HẠ TẦNG: tiến trình con đã nạp app.main — không còn đo được cấu hình riêng"
    )
    return out


# ---------------------------------------------------------------------------
# (P) Tầng structlog — chuỗi processor THẬT do configure_logging("web") dựng
# ---------------------------------------------------------------------------


def test_structlog_che_khoa_cccd(web):
    dong = _dong_chuoi(web, "P1")
    lo = [v for v in ("099999000101", "099999000102", "099999000103") if v in dong]
    assert lo == [], "CCCD theo khoá (citizen_id/new_citizen_id/cccd) lọt: %s" % dong


def test_structlog_che_detail_sql_trong_gia_tri(web):
    dong = _dong_chuoi(web, "P2")
    assert "099999000104" not in dong, "DETAIL Key (citizen_id…)=(…) lọt: %s" % dong


def test_structlog_che_tham_so_sql_trong_gia_tri(web):
    dong = _dong_chuoi(web, "P3")
    assert "099999000105" not in dong, "[parameters: …] của SQLAlchemy lọt: %s" % dong


def test_structlog_che_traceback_sau_format_exc_info(web):
    dong = _dong_chuoi(web, "P4")
    assert "099999000106" not in dong, "traceback (khoá exception) lọt CCCD: %s" % dong


def test_structlog_che_cccd_trong_cau(web):
    dong = _dong_chuoi(web, "P5")
    assert "099999000107" not in dong, "câu 'CCCD <số>' lọt: %s" % dong


def test_structlog_che_token_duong_dan(web):
    dong = _dong_chuoi(web, "P6")
    lo = [v for v in ("GIAV6TOKENP06", "GIAV6TOKENP16") if v in dong]
    assert lo == [], "token /confirm/ hoặc /magic-link/<action>/ lọt: %s" % dong


def test_structlog_che_khoa_chua_token(web):
    dong = _dong_chuoi(web, "P7")
    assert "GIAV6TOKENP07" not in dong, "khoá chứa 'token' lọt giá trị: %s" % dong


def test_structlog_che_khoa_pii_da_biet(web):
    dong = _dong_chuoi(web, "P8")
    lo = [v for v in ("0900000001", "gia@example.invalid", "Nguyen Van Gia") if v in dong]
    assert lo == [], "khoá phone/email/full_name lọt: %s" % dong


def test_structlog_giu_ma_ho_so_ma_loi_so_tien(web):
    dong = _dong_chuoi(web, "P9")
    mat = [v for v in ('"profile_id":4242', "V6_MA_LOI_GIA", '"amount":215100000',
                       "thu 215100000 dong cho ho so 4242") if v not in dong]
    assert mat == [], "che NHẦM dữ liệu chẩn đoán (mất %s): %s" % (mat, dong)


def test_structlog_che_mat_khau_trong_url(web):
    dong = _dong_chuoi(web, "P10")
    assert "GIAMATKHAUP10" not in dong, "mật khẩu trong redis_url lọt: %s" % dong


def test_structlog_che_khoa_bi_mat_long_trong_dict(web):
    """Khoá bí mật nằm LỒNG trong dict: ``api_key``/``authorization`` không thuộc tập
    khoá VĂN BẢN của filter gốc ⇒ chỉ processor che được (đo riêng chuỗi processor)."""
    dong = _dong_chuoi(web, "P11")
    lo = [v for v in ("GIAV6KHOAP11A", "GIAV6KHOAP11B") if v in dong]
    assert lo == [], "khoá bí mật LỒNG trong dict (api_key/authorization) lọt: %s" % dong


# ---------------------------------------------------------------------------
# (E/L/A) Cửa ra thật của tiến trình web: logger → handler gốc → stderr
# ---------------------------------------------------------------------------


def test_web_structlog_qua_handler_goc_khong_lo(web):
    out = _co_dau_do(web, "v6_e1_struct")
    lo = [v for v in ("099999000201", "GIAV6TOKENE01") if v in out]
    assert lo == [], "dòng structlog thật lọt %s" % lo


def test_handler_loi_ghi_cau_cccd_qua_logging_thuong(web):
    out = _co_dau_do(web, "DuplicateResourceError: CCCD")
    assert "099999000202" not in out, (
        "exception_handlers ghi f'{lớp}: {detail}' lọt số CCCD qua logging thường")


def test_handler_loi_ghi_cau_citizen_id_qua_logging_thuong(web):
    out = _co_dau_do(web, "Cannot enroll: Citizen ID")
    assert "099999000203" not in out, "câu 'Citizen ID <số>' lọt qua logging thường"


def test_handler_loi_ghi_detail_sql_qua_logging_thuong(web):
    out = _co_dau_do(web, "Unhandled exception: IntegrityError")
    assert "099999000204" not in out, (
        "DETAIL/[parameters] của IntegrityError lọt qua generic_exception_handler")


def test_logging_thuong_che_traceback(web):
    out = _co_dau_do(web, "v6_l4_traceback_thuong")
    assert "099999000205" not in out, "traceback (exc_text) của logging thường lọt CCCD"


def test_logging_thuong_che_doi_so_khong_phai_chuoi(web):
    out = _co_dau_do(web, "v6_l5_doi_so")
    assert "099999000206" not in out, (
        "đối số là đối tượng ngoại lệ (str() mang DETAIL) lọt qua logging thường")


def test_logging_thuong_che_token_dang_ujson_thoat_gach(web):
    out = _co_dau_do(web, "v6_l6_escape")
    assert "GIAV6TOKENL06" not in out, r"token dạng ujson '\/magic-link\/…' lọt"


def test_logging_thuong_che_token_trong_query(web):
    out = _co_dau_do(web, "v6_l7_query")
    assert "GIAV6TOKENL07" not in out, "?token=<giá trị> lọt"


def test_logging_thuong_giu_so_tien_ma_ho_so_ma_loi(web):
    out = _co_dau_do(web, "v6_l8_giu")
    assert "v6_l8_giu: thu 215100000 dong, ho so 4242, ma loi V6_MA_LOI_GIA" in out, (
        "che NHẦM số tiền / mã hồ sơ / mã lỗi trong câu log thường")


def test_logging_thuong_che_pii_dang_khoa_bang_gia_tri(web):
    out = _co_dau_do(web, "v6_l9_kv")
    lo = [v for v in ("gia2@example.invalid", "0900000002") if v in out]
    assert lo == [], "email=/phone= trong câu log thường lọt %s" % lo


def test_access_log_web_che_token(web):
    out = _co_dau_do(web, " - \"GET /api/admissions/confirm/")
    lo = [v for v in ("GIAV6TOKENA01", "GIAV6TOKENA02") if v in out]
    assert lo == [], "access log (uvicorn.access) lọt token %s" % lo


def test_access_formatter_uvicorn_van_dinh_dang_duoc_sau_khi_che():
    """Dev: uvicorn tự dựng ``AccessFormatter`` (tách 5 phần tử ``args``). Bộ che
    phải giữ ``args`` là tuple 5 phần tử — nếu gộp thành chuỗi, formatter ném
    và dòng access log mất hẳn."""
    import logging

    from uvicorn.logging import AccessFormatter

    from app.core.log_redaction import RedactingFilter

    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", "/confirm/GIAV6TOKENU01", "1.1", 200), None,
    )
    RedactingFilter().filter(rec)
    try:
        dong = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(rec)
    except Exception as exc:  # noqa: BLE001 — ghi lại để khẳng định bên dưới
        dong = "LOI-DINH-DANG %r" % (exc,)
    assert dong.startswith('10.0.0.1:5000 - "GET /confirm/<redacted> HTTP/1.1" 200'), dong


# ---------------------------------------------------------------------------
# Gunicorn: handler RIÊNG của gunicorn (propagate=False) — chỉ lớp mức-logger
# mà post_worker_init gắn mới che được
# ---------------------------------------------------------------------------


def test_gunicorn_post_worker_init_che_access_uvicorn(gunicorn):
    out = _khong_nap_app_main(gunicorn, '"GET /api/admissions/confirm/')
    assert "GIAV6TOKENG01" not in out, (
        "uvicorn.access trên handler của gunicorn lọt token — post_worker_init không che")


def test_gunicorn_access_that_che_request_va_referer(gunicorn):
    out = _khong_nap_app_main(gunicorn, '"v6-dau-do"')
    lo = [v for v in ("GIAV6TOKENG02", "GIAV6TOKENG03") if v in out]
    assert lo == [], "gunicorn.access (dòng request + referer) lọt token %s" % lo


# ---------------------------------------------------------------------------
# Celery worker / beat: chỉ nạp app.celery_app, KHÔNG nạp app.main
# ---------------------------------------------------------------------------


def test_celery_worker_structlog_che(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c1_struct")
    assert "099999000301" not in out, "worker: structlog lọt CCCD — chưa nạp bộ che"


def test_celery_worker_logging_thuong_che(celery_worker):
    out = _khong_nap_app_main(celery_worker, "DuplicateResourceError: CCCD")
    assert "099999000302" not in out, "worker: logging thường lọt CCCD"


def test_celery_worker_task_logger_che(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c3_task")
    assert "GIAV6TOKENC03" not in out, "worker: task logger lọt token"


def test_celery_worker_che_mat_khau_redis_url(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c4_redis")
    assert "GIAMATKHAUC04" not in out, "worker: redis_url lọt mật khẩu"


def test_celery_beat_structlog_che(celery_beat):
    out = _khong_nap_app_main(celery_beat, "v6_b1_struct")
    assert "099999000401" not in out, "beat: structlog lọt CCCD — chưa nạp bộ che"
