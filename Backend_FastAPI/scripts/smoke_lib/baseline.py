"""Baseline + cleanup cho lượt smoke: dump trước pack, restore sau pack.

Vì sao KHÔNG dọn theo hàng
--------------------------
`admission_profile_id` chỉ là **ranh giới sở hữu**, không phải khoá xoá:
`payment`/`payment_transaction`/`refund_request` có nhiều cạnh RESTRICT;
`audit_log` và `notification` trỏ bằng `entity_id`/`source_id` **không có FK**;
commission/accounting/config nằm ngoài cây profile. Xoá gốc nghĩa là hoặc bỏ
sót, hoặc xoá lan sang miền Admissions. Nên cleanup đi bằng đường thô mà chắc:
**drop + restore một database dùng riêng**.

Bốn hàng rào, theo đúng thứ tự
------------------------------
1. `kiem_moi_truong` — trước MỌI mutation.
2. `kiem_danh_tinh` — đúng server, đúng container, đúng project. Tên database
   **không** nhận diện được đích: một server khác vẫn có thể có database tên
   `qlts_smoke`. Khoá bằng compose project + container id + `system_identifier`
   của cụm PostgreSQL, và mọi lệnh trong lượt phải đi qua **cùng một** container.
3. `kiem_archive` — trước khi drop. Không đủ nếu chỉ xem magic header: một blob
   `PGDMP` + rác vẫn khớp header mà `pg_restore` không đọc nổi. Archive phải qua
   `pg_restore --list` và TOC phải chứa `alembic_version` cùng các bảng trọng yếu.
4. `kiem_sau_restore` — vân tay phải khớp baseline, và bản thân vân tay phải
   **đủ hình dạng** mới được coi là hợp lệ: thiếu bảng, trùng bảng, dòng rác hay
   tập rỗng đều là HỎNG. `{} == {}` không bao giờ được tính là PASS.

Mọi định danh (user, tên bảng) đi vào SQL đều qua allowlist — `shell=False`
ngăn shell injection, không ngăn SQL injection.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set

# Database DUY NHẤT được phép drop/restore. Đóng cứng, không đọc từ môi trường.
_DB_DUY_NHAT = "qlts_smoke"
# Compose project DUY NHẤT được phép. Cùng lý do.
_PROJECT_DUY_NHAT = "qltssmoke"

_MA_PGDMP = b"PGDMP"

# Định danh SQL chỉ được lấy từ allowlist. Không escape, không quote động —
# nếu một tên không có ở đây thì đó là lỗi lập trình, không phải dữ liệu.
USER_CHO_PHEP: Set[str] = {"qlts"}
_RE_DINH_DANH = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Allowlist môi trường. `development` là giá trị duy nhất mà dev stack đặt.
APP_ENV_CHO_PHEP: Set[str] = {"development"}

# Service DUY NHẤT được phép nhận lệnh psql/pg_dump. Nhãn `project` thôi không
# đủ: mọi container trong cùng compose project đều mang nhãn ấy, kể cả backend.
_SERVICE_DUY_NHAT = "postgres"

# Schema mà mọi bảng trọng yếu phải thuộc về.
_SCHEMA_BAT_BUOC = "public"

# Bảng bắt buộc phải có trong TOC của archive. Thiếu một cái nghĩa là bản dump
# không phải của lược đồ này — restore sẽ cho một database "thành công" mà rỗng
# đúng chỗ quan trọng nhất.
BANG_TRONG_YEU: Sequence[str] = (
    "alembic_version",
    "admission_profile",
    "fee",
    "invoice",
    "payment",
    "payment_transaction",
    # Bốn bảng dưới đây là của đúng những pack sắp chạy (FIN-10..14, FIN-24).
    # Thiếu chúng trong archive nghĩa là baseline không phủ được thứ pack sẽ
    # đụng tới — restore sẽ "thành công" mà nền thì sai.
    "refund_request",
    "overpayment_record",
    "payment_intent",
    "payment_import_batch",
)


class ChanLai(RuntimeError):
    """Một hàng rào đã chặn. Không có nhánh nào đi tiếp."""


# =============================================================================
# Hàng rào 1 — môi trường
# =============================================================================
def kiem_dich(ten_db: str) -> None:
    if ten_db != _DB_DUY_NHAT:
        raise ChanLai(
            f"đích {ten_db!r} không phải {_DB_DUY_NHAT!r}. Module này drop toàn "
            "bộ database — trỏ nhầm là mất sạch dữ liệu của đích đó."
        )


def kiem_user(user: str) -> str:
    if user not in USER_CHO_PHEP:
        raise ChanLai(
            f"user {user!r} không nằm trong allowlist {sorted(USER_CHO_PHEP)}. "
            "Định danh đi vào SQL phải đến từ allowlist; `shell=False` chặn "
            "shell injection chứ không chặn SQL injection."
        )
    return user


def kiem_ten_bang(ten: str) -> str:
    if not _RE_DINH_DANH.fullmatch(ten):
        raise ChanLai(f"tên bảng {ten!r} không hợp lệ")
    return ten


def kiem_moi_truong(
    *, app_env: str, ten_db: str, moi_truong: Optional[Mapping[str, str]] = None
) -> None:
    """Chặn trước MỌI mutation.

    ⚠️ Cố ý dùng **allowlist**, không phải blocklist. Bản đầu chỉ cấm
    `production`/`prod`, nên `APP_ENV=""` (biến chưa đặt), `staging`, `local`
    hay một tên viết sai đều đi lọt — với một công cụ DROP DATABASE thì "không
    nhận ra là production" không đủ, phải "chắc chắn là development".
    """
    env = dict(os.environ if moi_truong is None else moi_truong)
    if (app_env or "").strip().lower() not in APP_ENV_CHO_PHEP:
        raise ChanLai(
            f"APP_ENV={app_env!r} không nằm trong allowlist "
            f"{sorted(APP_ENV_CHO_PHEP)}. Công cụ này DROP database — một giá "
            "trị lạ hay rỗng phải là dừng, không phải mặc định cho qua."
        )
    kiem_dich(ten_db)
    if env.get("SMOKE_ALLOW_DESTRUCTIVE") != "1":
        raise ChanLai(
            "thiếu SMOKE_ALLOW_DESTRUCTIVE=1. Lệnh này DROP database; cờ phải do "
            "người chạy đặt tường minh cho từng lượt."
        )


# =============================================================================
# Hàng rào 2 — danh tính đích
# =============================================================================
def kiem_danh_tinh(
    *,
    project: str,
    container_id: str,
    nhan_container: Mapping[str, str],
    system_identifier: str,
    danh_tinh_baseline: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Khoá đích bằng bốn dấu, không phải bằng tên database.

    `danh_tinh_baseline` là danh tính đã ghi lúc tạo baseline. Truyền vào ở các
    bước sau để bắt ca đổi container giữa chừng — đúng ca mà "cùng tên database"
    không phát hiện nổi.
    """
    if project != _PROJECT_DUY_NHAT:
        raise ChanLai(
            f"compose project {project!r} không phải {_PROJECT_DUY_NHAT!r}"
        )
    nhan_project = nhan_container.get("com.docker.compose.project", "")
    if nhan_project != _PROJECT_DUY_NHAT:
        raise ChanLai(
            f"container {container_id[:12]} mang nhãn project {nhan_project!r} — "
            f"không thuộc {_PROJECT_DUY_NHAT!r}. Đây đúng là ca một container "
            "khác có database trùng tên."
        )
    nhan_service = nhan_container.get("com.docker.compose.service", "")
    if nhan_service != _SERVICE_DUY_NHAT:
        raise ChanLai(
            f"container {container_id[:12]} là service {nhan_service!r}, không "
            f"phải {_SERVICE_DUY_NHAT!r}. Nhãn `project` KHÔNG đủ để nhận diện: "
            "backend, frontend và postgres đều mang cùng nhãn project, mà lệnh "
            "psql/pg_dump chỉ được gửi tới đúng container database."
        )
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id or ""):
        raise ChanLai(f"container id không hợp lệ: {container_id!r}")
    if not re.fullmatch(r"\d{6,25}", system_identifier or ""):
        raise ChanLai(
            f"system_identifier không hợp lệ: {system_identifier!r} — đây là số "
            "nhận dạng cụm PostgreSQL, lấy từ `pg_control_system()`"
        )

    danh_tinh = {
        "project": project,
        "container_id": container_id,
        "system_identifier": system_identifier,
    }
    if danh_tinh_baseline is not None:
        for khoa in ("project", "container_id", "system_identifier"):
            cu, moi = danh_tinh_baseline.get(khoa), danh_tinh[khoa]
            if cu != moi:
                raise ChanLai(
                    f"danh tính đích ĐÃ ĐỔI giữa chừng: {khoa} {cu!r} → {moi!r}. "
                    "Bản dump và database đang không còn thuộc cùng một cụm."
                )
    return danh_tinh


# =============================================================================
# Hàng rào 3 — archive phải dùng được
# =============================================================================
def sha256_tep(duong: Path) -> str:
    h = hashlib.sha256()
    with open(duong, "rb") as f:
        for khoi in iter(lambda: f.read(1024 * 1024), b""):
            h.update(khoi)
    return h.hexdigest()


def kiem_header(duong: Path, sha_mong_doi: Optional[str] = None) -> str:
    """Phép kiểm RẺ, chạy trước — nhưng KHÔNG đủ để restore."""
    if not duong.is_file():
        raise ChanLai(f"không thấy bản dump {duong} — KHÔNG được drop database")
    if duong.stat().st_size == 0:
        raise ChanLai(f"bản dump {duong} RỖNG — KHÔNG được drop database")
    with open(duong, "rb") as f:
        if f.read(len(_MA_PGDMP)) != _MA_PGDMP:
            raise ChanLai(
                f"{duong} không phải archive `pg_dump -Fc` (thiếu header PGDMP). "
                "Tệp khác rỗng vẫn có thể là thông báo lỗi bị chuyển hướng vào đây."
            )
    sha = sha256_tep(duong)
    if sha_mong_doi is not None and sha != sha_mong_doi:
        raise ChanLai(
            f"checksum lệch: {sha[:12]}… ≠ baseline {sha_mong_doi[:12]}…. "
            "Bản dump đã đổi kể từ lúc ghi baseline — không restore mù."
        )
    return sha


def phan_tich_toc(dau_ra_pg_restore_list: str) -> Set[str]:
    """Rút tên bảng **có dữ liệu** ở schema `public` từ `pg_restore --list`.

    Dòng TOC có hai dạng đáng phân biệt:

        215; 1259 16409 TABLE      public payment qlts   ← chỉ ĐỊNH NGHĨA bảng
        3402; 0 16409 TABLE DATA   public payment qlts   ← có DỮ LIỆU

    Bản đầu khớp `TABLE\\s+(\\S+)\\s+(\\S+)` rồi lấy nhóm thứ hai, nên
    `TABLE evil payment` (schema `evil`) được đếm như bảng `payment` — một
    archive của lược đồ khác vẫn qua được hàng rào. Nay khoá cứng schema, và
    **đòi `TABLE DATA`**: một archive chỉ có định nghĩa bảng sẽ restore ra một
    database đủ bảng mà rỗng sạch, tức đúng thứ mà cleanup phải phát hiện.
    """
    ten: Set[str] = set()
    mau = re.compile(
        r"^\s*\d+;\s+\d+\s+\d+\s+TABLE\s+DATA\s+"
        rf"{re.escape(_SCHEMA_BAT_BUOC)}\s+(\w+)\b"
    )
    for dong in dau_ra_pg_restore_list.splitlines():
        if dong.lstrip().startswith(";"):
            continue
        khop = mau.match(dong)
        if khop:
            ten.add(khop.group(1))
    return ten


def kiem_archive(
    *,
    duong: Path,
    dau_ra_pg_restore_list: str,
    ma_thoat_pg_restore_list: int,
    sha_mong_doi: Optional[str] = None,
    bang_bat_buoc: Sequence[str] = BANG_TRONG_YEU,
) -> str:
    """Hàng rào ĐẦY ĐỦ: header + `pg_restore --list` đọc được + TOC đủ bảng.

    Một blob `PGDMP` + rác vượt qua được `kiem_header` nhưng chết ở đây — và đó
    chính là khoảng cách giữa "tệp trông như dump" và "dump dùng được".
    """
    sha = kiem_header(duong, sha_mong_doi)

    if ma_thoat_pg_restore_list != 0:
        raise ChanLai(
            f"`pg_restore --list` thoát {ma_thoat_pg_restore_list} trên {duong} — "
            "archive hỏng hoặc không đọc được. KHÔNG được drop database."
        )
    if not (dau_ra_pg_restore_list or "").strip():
        raise ChanLai(
            f"`pg_restore --list` không in gì cho {duong} — archive rỗng nội dung"
        )

    co = phan_tich_toc(dau_ra_pg_restore_list)
    thieu = [t for t in bang_bat_buoc if t not in co]
    if thieu:
        raise ChanLai(
            f"TOC của {duong} thiếu bảng trọng yếu: {thieu}. Restore sẽ cho một "
            "database 'thành công' mà rỗng đúng chỗ quan trọng nhất."
        )
    return sha


# =============================================================================
# Dựng lệnh — tách khỏi thực thi để test được mà không cần database
# =============================================================================
def lenh_dump(*, ten_db: str, user: str, duong_trong_container: str) -> List[str]:
    kiem_dich(ten_db)
    kiem_user(user)
    return [
        "pg_dump", "-Fc", "--no-owner", "--no-privileges",
        "-U", user, "-d", ten_db, "-f", duong_trong_container,
    ]


def lenh_liet_ke(*, duong_trong_container: str) -> List[str]:
    return ["pg_restore", "--list", duong_trong_container]


def lenh_sha256_trong_container(*, duong_trong_container: str) -> List[str]:
    """Hash **chính tệp mà `pg_restore` sẽ đọc**.

    Checksum tính trên host chỉ chứng minh tệp trên host còn nguyên. Nhưng
    `pg_restore` đọc bản đã `docker cp` vào container — hai tệp khác nhau. Một
    archive khác (TOC vẫn hợp lệ) nằm sẵn ở `/tmp/<run>.dump` trong container sẽ
    được restore trong khi ta vẫn báo "checksum khớp".
    """
    return ["sha256sum", duong_trong_container]


def doc_sha256_tu_sha256sum(dau_ra: str) -> str:
    """Rút hash từ `sha256sum` (`<hex>  <đường dẫn>`), fail-closed."""
    tho = (dau_ra or "").strip().split()
    if not tho or not re.fullmatch(r"[0-9a-f]{64}", tho[0]):
        raise ChanLai(f"không đọc được sha256 từ đầu ra: {dau_ra!r}")
    return tho[0]


def lenh_dem_session(*, ten_db: str, user: str) -> List[str]:
    kiem_dich(ten_db)
    kiem_user(user)
    return [
        "psql", "-U", user, "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1",
        "-c",
        "SELECT count(*) FROM pg_stat_activity WHERE datname = "
        f"'{ten_db}' AND pid <> pg_backend_pid();",
    ]


def lenh_system_identifier(*, user: str) -> List[str]:
    kiem_user(user)
    return [
        "psql", "-U", user, "-d", "postgres", "-At", "-v", "ON_ERROR_STOP=1",
        "-c", "SELECT system_identifier FROM pg_control_system();",
    ]


def lenh_drop_tao(*, ten_db: str, user: str) -> List[List[str]]:
    """Ngắt session còn sót rồi drop/create.

    Cố ý KHÔNG dùng `WITH (FORCE)` để chạy được trên PostgreSQL cũ.
    """
    kiem_dich(ten_db)
    kiem_user(user)
    ngat = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{ten_db}' AND pid <> pg_backend_pid();"
    )
    chung = ["psql", "-U", user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c"]
    return [
        chung + [ngat],
        chung + [f'DROP DATABASE IF EXISTS "{ten_db}";'],
        chung + [f'CREATE DATABASE "{ten_db}" OWNER "{user}";'],
    ]


def lenh_restore(*, ten_db: str, user: str, duong_trong_container: str) -> List[str]:
    kiem_dich(ten_db)
    kiem_user(user)
    return [
        "pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
        "-U", user, "-d", ten_db, duong_trong_container,
    ]


# =============================================================================
# Hàng rào 4 — vân tay hậu restore, fail-closed
# =============================================================================
def cau_lenh_van_tay(bang: Sequence[str]) -> str:
    """SQL đếm theo bảng.

    ⚠️ Số đếm chỉ là **thông tin phụ**: "xoá một, thêm một" giữ nguyên count.
    Nó bắt được restore trượt hẳn (bảng rỗng/thiếu bảng); phát hiện thay đổi
    tinh vi là việc của registry, `alembic_version` và checksum archive.
    """
    for t in bang:
        kiem_ten_bang(t)
    khoi = " UNION ALL ".join(
        f"SELECT '{t}' AS bang, count(*) AS so FROM {t}" for t in bang
    )
    return f"SELECT bang, so FROM ({khoi}) x ORDER BY bang;"


def phan_tich_van_tay(dau_ra: str, *, bang_bat_buoc: Sequence[str]) -> Dict[str, int]:
    """Đọc `psql -At -F'|'` thành `{bảng: số hàng}` — fail-closed.

    Bản đầu của hàm này im lặng bỏ dòng không parse được và có thể trả `{}`.
    Ghép với một phép so `==` thì `{} == {}` thành PASS — cleanup xanh giả trong
    khi database rỗng. Nay mọi dòng rác, mọi bảng trùng, mọi bảng thiếu đều là lỗi.
    """
    ket: Dict[str, int] = {}
    for so_dong, dong in enumerate(dau_ra.splitlines(), start=1):
        tho = dong.strip()
        if not tho:
            continue
        if "|" not in tho:
            raise ChanLai(f"dòng {so_dong} của vân tay không đọc được: {tho!r}")
        ten, _, so = tho.partition("|")
        ten, so = ten.strip(), so.strip()
        if not re.fullmatch(r"\d+", so):
            raise ChanLai(f"dòng {so_dong}: số hàng không hợp lệ: {so!r}")
        if ten in ket:
            raise ChanLai(f"bảng {ten!r} xuất hiện hai lần trong vân tay")
        ket[ten] = int(so)

    if not ket:
        raise ChanLai("vân tay RỖNG — không có gì để đối soát, không phải PASS")
    thieu = [t for t in bang_bat_buoc if t not in ket]
    if thieu:
        raise ChanLai(f"vân tay thiếu bảng bắt buộc: {thieu}")
    thua = [t for t in ket if t not in bang_bat_buoc]
    if thua:
        raise ChanLai(f"vân tay có bảng ngoài danh sách khai trước: {thua}")
    return ket


def kiem_sau_restore(
    *,
    van_tay_baseline: str,
    van_tay_hien_tai: str,
    alembic_baseline: str,
    alembic_hien_tai: str,
) -> None:
    # Đòi ĐÚNG hình dạng SHA-256, không chỉ "khác rỗng": bản đầu nhận
    # "x" == "x" làm PASS, tức hai giá trị rác giống nhau cũng qua. Vân tay
    # phải do parser hợp lệ sinh ra (`van_tay(phan_tich_van_tay(...))`).
    for ten, gia_tri in (
        ("baseline", van_tay_baseline),
        ("hiện tại", van_tay_hien_tai),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", gia_tri or ""):
            raise ChanLai(
                f"vân tay {ten} không phải SHA-256 hợp lệ: {gia_tri!r}. Hai giá "
                "trị rác bằng nhau không phải bằng chứng database đã về nền."
            )
    if not alembic_baseline or not alembic_hien_tai:
        raise ChanLai("thiếu alembic head để đối soát — không được coi là PASS")
    if alembic_baseline != alembic_hien_tai:
        raise ChanLai(
            f"alembic head sau restore {alembic_hien_tai!r} ≠ baseline "
            f"{alembic_baseline!r} — database smoke KHÔNG ở trạng thái nền"
        )
    if van_tay_baseline != van_tay_hien_tai:
        raise ChanLai(
            f"vân tay sau restore {van_tay_hien_tai[:12]}… ≠ baseline "
            f"{van_tay_baseline[:12]}…. Database smoke đang ở trạng thái KHÔNG "
            "xác định — không mở lại dịch vụ, không chạy pack tiếp theo."
        )
