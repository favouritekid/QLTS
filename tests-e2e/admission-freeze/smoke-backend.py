"""Smoke A — HTTP thật vào backend thật, KHÔNG chạm bất kỳ dịch vụ nào đang chạy.

Bản đầu của script này KHÔNG cô lập và tôi đã ghi sai là "không đụng stack
dev/prod". Ba đường rò, tất cả đều im lặng:

  1. ``docker compose run`` chỉ thay CMD, KHÔNG thay ``ENTRYPOINT`` — nên
     ``docker-entrypoint.sh`` vẫn chạy ``alembic upgrade head`` (DDL) và
     ``sync_notification_rules`` (ghi) lên CSDL dev.
  2. uvicorn mặc định chạy lifespan, mà lifespan ``create_all`` bảng Casbin và
     có thể nạp policy — lại là ghi.
  3. ``--no-deps`` chỉ không KHỞI ĐỘNG dependency; container vẫn có interface
     mạng. Qua ``docker compose run`` đó là mạng compose và chạm thẳng được
     postgres/redis; qua ``docker run`` trần thì là bridge mặc định — tên dịch
     vụ không phân giải nhưng egress vẫn mở.

Bản này đóng cả ba, và **đo** việc đóng thay vì tuyên bố:

  - ``--network none``        ⇒ container không có mạng nào ngoài loopback.
  - ``--entrypoint python``   ⇒ không alembic, không sync.
  - ``uvicorn --lifespan off`` ⇒ không Casbin ``create_all``, không socket worker.
  - env đều là giá trị giả ⇒ không mang theo secret thật nào.

``_bat_buoc_co_lap()`` chạy TRƯỚC khi dựng server và chỉ chấp nhận cấu hình
CHỨNG MINH ĐƯỢC: hai DSN phải khớp NGUYÊN VĂN sentinel, ``ADMISSION_FROZEN``
phải thuộc {"true","false"}, và container phải KHÔNG có interface nào ngoài
loopback. Vế cuối là phép đo trực tiếp của ``--network none`` — không tin cờ,
đo hệ quả. (Bản trước hỏi DNS tên dịch vụ; xem ``_giao_dien_ngoai_loopback()``
để biết vì sao phép ấy chưa bao giờ phát hiện được việc bỏ cờ.)

Chạy bằng ``run-smoke-backend.sh`` để không sót cờ nào.

Vì CSDL cố ý không tới được, các đường KHÔNG bị đóng băng có thể trả 5xx thay
vì 401/403. Điều đó không sao: bất biến duy nhất cần đo ở đây là
"tầng freeze có chặn hay không", tức **có phải 503 kèm code ADMISSION_FROZEN**.
"""
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Hai DSN sentinel DUY NHẤT được chấp nhận. Không suy diễn, không parse: bất kỳ
# giá trị nào khác — kể cả một DSN trỏ CSDL thật đang tạm không nghe — đều bị
# từ chối. Bản trước parse host/port rồi thử kết nối, nên URL rỗng hoặc không
# parse được cho ``host=None`` ⇒ "không nghe" ⇒ bị coi là ĐÃ cô lập.
SENTINEL_DB = "postgresql+asyncpg://smoke:smoke@127.0.0.1:1/smoke"
SENTINEL_REDIS = "redis://127.0.0.1:1/0"

CHO = os.environ.get("ADMISSION_FROZEN", "")
BASE = "http://127.0.0.1:8099"

# (method, path, có-phải-đường-ghi-tuyển-sinh)
CA = [
    ("POST", "/api/v2/admissions/1/choices", True),
    ("POST", "/api/v2/admissions/1/admin-rollback", True),
    ("PATCH", "/api/v2/admissions/1/priority-objects/DT01/verify", True),
    ("POST", "/api/v2/admin/rounds/1/extend", True),
    ("POST", "/api/v2/admin/years/2026/rounds", True),
    ("POST", "/api/v2/admin/priority-config/clone", True),
    ("PATCH", "/api/v2/admin/admission-paths/1/quota", True),
    ("POST", "/api/v2/admin/admission-backfill-exceptions/bulk-resolve", True),
    ("POST", "/api/v2/admin/path-subject-group-configs/1/items", True),
    ("DELETE", "/api/v2/admin/path-subject-group-configs/1/items/2", True),
    ("POST", "/api/v2/admissions/magic-link/confirm/tok", True),
    # v1 — không được hồi quy
    ("POST", "/api/admissions", True),
    ("POST", "/api/admission-config/methods", True),
    # Đọc phải đi tiếp kể cả khi đóng băng
    ("GET", "/api/v2/admissions/1/choices", False),
    ("GET", "/api/admissions", False),
    # Ngoài miền tuyển sinh — không được chạm
    ("POST", "/api/leads", False),
    ("POST", "/api/v2/admin/casbin/reload", False),
    ("PATCH", "/api/v2/admin/system-config/x", False),
    ("POST", "/api/v2/admin/vn-school/schools", False),
    # Khớp theo ĐOẠN path, không phải startswith
    ("POST", "/api/admissionsfoo", False),
    ("POST", "/api/v2/admin/roundsfoo", False),
]


def _phai_bang(ten, mong):
    thuc = os.environ.get(ten)
    if thuc != mong:
        return "%s = %r, phai la sentinel %r" % (ten, thuc, mong)
    return None


def _giao_dien_ngoai_loopback():
    """Danh sách interface KHÁC loopback. Không liệt kê được thì NÉM, không đoán.

    Bản trước hỏi "tên dịch vụ compose có phân giải được không" và coi câu trả
    lời "không" là bằng chứng chỉ có loopback. Sai: trên **bridge mặc định**
    của Docker không có DNS nội bộ cho tên dịch vụ, nên ba tên ấy KHÔNG phân
    giải trong khi container vẫn có ``eth0`` và ra ngoài được. Đã đo:

        docker run --network none …  ->  ['lo']          · DNS postgres: không
        docker run              …    ->  ['lo', 'eth0']  · DNS postgres: không

    Hai trạng thái khác hẳn nhau mà phép cũ cho cùng một kết luận, nên nó chưa
    bao giờ phát hiện được việc bỏ ``--network none``.

    Bản trước chỉ kiểm rỗng BÊN TRONG nhánh ``except``. Nếu
    ``if_nameindex()`` trả ``[]`` mà KHÔNG ném thì hàm về thẳng ``[]``, và
    ``[]`` bị đọc là "không có interface ngoài loopback" ⇒ cho chạy — đúng cái
    ngược lại với cam kết "không liệt kê được thì thoát 3". Mọi container thật
    luôn có ít nhất ``lo``, nên danh sách rỗng LUÔN nghĩa là không liệt kê
    được, bất kể nó đến từ ngoại lệ hay từ giá trị trả về.
    """
    ten = []
    try:
        ten = [n for _, n in socket.if_nameindex()]
    except (AttributeError, OSError):
        # API không dùng được ⇒ thử nguồn thứ hai.
        try:
            with io.open("/proc/net/dev", encoding="utf-8") as f:
                for dong in f.read().split(chr(10))[2:]:
                    if ":" in dong:
                        ten.append(dong.split(":")[0].strip())
        except OSError:
            ten = []

    # Kiểm rỗng SAU cả hai đường. Mọi container thật luôn có ít nhất ``lo``,
    # nên danh sách rỗng LUÔN nghĩa là không liệt kê được — bất kể nó đến từ
    # ngoại lệ hay từ giá trị trả về. Không suy ra "chỉ có loopback".
    if not ten:
        raise RuntimeError(
            "khong liet ke duoc interface mang: danh sach rong. Moi container "
            "that luon co it nhat 'lo', nen day KHONG phai bang chung chi co "
            "loopback."
        )

    return sorted(x for x in ten if x != "lo")


def _bat_buoc_co_lap():
    """Fail-closed. Chỉ chấp nhận cấu hình CHỨNG MINH ĐƯỢC là an toàn.

    Bản trước chấp nhận ba trạng thái không chứng minh được gì:

      - ``DATABASE_URL`` rỗng/không parse được ⇒ ``host=None`` ⇒ "không nghe"
        ⇒ tưởng là đã cô lập.
      - CSDL production tạm thời không nghe cũng cho ra cùng kết luận.
      - ``ADMISSION_FROZEN`` thiếu ⇒ ``"?"`` ⇒ xử như TẮT ⇒ smoke xanh trong
        khi không đo gì về trạng thái đóng băng cả.

    Nay: khớp NGUYÊN VĂN hai sentinel, cờ phải thuộc {"true","false"}, và
    container phải KHÔNG có interface nào ngoài loopback. Vế cuối mới là phép
    đo trực tiếp của ``--network none`` — phép hỏi-DNS trước đó không phải, vì
    bridge mặc định cũng không phân giải tên dịch vụ.
    """
    loi = [x for x in (
        _phai_bang("DATABASE_URL", SENTINEL_DB),
        _phai_bang("REDIS_URL", SENTINEL_REDIS),
    ) if x]

    if CHO not in ("true", "false"):
        loi.append('ADMISSION_FROZEN = %r, phai la "true" hoac "false"' % CHO)

    try:
        ngoai = _giao_dien_ngoai_loopback()
    except Exception as e:                       # không chứng minh được ⇒ từ chối
        loi.append("khong liet ke duoc interface mang (%s)" % e)
    else:
        if ngoai:
            loi.append(
                "container VAN CO MANG: interface ngoai loopback %s — chay lai "
                "voi --network none (dung run-smoke-backend.sh)" % ngoai
            )

    if loi:
        print("HARNESS KHONG CO LAP, TU CHOI DO:")
        for x in loi:
            print("   - " + x)
        print("Dung tests-e2e/admission-freeze/run-smoke-backend.sh de khoi sot co.")
        sys.exit(3)
    print("--- co lap: sentinel DSN khop, co ADMISSION_FROZEN=%s, "
          "chi co interface loopback" % CHO)


def goi(method, path):
    req = urllib.request.Request(
        BASE + path, method=method, data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(400).decode("utf-8", "replace")


_bat_buoc_co_lap()

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "127.0.0.1", "--port", "8099",
     "--lifespan", "off",            # không Casbin create_all, không socket worker
     "--log-level", "warning"],
    cwd="/app",
)
try:
    san_sang = False
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
                if r.status == 200:
                    san_sang = True
                    break
        except Exception:
            time.sleep(1)
    if not san_sang:
        print("KHONG DUNG DUOC UVICORN — khong ket luan gi")
        sys.exit(3)

    print("=== ADMISSION_FROZEN=%s ===" % CHO)
    loi = 0
    for method, path, la_ghi in CA:
        ma, than = goi(method, path)
        phai_chan = CHO == "true" and la_ghi
        if phai_chan:
            dat = ma == 503
            if dat:
                try:
                    dat = json.loads(than).get("code") == "ADMISSION_FROZEN"
                except Exception:
                    dat = False
            mong = "503 + code=ADMISSION_FROZEN"
        else:
            dat = ma != 503
            mong = "khac 503"
        print("  %-6s %-62s -> %-3s  %s"
              % (method, path, ma, "DAT" if dat else "LECH (mong %s)" % mong))
        if not dat:
            loi += 1
    print("=== LECH: %d/%d ===" % (loi, len(CA)))
    sys.exit(1 if loi else 0)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
