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
    out = _co_dau_do(web, "Unhandled exception: ValueError: loi khi ghi: DBError[")
    assert "Gia Mo" not in out, "generic handler: lỗi bọc lỗi CSDL ngắn lộ"


def test_v5_ban_cat_cua_str_loi(web):
    v = _truong(web, "V5T", "error")
    assert _la_tom_tat(v) and "Gia Nam" not in v, "bản CẮT str(e)[:9] lộ: %r" % v


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
    """Thông điệp nghiệp vụ cho NGƯỜI DÙNG không bị che nhầm (không regex)."""
    from app.core.log_redaction import chu_loi_an_toan

    loi = ValueError("Email gia@example.invalid khong hop le")
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
    "log_dispatch_failure",
}
#: Hàm chuyển đổi — tự nó không phải lối ra; kết quả đi đâu thì lối ra ở đó.
_S6_TRUNG_TINH = {"str", "repr", "len", "getattr", "format"}
#: Lời gọi log/in — thuộc tầng che log, không phải lối ra ở đây.
_S6_LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log",
           "_log_warning", "print"}
#: Lối ra ĐÃ RÀ, KHÔNG mang lỗi CSDL — (tệp, hàm bao, loại): (số chỗ, lý do).
_S6_MIEN = {
    ("app/gateways/zalo.py", "_call_template_api", "return"): (1, "lỗi HTTP của Zalo API, khối try không chạm CSDL"),
    ("app/gateways/zalo_bot.py", "send_message", "return"): (1, "đã qua _safe_error_message; lỗi HTTP Zalo Bot"),
    ("app/routers/monitoring.py", "get_notification_metrics", "gan"): (1, "lỗi Redis (safe_redis_*), không CSDL"),
    ("app/routers/monitoring.py", "get_system_overview", "gan"): (3, "Redis / Celery / Socket.IO — nhánh CSDL đã qua chu_loi_an_toan"),
    ("app/services/notification_channels/email_channel.py", "execute_delivery", "return"): (1, "lỗi SMTP"),
    ("app/services/notification_channels/email_channel.py", "send", "return"): (1, "lỗi SMTP"),
    ("app/services/notification_rule_loader.py", "get_rule_for_event", "raise"): (1, "lỗi kiểm cấu hình recipient_config (pydantic)"),
    ("app/services/payment_import_service.py", "parse_template", "raise"): (1, "lỗi đọc tệp Excel tải lên"),
    ("app/services/sms_contact_service.py", "_parse_rows", "raise"): (1, "lỗi đọc tệp CSV tải lên"),
    ("app/services/session_service.py", "revoke_session", "raise"): (1, "chữ lỗi chỉ ở context — context KHÔNG bao giờ ra phản hồi (exception_handlers)"),
    ("app/services/user_service.py", "invalidate_all_sessions", "raise"): (2, "lỗi Redis; chữ lỗi chỉ ở context"),
    ("app/tasks/utils.py", "_runner", "gan"): (1, "giữ ĐỐI TƯỢNG ngoại lệ để ném lại ở luồng gọi"),
}


def _s6_quet() -> dict:
    """Mọi lối ra NGOÀI log của chữ ngoại lệ trong ``except`` có thể bắt lỗi CSDL."""
    import ast
    from collections import Counter

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

    dem = Counter()
    goc = BACKEND / "app"
    for p in sorted(goc.rglob("*.py")):
        rel = p.relative_to(BACKEND).as_posix()
        if "/scripts/" in rel or "__pycache__" in rel:
            continue
        cay = ast.parse(p.read_text(encoding="utf-8"))
        cha = {c: n for n in ast.walk(cay) for c in ast.iter_child_nodes(n)}
        for h in ast.walk(cay):
            if not isinstance(h, ast.ExceptHandler) or not h.name or not (kieu(h.type) & _S6_KIEU):
                continue
            bao = h
            while bao in cha and not isinstance(bao, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bao = cha[bao]
            ten_bao = getattr(bao, "name", "<module>")
            than = ast.Module(body=h.body, type_ignores=[])
            nhiem = {h.name}
            for _ in range(3):  # lan truyền qua biến cục bộ (error_msg = str(e.orig) …)
                for n in ast.walk(than):
                    if isinstance(n, ast.Assign) and lo(n.value, nhiem):
                        nhiem |= {t.id for t in n.targets if isinstance(t, ast.Name)}
            bo_qua = {id(m) for n in ast.walk(than)
                      if isinstance(n, ast.Call) and ten(n.func) in _S6_LOG for m in ast.walk(n)}
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
                    dem[(rel, ten_bao, loai)] += 1
    return dict(dem)


def test_v5_khong_dua_chu_loi_csdl_ra_ngoai_log():
    """§6 (vòng 5): chữ ngoại lệ trong ``except`` có thể bắt lỗi CSDL KHÔNG được đi ra
    phản hồi HTTP / cột CSDL / danh sách trả về mà không qua ``chu_loi_an_toan``
    (hoặc ``mo_ta_loi``). Lối ra đã rà và KHÔNG mang lỗi CSDL nằm ở ``_S6_MIEN`` kèm
    lý do — khoá HAI chiều: chỗ mới chưa rà ⇒ ĐỎ; chỗ miễn đã biến mất ⇒ ĐỎ (dọn)."""
    thuc = _s6_quet()
    mong = {k: v[0] for k, v in _S6_MIEN.items()}
    moi = {k: n for k, n in thuc.items() if mong.get(k) != n}
    cu = {k: n for k, n in mong.items() if thuc.get(k) != n}
    assert not moi and not cu, (
        "lối ra chữ ngoại lệ CHƯA rà (bọc bằng chu_loi_an_toan, hoặc thêm vào _S6_MIEN kèm lý do "
        "nếu chắc chắn không mang lỗi CSDL): %s\nmiễn trừ không còn khớp: %s" % (moi, cu))
