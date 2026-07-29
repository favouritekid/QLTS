"""Đồng bộ cohort "đã đóng học phí HK1" sang hệ quản lý ký túc xá (Supabase).

MỘT CHIỀU, CHỈ ĐỌC phía QLTS. Không có đường nào trong file này ghi vào QLTS.

Vị từ cohort lấy từ ``repositories/dorm_export_repository.select_paid_hk1_cohort``
— cùng hàm mà test lock-in đang canh. KHÔNG viết lại điều kiện tại đây: hai hệ
nói hai danh sách khác nhau là kiểu sai không có gì nổ ra.

Usage (BẮT BUỘC override entrypoint — xem cảnh báo bên dưới):

    docker compose run --rm --no-deps --entrypoint python \\
        --env-from-file <file-secret-chi-tren-may-quan-tri> \\
        backend -m app.scripts.sync_dorm_students \\
            --academic-year 2026 --dry-run

⚠️ Là ``--env-from-file``, KHÔNG phải ``--env-file``. Với Compose v2 trở lên
``--env-file`` là cờ TOÀN CỤC (đứng trước ``run``) và nó chỉ nạp biến cho việc
nội suy trong file compose — các biến ``DORM_*`` không được khai báo ở đó nên sẽ
KHÔNG tới được container. Đặt ``--env-file`` sau ``run`` thì Compose báo cờ lạ
và thoát trước khi container khởi động.

⚠️ PHẢI override ``--entrypoint``: ``docker-entrypoint.sh`` chạy
``alembic upgrade head`` TRƯỚC command. Chạy dạng thường với ``DATABASE_URL`` trỏ
tunnel production đồng nghĩa với việc nâng cấp lược đồ database thật.

⚠️ Mặc định là DRY-RUN. Muốn ghi phải truyền ``--apply`` tường minh.

⚠️ File này CỐ Ý bị loại khỏi image production (xem ``.dockerignore``). Nó hạ
được cờ đủ-điều-kiện của cả một khoá học, nên không được nằm sẵn trong container
đang chạy — chỉ chạy qua bind-mount trên máy quản trị.

Biến môi trường (KHÔNG có giá trị mặc định — thiếu là dừng):
    DORM_SUPABASE_URL          URL project Supabase của hệ KTX
    DORM_SUPABASE_SECRET_KEY   khoá secret; chỉ sống trên máy quản trị

    Ba biến dưới đây định danh NGUỒN — xem ``assert_source_database_matches``.
    Chỉ bắt buộc khi ``--apply``:

    DORM_SYNC_SOURCE_DB        database nguồn mà đích này chấp nhận, dạng
                               ``host:port/dbname``
                               (ví dụ ``postgres:5432/qlts_production``)
    DORM_SYNC_SOURCE_SYSTEM_ID ``system_identifier`` của cluster nguồn. Lấy bằng:
                               ``select system_identifier from pg_control_system()``

    Biến dưới đây định danh ĐÍCH — xem ``assert_target_project_matches``.
    Bắt buộc với mọi đích không phải loopback:

    DORM_SYNC_TARGET_PROJECT_REF  project ref của Supabase nhận dữ liệu; phải
                               khớp hostname ``<ref>.supabase.co`` của
                               ``DORM_SUPABASE_URL``

⚠️ ``DORM_SYNC_SOURCE_ENV`` ĐÃ BỎ. Nó so ``APP_ENV`` với một nhãn khai trong
file secret — mà chính file secret ấy được nạp bằng ``--env-from-file`` nên nó
mang được luôn ``APP_ENV``. Hàng rào khi đó so hai giá trị đến từ cùng một
nguồn, và tự vô hiệu đúng ở ca nó sinh ra để chặn: chạy stack DEV với file
secret của KTX THẬT.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.repositories.dorm_export_repository import (
    count_atypical_statuses,
    describe_excluded_statuses,
    select_paid_hk1_cohort,
)

log = structlog.get_logger(__name__)

# Chuẩn hoá giới tính. QLTS lưu free-text ``varchar(50)`` do người nhập gõ tay,
# nên bảng ánh xạ phải bao gồm cả biến thể không dấu và viết tắt.
#
# ⚠️ Giá trị KHÔNG khớp sẽ thành ``unknown`` — và ``unknown`` CHẶN xếp phòng ở
# phía KTX. Đó là chủ đích: đoán bừa giới tính rồi xếp nhầm phòng là sự cố với
# người ở, còn ``unknown`` chỉ là một việc cần người xử lý.
_GENDER_MAP = {
    "nam": "male",
    "male": "male",
    "m": "male",
    "nữ": "female",
    "nu": "female",
    "female": "female",
    "f": "female",
}


def normalize_gender(raw: Optional[str]) -> str:
    """Quy giới tính nguồn về ``male`` | ``female`` | ``unknown``.

    ⚠️ Chuẩn hoá NFC TRƯỚC khi tra bảng. "Nữ" có hai cách mã hoá Unicode hợp lệ:
    tổ hợp sẵn (U+1EEF) và phân rã (``u`` + U+031B + U+0303). Hai chuỗi đó hiện
    ra giống hệt nhau trên màn hình nhưng KHÔNG bằng nhau trong Python, nên bản
    phân rã — do dán từ máy Mac, từ file import, từ một form web khác — sẽ trượt
    khoá ``"nữ"`` và rơi xuống ``unknown``, tức bị chặn xếp phòng vì lý do không
    ai nhìn ra được khi đọc dữ liệu.
    """
    if not raw:
        return "unknown"
    return _GENDER_MAP.get(unicodedata.normalize("NFC", raw).strip().lower(), "unknown")


# Trần độ dài của ``students.contact_phone`` / ``contact_phone2`` phía KTX.
# Giữ HẰNG SỐ ở đây để lý do bỏ số dài đọc được ngay tại chỗ kiểm.
_MAX_PHONE_LEN = 20


def chuan_hoa_so(raw: Optional[str]) -> Optional[str]:
    """Số điện thoại sạch, hoặc ``None``.

    ⚠️ Số dài quá trần thì BỎ, KHÔNG cắt. Cột đích có
    ``check (length <= 20)``, nên một giá trị bẩn làm PostgREST trả 400 và hỏng
    CẢ LÔ 200 hàng — không phải một hàng. Còn cắt thì tạo ra một số điện thoại
    khác gọi được, tức là dựng ra người liên hệ sai và không ai biết.

    "Không có số" là trạng thái hợp lệ và giao diện nói được điều đó; "số sai"
    thì không.
    """
    if raw is None:
        return None
    sach = str(raw).strip()
    if not sach or len(sach) > _MAX_PHONE_LEN:
        return None
    return sach


def build_student_payload(
    row: Any, sync_run_id: int, synced_at: Optional[str] = None
) -> Dict[str, Any]:
    """Dựng bản ghi gửi sang Supabase.

    ⚠️ CHỈ gồm các cột thuộc về NGUỒN. Cố ý không đụng tới:
      * ``placement_gender_override`` và các cột đi kèm — đó là quyết định của
        con người, lượt đồng bộ ghi đè lên là xoá mất dấu vết;
      * ``dorm_registrations`` / ``room_assignments`` — dữ liệu do phía KTX tạo.

    PostgREST chỉ cập nhật những cột được gửi lên, nên không liệt kê ở đây đồng
    nghĩa với giữ nguyên.

    Args:
        synced_at: mốc thời gian ISO-8601 của LƯỢT (một giá trị cho cả lượt, để
            mọi hàng của cùng một lượt có cùng mốc). Bỏ trống thì lấy giờ hiện
            tại.

    ⚠️ ``synced_at`` BẮT BUỘC nằm trong payload. Cột đó phía KTX chỉ có
    ``default now()`` của INSERT và không có trigger nào đụng tới, nên nếu không
    gửi lên thì merge-duplicates giữ nguyên giá trị cũ: mọi hàng đóng băng ở lần
    đồng bộ ĐẦU TIÊN, mãi mãi. Câu hỏi duy nhất cột đó sinh ra để trả lời —
    "danh sách này cũ chưa?" — sẽ nhận về ngày nhìn thấy lần đầu.
    """
    if synced_at is None:
        synced_at = datetime.now(timezone.utc).isoformat()

    lien_he = chuan_hoa_so(getattr(row, "contact_phone", None))
    lien_he_phu = chuan_hoa_so(getattr(row, "contact_phone2", None))
    # Hai ô hiện cùng một số thì ô thứ hai không nói thêm gì, chỉ khiến người
    # gọi thử lại đúng số vừa không nghe máy.
    if lien_he_phu is not None and lien_he_phu == lien_he:
        lien_he_phu = None

    return {
        "qlts_profile_id": row.qlts_profile_id,
        "full_name": row.full_name,
        "source_gender_raw": row.source_gender_raw,
        "normalized_gender": normalize_gender(row.source_gender_raw),
        "program_name": row.program_name,
        "contact_phone": lien_he,
        "contact_phone2": lien_he_phu,
        "academic_year": row.academic_year,
        "officer_qlts_id": row.officer_qlts_id,
        "unit_id": row.unit_id,
        # Có mặt trong nguồn = còn đủ điều kiện. Đây cũng là đường KÍCH HOẠT LẠI
        # cho người từng bị hạ cờ rồi quay lại danh sách.
        "source_eligible": True,
        "last_seen_sync_id": sync_run_id,
        "synced_at": synced_at,
    }


# Chỉ những host này được phép đi bằng ``http://``: Supabase chạy trên chính máy
# đang phát triển, gói tin không rời khỏi máy.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def assert_transport_is_encrypted(base_url: str) -> None:
    """Từ chối đích không mã hoá TRƯỚC khi bí mật nào rời khỏi máy.

    ⚠️ Mọi lời gọi ở đây mang khoá secret của hệ KTX trong HAI header
    (``apikey`` và ``Authorization``), và khi ``--apply`` thì thân request còn
    chứa họ tên người học. Qua ``http://`` thì cả hai đi ở dạng đọc được trên
    đường truyền — một cấu hình gõ nhầm scheme là đủ để rò khoá ghi toàn hệ.

    Loopback được miễn: đó là Supabase local lúc phát triển, gói tin không rời
    khỏi máy.
    """
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()

    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
        return

    raise ValueError(
        f"DORM_SUPABASE_URL phải dùng https:// (nhận được '{parsed.scheme}://{host}'). "
        "Khoá secret và họ tên người học đi trong các lời gọi này; không mã hoá "
        "đường truyền thì chúng đọc được trên đường đi."
    )


def assert_target_project_matches(base_url: str) -> None:
    """Đích phải là ĐÚNG project Supabase đã được duyệt.

    ⚠️ Hàng rào ở ``assert_source_database_matches`` bảo vệ NGUỒN — đọc đúng
    database. Nhưng ĐÍCH thì trước đây chỉ kiểm mỗi scheme https, nên một cặp
    URL + secret key hợp lệ của một project Supabase KHÁC vẫn nhận trọn cả
    cohort và báo thành công. Nguồn đúng + đích sai là ca không hàng rào nào
    khác chạm tới.

    Project ref nằm trong hostname của endpoint REST chuẩn:
    ``https://<ref>.supabase.co/rest/v1``.

    ⚠️ Gọi TRƯỚC khi dựng headers — khoá secret không được rời khỏi tiến trình
    trước khi biết nó đi tới đâu.

    Loopback được miễn: Supabase local không có project ref, và gói tin không
    rời khỏi máy.

    ⚠️ Custom domain KHÔNG được suy đoán. Nếu về sau dùng domain riêng thì phải
    khai một allowlist ánh xạ ``domain -> ref`` được duyệt riêng; đoán ref từ
    một hostname bất kỳ là bỏ đúng lớp bảo vệ này.
    """
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()

    if host in _LOOPBACK_HOSTS:
        return

    expected_ref = _require_env("DORM_SYNC_TARGET_PROJECT_REF").strip().lower()
    expected_host = f"{expected_ref}.supabase.co"

    if host != expected_host:
        raise ValueError(
            f"DORM_SUPABASE_URL trỏ tới '{host}' nhưng project được duyệt là "
            f"'{expected_ref}' (mong đợi '{expected_host}').\n"
            "  Đây là đích NHẬN dữ liệu cá nhân — sai project nghĩa là gửi cả "
            "cohort sang một hệ khác. Dùng domain riêng thì phải khai allowlist "
            "ánh xạ domain sang ref, không đoán."
        )


def _client_note(client_token: str) -> str:
    """Dấu của tiến trình chạy, ghi vào ``sync_runs.note``.

    Đây là thứ duy nhất cho phép nhận lại một lượt mà chính lần chạy này đã tạo
    khi phản hồi bị mất — xem ``open_sync_run``.
    """
    return f"client:{client_token}"


class DormApi:
    """Lớp mỏng gọi PostgREST của Supabase.

    Dùng REST thay vì nối thẳng Postgres để không phải mở cổng database của hệ
    KTX ra ngoài.
    """

    def __init__(self, base_url: str, secret_key: str) -> None:
        # Thứ tự có chủ đích: đường truyền, rồi ĐÍCH, rồi mới tới headers mang
        # khoá secret. Khoá không được nằm trong bất kỳ cấu trúc nào trước khi
        # cả hai câu hỏi "đi bằng gì" và "đi tới đâu" đã có câu trả lời đúng.
        assert_transport_is_encrypted(base_url)
        assert_target_project_matches(base_url)
        self._base = base_url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

    async def __aenter__(self) -> "DormApi":
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.is_success:
            return

        # ⚠️ KHÔNG đưa thân phản hồi vào thông điệp lỗi.
        #
        # PostgREST trả kèm giá trị của hàng gây lỗi ("Key (...)=(...) already
        # exists", chi tiết vi phạm CHECK…), tức có thể là tên người học. Thông
        # điệp này đi vào exception rồi ra stderr — mà stderr bị CI, cron và
        # container thu gom y như log. Tách khỏi structlog thôi là chưa đủ.
        #
        # Người vận hành cần đủ thông tin để tra: hành động nào, mã HTTP nào, và
        # request-id để đối chiếu với log phía Supabase.
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("sb-request-id")
            or "không có"
        )
        raise RuntimeError(
            f"{action} thất bại (HTTP {response.status_code}, "
            f"request-id {request_id}). "
            "Chi tiết nằm ở log phía Supabase — cố ý không in ra đây vì nội dung "
            "lỗi có thể chứa dữ liệu cá nhân."
        )

    async def find_run_by_token(
        self, academic_year: int, client_token: str
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Tìm lượt mang DẤU của lần chạy này.

        Trả ``("found", hàng)`` | ``("absent", None)`` | ``("unknown", None)``.

        ⚠️ BA kết quả, không phải hai. Gộp "đọc được, không có hàng nào" với
        "không đọc được" thành cùng một ``None`` sẽ khiến ca mất mạng CẢ HAI
        CHIỀU (POST mất ACK rồi GET đối soát cũng hỏng) bị tuyên bố là "chưa có
        gì thay đổi, chạy lại an toàn" — trong khi một hàng ``running`` có thể
        đang nằm đó và khoá năm học lại. Tuyên bố an toàn khi không biết là kiểu
        sai tệ hơn cả im lặng.

        ⚠️ LỌC ``status=running``. ``note`` KHÔNG unique — database chỉ ràng một
        lượt ĐANG CHẠY mỗi năm. Chạy lại với cùng ``--client-token`` sau một lượt
        đã ``failed`` sẽ để lại hàng lịch sử mang đúng dấu đó; không lọc thì lời
        gọi này nhận nhầm hàng cũ, còn hàng ``running`` vừa tạo bị bỏ lại và tiếp
        tục khoá năm học — đúng thứ cơ chế dấu sinh ra để tránh.

        ⚠️ Hàng đọc về cũng phải được KIỂM HÌNH DẠNG. Chỉ đọc thẳng ``row["id"]``
        thì một thân phản hồi lạ (``[{}]``) ném ``KeyError`` ra giữa nhánh phục
        hồi, thay vì trả ``unknown`` để người gọi xử lý tử tế.
        """
        try:
            response = await self._client.get(
                f"{self._base}/sync_runs",
                headers=self._headers,
                params={
                    "academic_year": f"eq.{academic_year}",
                    "note": f"eq.{_client_note(client_token)}",
                    "status": "eq.running",
                    "select": "id,status",
                    # Unique index đã bảo đảm tối đa một lượt running mỗi năm;
                    # `order` chỉ là chốt an toàn nếu ràng buộc đó đổi.
                    "order": "id.desc",
                    "limit": "1",
                },
            )
        except httpx.HTTPError:
            return "unknown", None

        if not response.is_success:
            return "unknown", None

        try:
            rows = response.json()
        except Exception:
            return "unknown", None

        if not isinstance(rows, list):
            return "unknown", None

        if not rows:
            return "absent", None

        row = rows[0]
        if not isinstance(row, dict):
            return "unknown", None

        run_id = row.get("id")
        # ``bool`` là lớp con của ``int`` — ``True`` không phải một id hợp lệ.
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            return "unknown", None

        # Vành đai thứ hai sau bộ lọc phía server: nếu vì lý do gì đó vẫn về một
        # hàng đã đóng, KHÔNG được coi là lượt vừa mở.
        if row.get("status") != "running":
            return "unknown", None

        return "found", row

    async def _recover_open_or_fail(
        self, academic_year: int, client_token: str, *, ly_do: str
    ) -> int:
        """Sau một phản hồi MƠ HỒ ở bước mở lượt: nhận lại hàng, hoặc nói thật.

        Ba nhánh, ba thông điệp khác nhau — người vận hành cần biết mình đang ở
        nhánh nào để quyết định chạy lại hay đi kiểm database.
        """
        outcome, run = await self.find_run_by_token(academic_year, client_token)

        if outcome == "found":
            log.warning(
                "dorm_sync_run_recovered", run_id=run["id"], client_token=client_token
            )
            return run["id"]

        if outcome == "absent":
            raise RuntimeError(
                f"Không mở được lượt đồng bộ ({ly_do}). Đã đối soát: KHÔNG có lượt "
                f"nào mang dấu '{_client_note(client_token)}' — database chưa nhận "
                "gì, chạy lại là an toàn."
            )

        # ⚠️ KHÔNG được nói "an toàn" ở đây. Lần đọc phục hồi cũng hỏng nghĩa là
        # ta không biết hàng đã được tạo hay chưa.
        raise RuntimeError(
            f"Không mở được lượt đồng bộ ({ly_do}) và KHÔNG đối soát được trạng "
            f"thái (lần đọc phục hồi cũng thất bại). Một lượt mang dấu "
            f"'{_client_note(client_token)}' CÓ THỂ đang treo 'running' và sẽ chặn "
            "mọi lần chạy sau cho năm này.\n"
            "  → Tra bảng sync_runs theo dấu đó TRƯỚC khi chạy lại. Muốn nhận lại "
            f"đúng lượt cũ thì chạy lại với --client-token {client_token}."
        )

    async def open_sync_run(
        self, academic_year: int, client_token: str, raw_count: int
    ) -> int:
        """Mở một lượt đồng bộ. Chịu được ca phản hồi bị mất.

        ⚠️ Bước này CŨNG có ca mất ACK, và nó là ca tệ nhất: hàng ``running`` đã
        nằm trong database còn client thì không có ``run_id`` nào để đối soát.
        Không xử lý thì ``uq_sync_run_active_per_year`` từ chối MỌI lần chạy sau
        cho năm học đó bằng 409 cho tới khi có người vào sửa tay — đúng cái bẫy
        mà các nhánh đóng sổ phía dưới sinh ra để tránh.

        Cách thoát: ghi DẤU của tiến trình vào ``sync_runs.note`` ngay trong câu
        INSERT, rồi khi phản hồi MƠ HỒ thì đọc lại theo dấu đó. Dấu là duy nhất
        cho mỗi lần chạy nên không thể nhận nhầm lượt của tiến trình khác.

        ⚠️ "Mơ hồ" gồm CẢ mã lỗi có phản hồi, không chỉ lỗi kết nối: 5xx và 408
        thường đến từ gateway đứng TRƯỚC database, nên INSERT có thể đã commit
        xong rồi phản hồi mới hỏng trên đường về. Ném thẳng ở những mã đó là bỏ
        lại đúng hàng ``running`` mà cơ chế dấu này sinh ra để nhận lại.
        """
        payload = {
            "academic_year": academic_year,
            "status": "running",
            "note": _client_note(client_token),
            # Ghi NGAY khi mở lượt, không đợi lúc đóng: một lượt hỏng giữa
            # chừng vẫn phải trả lời được "nguồn có bao nhiêu". Để trống tới
            # bước cuối nghĩa là đúng những lượt cần đối soát nhất lại là những
            # lượt không có con số đó.
            "raw_count": raw_count,
        }

        try:
            response = await self._client.post(
                f"{self._base}/sync_runs",
                headers={**self._headers, "Prefer": "return=representation"},
                json=payload,
            )
        except httpx.HTTPError:
            # Lỗi TRUYỀN TẢI: không biết database đã tạo hàng hay chưa.
            return await self._recover_open_or_fail(
                academic_year, client_token, ly_do="lỗi kết nối"
            )

        if response.status_code == 409:
            # Có thể chính là hàng của lần chạy này (một lời gọi trước đó đã tới
            # nơi rồi mất phản hồi). Hỏi theo dấu trước khi kết luận là của người
            # khác — nếu đúng dấu mình thì cứ dùng tiếp, không cần ai sửa tay.
            outcome, run = await self.find_run_by_token(academic_year, client_token)
            if outcome == "found":
                log.warning(
                    "dorm_sync_run_recovered",
                    run_id=run["id"],
                    client_token=client_token,
                )
                return run["id"]

            if outcome == "unknown":
                # ⚠️ Không đọc được KHÔNG phải "không mang dấu". Khẳng định lượt
                # đang chạy là của người khác trong khi chưa đọc nổi trạng thái
                # sẽ đẩy người vận hành đi đánh dấu failed một lượt có thể là của
                # chính họ — và lượt đó đang ghi dở.
                raise RuntimeError(
                    f"Đã có một lượt đồng bộ ĐANG CHẠY cho năm {academic_year} "
                    "nhưng KHÔNG đối soát được nó có phải của lần chạy này hay "
                    "không (lần đọc phục hồi thất bại).\n"
                    f"  → Chạy lại với --client-token {client_token} để nhận lại "
                    "đúng lượt đó nếu là của mình. Nếu vẫn hỏng, tra bảng "
                    f"sync_runs theo dấu '{_client_note(client_token)}' trước khi "
                    "đánh dấu failed bất cứ lượt nào."
                )

            raise RuntimeError(
                f"Đã có một lượt đồng bộ ĐANG CHẠY cho năm {academic_year} và nó "
                "KHÔNG mang dấu của lần chạy này. Chờ nó kết thúc hoặc đánh dấu "
                "failed trước khi chạy lượt mới. "
                "(Cột `note` của lượt đó cho biết tiến trình nào đã mở nó.)"
            )

        # Mã MƠ HỒ: gateway/upstream có thể đã commit rồi mới hỏng.
        if response.status_code == 408 or response.status_code >= 500:
            return await self._recover_open_or_fail(
                academic_year,
                client_token,
                ly_do=f"HTTP {response.status_code} từ gateway",
            )

        # Còn lại là câu trả lời DỨT KHOÁT của database (400/401/403…): không có
        # hàng nào được tạo, không cần đối soát.
        self._raise_for_status(response, "Mở lượt đồng bộ")

        try:
            return response.json()[0]["id"]
        except (IndexError, KeyError, TypeError, ValueError):
            # Phản hồi 2xx nhưng thân không đọc được (proxy cắt, JSON hỏng).
            # Hàng gần như chắc chắn ĐÃ được tạo — tìm lại theo dấu.
            return await self._recover_open_or_fail(
                academic_year, client_token, ly_do="phản hồi không đọc được"
            )

    async def get_sync_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Đọc trạng thái hiện tại của một lượt."""
        response = await self._client.get(
            f"{self._base}/sync_runs",
            headers=self._headers,
            params={
                "id": f"eq.{run_id}",
                "select": "id,status,source_count,upserted_count,deactivated_count",
            },
        )
        self._raise_for_status(response, "Đọc lượt đồng bộ")
        rows = response.json()
        return rows[0] if rows else None

    async def mark_sync_run_failed(self, run_id: int, counts: Dict[str, int]) -> int:
        """Đánh dấu một lượt ĐANG CHẠY là thất bại. Trả về SỐ HÀNG đã đổi.

        ⚠️ Phải trả về số hàng và người gọi phải kiểm. PostgREST coi PATCH khớp
        0 hàng là THÀNH CÔNG, nên chỉ nhìn mã HTTP thì một lời gọi không đổi gì
        vẫn được ghi nhận là "đã đánh dấu thất bại".

        ⚠️ Lọc thêm ``status=eq.running``: chỉ lọc theo ``id`` thì lời gọi này
        đổi được một lượt ĐÃ ``completed`` thành ``failed``.

        ⚠️ ``completed_at`` gửi mốc ISO-8601 tính ở đây, KHÔNG gửi chuỗi
        ``"now()"``. PostgREST truyền thẳng chuỗi vào câu UPDATE; Postgres nhận
        các giá trị đặc biệt ``now``/``today``/``epoch``/``infinity`` nhưng
        KHÔNG nhận ``now()`` — nó trả 400 và cả nhánh đánh dấu thất bại này
        không bao giờ chạy được, để lượt treo ``running`` và khoá cứng năm học
        bằng ``uq_sync_run_active_per_year``. Ràng buộc
        ``chk_sync_run_completed_has_time`` phía KTX bắt buộc cột này có giá trị
        khi trạng thái là ``failed``, nên không thể bỏ trống.
        """
        response = await self._client.patch(
            f"{self._base}/sync_runs",
            headers={**self._headers, "Prefer": "return=representation"},
            params={
                "id": f"eq.{run_id}",
                "status": "eq.running",
                "select": "id",
            },
            json={
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                **counts,
            },
        )
        self._raise_for_status(response, "Đánh dấu lượt thất bại")
        return len(response.json())

    async def reconcile_after_failure(
        self, run_id: int, source_count: int, upserted_count: int
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Xác định lượt thực sự kết thúc ra sao sau khi client gặp lỗi.

        Client gặp lỗi KHÔNG đồng nghĩa với việc database chưa làm gì. Ca mất
        ACK là ví dụ: hạ cờ đã commit xong, chỉ phản hồi không về. Tuyên bố
        "thất bại, không hạ cờ ai" trong ca đó là ghi sai sổ sách.

        Trả về ``(kết quả, hàng sync_runs đã đọc)`` với kết quả là
        ``finalized`` | ``marked_failed`` | ``unknown``.

        ⚠️ Trả kèm HÀNG ĐÃ ĐỌC thay vì để người gọi query lại. Lời gọi thứ hai
        chạy trong nhánh xử lý lỗi, nơi mạng vốn đang chập chờn: nếu nó ném
        exception thì một lượt ĐÃ THÀNH CÔNG bị báo thành traceback + thoát 1,
        và người vận hành tin là dữ liệu chưa đổi trong khi nó đã đổi.
        """
        try:
            run = await self.get_sync_run(run_id)
        except Exception:
            return "unknown", None

        if run is None:
            return "unknown", None

        if run["status"] == "completed":
            # Database đã hoàn tất. Lỗi phía client chỉ là lỗi đường truyền.
            return "finalized", run

        if run["status"] == "failed":
            return "marked_failed", run

        try:
            changed = await self.mark_sync_run_failed(
                run_id,
                {"source_count": source_count, "upserted_count": upserted_count},
            )
        except Exception:
            return "unknown", run

        # Đổi được đúng một hàng mới là đã đánh dấu thật. 0 hàng nghĩa là trạng
        # thái đã đổi giữa lúc đọc và lúc ghi — không được tuyên bố bừa.
        return ("marked_failed" if changed == 1 else "unknown"), run

    async def upsert_students(
        self, run_id: int, rows: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """Ghi một lô qua RPC. Trả ``(đã ghi, bị chặn)``.

        ⚠️ KHÔNG POST thẳng ``/students`` nữa. Ghi thẳng bảng có hai lỗ mà chỉ
        database bịt được: danh sách chặn tái tạo phải kiểm trong cùng
        transaction với INSERT, và lời gọi phải bị ràng vào một lượt CÒN SỐNG
        để một tiến trình đã bị đánh dấu hỏng không ghi đè dấu lượt của tiến
        trình đang chạy.

        ⚠️ Người gọi PHẢI kiểm ``đã ghi + bị chặn == len(rows)``. Lệch nghĩa là
        RPC bỏ sót hàng trong im lặng, và con số đó đi thẳng vào phép đối soát
        ``raw = source + blocked`` ở bước đóng sổ.
        """
        response = await self._client.post(
            f"{self._base}/rpc/upsert_students_batch",
            headers=self._headers,
            json={"p_run_id": run_id, "p_rows": rows},
        )
        self._raise_for_status(response, "Ghi danh sách học viên")

        body = response.json()
        # PostgREST trả `returns table (...)` dưới dạng mảng một phần tử.
        row = body[0] if isinstance(body, list) and body else body
        try:
            return int(row["upserted"]), int(row["blocked"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "Ghi danh sách học viên: phản hồi không đọc được số liệu lô. "
                "KHÔNG chạy tiếp — hai con số này quyết định bước hạ cờ."
            ) from exc

    async def count_students(self, academic_year: int) -> Optional[int]:
        """Số học viên hệ KTX đang có cho năm học. ``None`` = không đếm được.

        ⚠️ Trả ``None`` thay vì nổ khi phần tổng của ``Content-Range`` không
        phải số. PostgREST trả ``*/*`` khi không đếm được, và một proxy trung
        gian có thể gỡ mất header ``Prefer``. Con số này chỉ để người vận hành
        đối chiếu ở bước XEM TRƯỚC — ném ``ValueError`` từ ``int("*")`` sẽ biến
        một lần xem trước chỉ-đọc thành traceback trần.
        """
        response = await self._client.get(
            f"{self._base}/students",
            headers={**self._headers, "Prefer": "count=exact"},
            params={
                "academic_year": f"eq.{academic_year}",
                "select": "qlts_profile_id",
                "limit": "1",
            },
        )
        self._raise_for_status(response, "Đếm học viên")
        total = response.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else None

    async def finalize_sync_run(
        self, run_id: int, source_count: int, upserted_count: int
    ) -> int:
        """Hạ cờ đủ-điều-kiện VÀ đóng lượt — trong cùng một transaction.

        ⚠️ Hai việc này BẮT BUỘC đi cùng nhau. Tách thành hai lời gọi sẽ để lại
        khoảng trống: hạ cờ xong mà đóng lượt hỏng thì học viên đã bị hạ cờ
        trong khi lượt vẫn ``running`` — và lượt ``running`` đó khoá luôn năm học
        lại, nên mọi lần chạy sau đều bị từ chối trong lúc dữ liệu đã đổi một
        nửa. Nhánh "ghi hỏng giữa chừng" không phủ được ca này vì nó xảy ra SAU
        khi ghi xong.

        ⚠️ Chỉ được gọi SAU KHI toàn bộ dữ liệu nguồn đã ghi xong.

        Trả về số bản ghi bị hạ cờ.

        ⚠️ Có RETRY vì mất ACK là trạng thái mơ hồ HỢP LỆ: database đã hạ cờ và
        commit xong, nhưng phản hồi không về tới đây. Không thử lại thì script
        rơi vào nhánh xử lý lỗi và đánh dấu `failed` cho một lượt thực ra đã
        thành công — nhật ký nói ngược với dữ liệu. Hàm phía database idempotent
        với cùng bộ số liệu nên gọi lại là an toàn.
        """
        payload = {
            "p_run_id": run_id,
            "p_source_count": source_count,
            "p_upserted_count": upserted_count,
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                response = await self._client.post(
                    f"{self._base}/rpc/finalize_sync_run",
                    headers=self._headers,
                    json=payload,
                )
            except httpx.HTTPError as exc:
                # Lỗi TRUYỀN TẢI: không biết database đã chạy hay chưa. Đây đúng
                # là ca phải thử lại.
                last_error = exc
                log.warning("dorm_sync_finalize_retry", attempt=attempt)
                # Không ngủ sau lần thử CUỐI: kết quả đã được quyết định, giấc
                # ngủ đó chỉ kéo dài thêm thời gian lượt treo `running`.
                if attempt < 3:
                    await asyncio.sleep(attempt)
                continue

            # Lỗi có phản hồi (4xx/5xx) là câu trả lời dứt khoát từ database —
            # thử lại chỉ lặp lại đúng lỗi đó.
            self._raise_for_status(response, "Kết thúc lượt đồng bộ")
            return response.json()["deactivated_count"]

        raise RuntimeError(
            "Kết thúc lượt đồng bộ thất bại sau 3 lần thử (lỗi kết nối). "
            "Trạng thái lượt CHƯA rõ — kiểm bảng sync_runs trước khi chạy lại."
        ) from last_error


async def fetch_cohort(academic_year: int, *, verify_source: bool = False) -> List[Any]:
    """Đọc cohort từ QLTS trong transaction CHỈ ĐỌC.

    Args:
        verify_source: hỏi database xem nó là ai TRƯỚC khi đọc hàng nào. Bật khi
            ``--apply``; một lần xem trước chỉ-đọc không cần khai báo cấu hình
            nguồn, và bắt nó khai chỉ khiến người ta bỏ qua bước xem trước.
    """
    async with AsyncSessionLocal() as session:
        # Chốt chặn ở tầng database: kể cả khi có lỗi lập trình khiến một câu
        # ghi lọt vào, transaction sẽ từ chối thay vì sửa dữ liệu tuyển sinh.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        if verify_source:
            await assert_live_source_matches(session)
        result = await session.execute(select_paid_hk1_cohort(academic_year))
        return result.all()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        # Không có giá trị mặc định. Một script ghi dữ liệu mà tự đoán đích đến
        # là script sẽ ghi nhầm chỗ vào một ngày nào đó.
        print(f"✗ Thiếu biến môi trường {name}", file=sys.stderr)
        sys.exit(2)
    return value


def database_identity_from_url(database_url: str) -> str:
    """``host:port/dbname`` rút từ chuỗi kết nối, dùng để đối chiếu khai báo.

    Dùng ``make_url`` của SQLAlchemy thay vì tự tách chuỗi: ``DATABASE_URL``
    thật có driver (``postgresql+asyncpg``), mật khẩu chứa ký tự đã mã hoá URL,
    và có thể kèm query string — mọi parser viết tay đều sai ở một trong ba chỗ
    đó, và sai ở đây nghĩa là hàng rào so nhầm.
    """
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    return _ghep_dinh_danh(url.host or "", url.port or 5432, url.database or "")


def _ghep_dinh_danh(host: str, port: int, dbname: str) -> str:
    """Ghép định danh, chuẩn hoá ĐÚNG phần được phép chuẩn hoá.

    ⚠️ Hostname không phân biệt hoa/thường theo DNS nên hạ về chữ thường là
    đúng. TÊN DATABASE thì KHÔNG: PostgreSQL cho phép ``CREATE DATABASE "QLTS"``
    tồn tại song song với ``qlts`` trong cùng cluster. Hạ cả hai về chữ thường
    khiến cả ba lớp hàng rào cho qua trong khi đang đọc đúng cái database khác —
    và đó là ca hàng rào này sinh ra để chặn.
    """
    return f"{host.strip().lower()}:{port}/{dbname.strip()}"


def _chuan_hoa_dinh_danh_khai_bao(raw: str) -> str:
    """Chuẩn hoá giá trị khai trong file secret theo đúng quy tắc trên.

    Nhận ``host:port/dbname``; hạ hostname về chữ thường, giữ nguyên tên
    database. Dạng lạ thì trả về nguyên văn (đã strip) để phép so bên dưới
    trượt và người vận hành thấy thông điệp lệch, thay vì âm thầm hợp lệ hoá
    một chuỗi không đọc được.
    """
    value = raw.strip()
    if "/" not in value or ":" not in value.split("/", 1)[0]:
        return value

    hostport, dbname = value.split("/", 1)
    host, _, port = hostport.rpartition(":")
    return f"{host.strip().lower()}:{port.strip()}/{dbname.strip()}"


def assert_source_database_matches() -> None:
    """Nguồn phải ĐÚNG DATABASE mà đích khai báo — không phải đúng cái nhãn.

    ⚠️ Đây là hàng rào cho ca nguy hiểm nhất của công cụ: chạy stack DEV (cohort
    vài chục hồ sơ thử) với file secret của KTX THẬT. Nó ghi đè danh sách thật
    rồi hạ cờ toàn bộ những ai không có trong nguồn dev — mà lượt đó vẫn kết
    thúc ``completed`` và thoát 0.

    ⚠️ VÌ SAO KHÔNG SO ``APP_ENV`` NỮA. Bản trước so ``APP_ENV`` với
    ``DORM_SYNC_SOURCE_ENV``. Cả hai là NHÃN, và file secret được nạp bằng
    ``--env-from-file`` nên nó mang được luôn ``APP_ENV`` — hàng rào khi đó so
    hai giá trị đến từ cùng một file, tức tự vô hiệu đúng ở ca nó sinh ra để
    chặn. Thứ quyết định script đọc database nào là ``DATABASE_URL``.

    Lớp thứ nhất (rẻ, chạy trước khi mở kết nối): so ``host:port/dbname``.
    Hai lớp còn lại hỏi thẳng database — xem ``assert_live_source_matches``.
    """
    expected = _chuan_hoa_dinh_danh_khai_bao(_require_env("DORM_SYNC_SOURCE_DB"))
    # Bắt buộc khai từ đây, dù chỉ dùng ở lớp ba: thiếu nó mà vẫn chạy tiếp
    # nghĩa là lớp mạnh nhất im lặng không chạy.
    _require_env("DORM_SYNC_SOURCE_SYSTEM_ID")

    from app.config import settings

    actual = database_identity_from_url(settings.DATABASE_URL)

    if actual != expected:
        print(
            f"✗ Từ chối ghi: QLTS đang đọc database '{actual}' nhưng file cấu "
            f"hình của hệ KTX khai báo DORM_SYNC_SOURCE_DB='{expected}'.\n"
            "  Hai đầu lệch nhau nghĩa là đang đẩy dữ liệu của database này "
            "sang hệ ký túc xá của database khác.",
            file=sys.stderr,
        )
        sys.exit(2)


async def assert_live_source_matches(session: Any) -> None:
    """Hỏi thẳng database: mày tên gì, và mày là cluster nào.

    Chạy TRONG transaction chỉ-đọc đã mở, trước khi đọc hàng nào.

    ⚠️ Vì sao cần cả hai câu hỏi:

    * ``current_database()`` — chuỗi kết nối có thể bị pooler viết lại, có thể
      kèm ``?options=``, nên tên trong URL chưa chắc là tên database thật đang
      phục vụ. Câu này không bị chuỗi cấu hình đánh lừa.
    * ``system_identifier`` — nhưng tên database TRÙNG NHAU là chuyện thường:
      recipe kéo prod về dev vẫn giữ nguyên tên. ``system_identifier`` sinh lúc
      ``initdb`` và KHÔNG đổi qua restore logic, nên nó là thứ duy nhất ở đây
      chứng minh đang nói chuyện với ĐÚNG MÁY.

    ⚠️ Đọc không được ``system_identifier`` là DỪNG, không phải bỏ qua. Một
    hàng rào tự tắt khi gặp trở ngại thì không phải hàng rào — và ca "thiếu
    quyền đọc catalog" trùng đúng với ca "đây không phải cluster ta nghĩ".
    """
    expected_db = _chuan_hoa_dinh_danh_khai_bao(_require_env("DORM_SYNC_SOURCE_DB"))
    # Tên database so KHỚP CHÍNH XÁC, không hạ chữ — xem `_ghep_dinh_danh`.
    expected_dbname = expected_db.rsplit("/", 1)[-1]
    expected_system_id = _require_env("DORM_SYNC_SOURCE_SYSTEM_ID").strip()

    actual_dbname = (await session.execute(text("select current_database()"))).scalar()
    if (actual_dbname or "").strip() != expected_dbname:
        print(
            f"✗ Từ chối ghi: database thật tên '{actual_dbname}' nhưng khai báo "
            f"DORM_SYNC_SOURCE_DB trỏ '{expected_dbname}'.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        actual_system_id = (
            await session.execute(
                text("select system_identifier from pg_control_system()")
            )
        ).scalar()
    except Exception as exc:
        print(
            "✗ Từ chối ghi: không đọc được `system_identifier` của cluster "
            f"({type(exc).__name__}). Đây là lớp duy nhất chứng minh đúng MÁY, "
            "nên không đọc được thì dừng — không bỏ qua.",
            file=sys.stderr,
        )
        sys.exit(2)

    if str(actual_system_id).strip() != expected_system_id:
        print(
            "✗ Từ chối ghi: cluster nguồn có system_identifier "
            f"'{actual_system_id}' nhưng khai báo DORM_SYNC_SOURCE_SYSTEM_ID là "
            f"'{expected_system_id}'.\n"
            "  Tên database khớp mà cluster lệch = đang đọc một BẢN SAO, không "
            "phải hệ thật.",
            file=sys.stderr,
        )
        sys.exit(2)


# Đặt True khi người vận hành yêu cầu dừng (Ctrl-C / SIGTERM).
_stop_requested = False


def _install_stop_handlers() -> None:
    """Biến tín hiệu dừng thành "dừng sạch sau lô hiện tại".

    ⚠️ Vì sao không để tín hiệu ném thẳng: ``KeyboardInterrupt`` và
    ``SystemExit`` KHÔNG phải ``Exception``, nên chúng đi vòng qua mọi nhánh
    đóng sổ và để lượt treo ``running`` vĩnh viễn. Chỉ số
    ``uq_sync_run_active_per_year`` phía KTX khi đó từ chối MỌI lần chạy sau
    cho năm học đó bằng 409 — một cú Ctrl-C giữa lúc chờ mạng đủ để khoá cứng
    cả năm học cho tới khi có người sửa tay trong database.

    Lần bấm THỨ HAI trả lại hành vi mặc định: người vận hành đang muốn thoát
    gấp thì không nên bị công cụ giữ lại.
    """

    def _handler(signum: int, frame: Any) -> None:
        global _stop_requested
        if _stop_requested:
            signal.signal(signum, signal.SIG_DFL)
            raise KeyboardInterrupt
        _stop_requested = True
        print(
            "\n⏸ Đã nhận tín hiệu dừng — đóng sổ sau khi xong lô hiện tại. "
            "Bấm lần nữa để thoát ngay (lượt sẽ treo 'running').",
            file=sys.stderr,
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (AttributeError, OSError, ValueError):
            # Không chạy ở main thread, hoặc nền tảng không có tín hiệu đó.
            # Lưới ``except BaseException`` trong ``main`` vẫn còn.
            pass


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Đồng bộ cohort đã đóng học phí HK1 sang hệ KTX.",
    )
    parser.add_argument(
        "--academic-year",
        type=int,
        required=True,
        help="Năm học cần đồng bộ. BẮT BUỘC — không có mặc định.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Thực sự ghi. Không truyền = chỉ xem trước, không đụng dữ liệu.",
    )
    # Chấp nhận `--dry-run` tường minh dù đó đã là mặc định: người vận hành hay
    # gõ nó cho chắc, và một lệnh bị từ chối vì "unrecognized arguments" sẽ
    # khiến họ nghĩ mình gõ sai chỗ khác.
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ xem trước (đây là mặc định). Không đi cùng --apply.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Số bản ghi mỗi lượt gửi (mặc định 200).",
    )
    parser.add_argument(
        "--client-token",
        default=None,
        help=(
            "Dấu ghi vào sync_runs.note. Bỏ trống = sinh mới mỗi lần chạy. "
            "Truyền lại dấu của một lần chạy đứt giữa chừng để NHẬN LẠI đúng "
            "lượt đó thay vì bị 409 chặn."
        ),
    )
    parser.add_argument(
        "--allow-empty-cohort",
        action="store_true",
        help=(
            "Cho phép ghi khi nguồn KHÔNG có hồ sơ nào. Không truyền = dừng. "
            "Chỉ dùng khi thật sự muốn hạ cờ toàn bộ năm học đó."
        ),
    )
    args = parser.parse_args(argv)

    # Truyền cả hai là mâu thuẫn ý định. Im lặng chọn một bên sẽ dẫn tới ca tệ
    # nhất: người gõ `--dry-run --apply` tưởng mình đang xem trước.
    if args.apply and args.dry_run:
        parser.error("Không truyền đồng thời --apply và --dry-run.")

    # ⚠️ batch-size <= 0 là lỗi VÔ HIỆU HOÁ HÀNG LOẠT, không phải lỗi nhỏ.
    # `range(0, 381, -1)` và `range(0, 381, 0)` đều không sinh vòng lặp nào, nên
    # KHÔNG hồ sơ nào được ghi — rồi bước hạ cờ vẫn chạy và coi toàn bộ danh
    # sách là "không còn trong nguồn". Lượt đó kết thúc `completed`, thoát 0, và
    # nhìn từ ngoài y hệt một lần chạy thành công.
    if args.batch_size <= 0:
        parser.error(
            f"--batch-size phải là số nguyên dương, nhận được {args.batch_size}."
        )

    return args


async def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    supabase_url = _require_env("DORM_SUPABASE_URL")
    supabase_key = _require_env("DORM_SUPABASE_SECRET_KEY")

    if args.apply:
        # Chỉ ràng khi thực sự GHI: một lần xem trước chỉ-đọc không cần khai
        # báo cấu hình nguồn, và bắt nó khai báo chỉ khiến người ta bỏ qua bước
        # xem trước — mà bước xem trước chính là thứ chặn được lần ghi sai.
        assert_source_database_matches()
        _install_stop_handlers()

    # Lớp 2 và 3 của hàng rào nguồn chạy TRONG transaction chỉ-đọc, trước khi
    # đọc hàng nào — xem ``assert_live_source_matches``.
    rows = await fetch_cohort(args.academic_year, verify_source=args.apply)
    # Chỉ log SỐ ĐẾM. Tên, số điện thoại, mã hồ sơ của người học không đi vào
    # log — log thường được gom về nơi khác và giữ lại lâu hơn ta nghĩ.
    #
    # ``excluded_statuses`` đi kèm để nhật ký tự trả lời được câu hỏi hay gặp
    # nhất khi đối soát: "vì sao em này không có trong danh sách KTX".
    log.info(
        "dorm_sync_cohort_loaded",
        academic_year=args.academic_year,
        source_count=len(rows),
        atypical_count=count_atypical_statuses(rows),
        excluded_statuses=describe_excluded_statuses(),
    )

    # ⚠️ Nguồn RỖNG + ``--apply`` = hạ cờ TOÀN BỘ học viên của năm học đó.
    #
    # Đây là cùng một kiểu hỏng với ``--batch-size 0``, chỉ khác đường vào: gõ
    # nhầm năm, năm chưa mở, hay một thay đổi phía QLTS làm vị từ cohort trả
    # rỗng. Mọi hàng rào phía database đều lọt vì các con số đều bằng 0 và khớp
    # nhau, nên lượt kết thúc ``completed``, thoát 0, nhìn y hệt một lần chạy
    # thành công — trong khi cả năm học vừa bị đánh dấu không còn đủ điều kiện.
    #
    # "Năm đó thật sự không còn ai" là ca có thật nhưng hiếm; nó phải được gõ ra
    # tường minh chứ không phải là hành vi mặc định.
    if args.apply and not rows and not args.allow_empty_cohort:
        print(
            f"✗ Nguồn QLTS không có hồ sơ nào cho năm {args.academic_year}.\n"
            "  Ghi tiếp sẽ HẠ CỜ ĐỦ ĐIỀU KIỆN của toàn bộ học viên năm này ở hệ "
            "KTX.\n"
            "  Kiểm lại --academic-year. Nếu đúng là muốn vậy, truyền thêm "
            "--allow-empty-cohort.",
            file=sys.stderr,
        )
        return 1

    try:
        api = DormApi(supabase_url, supabase_key)
    except ValueError as exc:
        # Cấu hình sai đích đến — dừng trước khi mở kết nối, in gọn thay vì ném
        # traceback: người vận hành cần sửa biến môi trường, không cần ngăn xếp.
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    async with api:
        if not args.apply:
            # Mấy con số này là thứ đáng nhìn nhất trước khi ghi: bao nhiêu
            # người sẽ BỊ CHẶN xếp phòng (giới tính không rõ), bao nhiêu người
            # hiện ra không kèm ngành, và bao nhiêu hồ sơ đã đóng tiền nhưng vẫn
            # đang được xét (bất thường — nằm trong cohort là cố ý).
            existing = await api.count_students(args.academic_year)
            unknown_gender = sum(
                1 for r in rows if normalize_gender(r.source_gender_raw) == "unknown"
            )
            no_program = sum(1 for r in rows if r.program_name is None)

            # Ba con số về liên hệ. Cán bộ KTX làm việc bằng cách GỌI ĐIỆN, nên
            # "bao nhiêu em không gọi được" là thứ phải biết TRƯỚC khi ghi, chứ
            # không phải phát hiện lúc ngồi bấm số.
            payloads = [build_student_payload(r, sync_run_id=0) for r in rows]
            # "Không có số NÀO" — cả hai ô đều trống. Chỉ đếm ô chính sẽ báo
            # nhầm những em chỉ khai số phụ là không liên hệ được, trong khi họ
            # gọi được.
            khong_co_so = sum(
                1
                for p in payloads
                if p["contact_phone"] is None and p["contact_phone2"] is None
            )
            co_so_phu = sum(1 for p in payloads if p["contact_phone2"] is not None)
            # SỐ bị loại vì vượt trần (không phải số HỒ SƠ) — đếm trên cả hai ô.
            # Đây là ca im lặng nhất: dữ liệu CÓ mà vẫn không gọi được ai.
            #
            # Đếm thẳng trên giá trị nguồn, không suy từ payload: một ô phụ bị
            # bỏ vì TRÙNG số chính cũng cho `None` ở payload, và gộp nó vào đây
            # sẽ báo "quá dài" cho một dữ liệu hoàn toàn bình thường.
            so_qua_dai = sum(
                1
                for r in rows
                for cot in ("contact_phone", "contact_phone2")
                if len(str(getattr(r, cot, None) or "").strip()) > _MAX_PHONE_LEN
            )

            print("── XEM TRƯỚC (không ghi gì) ─────────────────────────")
            print(f"  Năm học              : {args.academic_year}")
            print(f"  Trong nguồn QLTS     : {len(rows)}")
            print(
                "  Đang có ở hệ KTX     : "
                f"{existing if existing is not None else 'không đếm được'}"
            )
            print(f"  Không rõ giới tính   : {unknown_gender}")
            print(f"  Chưa chốt ngành      : {no_program}")
            print(f"  Hồ sơ vẫn đang xét   : {count_atypical_statuses(rows)}")
            print(f"  Không có số liên hệ  : {khong_co_so}")
            print(f"  Có số phụ            : {co_so_phu}")
            print(f"  Số bị bỏ vì quá dài  : {so_qua_dai}")
            print("\n  Truyền --apply để thực sự ghi.")
            return 0

        # Dấu riêng cho lần chạy này: nếu phản hồi của bước mở lượt bị mất, đây
        # là thứ duy nhất cho phép nhận lại đúng hàng mình vừa tạo.
        #
        # In RA MÀN HÌNH trước khi gọi: nếu cả lời gọi lẫn lần đọc phục hồi đều
        # hỏng, đây là thứ người vận hành cầm đi tra database — mà lúc đó thì
        # không còn gì in ra được nữa.
        client_token = args.client_token or uuid.uuid4().hex
        print(f"  Dấu lượt chạy: {_client_note(client_token)}")

        try:
            run_id = await api.open_sync_run(
                args.academic_year, client_token, raw_count=len(rows)
            )
        except RuntimeError as exc:
            # Chưa mở được lượt thì chưa có gì để dọn. In gọn thay vì ném
            # traceback: người vận hành cần biết PHẢI LÀM GÌ, không cần ngăn xếp.
            print(f"✗ {exc}", file=sys.stderr)
            return 1

        log.info("dorm_sync_run_opened", run_id=run_id, client_token=client_token)

        # MỘT mốc thời gian cho cả lượt: mọi hàng của cùng một lượt phải mang
        # cùng ``synced_at``, nếu không thì "đồng bộ lần cuối lúc nào" trở thành
        # một dải giờ trải theo tốc độ chạy của từng lô.
        synced_at = datetime.now(timezone.utc).isoformat()

        upserted = 0
        blocked = 0
        try:
            for start in range(0, len(rows), args.batch_size):
                # Dừng GIỮA hai lô, không dừng giữa một lô: mỗi lô là một lời
                # gọi, dừng ở đây để lại trạng thái rõ ràng để đóng sổ.
                if _stop_requested:
                    raise RuntimeError(
                        "Người vận hành yêu cầu dừng trước khi ghi hết nguồn."
                    )

                batch = rows[start : start + args.batch_size]
                da_ghi, bi_chan = await api.upsert_students(
                    run_id,
                    [build_student_payload(r, run_id, synced_at) for r in batch],
                )

                # ⚠️ Đối soát TỪNG LÔ, không đợi tới cuối. Lệch nghĩa là RPC bỏ
                # sót hàng trong im lặng — và hai con số này đi thẳng vào phép
                # kiểm ``raw = source + blocked`` ở bước hạ cờ, nên phát hiện
                # muộn đồng nghĩa với hạ cờ theo một con số sai.
                if da_ghi + bi_chan != len(batch):
                    raise RuntimeError(
                        f"Lô {start // args.batch_size + 1}: gửi {len(batch)} hàng "
                        f"nhưng database báo ghi {da_ghi} + chặn {bi_chan}. "
                        "Dừng trước khi hạ cờ."
                    )

                upserted += da_ghi
                blocked += bi_chan
                log.info(
                    "dorm_sync_batch_done",
                    upserted=upserted,
                    blocked=blocked,
                    total=len(rows),
                )

            # ⚠️ Kiểm LẠI ngay trước bước phá huỷ. Vòng lặp chỉ nhìn cờ ở ĐẦU mỗi
            # lô, nên hai ca đi thẳng tới đây mà không qua lần kiểm nào: tín hiệu
            # tới trong lúc chạy lô CUỐI, và cohort rỗng (``--allow-empty-cohort``
            # → vòng lặp chạy 0 lần). Cả hai đều kết thúc bằng việc hạ cờ SAU KHI
            # người vận hành đã bấm dừng — ca thứ hai hạ cờ cả năm học.
            if _stop_requested:
                raise RuntimeError(
                    "Người vận hành yêu cầu dừng trước khi hạ cờ đủ điều kiện."
                )

            # CHỈ tới đây — sau khi TOÀN BỘ nguồn đã ghi xong — mới được hạ cờ.
            # Hạ cờ và đóng lượt đi cùng nhau trong một transaction phía database
            # (xem `finalize_sync_run`), nên không còn khoảng trống ở giữa.
            # ⚠️ ``source_count`` là EFFECTIVE total — số hàng thực sự phải ghi
            # sau khi trừ những hàng bị chặn tái tạo — KHÔNG phải số hàng nguồn.
            # Truyền ``len(rows)`` vào đây khi có dù chỉ một hàng bị chặn sẽ làm
            # guard "chưa ghi hết nguồn" phía database từ chối hạ cờ, và thông
            # điệp lúc đó nói về một sự cố không có thật.
            effective = len(rows) - blocked
            deactivated = await api.finalize_sync_run(
                run_id, source_count=effective, upserted_count=upserted
            )

        # ⚠️ ``BaseException``, không phải ``Exception``. ``KeyboardInterrupt``,
        # ``SystemExit`` và ``CancelledError`` không phải ``Exception``, nên bắt
        # hẹp hơn sẽ để chúng đi vòng qua toàn bộ phần đóng sổ dưới đây và bỏ
        # lại một lượt treo ``running`` — thứ khoá cứng năm học đó ở hệ KTX.
        # ``_install_stop_handlers`` là đường xử lý CHÍNH cho Ctrl-C/SIGTERM;
        # nhánh này là lưới cho những gì lọt qua nó.
        except BaseException as exc:
            # Lỗi phía client KHÔNG đồng nghĩa với việc database chưa làm gì.
            # Hỏi lại trạng thái thật thay vì tuyên bố bừa.
            outcome, run = await api.reconcile_after_failure(
                run_id, len(rows), upserted
            )

            if outcome == "finalized":
                # Database đã hoàn tất; chỉ phản hồi không về tới đây. Báo thất
                # bại trong ca này là ghi sai sổ sách.
                log.info("dorm_sync_completed_despite_client_error", run_id=run_id)
                print("── ĐÃ ĐỒNG BỘ (phản hồi tới muộn) ──────────────────")
                print(f"  Năm học            : {args.academic_year}")
                print(f"  Ghi/cập nhật       : {upserted}")
                print(
                    f"  Hạ cờ đủ điều kiện : "
                    f"{(run or {}).get('deactivated_count', '?')}"
                )
                return 0

            # ⚠️ KHÔNG đưa nội dung lỗi vào log có cấu trúc: xem `_raise_for_status`.
            log.error(
                "dorm_sync_failed",
                run_id=run_id,
                upserted_before_failure=upserted,
                outcome=outcome,
            )
            if _stop_requested or isinstance(
                exc, (KeyboardInterrupt, asyncio.CancelledError)
            ):
                # Ngắt theo yêu cầu: ``str(exc)`` của hai loại này thường rỗng,
                # in ra sẽ thành "✗ Đồng bộ thất bại:" cụt lủn.
                print("✗ Đồng bộ DỪNG theo yêu cầu người vận hành.", file=sys.stderr)
            else:
                print(f"✗ Đồng bộ thất bại: {exc}", file=sys.stderr)

            if outcome == "marked_failed":
                print(
                    "  → Lượt đã được đánh dấu 'failed'. KHÔNG ai bị hạ cờ "
                    "(transaction phía database đã rollback).",
                    file=sys.stderr,
                )
            else:
                # Không đọc/ghi được trạng thái. Tuyệt đối không tuyên bố
                # "không hạ cờ ai" — ta không biết điều đó có đúng hay không.
                print(
                    f"  ⚠️ KHÔNG XÁC ĐỊNH được trạng thái lượt {run_id}. "
                    "Có thể dữ liệu đã thay đổi.",
                    file=sys.stderr,
                )
                print(
                    "  → Kiểm bảng sync_runs và students TRƯỚC khi chạy lại. "
                    "Lượt còn 'running' sẽ chặn mọi lần chạy sau cho năm này.",
                    file=sys.stderr,
                )
            return 1

    print("── ĐÃ ĐỒNG BỘ ──────────────────────────────────────")
    print(f"  Năm học            : {args.academic_year}")
    print(f"  Nguồn (raw)        : {len(rows)}")
    print(f"  Bị chặn tái tạo    : {blocked}")
    print(f"  Ghi/cập nhật       : {upserted}")
    print(f"  Hạ cờ đủ điều kiện : {deactivated}")
    return 0


if __name__ == "__main__":
    # ⚠️ PHẢI thoát bằng đúng mã trả về. ``asyncio.run(main())`` trần luôn thoát
    # 0, nên một lượt đồng bộ hỏng vẫn báo thành công với người gọi và với CI.
    sys.exit(asyncio.run(main()))
