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


import asyncpg
import sqlalchemy.exc as _sa_exc
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi as _dbapi


def _nem(e, tu=None):
    """Ném rồi bắt lại ⇒ ngoại lệ có traceback thật và chuỗi ``__cause__``."""
    try:
        if tu is None:
            raise e
        raise e from tu
    except BaseException as x:
        return x


def loi_db(rang_buoc, thong_diep, chi_tiet=None, tham_so=None, sqlstate="23514",
           lop_sa=_sa_exc.IntegrityError, lop_ad="IntegrityError", pg=None):
    """Lỗi CSDL GIẢ đúng chuỗi thật: asyncpg → adapter DBAPI của SQLAlchemy
    (``raise … from``, gắn ``sqlstate``) → ``sqlalchemy.exc.*`` (``orig``)."""
    if pg is None:
        truong = {"C": sqlstate, "M": thong_diep, "S": "ERROR",
                  "n": rang_buoc, "t": "admission_profiles"}
        if chi_tiet:
            truong["D"] = chi_tiet
        pg = asyncpg.exceptions.PostgresError.new(truong)
    pg = _nem(pg)
    ad = getattr(_dbapi, lop_ad)("%s: %s" % (type(pg), pg))
    ad.pgcode = ad.sqlstate = getattr(pg, "sqlstate", None)
    ad = _nem(ad, pg)
    sa = lop_sa("INSERT INTO admission_profiles (full_name, citizen_id) VALUES ($1, $2)",
                tham_so, ad)
    return _nem(sa, ad)


def loi_db_moc(ma):
    """Lỗi CSDL mang giá trị giả ở DẠNG MÀ KHÔNG REGEX NÀO NHẬN RA (thông điệp,
    DETAIL) + tham số bind ⇒ chỉ tầng TÓM TẮT lỗi CSDL che được. Mốc ``ck_v6_<ma>``
    nằm cả trong thông điệp (trước vá) lẫn thuộc tính ràng buộc (sau vá)."""
    return loi_db("ck_v6_" + ma, 'violates check constraint "ck_v6_%s": gia tri GIAV6DB%sA' % (ma, ma),
                  chi_tiet="Chi tiet GIAV6DB%sB" % ma, tham_so=("GIAV6DB%sC" % ma,))


def loi_db_hang(ma, cccd):
    """Chuỗi owner (1): DETAIL ``Failing row`` có xuống dòng THẬT, không mốc phía sau."""
    return loi_db("ck_v6_" + ma, 'new row for relation "admission_profiles" violates check '
                  'constraint "ck_v6_%s"' % ma,
                  chi_tiet="Failing row contains (4242, GIA\n%s, Gia Lap Ten)." % cccd,
                  tham_so=("Gia Lap Ten", cccd))


def loi_ngan(thong_diep, **truong_them):
    """V6 vòng 5: lỗi asyncpg GIẢ có thông điệp NGẮN (< 8 ký tự) — phản ví dụ của
    review F30 (vòng 4 bỏ qua chuỗi < 8 / dòng < 12 ký tự)."""
    truong = {"C": "22000", "M": thong_diep, "S": "ERROR"}
    truong.update(truong_them)
    return _nem(asyncpg.exceptions.PostgresError.new(truong))


def boc_context(loi_csdl, mau="loi khi ghi: %s", lop=ValueError):
    """Ngoại lệ BỌC lỗi CSDL qua ``__context__`` (ném trong ``except``, KHÔNG ``from``);
    ``str`` của lỗi bọc chứa chữ của lỗi CSDL."""
    try:
        raise loi_csdl
    except Exception as _x:
        try:
            raise lop(mau % _x)
        except lop as _w:
            return _w


def loi_db_asyncpg_repr(cccd):
    """Chuỗi owner (3): asyncpg DataError — repr tham số có ``\\n``."""
    pg = asyncpg.exceptions.DataError(
        "invalid input for query argument $1: 'GIA\\n%s Gia Lap Ten' (expected str, got int)" % cccd)
    return loi_db(None, None, pg=pg, lop_sa=_sa_exc.DataError, lop_ad="DataError")


def loi_hang(cccd, email, sdt, rang_buoc):
    """IntegrityError giả của vi phạm CHECK: PostgreSQL in NGUYÊN hàng lỗi.
    Không truyền tham số bind ⇒ giá trị CHỈ nằm trong ``Failing row contains``.
    V6 vòng 4: dựng qua ĐÚNG chuỗi asyncpg → adapter → SQLAlchemy (``loi_db``) để
    tên ràng buộc đi bằng THUỘC TÍNH — bản tóm tắt lỗi CSDL không đọc thông điệp."""
    return loi_db(rang_buoc,
                  'new row for relation "admission_profiles" violates check constraint "%s"'
                  % rang_buoc,
                  chi_tiet="Failing row contains (4242, Nguyen Van Gia, %s, %s, %s, null)."
                  % (cccd, email, sdt))
'''

_DRIVER_WEB = _DRIVER_CHUNG + r'''
import app.main  # noqa: F401 — cấu hình log y như tiến trình web thật
import structlog
from starlette.requests import Request
from app.middleware.exception_handlers import (
    base_app_exception_handler,
    generic_exception_handler,
)
from app.utils.exceptions import ConflictError, DuplicateResourceError

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
# ---- F30: thông báo PostgreSQL 16 / asyncpg NHÚNG GIÁ TRỊ (mỗi họ một đầu dò)
chuoi("P12", "error", event="v6_p12", error=(
    'new row for relation "admission_profiles" violates check constraint "ck_v6"\n'
    "DETAIL:  Failing row contains (4242, Nguyen Van Gia, 099999000512, "
    "gia512@example.invalid, 0900000512, null)."))
chuoi("P13", "error", event="v6_p13", error=(
    'conflicting key value violates exclusion constraint "ex_v6"\n'
    "DETAIL:  Key (phone, unit_id)=(0900000513, 7) conflicts with existing key "
    "(phone, unit_id)=(0900000613, 7)."))
chuoi("P14", "error", event="v6_p14",
      error='invalid input syntax for type integer: "GIAV6NHAP14"')
chuoi("P15", "error", event="v6_p15",
      error='value "099999000515" is out of range for type integer')
chuoi("P16", "error", event="v6_p16",
      error="invalid input for query argument $2: '099999000516' (expected int, got str)")
chuoi("P17", "error", event="v6_p17", error=(
    "invalid input syntax for type json\n"
    'DETAIL:  Token "GIAV6JSON17" is invalid.\n'
    "CONTEXT:  JSON data, line 1: {ghi_chu: GIAV6JSON27"))
chuoi("P18", "error", event="v6_p18", error=(
    "CONTEXT:  unnamed portal parameter $1 = '099999000518'"))
# ---- Vòng 3: giá trị CHỨA nháy / ngoặc lồng — các mẫu từng dừng ở dấu nháy đầu tiên
chuoi("P23", "error", event="v6_p23", error=(
    'DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000995, Gia Lap Ten).'))
chuoi("P24", "error", event="v6_p24", error=(
    'DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000996, Gia Lap Ten).'
    " khi luu ho so"))
chuoi("P25", "error", event="v6_p25",
      error='invalid input syntax for type integer: "12"3 099999000981"')
chuoi("P26", "error", event="v6_p26",
      error='CONTEXT:  COPY admission_profiles, line 3, column ghi_chu: "a"b GIAV6COPY26"')
chuoi("P27", "error", event="v6_p27",
      error='CONTEXT:  JSON data, line 1: {"ghi_chu": "GIAV6JSON37", "x": 1}')
chuoi("P29", "error", event="v6_p29", error=(
    "DETAIL:  Key (full_name, citizen_id)=(Gia (Lap) Ten, 099999000999) already exists."))
chuoi("P30", "info", event="v6_p30",
      du_lieu='{"full_name": "Gia \\"Lap\\" Ten30", "x": 1}')
chuoi("P31", "info", event="v6_p31", dich='redis://:pa"ss31@redis:6379/1')
chuoi("P32", "error", event="v6_p32", error="DETAIL:  Key (phone)=(0900000932")
# ---- Vòng 4: lỗi CSDL ⇒ chỉ TÓM TẮT (loại, SQLSTATE, ràng buộc, bảng) — tầng tóm tắt
LOI_D1 = loi_db_moc("d1")
chuoi("D1", "error", event="v6_d1", exc_info=LOI_D1)          # traceback qua processor
chuoi("D6", "error", event="v6_d6", error=loi_db_moc("d6"))   # giá trị là đối tượng ngoại lệ
try:
    raise loi_db_moc("d5s")
except Exception as _e:                                        # error=str(e) trong except
    chuoi("D5s", "error", event="v6_d5s", error=str(_e))
try:
    raise loi_db_moc("d5n")
except Exception as _e:                                        # chuỗi LỒNG trong dict/list
    chuoi("D5n", "error", event="v6_d5n", ngu_canh={"loi": [f"that bai: {_e}"]})
# ---- Vòng 4: chuỗi owner dạng CHỮ THƯỜNG (lớp phụ regex) — đúng nguyên văn
chuoi("P33", "error", event="v6_p33",
      error="DETAIL:  Failing row contains (4242, GIA\n099999000999, Gia Lap Ten).")
chuoi("P34", "error", event="v6_p34",
      error="DETAIL:  Failing row contains (4242, GIA\\n099999000999, Gia Lap Ten).")
chuoi("P35", "error", event="v6_p35", error=(
    "invalid input for query argument $1: 'GIA\\n099999000999 Gia Lap Ten' (expected str, got int)"))
# Cột KHÔNG mang nhãn CCCD — nếu là `citizen_id` thì luật nhãn CCCD che hộ và ca
# này không còn canh được mẫu COPY (đã thấy ở lượt đỏ-trước đầu tiên).
chuoi("P19", "error", event="v6_p19", error=(
    'CONTEXT:  COPY admission_profiles, line 3, column ghi_chu: "GIAV6COPY19"'))
chuoi("P20", "error", event="v6_p20",
      error='invalid input value for enum gioi_tinh: "GIAV6ENUM20"')
chuoi("P21", "error", event="v6_p21", error=(
    'insert or update on table "admission_profiles" violates foreign key constraint "fk"\n'
    'DETAIL:  Key (lead_id)=(4242) is not present in table "leads".'))
chuoi("P22", "error", event="v6_p22", error=(
    'new row for relation "admission_profiles" violates check constraint "ck_v6"\n'
    "DETAIL:  Failing row contains (4242, dong mot\ndong hai 099999000522, "
    "gia522@example.invalid, null).\n"
    "[SQL: INSERT INTO admission_profiles VALUES ($1)]"))

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
thuong.warning(
    'v6_l10_failing_row: new row for relation "admission_profiles" violates check '
    'constraint "ck_v6_l10"\nDETAIL:  Failing row contains (4242, Nguyen Van Gia, '
    "099999000530, gia530@example.invalid, 0900000530, null).")
asyncio.run(generic_exception_handler(yeu_cau, loi_hang(
    "099999000531", "gia531@example.invalid", "0900000531", "ck_v6_l11")))
thuong.info("v6_l12_ma_hoa GET /login?next=%2Fconfirm%2FGIAV6TOKENL12")
# ---- Vòng 3: giá trị chứa nháy qua cửa ra THẬT (không có lớp thoát JSON thứ hai)
import json as _json
slog.warning("v6_e2_json", error=(
    'DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000963, Gia Lap Hai).\n'
    'full_name="Gia "Lap" Ten 0900000966"'))
# Giá trị đã che nằm ở CUỐI chuỗi JSON (ngay trước nháy đóng, không có `\n` thoát phía
# sau) — đúng chỗ lần che thứ hai ở handler gốc có thể nuốt tới hết dòng. Mốc `dau_do`
# gắn bằng bind ⇒ đứng TRƯỚC giá trị trong dòng JSON, sống sót nếu phần sau bị nuốt.
slog.bind(dau_do="v6_e3_json").warning("v6_e3", error=(
    'DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000967, Gia Lap Ten).'))
slog.bind(dau_do="v6_e4_json").warning("v6_e4", ghi_chu='full_name="Gia "Lap" Ten 0900000968"')
thuong.warning('v6_l13 DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000997, '
               "Gia Lap Ba). khi luu ho so")
thuong.info("v6_l14 " + _json.dumps(
    "invalid input for query argument $1: 'O\\'Gia 099999000990' (expected int)"))
thuong.info('v6_l15 full_name="Gia "Lap" Ten 0900000993"')
thuong.info("v6_l16 " + _json.dumps(
    'DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000964, Gia Lap Ten).'))
# ---- Vòng 4: lỗi CSDL qua cửa ra thật — mỗi đầu dò tách một tầng
thuong.error("v6_d2", exc_info=loi_db_moc("d2"))               # traceback qua handler gốc
thuong.error("v6_d4", exc_info=_nem(ConflictError("Khong luu duoc ho so 4242"),
                                    loi_db_moc("d4")))         # bọc lỗi CSDL (__cause__)
try:
    raise loi_db_moc("d5")
except Exception as _e:                                        # f"…{e}" trong except
    thuong.error("v6_d5 loi luu: " + str(_e))
thuong.error("v6_d7 %s", loi_db_moc("d7"))                     # đối số là đối tượng ngoại lệ
asyncio.run(generic_exception_handler(yeu_cau, loi_db_moc("d3")))
_LOI_D8 = loi_db_moc("d8")
asyncio.run(base_app_exception_handler(yeu_cau, _nem(
    ConflictError("Loi luu ho so: %s" % _LOI_D8), _LOI_D8)))  # detail nội suy str(lỗi CSDL)
# ---- Vòng 4: chuỗi owner (1) và (3) dưới dạng lỗi CSDL thật, qua 3 cửa ra web
slog.bind(dau_do="v6_s1s").error("v6_s1s", exc_info=loi_db_hang("s1s", "099999000901"))
thuong.error("v6_s1t", exc_info=loi_db_hang("s1t", "099999000902"))
asyncio.run(generic_exception_handler(yeu_cau, loi_db_hang("s1c", "099999000904")))
asyncio.run(generic_exception_handler(yeu_cau, loi_db_asyncpg_repr("099999000903")))
# ---- Vòng 5: thông điệp lỗi CSDL NGẮN — mỗi đầu dò một tên giả RIÊNG (quét cả đầu ra)
try:
    raise asyncpg.exceptions.DataError("Gia An")               # đúng phản ví dụ của review
except Exception as _e:
    thuong.error("v5_l1 loi: %s", str(_e))                     # đối số %s = str(e)
try:
    raise loi_ngan("Gia Vu")
except Exception as _e:
    thuong.error("v5_l4 %s", "ngu canh " + str(_e))            # đối số có chữ khác ⇒ CẢ đối số
try:
    raise loi_ngan("Gia Bo")
except Exception:
    thuong.exception("v5_l2")                                  # logging.exception
try:
    raise loi_ngan("Gia Cu")
except Exception as _e:
    thuong.error(f"v5_l3 that bai khi luu: {_e} (thu lai sau)")  # câu đã nội suy
slog.bind(dau_do="v5_s1").error("v5_s1", exc_info=loi_ngan("Gia Du"))  # structlog exc_info
try:
    raise asyncpg.exceptions.DataError("0999")
except Exception as _e:
    chuoi("V5S2", "error", event="v5_s2", error=str(_e))       # structlog error=str(e)
chuoi("V5S3", "error", event="v5_s3", error=loi_ngan("Gia Em"))  # giá trị là ngoại lệ
try:
    raise loi_ngan("Gia Ga")
except Exception as _e:
    chuoi("V5S4", "error", event=f"v5_s4 that bai: {_e}")      # CÂU event: giữ chữ khác
_LOI_V5S5 = loi_ngan("Gia Hy")
chuoi("V5S5", "error", event="v5_s5", exc_info=_LOI_V5S5,      # NGOÀI except: exc_info
      error=str(_LOI_V5S5))                                    # đi kèm error=str(e)
chuoi("V5P", "error", event="v5_p %s", positional_args=(loi_ngan("Gia Po"),))  # đối số vị trí
_LOI_W1 = loi_ngan("Gia Ky")
_W1 = _nem(ConflictError("Khong luu: %s" % _LOI_W1), _LOI_W1)  # bọc qua __cause__
thuong.error("v5_w1", exc_info=_W1)                            # traceback của lỗi bọc
thuong.error("v5_w1b %s", _W1)                                 # đối số là lỗi bọc
_LOI_W1S = loi_ngan("Gia Ra")
chuoi("V5W1", "error", event="v5_w1c",
      error=_nem(ConflictError("Khong luu: %s" % _LOI_W1S), _LOI_W1S))  # structlog giá trị lỗi bọc
thuong.error("v5_w2", exc_info=boc_context(loi_ngan("Gia Lo")))  # bọc qua __context__
try:
    raise boc_context(loi_ngan("Gia Mi"))
except ValueError as _w:
    chuoi("V5W3", "error", event="v5_w3", error=str(_w))       # str(lỗi bọc) trong except
asyncio.run(generic_exception_handler(yeu_cau, boc_context(loi_ngan("Gia Mo"))))
try:
    raise loi_ngan("Gia Nam Truong")
except Exception as _e:
    chuoi("V5T", "error", event="v5_t", error=str(_e)[:9])      # bản CẮT của str(e)
try:
    raise loi_ngan("Gia Wa", W="Gia Wo ngu canh")             # CONTEXT: KHÔNG có trong str(e)
except Exception as _e:
    chuoi("V5A", "error", event="v5_a", error=_e.context)      # nội suy riêng thuộc tính
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
# Vòng 3: formatter thường của celery (fmt) — KHÔNG có lớp thoát JSON thứ hai.
logging.getLogger("v6.celery.thuong").warning(
    'v6_c5 DETAIL:  Failing row contains (4242, {"ghi_chu": "x"}, 099999000965, Gia Lap Nam).')
# Vòng 4: lỗi CSDL qua formatter celery (fmt).
logging.getLogger("v6.celery.thuong").error("v6_c6", exc_info=loi_db_moc("c6"))
logging.getLogger("v6.celery.thuong").error("v6_c7", exc_info=loi_db_hang("c7", "099999000905"))
# Vòng 5: lỗi CSDL thông điệp NGẮN qua formatter celery (fmt).
try:
    raise asyncpg.exceptions.DataError("Gia Pho")
except Exception as _e:
    logging.getLogger("v6.celery.thuong").error("v5_c1 loi: %s", str(_e))
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


# ---- F30: thông báo PostgreSQL / asyncpg nhúng giá trị (qua chuỗi processor THẬT)


def test_structlog_che_failing_row_contains(web):
    dong = _dong_chuoi(web, "P12")
    lo = [v for v in ("099999000512", "gia512@example.invalid", "0900000512",
                      "Nguyen Van Gia") if v in dong]
    assert lo == [], "DETAIL 'Failing row contains (…)' lọt %s: %s" % (lo, dong)


def test_structlog_che_failing_row_gia_tri_xuong_dong(web):
    dong = _dong_chuoi(web, "P22")
    lo = [v for v in ("099999000522", "gia522@example.invalid") if v in dong]
    assert lo == [], "hàng lỗi có giá trị XUỐNG DÒNG lọt phần sau dòng đầu %s: %s" % (lo, dong)


def test_structlog_che_exclusion_existing_key_chu_thuong(web):
    dong = _dong_chuoi(web, "P13")
    lo = [v for v in ("0900000513", "0900000613") if v in dong]
    assert lo == [], "exclusion constraint '… existing key (…)=(…)' lọt %s: %s" % (lo, dong)


def test_structlog_che_invalid_input_syntax(web):
    dong = _dong_chuoi(web, "P14")
    assert "GIAV6NHAP14" not in dong, "'invalid input syntax for type …: \"…\"' lọt: %s" % dong


def test_structlog_che_value_out_of_range(web):
    dong = _dong_chuoi(web, "P15")
    assert "099999000515" not in dong, "'value \"…\" is out of range' lọt: %s" % dong


def test_structlog_che_tham_so_asyncpg_query_argument(web):
    dong = _dong_chuoi(web, "P16")
    assert "099999000516" not in dong, "asyncpg 'query argument $n: …' lọt: %s" % dong


def test_structlog_che_json_token_va_context(web):
    dong = _dong_chuoi(web, "P17")
    lo = [v for v in ("GIAV6JSON17", "GIAV6JSON27") if v in dong]
    assert lo == [], "JSON đầu vào (Token \"…\" / JSON data, line N) lọt %s: %s" % (lo, dong)


def test_structlog_che_tham_so_bind_trong_context(web):
    dong = _dong_chuoi(web, "P18")
    assert "099999000518" not in dong, "'portal parameter $1 = …' lọt: %s" % dong


def test_structlog_che_copy_context(web):
    dong = _dong_chuoi(web, "P19")
    assert "GIAV6COPY19" not in dong, "'COPY …, column …: \"…\"' lọt: %s" % dong


def test_structlog_che_invalid_input_value_for_enum(web):
    dong = _dong_chuoi(web, "P20")
    assert "GIAV6ENUM20" not in dong, "'invalid input value for enum …' lọt: %s" % dong


# ---- Vòng 3: giá trị chứa nháy / ngoặc lồng (che THỪA tới hết dòng thay vì che thiếu)


def test_structlog_failing_row_gia_tri_json_co_nhay(web):
    dong = _dong_chuoi(web, "P23")
    lo = [v for v in ("099999000995", "Gia Lap Ten") if v in dong]
    assert lo == [], "hàng lỗi có giá trị JSON (nháy) lộ phần đuôi %s: %s" % (lo, dong)


def test_structlog_failing_row_nhay_va_chu_phia_sau(web):
    dong = _dong_chuoi(web, "P24")
    lo = [v for v in ("099999000996", "Gia Lap Ten") if v in dong]
    assert lo == [], "hàng lỗi có nháy + chữ phía sau lộ %s: %s" % (lo, dong)


def test_structlog_nhan_gia_tri_chua_nhay(web):
    dong = _dong_chuoi(web, "P25")
    assert "099999000981" not in dong, "'…for type integer: \"12\"3 …\"' lộ đuôi: %s" % dong


def test_structlog_copy_gia_tri_chua_nhay(web):
    dong = _dong_chuoi(web, "P26")
    assert "GIAV6COPY26" not in dong, "COPY với giá trị chứa nháy lộ đuôi: %s" % dong


def test_structlog_json_data_co_nhay(web):
    dong = _dong_chuoi(web, "P27")
    assert "GIAV6JSON37" not in dong, "'JSON data, line N: {\"…\"' dừng ở nháy, lộ: %s" % dong


def test_structlog_key_gia_tri_co_ngoac_long(web):
    dong = _dong_chuoi(web, "P29")
    assert "099999000999" not in dong, "Key (…)=(… (…) …) ngoặc lồng lộ đuôi: %s" % dong


def test_structlog_kv_nhay_thoat_khong_lo(web):
    dong = _dong_chuoi(web, "P30")
    assert "Ten30" not in dong, "\"full_name\": \"… \\\"…\\\" …\" (nháy thoát) lộ đuôi: %s" % dong


def test_structlog_kv_nhay_thoat_giu_phan_sau(web):
    dong = _dong_chuoi(web, "P30")
    assert '\\"x\\": 1}' in dong, "che THỪA khi điểm kết thúc giá trị xác định được: %s" % dong


def test_structlog_mat_khau_url_chua_nhay(web):
    dong = _dong_chuoi(web, "P31")
    assert "ss31" not in dong, "mật khẩu URL chứa nháy lộ: %s" % dong


def test_structlog_key_dong_cut_cot_pii(web):
    dong = _dong_chuoi(web, "P32")
    assert "0900000932" not in dong, "Key (phone)=(… bị cắt cụt (không đuôi) lộ: %s" % dong


# ---- Vòng 4: lỗi CSDL — chỉ TÓM TẮT (giá trị giả GIAV6DB… ở dạng KHÔNG regex nào nhận ra)


def _moc_db(ma: str) -> tuple:
    return tuple("GIAV6DB%s%s" % (ma, h) for h in "ABC")


def test_structlog_traceback_loi_csdl_chi_tom_tat(web):
    dong = _dong_chuoi(web, "D1")
    lo = [v for v in _moc_db("d1") if v in dong]
    assert lo == [], "traceback lỗi CSDL qua processor lộ thông điệp/DETAIL/tham số %s: %s" % (lo, dong)


def test_structlog_tom_tat_loi_csdl_giu_chan_doan(web):
    dong = _dong_chuoi(web, "D1")
    mat = [v for v in ("IntegrityError", "CheckViolationError", "sqlstate=23514",
                       "constraint=ck_v6_d1", "table=admission_profiles") if v not in dong]
    assert mat == [], "tóm tắt lỗi CSDL mất thông tin chẩn đoán %s: %s" % (mat, dong)


def test_structlog_gia_tri_la_doi_tuong_loi_csdl(web):
    dong = _dong_chuoi(web, "D6")
    lo = [v for v in _moc_db("d6") if v in dong]
    assert lo == [], "error=<ngoại lệ CSDL> lộ %s: %s" % (lo, dong)


def test_structlog_str_loi_csdl_trong_except(web):
    dong = _dong_chuoi(web, "D5s")
    lo = [v for v in _moc_db("d5s") if v in dong]
    assert lo == [], "error=str(e) trong except lỗi CSDL lộ %s: %s" % (lo, dong)


def test_structlog_str_loi_csdl_long_trong_dict_trong_except(web):
    dong = _dong_chuoi(web, "D5n")
    lo = [v for v in _moc_db("d5n") if v in dong]
    assert lo == [], "ctx={'loi': [f'{e}']} trong except lỗi CSDL lộ %s: %s" % (lo, dong)


def test_structlog_chu_owner_failing_row_xuong_dong(web):
    dong = _dong_chuoi(web, "P33")
    lo = [v for v in ("099999000999", "Gia Lap Ten") if v in dong]
    assert lo == [], "lớp phụ: Failing row xuống dòng THẬT, không mốc, lộ dòng 2 %s: %s" % (lo, dong)


def test_structlog_chu_owner_failing_row_da_thoat_json(web):
    dong = _dong_chuoi(web, "P34")
    lo = [v for v in ("099999000999", "Gia Lap Ten") if v in dong]
    assert lo == [], "lớp phụ: Failing row dạng đã thoát JSON lộ %s: %s" % (lo, dong)


def test_structlog_chu_owner_asyncpg_repr_xuong_dong(web):
    dong = _dong_chuoi(web, "P35")
    lo = [v for v in ("099999000999", "Gia Lap Ten") if v in dong]
    assert lo == [], "lớp phụ: repr asyncpg có \\n lộ phần sau %s: %s" % (lo, dong)


def test_structlog_giu_key_khoa_ngoai_khong_phai_pii(web):
    dong = _dong_chuoi(web, "P21")
    assert "Key (lead_id)=(4242)" in dong, (
        "che NHẦM giá trị khoá ngoại không phải PII (mất chẩn đoán): %s" % dong)


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


def test_logging_thuong_che_failing_row_contains(web):
    out = _co_dau_do(web, "v6_l10_failing_row")
    lo = [v for v in ("099999000530", "gia530@example.invalid", "0900000530") if v in out]
    assert lo == [], "'Failing row contains' qua logging thường lọt %s" % lo


def test_handler_loi_ghi_failing_row_qua_generic_handler(web):
    out = _co_dau_do(web, "ck_v6_l11")
    lo = [v for v in ("099999000531", "gia531@example.invalid", "0900000531") if v in out]
    assert lo == [], (
        "generic_exception_handler ghi str(IntegrityError) lọt hàng lỗi %s" % lo)


def _dong_json(r: subprocess.CompletedProcess, dau_do: str) -> str:
    """Dòng JSON structlog mang mốc ``"dau_do":"<dau_do>"`` (mốc đứng ĐẦU dòng)."""
    _co_dau_do(r, dau_do)
    dong = [x for x in r.stderr.splitlines() if '"dau_do":"%s"' % dau_do in x]
    assert len(dong) == 1, "HẠ TẦNG: không thấy đúng một dòng JSON %s" % dau_do
    return dong[0]


def _doc_json(dong: str) -> dict:
    import json

    try:
        return json.loads(dong)
    except ValueError as exc:
        return {"LOI_JSON": repr(exc)}


def test_web_structlog_failing_row_nhay_qua_handler_goc(web):
    out = _co_dau_do(web, "v6_e2_json")
    # Tên giả RIÊNG của đầu dò (vòng 4): chuỗi owner cũng mang "Gia Lap Ten" — quét cả
    # đầu ra mà dùng tên chung thì ca đỏ vì đầu dò KHÁC (đã thấy ở lượt đỏ-trước đầu).
    lo = [v for v in ("099999000963", "0900000966", "Gia Lap Hai") if v in out]
    assert lo == [], "dòng structlog thật (Failing row + KV nháy hỏng) lộ %s" % lo


def test_web_structlog_failing_row_cuoi_gia_tri_json_hop_le(web):
    """Processor che giá trị THÔ, filter gốc che lại dòng đã render: với ``Failing row
    contains (<redacted>).`` đứng cuối chuỗi, lần che thứ hai KHÔNG được nuốt tới hết
    dòng làm hỏng JSON (nhánh "đã che" — idempotent)."""
    dong = _dong_json(web, "v6_e3_json")
    ob = _doc_json(dong)
    assert ob.get("event") == "v6_e3" and "logger" in ob and "level" in ob, (
        "dòng structlog không còn là JSON đủ trường sau hai lớp che: %s" % dong)


def test_web_structlog_kv_da_che_cuoi_gia_tri_json_hop_le(web):
    """``full_name=\\"<redacted>\\"`` đứng cuối chuỗi JSON (sau nó là nháy đóng của
    chuỗi bao ngoài): nhánh "đã che" của KV phải nhận nháy ấy, không che thừa tới
    hết dòng."""
    dong = _dong_json(web, "v6_e4_json")
    ob = _doc_json(dong)
    assert ob.get("event") == "v6_e4" and "logger" in ob and "level" in ob, (
        "dòng structlog không còn là JSON đủ trường sau hai lớp che: %s" % dong)


def test_logging_thuong_failing_row_nhay_chu_phia_sau(web):
    out = _co_dau_do(web, "v6_l13")
    lo = [v for v in ("099999000997", "Gia Lap Ba") if v in out]  # tên giả riêng (vòng 4)
    assert lo == [], "logging thường: Failing row có nháy lộ %s" % lo


def test_logging_thuong_asyncpg_repr_da_thoat(web):
    out = _co_dau_do(web, "v6_l14")
    assert "099999000990" not in out, "asyncpg repr ('O\\\\'Gia…) đã thoát thêm một lớp lộ đuôi"


def test_logging_thuong_kv_nhay_hong_che_toi_het_dong(web):
    out = _co_dau_do(web, "v6_l15")
    assert "0900000993" not in out, "full_name=\"Gia \"Lap\" Ten …\" (nháy lồng) lộ đuôi"


def test_logging_thuong_failing_row_dang_da_thoat_json(web):
    out = _co_dau_do(web, "v6_l16")
    assert "099999000964" not in out, "Failing row ở dạng đã thoát JSON lộ"


def test_logging_thuong_traceback_loi_csdl_chi_tom_tat(web):
    out = _co_dau_do(web, "v6_d2")
    lo = [v for v in _moc_db("d2") if v in out]
    assert lo == [], "traceback lỗi CSDL qua handler gốc lộ %s" % lo


def test_logging_thuong_loi_boc_loi_csdl_qua_cause(web):
    out = _co_dau_do(web, "v6_d4")
    lo = [v for v in _moc_db("d4") if v in out]
    assert lo == [], "ngoại lệ BỌC lỗi CSDL (__cause__) — traceback chuỗi lộ %s" % lo


def test_logging_thuong_str_loi_csdl_trong_except(web):
    out = _co_dau_do(web, "v6_d5")
    lo = [v for v in _moc_db("d5") if v in out]
    assert lo == [], "f'…{e}' trong except lỗi CSDL lộ %s" % lo


def test_logging_thuong_doi_so_la_loi_csdl(web):
    out = _co_dau_do(web, "v6_d7")
    lo = [v for v in _moc_db("d7") if v in out]
    assert lo == [], "logger.error('%%s', <lỗi CSDL>) lộ %s" % lo


def test_generic_handler_loi_csdl_chi_tom_tat(web):
    out = _co_dau_do(web, "ck_v6_d3")
    lo = [v for v in _moc_db("d3") if v in out]
    assert lo == [], "generic_exception_handler ghi str(lỗi CSDL) lộ %s" % lo


def test_base_handler_detail_noi_suy_loi_csdl(web):
    out = _co_dau_do(web, "ck_v6_d8")
    lo = [v for v in _moc_db("d8") if v in out]
    assert lo == [], "ConflictError(detail=f'…{lỗi CSDL}') qua handler lộ %s" % lo


def test_web_structlog_loi_csdl_failing_row_xuong_dong(web):
    out = _co_dau_do(web, "v6_s1s")
    assert "099999000901" not in out, "structlog thật: lỗi CSDL có Failing row xuống dòng lộ"


def test_logging_thuong_loi_csdl_failing_row_xuong_dong(web):
    out = _co_dau_do(web, "v6_s1t")
    assert "099999000902" not in out, "handler gốc: lỗi CSDL có Failing row xuống dòng lộ"


def test_generic_handler_loi_csdl_failing_row_xuong_dong(web):
    out = _co_dau_do(web, "ck_v6_s1c")
    assert "099999000904" not in out, "generic handler: lỗi CSDL có Failing row xuống dòng lộ"


def test_generic_handler_loi_asyncpg_repr_xuong_dong(web):
    out = _co_dau_do(web, "Unhandled exception: DataError")
    assert "099999000903" not in out, "generic handler: asyncpg DataError (repr có \\n) lộ"


def test_logging_thuong_che_token_duong_dan_ma_hoa_url(web):
    out = _co_dau_do(web, "v6_l12_ma_hoa")
    assert "GIAV6TOKENL12" not in out, "token sau '%2Fconfirm%2F' (mã hoá URL) lọt"


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


def test_celery_fmt_failing_row_gia_tri_co_nhay(celery_worker):
    """Formatter thường của celery (khuôn ``fmt``) — không có lớp thoát JSON thứ hai."""
    out = _khong_nap_app_main(celery_worker, "v6_c5")
    lo = [v for v in ("099999000965", "Gia Lap Nam") if v in out]  # tên giả riêng (vòng 4)
    assert lo == [], "worker: Failing row có nháy lộ qua formatter celery %s" % lo


def test_celery_fmt_loi_csdl_chi_tom_tat(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c6")
    lo = [v for v in _moc_db("c6") if v in out]
    assert lo == [], "worker: traceback lỗi CSDL qua formatter celery lộ %s" % lo


def test_celery_fmt_loi_csdl_failing_row_xuong_dong(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c7")
    assert "099999000905" not in out, "worker: lỗi CSDL có Failing row xuống dòng lộ"


def test_celery_worker_che_mat_khau_redis_url(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v6_c4_redis")
    assert "GIAMATKHAUC04" not in out, "worker: redis_url lọt mật khẩu"


def test_celery_beat_structlog_che(celery_beat):
    out = _khong_nap_app_main(celery_beat, "v6_b1_struct")
    assert "099999000401" not in out, "beat: structlog lọt CCCD — chưa nạp bộ che"



# =============================================================================
# V6 vòng 5 — F30: thay TOÀN BỘ nội dung lỗi CSDL đã nhận diện, KHÔNG ngưỡng độ dài
# =============================================================================
# Mỗi đầu dò một tên giả RIÊNG (``Gia An``, ``Gia Vu``…) ⇒ quét cả đầu ra không nhiễm
# chéo. "Chỉ còn metadata": giá trị/đối số lấy từ lỗi CSDL phải là ĐÚNG bản tóm tắt.


def _dong_co(out: str, moc: str) -> str:
    dong = [x for x in out.splitlines() if moc in x]
    assert dong, "HẠ TẦNG: không thấy dòng mang mốc %r" % moc
    return "\n".join(dong)


def _truong(r: subprocess.CompletedProcess, ma: str, khoa: str):
    import json

    dong = _dong_chuoi(r, ma)
    return json.loads(dong.split("|", 2)[2]).get(khoa)


def _la_tom_tat(v) -> bool:
    return isinstance(v, str) and v.startswith("DBError[") and v.endswith("]")


def test_v5_logging_doi_so_str_loi_ngan_chi_con_tom_tat(web):
    out = _co_dau_do(web, "v5_l1 loi:")
    assert "Gia An" not in out and "v5_l1 loi: DBError[" in _dong_co(out, "v5_l1 loi:"), (
        "logging %%s với str(DataError('Gia An')) — 6 ký tự: %s" % _dong_co(out, "v5_l1"))


def test_v5_logging_doi_so_co_chu_khac_ca_gia_tri_thanh_tom_tat(web):
    out = _co_dau_do(web, "v5_l4")
    dong = _dong_co(out, "v5_l4")
    assert "Gia Vu" not in out and "v5_l4 DBError[" in dong, (
        "đối số lấy từ lỗi CSDL phải thành CẢ bản tóm tắt: %s" % dong)


def test_v5_logging_exception_loi_ngan(web):
    out = _co_dau_do(web, "v5_l2")
    assert "Gia Bo" not in out, "logging.exception với lỗi CSDL thông điệp ngắn lộ"


def test_v5_logging_cau_noi_suy_giu_chu_khac(web):
    out = _co_dau_do(web, "v5_l3")
    dong = _dong_co(out, "v5_l3")
    assert "Gia Cu" not in out and "v5_l3 that bai khi luu: DBError[" in dong \
        and "(thu lai sau)" in dong, "câu f'…{e}…': chỉ phần lấy từ lỗi thành tóm tắt: %s" % dong


def test_v5_structlog_exc_info_loi_ngan(web):
    out = _co_dau_do(web, '"dau_do":"v5_s1"')
    assert "Gia Du" not in out, "structlog exc_info với lỗi CSDL thông điệp ngắn lộ"


def test_v5_structlog_error_str_chi_con_tom_tat(web):
    v = _truong(web, "V5S2", "error")
    assert _la_tom_tat(v) and "0999" not in v, "error=str(e) phải là ĐÚNG bản tóm tắt: %r" % v


def test_v5_structlog_gia_tri_ngoai_le_ngan(web):
    dong = _dong_chuoi(web, "V5S3")
    assert "Gia Em" not in dong and _la_tom_tat(_truong(web, "V5S3", "error")), dong


def test_v5_structlog_cau_event_giu_chu_khac(web):
    ev = _truong(web, "V5S4", "event")
    assert isinstance(ev, str) and ev.startswith("v5_s4 that bai: DBError[") and "Gia Ga" not in ev, (
        "event: chỉ phần lấy từ lỗi thành tóm tắt, chữ khác GIỮ: %r" % ev)


def test_v5_structlog_exc_info_kem_error_str_ngoai_except(web):
    dong = _dong_chuoi(web, "V5S5")
    assert "Gia Hy" not in dong and _la_tom_tat(_truong(web, "V5S5", "error")), (
        "error=str(e) đi kèm exc_info=e NGOÀI except lộ: %s" % dong)


def test_v5_structlog_doi_so_vi_tri_la_loi_csdl(web):
    ev = _truong(web, "V5P", "event")
    assert isinstance(ev, str) and ev.startswith("v5_p DBError[") and "Gia Po" not in ev, (
        "log.error('… %%s', lỗi CSDL) — đối số vị trí lộ: %r" % ev)


def test_v5_boc_cause_traceback_va_doi_so(web):
    out = _co_dau_do(web, "v5_w1b")
    assert "Gia Ky" not in out and "v5_w1b Khong luu: DBError[" in _dong_co(out, "v5_w1b"), (
        "lỗi BỌC (__cause__): traceback/đối số còn chữ của lỗi CSDL")


def test_v5_boc_cause_gia_tri_structlog(web):
    v = _truong(web, "V5W1", "error")
    assert isinstance(v, str) and v.startswith("Khong luu: DBError[") and "Gia Ra" not in v, (
        "structlog error=<lỗi bọc>: %r" % v)


def test_v5_boc_context_traceback(web):
    out = _co_dau_do(web, "v5_w2")
    assert "Gia Lo" not in out, "lỗi BỌC qua __context__: traceback còn chữ của lỗi CSDL"


def test_v5_boc_context_str_trong_except_chi_con_tom_tat(web):
    v = _truong(web, "V5W3", "error")
    assert _la_tom_tat(v) and "Gia Mi" not in v, (
        "str(lỗi bọc) trong except phải là ĐÚNG bản tóm tắt: %r" % v)


def test_v5_generic_handler_loi_boc_ngan(web):
    out = _co_dau_do(web, "Unhandled exception: ValueError: loi khi ghi:")
    dong = _dong_co(out, "Unhandled exception: ValueError: loi khi ghi:")
    assert "Gia Mo" not in out and "loi khi ghi: DBError[" in dong, (
        "generic handler: lỗi bọc lỗi CSDL ngắn lộ: %s" % dong)


def test_v5_ban_cat_cua_str_loi(web):
    v = _truong(web, "V5T", "error")
    assert _la_tom_tat(v) and "Gia Nam" not in v, "bản CẮT str(e)[:9] lộ: %r" % v


def test_v5_thuoc_tinh_context_ngoai_str(web):
    """``e.context`` (CONTEXT của PostgreSQL) KHÔNG có trong ``str(e)`` của asyncpg — chỉ
    tầng thuộc tính chữ nhận ra nó là chữ của lỗi CSDL."""
    v = _truong(web, "V5A", "error")
    assert _la_tom_tat(v) and "Gia Wo" not in v, "error=e.context lộ: %r" % v


def test_v5_celery_doi_so_str_loi_ngan(celery_worker):
    out = _khong_nap_app_main(celery_worker, "v5_c1 loi:")
    assert "Gia Pho" not in out and "v5_c1 loi: DBError[" in out, (
        "worker: logging %s với str(lỗi CSDL ngắn) lộ")


# ---- chu_loi_an_toan: chữ lỗi đưa RA NGOÀI log (phản hồi HTTP, cột CSDL) ----------


def test_v5_chu_loi_an_toan_loi_csdl_chi_tom_tat():
    import asyncpg

    from app.core.log_redaction import chu_loi_an_toan

    v = chu_loi_an_toan(asyncpg.exceptions.DataError("Gia Qu"))
    assert _la_tom_tat(v) and "Gia Qu" not in v, v


def test_v5_chu_loi_an_toan_giu_nguyen_loi_khong_csdl():
    """Thông điệp nghiệp vụ cho NGƯỜI DÙNG không bị che nhầm (không regex).
    Dùng đúng dạng thông báo trùng CCCD của hệ thống — regex lớp phụ CÓ che nó
    (khẳng định ngay dưới), nên ca này phân biệt được "không regex" với "có regex"."""
    from app.core.log_redaction import chu_loi_an_toan, redact_text

    loi = ValueError("CCCD 099999000984 đã tồn tại trong hệ thống")
    assert redact_text(str(loi)) != str(loi), "HẠ TẦNG: regex không đổi thông điệp mẫu"
    assert chu_loi_an_toan(loi) == str(loi)


def test_v5_chu_loi_an_toan_loi_boc_giu_chu_nghiep_vu():
    import asyncpg

    from app.core.log_redaction import chu_loi_an_toan

    goc = asyncpg.exceptions.DataError("Gia Su")
    try:
        try:
            raise goc
        except Exception as e:
            raise RuntimeError("Khong luu: %s" % e) from e
    except RuntimeError as boc:
        v = chu_loi_an_toan(boc)
    assert v.startswith("Khong luu: DBError[") and "Gia Su" not in v, v


# ---- §6: chữ của ngoại lệ (có thể là lỗi CSDL) KHÔNG đi ra ngoài log thô ----------

_S6_KIEU = {
    "Exception", "BaseException", "IntegrityError", "DBAPIError", "OperationalError",
    "DataError", "ProgrammingError", "StatementError", "SQLAlchemyError", "PostgresError",
    "InterfaceError", "InternalError", "NotSupportedError", "DatabaseError",
    "UniqueViolationError", "ForeignKeyViolationError", "CheckViolationError",
}
#: Hàm BỌC an toàn — chữ ngoại lệ đi qua chúng thì không còn là chữ thô.
_S6_HAM_BOC = {
    "chu_loi_an_toan", "mo_ta_loi", "tom_tat_loi_csdl", "_safe_bulk_error_message",
    "type", "isinstance", "_is_lock_not_available", "_handle_lead_integrity_error",
    "log_dispatch_failure", "thoat_cli_an_toan", "loai_loi_an_toan",
}
#: Hàm chuyển đổi — tự nó không phải lối ra; kết quả đi đâu thì lối ra ở đó.
_S6_TRUNG_TINH = {"str", "repr", "len", "getattr", "format"}
#: Lời gọi log/in — thuộc tầng che log, không phải lối ra ở đây.
_S6_LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log",
           "_log_warning", "print"}
#: V6 vòng 6 (F41): tiến trình DÒNG LỆNH chạy NGOÀI web/celery lúc deploy / tạo container —
#: đầu ra của chúng vào log deploy (Actions, kho PUBLIC) hoặc ``docker logs``. Ở các tệp này
#: ``print`` LÀ lối ra (không phải tầng che log).
_S6_CLI = (
    "alembic/env.py",                          # one-off deploy.sh Step 6 + docker-entrypoint.sh
    "scripts/pre_deploy_check.py",             # deploy.sh Step 7
    "app/scripts/sync_notification_rules.py",  # docker-entrypoint.sh + chạy tay lúc cutover
)
#: Lối ra ĐÃ RÀ, KHÔNG mang lỗi CSDL — (tệp, hàm bao, loại): (số chỗ, lý do).
#: Miễn trừ CHỈ hợp lệ khi khối ``try`` KHÔNG có thao tác CSDL (guard tự kiểm — vòng 5b: một
#: miễn trừ ghi nhầm "lỗi SMTP" đã giấu ``email_channel.send``, nơi ``try`` bọc ``db.execute``).
_S6_MIEN = {
    ("app/gateways/zalo.py", "_call_template_api", "return"): (1, "lỗi HTTP của Zalo API, khối try không chạm CSDL"),
    ("app/gateways/zalo_bot.py", "send_message", "return"): (1, "đã qua _safe_error_message; lỗi HTTP Zalo Bot"),
    ("app/routers/monitoring.py", "get_notification_metrics", "gan"): (1, "lỗi Redis (safe_redis_*), không CSDL"),
    ("app/routers/monitoring.py", "get_system_overview", "gan"): (3, "Redis / Celery / Socket.IO — nhánh CSDL đã qua chu_loi_an_toan"),
    ("app/services/notification_rule_loader.py", "get_rule_for_event", "raise"): (1, "lỗi kiểm cấu hình recipient_config (pydantic)"),
    ("app/services/payment_import_service.py", "parse_template", "raise"): (1, "lỗi đọc tệp Excel tải lên"),
    ("app/services/sms_contact_service.py", "_parse_rows", "raise"): (1, "lỗi đọc tệp CSV tải lên"),
    ("app/tasks/utils.py", "_runner", "gan"): (1, "giữ ĐỐI TƯỢNG ngoại lệ để ném lại ở luồng gọi"),
    ("app/scripts/sync_notification_rules.py", "_recipient_config_for", "raise"): (
        1, "lỗi dựng resolver từ cấu hình hạt giống trong mã (không chạm CSDL); thông điệp ra qua cửa ra CLI an toàn"),
}


#: Thuộc tính mà ``await <x>.<thuộc tính>(…)`` là thao tác CSDL (xấp xỉ RỘNG có chủ ý: ``await
#: redis.get`` cũng bị tính — hệ quả chỉ là phải bọc ``chu_loi_an_toan``, vốn vô hại với lỗi khác).
_S6_THAO_TAC_CSDL = {
    "execute", "get", "scalar", "scalars", "scalar_one", "scalar_one_or_none", "commit", "flush",
    "refresh", "delete", "merge", "rollback", "stream", "run_sync", "begin", "begin_nested",
}


def _s6_quet() -> dict:
    """Mọi lối ra NGOÀI log của chữ ngoại lệ trong ``except`` có thể bắt lỗi CSDL.
    Trả ``{(tệp, hàm bao, loại): {"n": số chỗ, "dong": [dòng…], "csdl": bool}}`` — ``csdl``:
    khối ``try`` có thao tác CSDL trực tiếp, hoặc ``except`` bắt KIỂU lỗi CSDL."""
    import ast

    def ten(f):
        return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")

    def kieu(t):
        if t is None:
            return {"<bare>"}
        if isinstance(t, ast.Tuple):
            return set().union(*(kieu(x) for x in t.elts))
        return {ten(t) or "?"}

    def lo(node, nhiem):
        if isinstance(node, ast.Call) and ten(node.func) in _S6_HAM_BOC:
            return False
        if isinstance(node, ast.Name) and node.id in nhiem:
            return True
        return any(lo(c, nhiem) for c in ast.iter_child_nodes(node))

    def dong_lo(node, nhiem):
        """Dòng của chỗ dùng biến nhiễm ĐẦU TIÊN không qua hàm bọc (báo đúng dòng lối ra)."""
        if isinstance(node, ast.Call) and ten(node.func) in _S6_HAM_BOC:
            return None
        if isinstance(node, ast.Name) and node.id in nhiem:
            return node.lineno
        for c in ast.iter_child_nodes(node):
            d = dong_lo(c, nhiem)
            if d is not None:
                return d
        return None

    def la_with_csdl(w):
        for it in w.items:
            e = it.context_expr
            if isinstance(e, ast.Call) and (ten(e.func) == "AsyncSessionLocal"
                                            or ten(e.func) in ("begin", "begin_nested")):
                return True
        return False

    def try_co_csdl(t, cha):
        for n in ast.walk(ast.Module(body=t.body, type_ignores=[])):
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Attribute) \
                    and n.value.func.attr in _S6_THAO_TAC_CSDL:
                return True
            if isinstance(n, ast.AsyncWith) and la_with_csdl(n):
                return True
        ong = cha.get(t)
        while ong is not None and not isinstance(ong, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(ong, ast.AsyncWith) and la_with_csdl(ong):
                return True
            ong = cha.get(ong)
        return False

    kq: dict = {}
    goc = BACKEND / "app"
    tep_quet = [p for p in sorted(goc.rglob("*.py"))
                if "/scripts/" not in p.relative_to(BACKEND).as_posix()
                and "__pycache__" not in p.relative_to(BACKEND).as_posix()]
    tep_quet += [BACKEND / r for r in _S6_CLI]
    for p in tep_quet:
        rel = p.relative_to(BACKEND).as_posix()
        la_cli = rel in _S6_CLI
        cay = ast.parse(p.read_text(encoding="utf-8"))
        cha = {c: n for n in ast.walk(cay) for c in ast.iter_child_nodes(n)}
        for h in ast.walk(cay):
            if not isinstance(h, ast.ExceptHandler) or not h.name or not (kieu(h.type) & _S6_KIEU):
                continue
            bao = h
            while bao in cha and not isinstance(bao, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bao = cha[bao]
            ten_bao = getattr(bao, "name", "<module>")
            csdl = bool(kieu(h.type) & (_S6_KIEU - {"Exception", "BaseException"})) or (
                isinstance(cha.get(h), ast.Try) and try_co_csdl(cha[h], cha))
            than = ast.Module(body=h.body, type_ignores=[])
            nhiem = {h.name}
            for _ in range(3):  # lan truyền qua biến cục bộ (error_msg = str(e.orig) …)
                for n in ast.walk(than):
                    if isinstance(n, ast.Assign) and lo(n.value, nhiem):
                        nhiem |= {t.id for t in n.targets if isinstance(t, ast.Name)}
            log_o_day = _S6_LOG - {"print"} if la_cli else _S6_LOG
            bo_qua = {id(m) for n in ast.walk(than)
                      if isinstance(n, ast.Call) and ten(n.func) in log_o_day for m in ast.walk(n)}
            for n in ast.walk(than):
                if id(n) in bo_qua:
                    continue
                loai = None
                if isinstance(n, ast.Raise) and n.exc is not None:
                    if not (isinstance(n.exc, ast.Name) and n.exc.id in nhiem) and lo(n.exc, nhiem):
                        loai = "raise"
                elif isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)) and n.value is not None \
                        and lo(n.value, nhiem):
                    loai = type(n).__name__.lower()
                elif isinstance(n, ast.Assign) and lo(n.value, nhiem) and any(
                        isinstance(t, (ast.Attribute, ast.Subscript)) for t in n.targets):
                    loai = "gan"
                elif isinstance(n, ast.Call) and ten(n.func) not in _S6_HAM_BOC | _S6_TRUNG_TINH \
                        and any(lo(a, nhiem) for a in list(n.args) + [k.value for k in n.keywords]):
                    ong, trong = cha.get(n), False
                    while ong is not None and ong is not h:
                        if isinstance(ong, (ast.Raise, ast.Return, ast.Yield, ast.YieldFrom,
                                            ast.Assign, ast.Call)):
                            trong = True
                            break
                        ong = cha.get(ong)
                    if not trong:
                        loai = "goi:" + ten(n.func)
                if loai:
                    o = kq.setdefault((rel, ten_bao, loai), {"n": 0, "dong": [], "csdl": False})
                    o["n"] += 1
                    o["dong"].append(dong_lo(n.exc if isinstance(n, ast.Raise) else n, nhiem)
                                     or n.lineno)
                    o["csdl"] = o["csdl"] or csdl
    return kq


def test_v5_khong_dua_chu_loi_csdl_ra_ngoai_log():
    """§6 (vòng 5, v2 ở 5b): chữ ngoại lệ trong ``except`` có thể bắt lỗi CSDL KHÔNG được
    đi ra phản hồi HTTP / cột CSDL / danh sách trả về mà không qua ``chu_loi_an_toan``
    (hoặc ``mo_ta_loi``). Lối ra đã rà và KHÔNG mang lỗi CSDL nằm ở ``_S6_MIEN`` kèm lý do
    — khoá HAI chiều (chỗ mới ⇒ ĐỎ; miễn trừ biến mất ⇒ ĐỎ), và miễn trừ KHÔNG được phủ
    khối ``try`` có thao tác CSDL (⇒ ĐỎ: phải bọc)."""
    thuc = _s6_quet()
    mong = {k: v[0] for k, v in _S6_MIEN.items()}
    moi = {k: v for k, v in thuc.items() if mong.get(k) != v["n"]}
    cu = {k: n for k, n in mong.items() if k not in thuc or thuc[k]["n"] != n}
    mien_sai = {k: v for k, v in thuc.items() if k in _S6_MIEN and v["csdl"]}
    assert not moi and not cu and not mien_sai, (
        "lối ra chữ ngoại lệ CHƯA rà (bọc bằng chu_loi_an_toan, hoặc thêm vào _S6_MIEN kèm lý do "
        "nếu chắc chắn không mang lỗi CSDL): %s\nmiễn trừ không còn khớp: %s\n"
        "miễn trừ phủ khối try CÓ thao tác CSDL (phải bọc, không được miễn): %s" % (moi, cu, mien_sai))



# =============================================================================
# V6 vòng 6 — F41: Alembic CLI (deploy one-off + docker-entrypoint.sh) KHÔNG in chữ lỗi CSDL
# =============================================================================
# Đi qua ĐÚNG cửa ra thật (CLAUDE.md §10): subprocess ``alembic upgrade head`` (= one-off
# ``--entrypoint alembic backend upgrade head`` của deploy.sh) và ``bash docker-entrypoint.sh``
# (``alembic upgrade head`` lúc tạo container). ``alembic/env.py`` THẬT; chỉ thư mục phiên bản
# là tạm (``version_locations`` trong một alembic.ini chép, trỏ qua ``ALEMBIC_CONFIG``) và CSDL
# là một CSDL nháp riêng (không chạm qlts_test). Migration tạm gây vi phạm CHECK THẬT trên
# Postgres với giá trị GIẢ ngắn (< 8 ký tự) và dài, có DETAIL (hàng lỗi) + tham số bind.

_F41_DB = "v6_alembic_gia"
_F41_KICH_BAN = {
    # mã: (giá trị ngắn, giá trị dài) — riêng từng kịch bản ⇒ quét cả đầu ra không nhiễm chéo
    "loi": ("Gia Ut", "099999000992 Nguyen Van Gia dai hon tam ky tu"),
    "log": ("Gia Uy", "099999000993 Tran Thi Gia dai hon tam ky tu"),
}
_F41_MIGRATION = """\
\"\"\"V6 vòng 6 — migration TẠM gây lỗi CSDL giả (kịch bản {kb}).\"\"\"
import logging

import sqlalchemy as sa
from alembic import op

revision = "v6gia_{kb}"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    b = op.get_bind()
    b.execute(sa.text("DROP TABLE IF EXISTS v6_gia_alembic"))
    b.execute(sa.text(
        "CREATE TABLE v6_gia_alembic (id int, ten text, cccd text, "
        "CONSTRAINT ck_v6_gia_alembic CHECK (length(ten) > 100))"))
    try:
        b.execute(sa.text("INSERT INTO v6_gia_alembic VALUES (1, :ten, :cccd)"),
                  {{"ten": "{ngan}", "cccd": "{dai}"}})
    except Exception as e:
        if "{kb}" != "log":
            raise
        # Thư viện / migration ghi log lỗi qua logger (alembic, sqlalchemy) rồi dừng bằng một
        # lỗi KHÔNG mang chữ của lỗi CSDL — đo RIÊNG tầng phủ logger của fileConfig.
        logging.getLogger("alembic.runtime.migration").error("v6 ghi log loi: %s", e, exc_info=True)
        logging.getLogger("sqlalchemy.engine").warning("v6 ghi log chuoi: " + str(e))
        raise RuntimeError("v6 dung sau khi ghi log") from None


def downgrade():
    pass
"""


def _f41_url(ten_db: str) -> str:
    import re

    url = os.environ.get("DATABASE_URL", "")
    m = re.match(r"^(postgresql(?:\+asyncpg)?://[^/]+/)([^?]+)(\?.*)?$", url)
    assert m, "HẠ TẦNG: DATABASE_URL không đúng dạng postgresql://…/<db>"
    return m.group(1) + ten_db + (m.group(3) or "")


def _f41_db(lenh: str) -> None:
    import asyncio

    import asyncpg

    async def _chay():
        c = await asyncpg.connect(_f41_url("postgres").replace("+asyncpg", ""))
        try:
            await c.execute(lenh)
        finally:
            await c.close()

    asyncio.run(_chay())


def _f41_chay(tmp: Path, kb: str, duong: str) -> subprocess.CompletedProcess:
    import shutil

    ngan, dai = _F41_KICH_BAN[kb]
    thu_muc = tmp / ("%s-%s" % (kb, duong))
    (thu_muc / "versions").mkdir(parents=True)
    (thu_muc / "versions" / ("v6gia_%s.py" % kb)).write_text(
        _F41_MIGRATION.format(kb=kb, ngan=ngan, dai=dai), encoding="utf-8")
    ini = (BACKEND / "alembic.ini").read_text(encoding="utf-8")
    assert "script_location = %(here)s/alembic" in ini, "HẠ TẦNG: alembic.ini đổi khuôn"
    ini = ini.replace(
        "script_location = %(here)s/alembic",
        "script_location = %s\nversion_locations = %s"
        % ((BACKEND / "alembic").as_posix(), (thu_muc / "versions").as_posix()))
    (thu_muc / "alembic.ini").write_text(ini, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "ALEMBIC_CONFIG": str(thu_muc / "alembic.ini"),
        "DATABASE_URL": _f41_url(_F41_DB),
        "RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP": "false",  # chỉ đo bước alembic của entrypoint
        "PYTHONIOENCODING": "utf-8",
    })
    if duong == "tran":
        alembic_bin = shutil.which("alembic")
        assert alembic_bin, "HẠ TẦNG: không thấy lệnh alembic"
        lenh = [alembic_bin, "upgrade", "head"]
    else:
        lenh = ["bash", str(BACKEND / "docker-entrypoint.sh"), "echo", "V6_KHONG_DUOC_TOI_DAY"]
    _f41_db("DROP DATABASE IF EXISTS %s WITH (FORCE)" % _F41_DB)
    _f41_db("CREATE DATABASE %s" % _F41_DB)
    try:
        return subprocess.run(lenh, cwd=str(BACKEND), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=240, env=env)
    finally:
        _f41_db("DROP DATABASE IF EXISTS %s WITH (FORCE)" % _F41_DB)


@pytest.fixture(scope="module")
def f41(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("v6_alembic")
    return {(kb, d): _f41_chay(tmp, kb, d) for kb in _F41_KICH_BAN for d in ("tran", "entrypoint")}


def _f41_dau_ra(r: subprocess.CompletedProcess, kb: str) -> str:
    """Toàn bộ stdout + stderr, sau khi xác nhận migration tạm THẬT SỰ đã chạy tới lỗi."""
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    assert "v6gia_%s" % kb in out, "HẠ TẦNG: migration tạm không chạy:\n%s" % out[-3000:]
    assert "V6_KHONG_DUOC_TOI_DAY" not in out, "HẠ TẦNG: entrypoint chạy tiếp sau alembic hỏng"
    if kb == "log":
        assert "v6 ghi log loi:" in out, "HẠ TẦNG: dòng log của kịch bản log không có mặt"
    return out


def _f41_lo(out: str, kb: str) -> list:
    ngan, dai = _F41_KICH_BAN[kb]
    return [v for v in (ngan, dai, dai[:12]) if v in out]


def test_v6_alembic_cli_tran_loi_csdl_khong_lo(f41):
    """One-off ``alembic upgrade head`` (deploy.sh Step 6): traceback không bắt ⇒ chỉ còn
    tóm tắt; mã thoát KHÁC 0."""
    r = f41[("loi", "tran")]
    out = _f41_dau_ra(r, "loi")
    lo = _f41_lo(out, "loi")
    assert r.returncode != 0 and lo == [] and "DBError[" in out and "alembic: THẤT BẠI" in out, (
        "alembic CLI lộ %s (rc=%s):\n%s" % (lo, r.returncode, out[-3000:]))


def test_v6_alembic_entrypoint_loi_csdl_khong_lo(f41):
    """``docker-entrypoint.sh`` (``alembic upgrade head`` lúc tạo container ⇒ docker logs)."""
    r = f41[("loi", "entrypoint")]
    out = _f41_dau_ra(r, "loi")
    lo = _f41_lo(out, "loi")
    assert r.returncode != 0 and lo == [] and "DBError[" in out and "alembic: THẤT BẠI" in out, (
        "entrypoint lộ %s (rc=%s):\n%s" % (lo, r.returncode, out[-3000:]))


def test_v6_alembic_cli_tran_logger_filecfg_khong_lo(f41):
    """Logger ``alembic`` / ``sqlalchemy.engine`` do ``fileConfig(alembic.ini)`` dựng (handler
    console ra stderr): dòng log mang lỗi CSDL ⇒ chỉ còn tóm tắt."""
    r = f41[("log", "tran")]
    out = _f41_dau_ra(r, "log")
    lo = _f41_lo(out, "log")
    assert r.returncode != 0 and lo == [] and "DBError[" in out, (
        "logger của fileConfig lộ %s (rc=%s):\n%s" % (lo, r.returncode, out[-3000:]))


def test_v6_alembic_entrypoint_logger_filecfg_khong_lo(f41):
    r = f41[("log", "entrypoint")]
    out = _f41_dau_ra(r, "log")
    lo = _f41_lo(out, "log")
    assert r.returncode != 0 and lo == [] and "DBError[" in out, (
        "entrypoint: logger của fileConfig lộ %s (rc=%s):\n%s" % (lo, r.returncode, out[-3000:]))


def test_v6_cli_deploy_bat_ngoai_le_o_cua_ra():
    """Mỗi tiến trình dòng lệnh chạy lúc deploy / tạo container bắt ngoại lệ không bắt ở
    CỬA RA bằng ``thoat_cli_an_toan`` (in mô tả an toàn, thoát mã khác 0); ``alembic/env.py``
    còn phủ bộ che lên handler do ``fileConfig`` dựng."""
    import ast

    def goi(n, ten_ham):
        return isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Name) and n.func.id == ten_ham)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == ten_ham))

    def try_bat_o_cua_ra(khoi) -> bool:
        for n in khoi:
            if isinstance(n, ast.Try) and any(
                    any(goi(m, "thoat_cli_an_toan") for m in ast.walk(h)) for h in n.handlers):
                return True
        return False

    thieu = []
    for rel in _S6_CLI:
        cay = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        if rel == "alembic/env.py":
            than = cay.body
            ok = try_bat_o_cua_ra(than)
            # Thứ tự THỰC THI ở mức module — kể cả thân khối ``try`` của giai đoạn nạp cấu
            # hình (V6 vòng 7: fileConfig + phủ bộ che nằm TRONG cửa ra CLI).
            phang = [m for n in than for m in (n.body if isinstance(n, ast.Try) else [n])]
            vt_cfg = [i for i, n in enumerate(phang) if any(goi(m, "fileConfig") for m in ast.walk(n))]
            vt_che = [i for i, n in enumerate(phang)
                      if isinstance(n, ast.Expr) and goi(n.value, "gan_bo_che_moi_handler")]
            if not (vt_cfg and vt_che and min(vt_che) > max(vt_cfg)):
                thieu.append("%s: thiếu gan_bo_che_moi_handler() SAU fileConfig ở mức module" % rel)
        else:
            khoi_main = [n for n in cay.body if isinstance(n, ast.If)
                         and "__main__" in ast.unparse(n.test)]
            ok = bool(khoi_main) and try_bat_o_cua_ra(khoi_main[0].body)
        if not ok:
            thieu.append("%s: ngoại lệ không bắt KHÔNG qua thoat_cli_an_toan ở cửa ra" % rel)
    assert thieu == [], "\n".join(thieu)


# =============================================================================
# V6 vòng 7 — F41: lỗi CẤU HÌNH lúc nạp (import app.config) qua cửa ra CLI, mô tả của CHỦ
# SỞ HỮU lỗi cấu hình (app/utils/redact.py)
# =============================================================================
# ``app/config.py`` dựng ``Settings()`` ở mức module rồi ``raise e`` lại ``ValidationError``
# của pydantic — chữ lỗi chèn ``input_value=<giá trị đặt sai>``. Đo qua ĐÚNG đường thật
# (subprocess): Alembic CLI trần (= one-off deploy.sh Step 6), ``bash docker-entrypoint.sh``
# Gate 1, ``python -m app.scripts.sync_notification_rules`` trần (cutover tay) và qua
# entrypoint Gate 2 (``RUN_MIGRATIONS_ON_STARTUP=false`` — chế độ lùi ảnh). Hai lỗi giả: sai
# KIỂU (giá trị ngắn < 8 ký tự) và validator TỪ CHỐI một khoá bí mật (giá trị dài).
# DATABASE_URL trỏ một CSDL KHÔNG tồn tại + thư mục phiên bản RỖNG ⇒ kể cả khi lỗi cấu hình
# không xảy ra thì cũng không chạm CSDL nào (và điều kiện HẠ TẦNG dưới đây ĐỎ).

_V7_URL_GIA = "postgresql+asyncpg://gia_v7:GiaMk%40v7q@127.0.0.1:1/v7_cau_hinh_khong_ton_tai"
_V7_KICH_BAN = {
    # mã: (biến, giá trị GIẢ, chuỗi CẤM có mặt, dòng mô tả an toàn mong đợi ở cửa ra,
    #      mốc HẠ TẦNG chứng minh lỗi giả THẬT SỰ xảy ra, các đường áp dụng)
    "kieu": ("MAIL_PORT", "GiaCfg7", ("GiaCfg7", "GiaCfg", "input_value"),
             "MAIL_PORT: không phải số nguyên hợp lệ [int_parsing]",
             "CRITICAL [config.py]: Failed to initialize Settings", "*"),
    "bimat": ("PUBLIC_INTAKE_API_KEY", "GIA-KHOA-BI-MAT-V7-ngan",
              ("GIA-KHOA-BI-MAT-V7-ngan", "GIA-KHOA", "input_value"),
              "PUBLIC_INTAKE_API_KEY: validator từ chối giá trị [value_error]",
              "CRITICAL [config.py]: Failed to initialize Settings", "*"),
    # ``%`` trong DATABASE_URL (mật khẩu mã hoá URL, ``%40`` = ``@``): configparser của
    # ``set_main_option`` ném ``ValueError("invalid interpolation syntax in '<NGUYÊN URL>'…")``
    # — Settings dựng ĐƯỢC; chỉ Alembic gọi set_main_option.
    "url": ("DATABASE_URL", _V7_URL_GIA, ("GiaMk", "gia_v7:", "invalid interpolation syntax in '"),
            "ValueError — không in message", "set_main_option", "alembic"),
}
_V7_DUONG = ("alembic-tran", "alembic-entrypoint", "sync-tran", "sync-entrypoint")


def _v7_chay(tmp: Path, kb: str, duong: str) -> subprocess.CompletedProcess:
    import shutil

    bien, gia = _V7_KICH_BAN[kb][:2]
    thu_muc = tmp / ("%s-%s" % (kb, duong))
    (thu_muc / "versions").mkdir(parents=True)
    ini = (BACKEND / "alembic.ini").read_text(encoding="utf-8")
    assert "script_location = %(here)s/alembic" in ini, "HẠ TẦNG: alembic.ini đổi khuôn"
    ini = ini.replace(
        "script_location = %(here)s/alembic",
        "script_location = %s\nversion_locations = %s"
        % ((BACKEND / "alembic").as_posix(), (thu_muc / "versions").as_posix()))
    (thu_muc / "alembic.ini").write_text(ini, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "ALEMBIC_CONFIG": str(thu_muc / "alembic.ini"),
        "DATABASE_URL": _f41_url("v7_cau_hinh_khong_ton_tai"),
        "PYTHONIOENCODING": "utf-8",
        bien: gia,
    })
    if duong == "alembic-tran":
        alembic_bin = shutil.which("alembic")
        assert alembic_bin, "HẠ TẦNG: không thấy lệnh alembic"
        lenh = [alembic_bin, "upgrade", "head"]
    elif duong == "sync-tran":
        lenh = [sys.executable, "-m", "app.scripts.sync_notification_rules"]
    else:
        alembic_truoc = duong == "alembic-entrypoint"
        env["RUN_MIGRATIONS_ON_STARTUP"] = "true" if alembic_truoc else "false"
        env["RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP"] = "false" if alembic_truoc else "true"
        lenh = ["bash", str(BACKEND / "docker-entrypoint.sh"), "echo", "V6_KHONG_DUOC_TOI_DAY"]
    return subprocess.run(lenh, cwd=str(BACKEND), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=240, env=env)


@pytest.fixture(scope="module")
def f41cfg(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("v7_cau_hinh")
    return {(kb, d): _v7_chay(tmp, kb, d) for kb, v in _V7_KICH_BAN.items() for d in _V7_DUONG
            if v[5] == "*" or d.startswith(v[5])}


def _v7_vi_pham(f41cfg: dict, duong: str, ten: str) -> list:
    """Vi phạm (rỗng = đạt) của MỌI kịch bản trên một đường: rc ≠ 0; stdout + stderr KHÔNG
    chứa giá trị giả (cả tiền tố) lẫn ``input_value``; SAU dòng ``<ten>: THẤT BẠI`` của cửa ra
    CLI có dòng mô tả an toàn của chủ sở hữu lỗi cấu hình (vị trí + mã lỗi / chỉ tên lớp)."""
    sai = []
    for kb, (bien, gia, cam, dong, moc_ht, _) in _V7_KICH_BAN.items():
        if (kb, duong) not in f41cfg:
            continue
        r = f41cfg[(kb, duong)]
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        assert moc_ht in out, (
            "HẠ TẦNG: lỗi cấu hình giả (%s) không xảy ra trên %s:\n%s" % (kb, duong, out[-3000:]))
        lo = [v for v in cam if v in out]
        moc = ten + ": THẤT BẠI"
        sau = out.split(moc, 1)[1] if moc in out else ""
        # entrypoint chạy TIẾP sau bước hỏng = fail-open (cùng họ với rc = 0)
        chay_tiep = "V6_KHONG_DUOC_TOI_DAY" in out
        if r.returncode == 0 or chay_tiep or lo or dong not in sau:
            sai.append("[%s] lộ %s · rc=%s · chạy tiếp: %s · có dòng mô tả an toàn ở cửa ra: %s\n%s"
                       % (kb, lo, r.returncode, chay_tiep, dong in sau, out[-2500:]))
    return sai


def test_v7_alembic_cli_tran_loi_cau_hinh_khong_lo(f41cfg):
    """One-off ``alembic upgrade head`` (deploy.sh Step 6) với cấu hình hỏng lúc nạp."""
    sai = _v7_vi_pham(f41cfg, "alembic-tran", "alembic")
    assert sai == [], "alembic CLI — lỗi cấu hình lúc nạp:\n" + "\n".join(sai)


def test_v7_alembic_entrypoint_loi_cau_hinh_khong_lo(f41cfg):
    """``docker-entrypoint.sh`` Gate 1 (``alembic upgrade head`` lúc tạo container)."""
    sai = _v7_vi_pham(f41cfg, "alembic-entrypoint", "alembic")
    assert sai == [], "entrypoint Gate 1 — lỗi cấu hình lúc nạp:\n" + "\n".join(sai)


def test_v7_sync_rules_tran_loi_cau_hinh_khong_lo(f41cfg):
    """``python -m app.scripts.sync_notification_rules`` (cutover tay)."""
    sai = _v7_vi_pham(f41cfg, "sync-tran", "sync_notification_rules")
    assert sai == [], "sync_notification_rules — lỗi cấu hình lúc nạp:\n" + "\n".join(sai)


def test_v7_sync_rules_entrypoint_loi_cau_hinh_khong_lo(f41cfg):
    """``docker-entrypoint.sh`` Gate 2 khi Gate 1 tắt (``RUN_MIGRATIONS_ON_STARTUP=false``)."""
    sai = _v7_vi_pham(f41cfg, "sync-entrypoint", "sync_notification_rules")
    assert sai == [], "entrypoint Gate 2 — lỗi cấu hình lúc nạp:\n" + "\n".join(sai)


def test_v7_cli_nap_cau_hinh_trong_cua_ra():
    """Ở mỗi tiến trình dòng lệnh của ``_S6_CLI``: MỌI import ``app.*`` ở mức module (trừ hai
    chủ sở hữu không side effect) nằm trong một khối ``try`` mà nhánh bắt gọi
    ``thoat_cli_an_toan(…, bo_mo_ta=mo_ta_loi_an_toan)``. Riêng ``alembic/env.py``: câu lệnh
    THỰC THI ở mức module ngoài các khối cửa ra chỉ được là import / ``sys.path.*`` / định
    nghĩa hàm — thứ gì khác ném ra thì ra THÔ."""
    import ast

    chu = {"app.core.log_redaction", "app.utils.redact"}

    def cua_ra(n, can_bo_mo_ta: bool) -> bool:
        if not isinstance(n, ast.Try):
            return False
        for h in n.handlers:
            for m in ast.walk(h):
                if not (isinstance(m, ast.Call) and (
                        getattr(m.func, "id", None) == "thoat_cli_an_toan"
                        or getattr(m.func, "attr", None) == "thoat_cli_an_toan")):
                    continue
                if not can_bo_mo_ta or any(
                        k.arg == "bo_mo_ta" and isinstance(k.value, ast.Name)
                        and k.value.id == "mo_ta_loi_an_toan" for k in m.keywords):
                    return True
        return False

    def import_app(n) -> bool:
        if isinstance(n, ast.ImportFrom):
            ten = n.module or ""
            return (ten == "app" or ten.startswith("app.")) and ten not in chu
        if isinstance(n, ast.Import):
            return any((a.name == "app" or a.name.startswith("app.")) and a.name not in chu
                       for a in n.names)
        return False

    sai = []
    for rel in _S6_CLI:
        cay = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        for n in cay.body:
            if cua_ra(n, True):
                continue
            for m in (n.body if isinstance(n, ast.Try) else [n]):
                if import_app(m):
                    sai.append("%s:%d: import ứng dụng NGOÀI cửa ra nạp cấu hình: %s"
                               % (rel, m.lineno, ast.unparse(m)[:80]))
        if rel != "alembic/env.py":
            continue
        if not any(cua_ra(n, True) for n in cay.body):
            sai.append("%s: không có khối nạp cấu hình bắt về thoat_cli_an_toan(bo_mo_ta=…)" % rel)
        for n in cay.body:
            if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(n, ast.Try) and cua_ra(n, False):
                continue
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                continue
            if (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and ast.unparse(n.value.func).startswith("sys.path.")):
                continue
            sai.append("%s:%d: câu lệnh THỰC THI ngoài cửa ra CLI: %s"
                       % (rel, n.lineno, ast.unparse(n)[:80]))
    assert sai == [], "\n".join(sai)


# =============================================================================
# V6 vòng 8 — N17.14: lỗi cấu hình được che NGAY TẠI NGUỒN CHUNG (app/config.py) — đo
# qua TIẾN TRÌNH THẬT của production
# =============================================================================
# ``app/config.py`` từng ``raise e`` lại ``ValidationError`` thô (``input_value=``) ⇒ MỌI
# tiến trình import ``app.config`` in thô vào docker logs. Mỗi tiến trình dưới đây chạy với
# cấu hình GIẢ hỏng, CÓ HẠN; còn sống quá hạn = cấu hình lọt (tiến trình đã lên) hoặc treo ⇒
# ĐỎ. Dọn ĐÚNG nhóm tiến trình của lượt (``start_new_session`` ⇒ pgid = pid; giết cả nhóm sau
# khi xong — worker gunicorn / tiến trình con celery không mồ côi). Lệnh = lệnh của ảnh /
# compose production (Dockerfile CMD, ``command:`` của celery-worker / celery-beat).
#
# V6 vòng 8b (F44): MỖI ca chạy RIÊNG tiến trình của nó (không fixture module chạy nối tiếp
# cả năm trong setup ca đầu); hạn nội bộ ``_V8_HAN_S`` ≈ 10 s, nhỏ hơn RÕ ``--timeout=60``
# mỗi ca của CI (lượt bình thường: cả năm ≈ 3,9 s); quá hạn được xét TRƯỚC mọi điều kiện
# khác (kể cả mốc HẠ TẦNG "có dòng CRITICAL" — tiến trình treo bị SIGKILL có thể chưa xả bộ
# đệm stdout); giết nhóm + thu stdout/stderr đều CÓ HẠN. Ca xấu nhất mỗi test:
# ``_V8_HAN_S + 2 × _V8_HAN_DON_S`` = 20 s < 60 s ⇒ tiến trình treo đỏ TẠI khẳng định
# "quá hạn (còn sống)", không phải ERROR của pytest-timeout.

_V8_GIA = {"MAIL_PORT": "GiaCfg8", "PUBLIC_INTAKE_API_KEY": "GIA-KHOA-BI-MAT-V8-ngan"}
_V8_CAM = ("GiaCfg8", "GiaCfg", "GIA-KHOA-BI-MAT-V8-ngan", "GIA-KHOA", "input_value")
_V8_MO_TA = ("MAIL_PORT: không phải số nguyên hợp lệ [int_parsing]",
             "PUBLIC_INTAKE_API_KEY: validator từ chối giá trị [value_error]")
_V8_GUNICORN = ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
_V8_TIEN_TRINH = {
    "gunicorn": _V8_GUNICORN,
    "celery-worker": ["celery", "-A", "app.celery_app", "worker", "-Q", "default,celery",
                      "--loglevel=info", "--concurrency=2"],
    "celery-beat": ["celery", "-A", "app.celery_app", "beat", "--loglevel=info"],
    # cả HAI gate tắt ⇒ entrypoint đi thẳng tới ``exec gunicorn`` (chế độ của celery và của
    # backend khi lùi ảnh + tắt sync)
    "entrypoint-gunicorn": ["bash", "docker-entrypoint.sh"] + _V8_GUNICORN,
    # script vận hành thật (RUNBOOK STS20; mặc định DRY-RUN) import app.config ở mức module
    "script-backfill": [sys.executable, "scripts/backfill_sts20_giveup.py"],
}
_V8_HAN_S = 10        # hạn sống của tiến trình đo
_V8_HAN_DON_S = 5     # hạn thu đầu ra / gặt tiến trình SAU khi giết nhóm


def _v8_chu(x) -> str:
    if x is None:
        return ""
    return x.decode("utf-8", "replace") if isinstance(x, bytes) else x


def _v8_giet_nhom(pgid: int) -> None:
    import signal

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _v8_chay(ten: str) -> dict:
    env = dict(os.environ)
    env.update(_V8_GIA)
    env.update({
        "DATABASE_URL": _f41_url("v8_cau_hinh_khong_ton_tai"),
        "PYTHONIOENCODING": "utf-8",
        "RUN_MIGRATIONS_ON_STARTUP": "false",
        "RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP": "false",
    })
    p = subprocess.Popen(_V8_TIEN_TRINH[ten], cwd=str(BACKEND), env=env, start_new_session=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    het_gio = False
    thu_thieu = False
    try:
        out, err = p.communicate(timeout=_V8_HAN_S)
    except subprocess.TimeoutExpired:
        het_gio = True
        _v8_giet_nhom(p.pid)
        try:
            out, err = p.communicate(timeout=_V8_HAN_DON_S)
        except subprocess.TimeoutExpired as qh:
            # một tiến trình đã thoát khỏi nhóm vẫn giữ ống ⇒ KHÔNG chờ vô hạn
            thu_thieu = True
            out, err = _v8_chu(qh.output), _v8_chu(qh.stderr)
            for ong in (p.stdout, p.stderr):
                try:
                    ong.close()
                except OSError:
                    pass
    finally:
        _v8_giet_nhom(p.pid)  # dọn MỌI tiến trình còn lại của nhóm (worker gunicorn, con celery)
    try:
        p.wait(timeout=_V8_HAN_DON_S)
    except subprocess.TimeoutExpired:
        thu_thieu = True
    return {"rc": p.returncode, "het_gio": het_gio, "thu_thieu": thu_thieu,
            "out": _v8_chu(out) + "\n" + _v8_chu(err)}


def _v8_vi_pham(kq: dict) -> list:
    out = kq["out"]
    if kq["het_gio"]:  # xét TRƯỚC mọi điều kiện khác, kể cả mốc HẠ TẦNG bên dưới
        return ["quá hạn (còn sống) sau %d s — tiến trình KHÔNG dừng với cấu hình hỏng (đã giết "
                "cả nhóm%s)\n%s" % (_V8_HAN_S, "; KHÔNG thu hết đầu ra trong hạn" if kq["thu_thieu"]
                                    else "", out[-3000:])]
    assert "CRITICAL [config.py]: Failed to initialize Settings" in out, (
        "HẠ TẦNG: lỗi cấu hình giả không xảy ra:\n%s" % out[-3000:])
    lo = [v for v in _V8_CAM if v in out]
    # dòng của LỖI ném ra (không phải dòng CRITICAL) mang mô tả an toàn
    dong_loi = [d for d in out.splitlines() if "LoiCauHinh" in d and "CRITICAL [config.py]" not in d]
    co_mo_ta = any(all(m in d for m in _V8_MO_TA) for d in dong_loi)
    if kq["rc"] == 0 or lo or not co_mo_ta:
        return ["quá hạn (còn sống): False · rc=%s · lộ %s · có dòng lỗi mang mô tả an toàn: %s\n%s"
                % (kq["rc"], lo, co_mo_ta, out[-3000:])]
    return []


def test_v8_gunicorn_loi_cau_hinh_khong_lo():
    """``gunicorn app.main:app -c gunicorn.conf.py`` (CMD của ảnh backend)."""
    sai = _v8_vi_pham(_v8_chay("gunicorn"))
    assert sai == [], "gunicorn — lỗi cấu hình:\n" + "\n".join(sai)


def test_v8_celery_worker_loi_cau_hinh_khong_lo():
    """``celery -A app.celery_app worker …`` (command của celery-worker)."""
    sai = _v8_vi_pham(_v8_chay("celery-worker"))
    assert sai == [], "celery worker — lỗi cấu hình:\n" + "\n".join(sai)


def test_v8_celery_beat_loi_cau_hinh_khong_lo():
    """``celery -A app.celery_app beat …`` (command của celery-beat)."""
    sai = _v8_vi_pham(_v8_chay("celery-beat"))
    assert sai == [], "celery beat — lỗi cấu hình:\n" + "\n".join(sai)


def test_v8_entrypoint_tat_hai_gate_loi_cau_hinh_khong_lo():
    """``docker-entrypoint.sh`` với CẢ HAI gate tắt ⇒ ``exec gunicorn``."""
    sai = _v8_vi_pham(_v8_chay("entrypoint-gunicorn"))
    assert sai == [], "entrypoint (hai gate tắt) — lỗi cấu hình:\n" + "\n".join(sai)


def test_v8_script_that_loi_cau_hinh_khong_lo():
    """Script vận hành thật import ``app.config`` ở mức module."""
    sai = _v8_vi_pham(_v8_chay("script-backfill"))
    assert sai == [], "script backfill_sts20_giveup — lỗi cấu hình:\n" + "\n".join(sai)



# =============================================================================
# V6 vòng 6 — SMTP: error_reason của email_channel.execute_delivery chỉ giữ loại lỗi + mã SMTP
# =============================================================================
# ``error_message`` của ChannelResult đi vào cột ``error_reason`` (delivery_tasks,
# dispatcher). Chữ lỗi SMTP mang địa chỉ email (``SMTPRecipientsRefused`` in nguyên dict
# người nhận). Ghi chú: ``EmailService.send_email`` tự nuốt lỗi gửi (trả False ⇒ thông báo
# cố định); nhánh ``except`` ở ``execute_delivery`` nhận lỗi dựng nội dung, và lỗi SMTP nếu
# lớp dưới đổi — ca kiểm cho ``send_delivery_email`` ném thẳng để đo đúng nhánh ấy.


def _smtp_loi_mau() -> list:
    import smtplib

    return [
        smtplib.SMTPRecipientsRefused(
            {"gia991@example.invalid": (550, b"5.1.1 <gia991@example.invalid> user unknown")}),
        smtplib.SMTPSenderRefused(553, b"sender gia992@example.invalid rejected", "gia992@example.invalid"),
        smtplib.SMTPDataError(554, b"message for gia993@example.invalid refused"),
        smtplib.SMTPAuthenticationError(535, b"auth failed gia994@example.invalid"),
        smtplib.SMTPResponseException(452, b"mailbox gia995@example.invalid full"),
        smtplib.SMTPConnectError(421, b"busy gia996@example.invalid"),
        smtplib.SMTPServerDisconnected("closed while sending to gia997@example.invalid"),
        ConnectionRefusedError(111, "Connection refused gia998@example.invalid"),
        TimeoutError("timed out sending to gia999@example.invalid"),
        KeyError("gia990@example.invalid"),
    ]


def _smtp_chay_execute_delivery(loi: BaseException):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.services.notification_channels.email_channel import EmailChannel

    giao = SimpleNamespace(id=4242, user_id=None, destination="gia-nhan@example.invalid",
                           payload_snapshot={"title": "t", "message": "m", "type": "info"})
    with patch("app.services.email_service.email_service.send_delivery_email", side_effect=loi):
        return asyncio.run(EmailChannel().execute_delivery(giao, db=None))


def test_v6_smtp_error_reason_khong_mang_email():
    """``error_reason`` (qua ``ChannelResult.error_message``) KHÔNG mang địa chỉ email / chữ lỗi
    SMTP; CÓ loại lỗi, mã SMTP (nếu có) và delivery id."""
    sai = []
    for loi in _smtp_loi_mau():
        kq = _smtp_chay_execute_delivery(loi)
        em = kq.error_message or ""
        ma = getattr(loi, "smtp_code", None)
        if ma is None and getattr(loi, "recipients", None):
            ma = 550
        if ("@example.invalid" in em or type(loi).__name__ not in em or "delivery=4242" not in em
                or (isinstance(ma, int) and "smtp_code=%d" % ma not in em)):
            sai.append((type(loi).__name__, em))
    assert sai == [], "error_reason của lỗi SMTP sai khuôn / mang email: %s" % sai


def test_v6_smtp_phan_loai_retry_dead_letter_khong_doi():
    """Bảng lỗi SMTP → nhánh của ``delivery_tasks._is_permanent_error`` (dead-letter hay thử
    lại): giá trị MỚI phải cho CÙNG nhánh với giá trị CŨ (``str(e)``) — đổi khuôn chữ không
    được đổi cách xử lý."""
    from app.tasks.delivery_tasks import _is_permanent_error

    lech = []
    for loi in _smtp_loi_mau():
        moi = _smtp_chay_execute_delivery(loi).error_message
        if _is_permanent_error(moi) != _is_permanent_error(str(loi)):
            lech.append((type(loi).__name__, _is_permanent_error(str(loi)), _is_permanent_error(moi)))
    assert lech == [], "phân loại retry/dead-letter đổi (loại, cũ, mới): %s" % lech



def test_v6_smtp_dong_log_khong_mang_chu_loi_smtp():
    """Anh em của ``error_reason`` (§6): dòng LOG của ``execute_delivery`` và của
    ``EmailService.send_email`` (đường lỗi SMTP THẬT — send_email tự nuốt lỗi gửi) ghi
    ``error=`` chỉ loại + mã. ``capture_logs`` lấy giá trị TRƯỚC mọi processor — tức đúng
    thứ mã nguồn đưa cho logger, không nhờ tầng che nào."""
    import smtplib
    from unittest.mock import patch

    import structlog

    from app.services.email_service import email_service

    sai = []
    for loi in _smtp_loi_mau():
        with structlog.testing.capture_logs() as cap:
            _smtp_chay_execute_delivery(loi)
        sai += [("execute_delivery", type(loi).__name__, d.get("error")) for d in cap
                if "@example.invalid" in str(d.get("error", ""))]
    loi_gui = smtplib.SMTPRecipientsRefused(
        {"gia981@example.invalid": (550, b"5.1.1 <gia981@example.invalid> user unknown")})
    with patch.object(email_service, "smtp_user", "gia-user"), \
            patch.object(email_service, "smtp_password", "gia-mat-khau"), \
            patch.object(email_service, "_create_connection", side_effect=loi_gui), \
            structlog.testing.capture_logs() as cap:
        assert email_service.send_email("gia-nhan@example.invalid", "t", "<p>h</p>", "h") is False
    sai += [("send_email", d.get("event"), d.get("error")) for d in cap
            if "@example.invalid" in str(d.get("error", ""))]
    assert cap, "HẠ TẦNG: send_email không ghi dòng log nào"
    assert sai == [], "dòng log ghi chữ lỗi SMTP (mang email): %s" % sai
