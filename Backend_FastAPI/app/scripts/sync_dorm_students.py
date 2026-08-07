"""Đồng bộ cohort "đã đóng học phí HK1" sang hệ quản lý ký túc xá (Supabase).

MỘT CHIỀU, CHỈ ĐỌC phía QLTS. Không có đường nào trong file này ghi vào QLTS.

Vị từ cohort lấy từ ``repositories/dorm_export_repository.select_paid_hk1_cohort``
— cùng hàm mà test lock-in đang canh. KHÔNG viết lại điều kiện tại đây: hai hệ
nói hai danh sách khác nhau là kiểu sai không có gì nổ ra.

Usage (ba cờ dưới đây đều BẮT BUỘC — xem cảnh báo bên dưới):

    docker compose -f docker-compose.yml run --rm --no-deps --entrypoint python \\
        -v <duong-dan>/sync_dorm_students.py:/app/app/scripts/sync_dorm_students.py \\
        --env-from-file <file-secret-chi-tren-may-quan-tri> \\
        backend -m app.scripts.sync_dorm_students \\
            --academic-year 2026 --dry-run

⚠️ ``-f docker-compose.yml`` BẮT BUỘC. Thiếu nó, Compose tự nạp
``docker-compose.override.yml`` — file đó đặt ``APP_ENV=development``, trỏ
``DATABASE_URL`` sang database dev, và bind-mount TOÀN BỘ source. Chạy lệnh đồng
bộ production trong cấu hình đó là đọc nhầm nguồn ngay từ đầu.

⚠️ ``-v ...sync_dorm_students.py`` BẮT BUỘC, và mount ĐÚNG MỘT FILE. File này
cố ý bị loại khỏi image (xem ``.dockerignore``) nên không có sẵn trong
container; còn hai module nó dùng — ``repositories/dorm_export_repository`` và
``constants/hk1_fee`` — thì ĐÃ được deploy trong image. Mount cả cây source để
"cho tiện" sẽ chạy code đang checkout trên máy, không phải code đã qua CI và
deploy.

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
import signal
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog

from app.repositories.dorm_export_repository import (
    count_atypical_statuses,
    describe_excluded_statuses,
)
from app.services.dorm_sync_config import DormSyncConfig
from app.utils.exceptions import DormSyncConfigError, DormSyncGuardError

# 🔴 IMPORT LẠI, không chép. Lõi nằm ở service để CLI và API dùng CHUNG một
# đường; hai bản sao sẽ lệch nhau ngay lần sửa đầu.
#
# Re-export ĐỦ tên public: mọi thứ đang import từ module này — kể cả bộ test
# CLI — phải tiếp tục thấy CÙNG đối tượng, không phải một bản sao thứ hai.
from app.services.dorm_sync_service import (  # noqa: F401
    DormApi,
    _DANG_MA_SQLSTATE,
    _GENDER_MAP,
    _LOOPBACK_HOSTS,
    _MAX_PHONE_LEN,
    _THONG_DIEP_THEO_MA,
    _TRANG_THAI_DA_DONG,
    _TRANG_THAI_SYNC_RUN,
    _TRAN_LO,
    _chuan_hoa_dinh_danh_khai_bao,
    _client_note,
    _doc_hang_sync_run,
    _doc_so_lieu_lo,
    _ghep_dinh_danh,
    assert_live_source_matches,
    assert_payload_contract,
    assert_source_database_matches,
    assert_target_project_matches,
    assert_transport_is_encrypted,
    build_student_payload,
    chuan_hoa_so,
    database_identity_from_url,
    doc_ma_loi,
    fetch_cohort,
    normalize_gender,
)

log = structlog.get_logger(__name__)


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
        help=f"Số bản ghi mỗi lượt gửi (mặc định 200, tối đa {_TRAN_LO}).",
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

    # ⚠️ Trần PHẢI trùng con số của RPC (`upsert_students_batch` từ chối lô > 500
    # bằng P0111). Không chặn ở đây thì `--batch-size 501` MỞ LƯỢT trước rồi mới
    # hỏng ở lô đầu — để lại một lượt phải đóng sổ vì một con số gõ sai. Hai đầu
    # lệch nhau là kiểu lỗi chỉ lộ ra ở lần chạy thật.
    if args.batch_size > _TRAN_LO:
        parser.error(
            f"--batch-size tối đa {_TRAN_LO} (trần của RPC upsert_students_batch), "
            f"nhận được {args.batch_size}."
        )

    return args



def _in_thong_bao_phuc_hoi(api: Any) -> None:
    """In lại ba thông báo phục hồi lượt cũ mà lõi ghi dưới dạng có cấu trúc.

    🔴 Lõi không được in: nó dùng chung cho web, nơi stdout là log tiến trình
    chứ không phải màn hình của người vận hành. Nhưng người vận hành thì phải
    thấy ĐỦ ba tình huống — lượt cũ còn chạy, lượt cũ hoá ra đã xong, lượt cũ
    đã đóng sổ — vì mỗi tình huống đòi một quyết định khác nhau.
    """
    for tb in getattr(api, "thong_bao_phuc_hoi", []):
        loai = tb.get("loai")
        run_id = tb.get("run_id")
        if loai == "lut_cu_dang_chay":
            print(
                f"  ⚠️ Có lượt #{run_id} đang chạy mang dấu "
                f"'{tb.get('dau')}' của lần chạy TRƯỚC."
            )
        elif loai == "lut_cu_da_hoan_tat":
            # RPC cố ý KHÔNG hạ `completed` xuống `failed`. Lượt trước đã xong
            # thật; nói rõ để người vận hành biết mình đang chạy lượt thứ hai
            # chứ không phải sửa một lượt hỏng.
            print(
                f"  ⚠️ Lượt #{run_id} hoá ra đã HOÀN TẤT, không phải hỏng. "
                "Mở lượt mới — đây là một lần đồng bộ nữa, không phải phục hồi."
            )
        elif loai == "lut_cu_da_dong_so":
            print(f"  Đã đóng sổ lượt #{run_id} (failed). Mở lượt mới.")
    if getattr(api, "thong_bao_phuc_hoi", None):
        api.thong_bao_phuc_hoi.clear()


async def main(argv: Optional[List[str]] = None) -> int:
    """Vỏ dòng lệnh: giữ NGUYÊN mã thoát cũ dù lõi nay ném exception.

    🔴 Lõi đã chuyển sang ``app/services/dorm_sync_service.py`` và ở đó những
    chỗ trước kia ``sys.exit(2)`` nay ném ``DormSyncConfigError`` /
    ``DormSyncGuardError`` — service chạy trong web worker, mà ``sys.exit`` ở
    đó giết luôn request của người khác.

    Người vận hành thì không được thấy khác biệt nào: cùng thông điệp ra
    stderr, cùng mã thoát 2. Đây là đường thoát vận hành duy nhất khi ứng dụng
    sập, nên hành vi của nó là hợp đồng.
    """
    try:
        return await _chay(argv)
    except (DormSyncConfigError, DormSyncGuardError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2


async def _chay(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    # Adapter môi trường của vỏ CLI. Lõi KHÔNG đọc os.environ nữa — nó chạy
    # trong web worker, nơi cấu hình tới từ Settings chứ không từ shell.
    cau_hinh = DormSyncConfig.from_environment(doi_dinh_danh_nguon=args.apply)
    supabase_url = cau_hinh.supabase_url
    supabase_key = cau_hinh.supabase_secret_key

    if args.apply:
        # Chỉ ràng khi thực sự GHI: một lần xem trước chỉ-đọc không cần khai
        # báo cấu hình nguồn, và bắt nó khai báo chỉ khiến người ta bỏ qua bước
        # xem trước — mà bước xem trước chính là thứ chặn được lần ghi sai.
        assert_source_database_matches(
            cau_hinh.source_db, cau_hinh.source_system_id
        )
        _install_stop_handlers()

    # Lớp 2 và 3 của hàng rào nguồn chạy TRONG transaction chỉ-đọc, trước khi
    # đọc hàng nào — xem ``assert_live_source_matches``.
    rows = await fetch_cohort(
        args.academic_year,
        verify_source=args.apply,
        expected_source_db=cau_hinh.source_db,
        expected_system_id=cau_hinh.source_system_id,
    )
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

    # 🔴 Cổng hợp đồng — TRƯỚC khi mở lượt, và chạy cả ở chế độ xem trước.
    #
    # Xem trước cũng phải đỏ: nếu script và repository lệch phiên bản thì bản
    # xem trước in ra những con số KHÔNG phải thứ `--apply` sẽ ghi, và người
    # vận hành duyệt một thứ rồi chạy một thứ khác.
    try:
        assert_payload_contract(rows)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

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
        api = DormApi(
            supabase_url,
            supabase_key,
            expected_project_ref=cau_hinh.target_project_ref,
        )
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
            # Chất lượng nguồn của chiều TRÌNH ĐỘ. Con số này phải nhìn được
            # TRƯỚC `--apply`: cột đó nuôi bảng dùng để quyết định quy mô đầu
            # tư, và một nguồn hỏng ở đây cho ra bảng toàn "(chưa rõ trình độ)"
            # — vẫn vẽ ra được, vẫn cộng ra tổng đúng, chỉ là vô dụng.
            no_degree = sum(1 for r in rows if r.degree_level is None)

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
            print(f"  Chưa rõ trình độ     : {no_degree}")
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
        # ⚠️ Token TRUYỀN TAY và token TỰ SINH có ý nghĩa khác nhau khi gặp một
        # lượt cũ mang cùng dấu — xem `_nhan_lai_hay_thay_the`. Phân biệt bằng
        # `args.client_token`, không phải bằng `client_token` (đã bị `or` lấp).
        la_lan_chay_lai = args.client_token is not None
        client_token = args.client_token or uuid.uuid4().hex
        print(f"  Dấu lượt chạy: {_client_note(client_token)}")
        if la_lan_chay_lai:
            print(
                "  (dấu do người vận hành truyền vào — lượt cũ mang dấu này sẽ "
                "được ĐÓNG SỔ rồi mở lượt mới, không nhận lại)"
            )

        try:
            run_id = await api.open_sync_run(
                args.academic_year,
                client_token,
                raw_count=len(rows),
                la_lan_chay_lai=la_lan_chay_lai,
            )
            _in_thong_bao_phuc_hoi(api)
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
            outcome, run = await api.reconcile_after_failure(run_id)

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
