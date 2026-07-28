"""Đồng bộ cohort "đã đóng học phí HK1" sang hệ quản lý ký túc xá (Supabase).

MỘT CHIỀU, CHỈ ĐỌC phía QLTS. Không có đường nào trong file này ghi vào QLTS.

Vị từ cohort lấy từ ``repositories/dorm_export_repository.select_paid_hk1_cohort``
— cùng hàm mà test lock-in đang canh. KHÔNG viết lại điều kiện tại đây: hai hệ
nói hai danh sách khác nhau là kiểu sai không có gì nổ ra.

Usage (BẮT BUỘC override entrypoint — xem cảnh báo bên dưới):

    docker compose run --rm --no-deps --entrypoint python \\
        --env-file <file-secret-chi-tren-may-quan-tri> \\
        backend -m app.scripts.sync_dorm_students \\
            --academic-year 2026 --dry-run

⚠️ PHẢI override ``--entrypoint``: ``docker-entrypoint.sh`` chạy
``alembic upgrade head`` TRƯỚC command. Chạy dạng thường với ``DATABASE_URL`` trỏ
tunnel production đồng nghĩa với việc nâng cấp lược đồ database thật.

⚠️ Mặc định là DRY-RUN. Muốn ghi phải truyền ``--apply`` tường minh.

⚠️ File này CỐ Ý bị loại khỏi image production (xem ``.dockerignore``). Nó hạ
được cờ đủ-điều-kiện của cả một khoá học, nên không được nằm sẵn trong container
đang chạy — chỉ chạy qua bind-mount trên máy quản trị.

Biến môi trường (KHÔNG có giá trị mặc định — thiếu là dừng):
    DORM_SUPABASE_URL         URL project Supabase của hệ KTX
    DORM_SUPABASE_SECRET_KEY  khoá secret; chỉ sống trên máy quản trị
    DORM_SYNC_SOURCE_ENV      môi trường nguồn mà đích này chấp nhận
                              (``production`` | ``development`` | …). Phải khớp
                              ``APP_ENV`` của stack đang chạy — xem
                              ``assert_source_env_matches``. Chỉ bắt buộc khi
                              ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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

    return {
        "qlts_profile_id": row.qlts_profile_id,
        "full_name": row.full_name,
        "source_gender_raw": row.source_gender_raw,
        "normalized_gender": normalize_gender(row.source_gender_raw),
        "program_name": row.program_name,
        "academic_year": row.academic_year,
        "officer_qlts_id": row.officer_qlts_id,
        "unit_id": row.unit_id,
        # Có mặt trong nguồn = còn đủ điều kiện. Đây cũng là đường KÍCH HOẠT LẠI
        # cho người từng bị hạ cờ rồi quay lại danh sách.
        "source_eligible": True,
        "last_seen_sync_id": sync_run_id,
        "synced_at": synced_at,
    }


class DormApi:
    """Lớp mỏng gọi PostgREST của Supabase.

    Dùng REST thay vì nối thẳng Postgres để không phải mở cổng database của hệ
    KTX ra ngoài.
    """

    def __init__(self, base_url: str, secret_key: str) -> None:
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

    async def open_sync_run(self, academic_year: int) -> int:
        response = await self._client.post(
            f"{self._base}/sync_runs",
            headers={**self._headers, "Prefer": "return=representation"},
            json={"academic_year": academic_year, "status": "running"},
        )
        if response.status_code == 409:
            raise RuntimeError(
                f"Đã có một lượt đồng bộ ĐANG CHẠY cho năm {academic_year}. "
                "Chờ nó kết thúc hoặc đánh dấu failed trước khi chạy lượt mới."
            )
        self._raise_for_status(response, "Mở lượt đồng bộ")
        return response.json()[0]["id"]

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

    async def upsert_students(self, rows: List[Dict[str, Any]]) -> None:
        response = await self._client.post(
            f"{self._base}/students",
            headers={
                **self._headers,
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            params={"on_conflict": "qlts_profile_id"},
            json=rows,
        )
        self._raise_for_status(response, "Ghi danh sách học viên")

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


async def fetch_cohort(academic_year: int) -> List[Any]:
    """Đọc cohort từ QLTS trong transaction CHỈ ĐỌC."""
    async with AsyncSessionLocal() as session:
        # Chốt chặn ở tầng database: kể cả khi có lỗi lập trình khiến một câu
        # ghi lọt vào, transaction sẽ từ chối thay vì sửa dữ liệu tuyển sinh.
        await session.execute(text("SET TRANSACTION READ ONLY"))
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


def assert_source_env_matches() -> None:
    """Hai đầu phải cùng một môi trường, nếu không thì dừng.

    ⚠️ Đây là hàng rào cho ca nguy hiểm nhất của công cụ này: nguồn trỏ một
    môi trường còn đích trỏ môi trường khác. Chạy stack DEV (cohort vài chục
    hồ sơ thử) với file secret của KTX THẬT sẽ ghi đè danh sách thật rồi hạ cờ
    toàn bộ những ai không có trong nguồn dev — mà lượt đó vẫn kết thúc
    ``completed`` và thoát 0.

    ``APP_ENV`` mô tả NGUỒN (do stack backend đang chạy quyết định);
    ``DORM_SYNC_SOURCE_ENV`` mô tả nguồn mà ĐÍCH chấp nhận và nằm trong chính
    file secret của hệ KTX. Khớp nhau mới đi tiếp. Không có mặc định: thiếu
    biến là dừng, vì một hàng rào tự đoán giá trị thì không phải hàng rào.
    """
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    expected = _require_env("DORM_SYNC_SOURCE_ENV").strip().lower()

    if app_env != expected:
        print(
            f"✗ Từ chối ghi: nguồn QLTS đang ở môi trường '{app_env}' nhưng file "
            f"cấu hình của hệ KTX khai báo DORM_SYNC_SOURCE_ENV='{expected}'.\n"
            "  Hai đầu lệch nhau nghĩa là đang đẩy dữ liệu của môi trường này "
            "sang hệ của môi trường khác.",
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
        # báo môi trường, và bắt nó khai báo chỉ khiến người ta bỏ qua bước xem.
        assert_source_env_matches()
        _install_stop_handlers()

    rows = await fetch_cohort(args.academic_year)
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

    async with DormApi(supabase_url, supabase_key) as api:
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
            print("\n  Truyền --apply để thực sự ghi.")
            return 0

        try:
            run_id = await api.open_sync_run(args.academic_year)
        except RuntimeError as exc:
            # Chưa mở được lượt thì chưa có gì để dọn. In gọn thay vì ném
            # traceback: người vận hành cần biết PHẢI LÀM GÌ, không cần ngăn xếp.
            print(f"✗ {exc}", file=sys.stderr)
            return 1

        log.info("dorm_sync_run_opened", run_id=run_id)

        # MỘT mốc thời gian cho cả lượt: mọi hàng của cùng một lượt phải mang
        # cùng ``synced_at``, nếu không thì "đồng bộ lần cuối lúc nào" trở thành
        # một dải giờ trải theo tốc độ chạy của từng lô.
        synced_at = datetime.now(timezone.utc).isoformat()

        upserted = 0
        try:
            for start in range(0, len(rows), args.batch_size):
                # Dừng GIỮA hai lô, không dừng giữa một lô: mỗi lô là một lời
                # gọi, dừng ở đây để lại trạng thái rõ ràng để đóng sổ.
                if _stop_requested:
                    raise RuntimeError(
                        "Người vận hành yêu cầu dừng trước khi ghi hết nguồn."
                    )

                batch = rows[start : start + args.batch_size]
                await api.upsert_students(
                    [build_student_payload(r, run_id, synced_at) for r in batch]
                )
                upserted += len(batch)
                log.info("dorm_sync_batch_done", upserted=upserted, total=len(rows))

            # CHỈ tới đây — sau khi TOÀN BỘ nguồn đã ghi xong — mới được hạ cờ.
            # Hạ cờ và đóng lượt đi cùng nhau trong một transaction phía database
            # (xem `finalize_sync_run`), nên không còn khoảng trống ở giữa.
            deactivated = await api.finalize_sync_run(
                run_id, source_count=len(rows), upserted_count=upserted
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
    print(f"  Ghi/cập nhật       : {upserted}")
    print(f"  Hạ cờ đủ điều kiện : {deactivated}")
    return 0


if __name__ == "__main__":
    # ⚠️ PHẢI thoát bằng đúng mã trả về. ``asyncio.run(main())`` trần luôn thoát
    # 0, nên một lượt đồng bộ hỏng vẫn báo thành công với người gọi và với CI.
    sys.exit(asyncio.run(main()))
