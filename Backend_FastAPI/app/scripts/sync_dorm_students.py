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

Biến môi trường (KHÔNG có giá trị mặc định — thiếu là dừng):
    DORM_SUPABASE_URL         URL project Supabase của hệ KTX
    DORM_SUPABASE_SECRET_KEY  khoá secret; chỉ sống trên máy quản trị
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
import structlog
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.repositories.dorm_export_repository import select_paid_hk1_cohort

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
    """Quy giới tính nguồn về ``male`` | ``female`` | ``unknown``."""
    if not raw:
        return "unknown"
    return _GENDER_MAP.get(raw.strip().lower(), "unknown")


def build_student_payload(row: Any, sync_run_id: int) -> Dict[str, Any]:
    """Dựng bản ghi gửi sang Supabase.

    ⚠️ CHỈ gồm các cột thuộc về NGUỒN. Cố ý không đụng tới:
      * ``placement_gender_override`` và các cột đi kèm — đó là quyết định của
        con người, lượt đồng bộ ghi đè lên là xoá mất dấu vết;
      * ``dorm_registrations`` / ``room_assignments`` — dữ liệu do phía KTX tạo.

    PostgREST chỉ cập nhật những cột được gửi lên, nên không liệt kê ở đây đồng
    nghĩa với giữ nguyên.
    """
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
        # KHÔNG in headers hay URL đầy đủ: chúng mang khoá secret.
        raise RuntimeError(
            f"{action} thất bại (HTTP {response.status_code}): {response.text[:300]}"
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

    async def close_sync_run(
        self, run_id: int, status: str, counts: Dict[str, int]
    ) -> None:
        response = await self._client.patch(
            f"{self._base}/sync_runs",
            headers=self._headers,
            params={"id": f"eq.{run_id}"},
            json={
                "status": status,
                "completed_at": "now()",
                **counts,
            },
        )
        self._raise_for_status(response, "Đóng lượt đồng bộ")

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

    async def count_students(self, academic_year: int) -> int:
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
        content_range = response.headers.get("content-range", "*/0")
        return int(content_range.split("/")[-1])

    async def deactivate_missing(self, academic_year: int, run_id: int) -> int:
        """Hạ cờ đủ-điều-kiện cho người KHÔNG xuất hiện ở lượt này.

        ⚠️ Chỉ được gọi SAU KHI toàn bộ dữ liệu nguồn đã ghi xong. Gọi sớm —
        hoặc gọi khi lượt tải hỏng giữa chừng — sẽ đánh dấu cả nhóm chưa kịp đọc
        tới là "đã rời khỏi danh sách".

        ⚠️ Chỉ đụng cờ nguồn. Người đang Ở KÝ TÚC XÁ vẫn giữ nguyên chỗ; phía
        KTX hiện cảnh báo và để quản lý quyết định.
        """
        response = await self._client.patch(
            f"{self._base}/students",
            headers={**self._headers, "Prefer": "return=representation"},
            params={
                "academic_year": f"eq.{academic_year}",
                "or": f"(last_seen_sync_id.is.null,last_seen_sync_id.neq.{run_id})",
                "source_eligible": "eq.true",
                "select": "qlts_profile_id",
            },
            json={"source_eligible": False},
        )
        self._raise_for_status(response, "Hạ cờ đủ điều kiện")
        return len(response.json())


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
    args = parser.parse_args(argv)

    # Truyền cả hai là mâu thuẫn ý định. Im lặng chọn một bên sẽ dẫn tới ca tệ
    # nhất: người gõ `--dry-run --apply` tưởng mình đang xem trước.
    if args.apply and args.dry_run:
        parser.error("Không truyền đồng thời --apply và --dry-run.")

    return args


async def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    supabase_url = _require_env("DORM_SUPABASE_URL")
    supabase_key = _require_env("DORM_SUPABASE_SECRET_KEY")

    rows = await fetch_cohort(args.academic_year)
    # Chỉ log SỐ ĐẾM. Tên, số điện thoại, mã hồ sơ của người học không đi vào
    # log — log thường được gom về nơi khác và giữ lại lâu hơn ta nghĩ.
    log.info(
        "dorm_sync_cohort_loaded",
        academic_year=args.academic_year,
        source_count=len(rows),
    )

    async with DormApi(supabase_url, supabase_key) as api:
        existing = await api.count_students(args.academic_year)

        if not args.apply:
            # Hai con số này là thứ đáng nhìn nhất trước khi ghi: chúng cho biết
            # sẽ có bao nhiêu người BỊ CHẶN xếp phòng (giới tính không rõ) và
            # bao nhiêu người hiện ra không kèm ngành.
            unknown_gender = sum(
                1 for r in rows if normalize_gender(r.source_gender_raw) == "unknown"
            )
            no_program = sum(1 for r in rows if r.program_name is None)

            print("── XEM TRƯỚC (không ghi gì) ─────────────────────────")
            print(f"  Năm học              : {args.academic_year}")
            print(f"  Trong nguồn QLTS     : {len(rows)}")
            print(f"  Đang có ở hệ KTX     : {existing}")
            print(f"  Không rõ giới tính   : {unknown_gender}")
            print(f"  Chưa chốt ngành      : {no_program}")
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

        upserted = 0
        try:
            for start in range(0, len(rows), args.batch_size):
                batch = rows[start : start + args.batch_size]
                await api.upsert_students(
                    [build_student_payload(r, run_id) for r in batch]
                )
                upserted += len(batch)
                log.info("dorm_sync_batch_done", upserted=upserted, total=len(rows))

            # CHỈ tới đây — sau khi TOÀN BỘ nguồn đã ghi xong — mới được hạ cờ.
            deactivated = await api.deactivate_missing(args.academic_year, run_id)

        except Exception as exc:
            # Lượt hỏng giữa chừng: đánh dấu failed và TUYỆT ĐỐI không hạ cờ ai.
            await api.close_sync_run(
                run_id,
                "failed",
                {"source_count": len(rows), "upserted_count": upserted},
            )
            # ⚠️ KHÔNG đưa nội dung lỗi vào log có cấu trúc: thông điệp của
            # PostgREST có thể mang theo giá trị của hàng gây lỗi (tên người
            # học), mà log thường được gom về nơi khác và giữ rất lâu. Log chỉ
            # ghi ĐẾN ĐÂU thì hỏng; chi tiết in ra màn hình cho người đang chạy.
            log.error(
                "dorm_sync_failed",
                run_id=run_id,
                upserted_before_failure=upserted,
            )
            print(f"✗ Đồng bộ thất bại: {exc}", file=sys.stderr)
            print(
                "  → KHÔNG hạ cờ đủ-điều-kiện của ai. Chạy lại khi đã xử lý xong.",
                file=sys.stderr,
            )
            return 1

        await api.close_sync_run(
            run_id,
            "completed",
            {
                "source_count": len(rows),
                "upserted_count": upserted,
                "deactivated_count": deactivated,
            },
        )

    print("── ĐÃ ĐỒNG BỘ ──────────────────────────────────────")
    print(f"  Năm học            : {args.academic_year}")
    print(f"  Ghi/cập nhật       : {upserted}")
    print(f"  Hạ cờ đủ điều kiện : {deactivated}")
    return 0


if __name__ == "__main__":
    # ⚠️ PHẢI thoát bằng đúng mã trả về. ``asyncio.run(main())`` trần luôn thoát
    # 0, nên một lượt đồng bộ hỏng vẫn báo thành công với người gọi và với CI.
    sys.exit(asyncio.run(main()))
