# -*- coding: utf-8 -*-
"""Lõi đồng bộ QLTS → ký túc xá, dùng chung cho CLI và cho API.

🔴 Toàn bộ nội dung dưới đây được **DI CHUYỂN** từ
``app/scripts/sync_dorm_students.py``, không sao chép. Hai bản sao sẽ lệch nhau
ngay lần sửa đầu, và lệch ở đây nghĩa là hai hệ nói hai danh sách khác nhau —
kiểu sai không có gì nổ ra cho tới lúc ai đó bị hạ cờ oan.

``sync_dorm_students.py`` nay chỉ còn vỏ dòng lệnh (``parse_args``, ``main``,
xử lý tín hiệu, và mã thoát) và import lại mọi thứ từ đây.

⚠️ Khác biệt DUY NHẤT so với bản trong script: những chỗ trước đây ``print`` rồi
``sys.exit(2)`` nay **ném domain exception**. Service không được tự kết thúc
tiến trình — nó chạy trong web worker, và ``sys.exit`` ở đó giết luôn request
của người khác. Vỏ CLI bắt lại và giữ nguyên mã thoát 2.

⚠️ Hàng rào định danh nguồn (``assert_source_database_matches``,
``assert_live_source_matches``) GIỮ NGUYÊN hành vi: hỏi thẳng database
``current_database()`` và ``system_identifier``. ``APP_ENV`` chỉ là một nhãn
trong file env nên KHÔNG thay thế được — nó không phân biệt nổi production với
một bản clone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.repositories.dorm_export_repository import select_paid_hk1_cohort
from app.utils.exceptions import (
    DormSyncConfigError,
    DormSyncGuardError,
    DormSyncTargetMismatchError,
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


def assert_payload_contract(rows: List[Any]) -> None:
    """Mọi hàng nguồn phải mang ĐỦ các trường mà payload cần.

    🔴 Chạy TRƯỚC khi mở lượt đồng bộ, trên TOÀN BỘ hàng.

    Vì sao không để `build_student_payload` tự nổ: nó được gọi theo từng lô,
    sau khi lượt đã mở. Một `AttributeError` ở lô thứ ba để lại một lượt
    `running` với hai lô đã ghi — trạng thái nửa vời mà người vận hành phải đi
    dọn tay. Kiểm hết ở đây thì hoặc chạy trọn, hoặc chưa ghi gì.

    Vì sao không dùng `getattr(..., None)`: hàng thiếu thuộc tính nghĩa là
    script và repository lệch phiên bản (chạy bản script mới trên image backend
    cũ). Suy ra `None` rồi gửi đi là XOÁ dữ liệu đã có ở đầu kia — nhánh
    `do update` của `upsert_students_batch` ghi đè `degree_level` cho cả lô.
    Đã tái hiện: hàng "Trung cấp" + payload thiếu khoá → RPC trả thành công,
    giá trị thành NULL.

    ⚠️ Chỉ kiểm SỰ CÓ MẶT của thuộc tính, không kiểm giá trị. `degree_level =
    None` là hợp lệ và có thật: ngành chưa chốt, hoặc ngành thiếu FK trình độ
    bên QLTS.

    Raises:
        RuntimeError: khi có hàng thiếu trường — kèm TÊN TRƯỜNG và SỐ hàng, không
            kèm danh tính người học.
    """
    bat_buoc = (
        "qlts_profile_id",
        "full_name",
        "source_gender_raw",
        "program_name",
        "degree_level",
        # 🔴 Hai cột điện thoại nằm ĐÂY, không phải chỗ khác.
        #
        # Bản trước vá `degree_level` rồi để nguyên `getattr(..., None)` cho hai
        # cột này — tức chừa nguyên lỗ hổng vừa bịt, cho đúng những cột mà cán
        # bộ KTX dùng để GỌI ĐIỆN. `contact_phone2` mới có từ `20260729000001`,
        # nên "script mới trên image backend cũ" là ca có thật với chúng hơn cả
        # với `degree_level`.
        #
        # Guard P0122 phía KTX chỉ bắt buộc `degree_level`, nên nếu payload
        # thiếu khoá điện thoại thì RPC nhận, nhánh `do update` ghi
        # `contact_phone2 = null` cho CẢ LÔ, và lượt đồng bộ báo thành công.
        "contact_phone",
        "contact_phone2",
        "academic_year",
        "officer_qlts_id",
        "unit_id",
    )

    thieu: Dict[str, int] = {}
    for row in rows:
        for truong in bat_buoc:
            if not hasattr(row, truong):
                thieu[truong] = thieu.get(truong, 0) + 1

    if thieu:
        chi_tiet = ", ".join(f"{k} ({v} hàng)" for k, v in sorted(thieu.items()))
        raise RuntimeError(
            "Hàng nguồn thiếu trường mà payload cần: "
            f"{chi_tiet}. Script và repository đang lệch phiên bản — "
            "KHÔNG ghi tiếp, vì gửi giá trị rỗng sẽ xoá dữ liệu đã có ở hệ KTX."
        )


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

    # Truy cập THẲNG — cùng lý do với `degree_level` bên dưới. Hàng thiếu
    # thuộc tính đã bị `assert_payload_contract` chặn TRƯỚC khi mở lượt.
    lien_he = chuan_hoa_so(row.contact_phone)
    lien_he_phu = chuan_hoa_so(row.contact_phone2)
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
        # ⚠️ Đi CÙNG `program_name`, không tách. Cùng một tên ngành tồn tại ở
        # hai trình độ (xem `_resolved_degree_level_subquery`), nên thiếu cột
        # này thì phía KTX gộp hai chương trình khác nhau thành một dòng thống
        # kê — và dòng đó trông hoàn toàn bình thường.
        #
        # 🔴 Truy cập THẲNG, KHÔNG `getattr(..., None)`.
        #
        # Bản trước dùng `getattr` với mặc định `None` và gọi đó là fail-soft.
        # Nó không phải: hàng nguồn thiếu thuộc tính nghĩa là script và
        # repository lệch phiên bản, mà `None` ở đây đi thẳng vào nhánh
        # `do update` phía KTX và XOÁ trình độ của toàn bộ lô. Đã tái hiện: hàng
        # đang mang "Trung cấp", payload thiếu khoá, RPC trả về thành công, giá
        # trị sau đó là NULL. Lượt đồng bộ báo THÀNH CÔNG trong khi vừa đưa 457
        # học viên về "chưa rõ trình độ".
        #
        # Lệch phiên bản phải nổ, và nổ ở `assert_payload_contract` TRƯỚC khi
        # mở lượt — không phải giữa một lượt ghi đã mở.
        "degree_level": row.degree_level,
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

    ⚠️ Mọi lời gọi ở đây mang khoá secret của hệ KTX trong header ``apikey``
    (và thêm ``Authorization`` nếu khoá là JWT legacy — xem ``DormApi``), còn
    khi ``--apply`` thì thân request chứa họ tên và số điện thoại người học.
    Qua ``http://`` thì tất cả đi ở dạng đọc được trên đường truyền — một cấu
    hình gõ nhầm scheme là đủ để rò khoá ghi toàn hệ.

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


# Toàn bộ state machine của một lượt đồng bộ.
_TRANG_THAI_SYNC_RUN = {"running", "failed", "completed"}
# Tập con: lượt đã đóng sổ, không nhận ghi nữa.
_TRANG_THAI_DA_DONG = {"failed", "completed"}

# Trần một lô gửi lên RPC. PHẢI trùng con số trong `upsert_students_batch`
# (migration `20260729000002`, guard P0111). Hai đầu lệch nhau thì một giá trị
# hợp lệ với CLI sẽ mở lượt rồi hỏng ngay ở lô đầu — và bỏ lại một lượt phải
# đóng sổ vì một con số gõ sai.
_TRAN_LO = 500


def _doc_hang_sync_run(body: Any, run_id: int) -> Dict[str, Any]:
    """Đọc hàng ``sync_runs`` từ phản hồi, kiểm ĐÚNG DANH TÍNH.

    ⚠️ Không chỉ kiểm hình dạng mà kiểm cả ``id``. Một phản hồi mang hàng của
    lượt KHÁC — proxy trả nhầm, RPC đổi hành vi, nhiều hàng — mà ta nhận bừa
    thì kết luận "lượt này đã đóng" nói về một lượt không phải nó, và lượt thật
    vẫn treo ``running`` khoá năm học.

    ⚠️ Cũng kiểm ``status`` thuộc tập đã đóng. Nhận một hàng còn ``running``
    làm bằng chứng đã đóng sổ là tự tuyên bố xong việc chưa làm.
    """

    def _hong(vi_sao: str) -> RuntimeError:
        return RuntimeError(f"Đóng sổ lượt hỏng: {vi_sao}.")

    # ⚠️ ĐO TRÊN POSTGREST THẬT: hàm `returns public.sync_runs` là composite
    # SCALAR, không phải `setof`, nên PostgREST trả về một OBJECT ĐƠN — khác
    # `upsert_students_batch` (`returns table (...)`) vốn trả mảng.
    #
    # Bản trước đòi mảng đúng một phần tử, nên MỌI lần đóng sổ thành công đều
    # ném ngay tại đây rồi rơi xuống nhánh xử lý lỗi. Nó vẫn ra kết quả đúng
    # nhờ lần đối soát thứ hai, nhưng đường chính thì hỏng hoàn toàn và không
    # có gì trên màn hình nói ra điều đó.
    #
    # Vẫn nhận mảng một phần tử: nếu sau này ai đó đổi sang `returns setof`
    # hoặc bật `Accept: application/vnd.pgrst.object`, contract vẫn chạy.
    if isinstance(body, list):
        if len(body) != 1:
            raise _hong("phản hồi là mảng nhưng không có đúng một phần tử")
        row = body[0]
    else:
        row = body

    if not isinstance(row, dict):
        raise _hong("phản hồi không phải object")

    got_id = row.get("id")
    if not isinstance(got_id, int) or isinstance(got_id, bool):
        raise _hong("thiếu `id` hoặc `id` không phải số nguyên")
    if got_id != run_id:
        raise _hong(f"phản hồi mang lượt {got_id}, không phải {run_id}")

    if row.get("status") not in _TRANG_THAI_DA_DONG:
        raise _hong(
            f"trạng thái trả về không phải lượt đã đóng ({row.get('status')!r})"
        )

    return row


def _doc_so_lieu_lo(body: Any) -> Tuple[int, int]:
    """Đọc ``(đã ghi, bị chặn)`` từ phản hồi RPC — fail-closed từng bước.

    ⚠️ ``int(...)`` trần KHÔNG đủ. Nó nhận ``True`` (thành 1), nhận chuỗi
    ``"3"``, và cắt ``2.9`` thành 2. Cả ba đều nghĩa là database và client đang
    hiểu nhau khác đi, mà hai con số này quyết định phép kiểm
    ``raw = source + blocked`` ở bước hạ cờ — nhận bừa ở đây là hạ cờ theo một
    con số sai.

    ⚠️ Mảng phải có ĐÚNG một phần tử. Nhiều hơn nghĩa là RPC trả nhiều hàng —
    lấy hàng đầu và bỏ qua phần còn lại là giấu đúng điều bất thường đó.
    """

    def _khong_doc_duoc(vi_sao: str) -> RuntimeError:
        return RuntimeError(
            f"Ghi danh sách học viên: {vi_sao}. KHÔNG chạy tiếp — hai con số "
            "này quyết định bước hạ cờ."
        )

    if not isinstance(body, list) or len(body) != 1:
        raise _khong_doc_duoc("phản hồi không phải mảng đúng một phần tử")

    row = body[0]
    if not isinstance(row, dict):
        raise _khong_doc_duoc("phần tử phản hồi không phải object")

    ket_qua = []
    for khoa in ("upserted", "blocked"):
        gia_tri = row.get(khoa)
        # `bool` là lớp con của `int` — `True` không phải một số đếm hợp lệ.
        if not isinstance(gia_tri, int) or isinstance(gia_tri, bool):
            raise _khong_doc_duoc(f"`{khoa}` không phải số nguyên")
        if gia_tri < 0:
            raise _khong_doc_duoc(f"`{khoa}` âm ({gia_tri})")
        ket_qua.append(gia_tri)

    return ket_qua[0], ket_qua[1]


def assert_target_project_matches(base_url: str, expected_ref: str) -> None:
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

    expected_ref = (expected_ref or "").strip().lower()
    if not expected_ref:
        raise DormSyncConfigError(
            "Thiếu biến môi trường DORM_SYNC_TARGET_PROJECT_REF"
        )
    expected_host = f"{expected_ref}.supabase.co"

    if host != expected_host:
        # 🔴 Lỗi nghiệp vụ CÓ KIỂU, không phải ``ValueError`` trần.
        #
        # Hàm này chạy cả trong web worker. Một ``ValueError`` ở đó thành 500
        # không mã lỗi, còn thông điệp — vốn mang hostname của cả đích thật lẫn
        # đích được duyệt — đi thẳng vào traceback. ``DormSyncGuardError`` tách
        # đôi: ``detail`` ở cấp lớp là câu chung chung ra HTTP, bản chi tiết
        # nằm ở ``operator_detail`` cho người vận hành trước terminal.
        raise DormSyncTargetMismatchError(
            f"DORM_SUPABASE_URL trỏ tới '{host}' nhưng project được duyệt là "
            f"'{expected_ref}' (mong đợi '{expected_host}').\n"
            "  Đây là đích NHẬN dữ liệu cá nhân — sai project nghĩa là gửi cả "
            "cohort sang một hệ khác. Dùng domain riêng thì phải khai allowlist "
            "ánh xạ domain sang ref, không đoán.",
            context={"guard": "target_project_ref"},
        )


class LoaiThongBao(StrEnum):
    """Tập ĐÓNG các tình huống phục hồi lượt cũ.

    🔴 Vì sao không để ``str``: nơi trình bày rẽ nhánh theo giá trị này, và một
    chuỗi tự do thì gõ sai vẫn chạy — chỉ là không nhánh nào khớp, nên cảnh báo
    BIẾN MẤT trong im lặng. Người vận hành không thấy dòng "đã đóng sổ lượt
    #11" thì tưởng lượt cũ vẫn còn sống, và đó là lúc họ đi sửa tay một thứ đã
    được sửa rồi.

    Là ``StrEnum`` nên nó vẫn so được với chuỗi và tuần tự hoá thẳng ra JSON
    cho đường web sắp tới — không phải đổi kiểu lần nữa ở bước 9.
    """

    LUOT_CU_DANG_CHAY = "lut_cu_dang_chay"
    LUOT_CU_DA_HOAN_TAT = "lut_cu_da_hoan_tat"
    LUOT_CU_DA_DONG_SO = "lut_cu_da_dong_so"


@dataclass(frozen=True)
class DormSyncNotice:
    """Một điều người vận hành PHẢI biết về lượt trước, ở dạng có kiểu.

    ``loai`` là hằng số do ta đặt, không phải câu chữ: câu chữ thuộc về nơi
    trình bày (vỏ CLI hôm nay, giao diện web ngày mai), còn lõi chỉ nói điều gì
    đã xảy ra.
    """

    loai: LoaiThongBao
    run_id: int
    dau: Optional[str] = None

    def __post_init__(self) -> None:
        # ⚠️ Ép qua enum ngay lúc dựng, không chỉ khai kiểu. Chú thích kiểu ở
        # Python không kiểm gì lúc chạy, nên một `loai="lut_cu_dang_chayy"`
        # vẫn dựng được object và chỉ hỏng ở nơi trình bày — xa chỗ gõ sai.
        object.__setattr__(self, "loai", LoaiThongBao(self.loai))


@dataclass(frozen=True)
class OpenSyncRunResult:
    """Kết quả mở lượt: ``run_id`` VÀ những gì đã xảy ra để có được nó.

    🔴 Vì sao không phải ``int`` cộng một danh sách trên instance ``DormApi``:
    một danh sách sống trên object là trạng thái dùng chung giữa các lời gọi.
    Người gọi thứ hai đọc lại được cảnh báo của lời gọi thứ nhất (lượt cũ "đã
    đóng sổ" hiện lên lần nữa cho một lượt hoàn toàn bình thường), và người gọi
    nào quên đọc thì cảnh báo biến mất không dấu vết. Cả hai kiểu sai đều im
    lặng.

    Buộc nó vào giá trị trả về thì phạm vi của cảnh báo đúng bằng phạm vi của
    lời gọi sinh ra nó — không cần ai nhớ ``clear()``.
    """

    run_id: int
    notices: Tuple[DormSyncNotice, ...] = ()


def _client_note(client_token: str) -> str:
    """Dấu của tiến trình chạy, ghi vào ``sync_runs.note``.

    Đây là thứ duy nhất cho phép nhận lại một lượt mà chính lần chạy này đã tạo
    khi phản hồi bị mất — xem ``open_sync_run``.
    """
    return f"client:{client_token}"


# Mã lỗi do CHÍNH TA đặt trong migration `20260729000005`, và thông điệp tiếng
# Việt nằm ở ĐÂY — phía client.
#
# ⚠️ KHÔNG lấy `message` của server. PostgREST trả nguyên văn thông điệp của
# Postgres, mà thông điệp đó mang theo GIÁ TRỊ gây lỗi (`Key (...)=(...) already
# exists`, `invalid input syntax for type integer: "1.5"`). Nếu ai đó nhét nhầm
# số điện thoại vào một trường số thì chính dòng lỗi ấy in dữ liệu cá nhân ra
# stderr — mà stderr bị CI, cron và container thu gom y như log. Đây cũng là lý
# do `_raise_for_status` giấu thân phản hồi.
#
# Mã SQLSTATE thì ngược lại: nó là hằng số năm ký tự do ta đặt, không mang dữ
# liệu hàng, nên in ra được.
_THONG_DIEP_THEO_MA: Dict[str, str] = {
    # Chung
    "P0101": "Tham số bắt buộc bị để trống.",
    "P0002": "Không tìm thấy lượt đồng bộ.",
    "P0102": "Không tìm thấy lượt đồng bộ.",
    "P0113": "Lượt đồng bộ không còn ở trạng thái `running`.",
    # Validate payload của upsert_students_batch
    "P0110": "Payload gửi lên không phải mảng JSON.",
    "P0111": "Lô vượt trần 500 hàng.",
    "P0112": "Payload có khoá mà database không nhận.",
    "P0114": "Có hàng thiếu `qlts_profile_id`.",
    "P0115": "Có `qlts_profile_id` trùng trong cùng một lô.",
    "P0116": "Lô chứa hàng thuộc năm học khác với lượt.",
    "P0117": "Phần tử của payload không phải object.",
    "P0118": "Sai kiểu ở một trường của payload.",
    "P0119": "Một trường số nhận giá trị không phải số nguyên.",
    "P0122": "Payload thiếu khoá bắt buộc (vắng khoá KHÁC null).",
    "P0121": "Một trường số vượt khoảng cho phép.",
    # finalize_sync_run
    "P0130": "`p_run_id` bị để trống.",
    "P0131": "`p_source_count` bị để trống.",
    "P0132": "`p_upserted_count` bị để trống.",
    "P0133": "Lượt đã kết thúc với số liệu khác; database từ chối ghi đè.",
    "P0135": "Số liệu gửi lên bị âm.",
    "P0136": "Chưa ghi hết phần đáng ghi (nguồn khác số đã ghi).",
    "P0137": "Lệch contract: raw khác nguồn cộng phần bị chặn.",
    "P0138": "Số bản ghi mang dấu lượt không khớp số đã ghi.",
    "P0139": "Lượt không có `raw_count` — không đối soát được.",
    "P0191": (
        "Thiếu ảnh chụp chỗ ở phía KTX — lượt này chưa qua bước xem trước."
    ),
    "P0192": (
        "Chỗ ở phía ký túc xá ĐÃ ĐỔI sau khi xem trước. Có người vừa nhận "
        "hoặc đổi giường; xem lại danh sách cảnh báo rồi chạy lại."
    ),
    # tombstone_student
    "P0120": "Học viên còn chỗ ở đang hoạt động.",
}

_DANG_MA_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")

# md5 hệ 16 chữ thường, đúng 32 ký tự — dạng `md5()` của Postgres trả về.
_DANG_FINGERPRINT = re.compile(r"^[0-9a-f]{32}$")

# Những trường của một hàng cảnh báo mà NGƯỜI BẤM đọc trước khi quyết định.
# Kiểm đủ cả tập: thiếu một trường thì dòng cảnh báo in ra "None" ở đúng chỗ
# lẽ ra nói người đó đang nằm giường nào — mà đó là thông tin duy nhất giúp họ
# nhận ra danh sách này có gì sai.
_TRUONG_CANH_BAO = (
    ("qlts_profile_id", int),
    ("full_name", str),
    ("building_name", str),
    ("room_code", str),
    ("bed_no", int),
    ("status", str),
)


@dataclass(frozen=True)
class TargetSnapshot:
    """Ảnh chụp "ai sắp mất cờ mà vẫn đang giữ giường", kèm dấu vân tay của nó.

    🔴 MỘT lời gọi trả cả hai. Hai lời gọi HTTP là hai ảnh chụp khác nhau: một
    thay đổi chen vào giữa sẽ khiến người bấm nhìn danh sách A trong khi con số
    mang đi chốt lại nói về trạng thái B — đúng cái chốt này sinh ra để chặn,
    chỉ dịch sang chỗ khác.

    🔴 ``fingerprint`` do DATABASE tính. Dựng lại chuỗi canonical rồi băm bằng
    Python là đặt cược rằng hai bên serialize giống hệt nhau, và cược đó chỉ
    được thanh toán ở production — sau khi đã upsert xong.
    """

    rows: Tuple[Dict[str, Any], ...]
    fingerprint: str


def _doc_target_snapshot(body: Any) -> TargetSnapshot:
    """Đọc phản hồi của ``dorm_sync_target_snapshot`` — fail-closed từng bước.

    ⚠️ Con số này đi thẳng vào ``finalize_sync_run`` làm điều kiện hạ cờ. Nhận
    bừa một thân phản hồi lạ nghĩa là mang một chuỗi vô nghĩa đi chốt: hoặc nó
    không khớp và mọi lượt bị chặn, hoặc — tệ hơn — ai đó "sửa" bằng cách bỏ
    chốt đi.
    """

    def _hong(vi_sao: str) -> RuntimeError:
        return RuntimeError(
            f"Ảnh chụp chỗ ở phía KTX không đọc được: {vi_sao}. KHÔNG chạy "
            "tiếp — giá trị này là điều kiện của bước hạ cờ."
        )

    # 🔴 CHỈ object. `dorm_sync_target_snapshot` khai `returns jsonb` scalar,
    # nên PostgREST trả thẳng object — mảng là hình dạng KHÁC contract.
    #
    # ⚠️ Bản trước tự tháo mảng một phần tử "phòng khi ai đó đổi sang
    # `returns setof`". Đó chính là cách một thay đổi contract đi qua mà không
    # ai biết: ngày phía KTX đổi kiểu trả về, client vẫn chạy, vẫn xanh, và thứ
    # duy nhất lẽ ra báo động — một lời từ chối ồn ào — đã được gỡ trước.
    # Contract đổi thì phải có người quyết định, không phải một nhánh im lặng
    # nhận cả hai dạng.
    if not isinstance(body, dict):
        raise _hong("phản hồi không phải object")

    fingerprint = body.get("fingerprint")
    if not isinstance(fingerprint, str) or not _DANG_FINGERPRINT.match(fingerprint):
        # ⚠️ KHÔNG in giá trị nhận được: nó do phía kia kiểm soát và sẽ đi
        # thẳng vào log qua đúng cái cửa `_raise_for_status` vừa đóng.
        raise _hong("`fingerprint` không phải chuỗi md5 32 ký tự")

    rows = body.get("rows")
    if not isinstance(rows, list):
        raise _hong("`rows` không phải mảng")

    for row in rows:
        if not isinstance(row, dict):
            raise _hong("một phần tử của `rows` không phải object")
        for ten, kieu in _TRUONG_CANH_BAO:
            gia_tri = row.get(ten)
            # `bool` là lớp con của `int` — không phải một số hợp lệ ở đây.
            if kieu is int and isinstance(gia_tri, bool):
                raise _hong(f"`{ten}` là bool, không phải số nguyên")
            if not isinstance(gia_tri, kieu):
                raise _hong(f"hàng cảnh báo thiếu `{ten}` hoặc sai kiểu")

    return TargetSnapshot(rows=tuple(rows), fingerprint=fingerprint)


def doc_ma_loi(response: httpx.Response) -> Optional[str]:
    """Lấy MỖI mã ``code`` từ thân lỗi PostgREST. ``None`` nếu không đọc được.

    Chỉ nhận chuỗi đúng dạng SQLSTATE (năm ký tự chữ hoa/số). Thân phản hồi là
    dữ liệu do phía kia kiểm soát, nên không tin nó đưa gì cũng in: một
    ``code`` dài ngoằng chứa văn bản tự do sẽ đi thẳng vào log qua đúng cái cửa
    ta vừa đóng.
    """
    try:
        than = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(than, dict):
        return None
    ma = than.get("code")
    if isinstance(ma, str) and _DANG_MA_SQLSTATE.match(ma):
        return ma
    return None


# 🔴 Những mã mà database đã QUYẾT ĐỊNH — thử lại chỉ nhận đúng câu trả lời đó.
#
# ⚠️ Vì sao cần danh sách này ở bước đóng sổ: PostgREST ánh xạ MỌI SQLSTATE bắt
# đầu bằng `P0` (trừ P0001/P0002/P0003) sang **HTTP 500**. Mà nhánh 5xx của
# `finalize_sync_run` cố ý coi 500 là "mơ hồ, có thể gateway" rồi đối soát và
# thử lại — đúng và cần thiết cho một 502 thật, nhưng với P0192 thì nó biến một
# lời từ chối dứt khoát thành ba lượt thử cách nhau vài giây, và kết thúc bằng
# thông điệp "trạng thái lượt CHƯA rõ" trong khi database đã nói rất rõ.
#
# Phân biệt bằng THÂN phản hồi: một 500 mang SQLSTATE của ta nghĩa là lời gọi
# đã tới database và database đã trả lời. Một 502 từ gateway không có thân JSON
# nào như vậy.
#
# ⚠️ Tập này khai TƯỜNG MINH chứ không phải "mọi mã đọc được". Một mã lạ (ví dụ
# `57P01` — server ngắt kết nối) rơi về nhánh đối soát-rồi-thử-lại như cũ, tức
# vẫn là hành vi an toàn hơn.
_MA_DUT_KHOAT_KHI_DONG_SO = frozenset(
    {
        "P0002",  # không tìm thấy lượt
        "P0102",  # không tìm thấy lượt
        "P0113",  # lượt không còn `running`
        "P0130",
        "P0131",
        "P0132",
        "P0133",  # đã kết thúc với số liệu khác
        "P0135",
        "P0136",
        "P0137",
        "P0138",
        "P0139",
        "P0191",  # thiếu fingerprint
        "P0192",  # fingerprint lệch — chỗ ở đã đổi
    }
)


class DormApi:
    """Lớp mỏng gọi PostgREST của Supabase.

    Dùng REST thay vì nối thẳng Postgres để không phải mở cổng database của hệ
    KTX ra ngoài.
    """

    def __init__(
        self, base_url: str, secret_key: str, *, expected_project_ref: str
    ) -> None:
        # Thứ tự có chủ đích: đường truyền, rồi ĐÍCH, rồi mới tới headers mang
        # khoá secret. Khoá không được nằm trong bất kỳ cấu trúc nào trước khi
        # cả hai câu hỏi "đi bằng gì" và "đi tới đâu" đã có câu trả lời đúng.
        assert_transport_is_encrypted(base_url)
        assert_target_project_matches(base_url, expected_project_ref)
        # 🔴 Lõi KHÔNG in ra stdout: nó chạy trong web worker, nơi stdout là
        # log của tiến trình chứ không phải màn hình của ai. Ba thông báo phục
        # hồi lượt cũ đi ra theo GIÁ TRỊ TRẢ VỀ của ``open_sync_run``
        # (``OpenSyncRunResult``), không phải một danh sách sống trên object —
        # xem docstring của lớp đó. Cũng không dùng callback nhận hàm in: như
        # vậy chỉ giấu phụ thuộc trình bày sau một tham số.
        self._base = base_url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": secret_key,
            "Content-Type": "application/json",
        }

        # ⚠️ `Authorization: Bearer` CHỈ cho khoá dạng JWT (legacy
        # `service_role`). Khoá thế hệ mới `sb_secret_...` không phải JWT, và
        # gửi nó ở vị trí Bearer là dùng sai contract của header đó.
        #
        # Đo trên PostgREST của Supabase local: gửi cả hai header với khoá
        # `sb_secret_` vẫn trả 200, nên đây KHÔNG phải lỗi đang hỏng. Nhưng nó
        # dựa vào việc máy chủ bỏ qua một header sai — một hành vi không có gì
        # bảo đảm, và ngày nó siết lại thì lượt đồng bộ chết bằng 401 ở đúng
        # thao tác ghi dữ liệu thật.
        if secret_key.startswith("eyJ"):
            self._headers["Authorization"] = f"Bearer {secret_key}"

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

        # Mã lỗi thì in được — nó là hằng số ta tự đặt, không mang dữ liệu hàng.
        # Thông điệp đi kèm lấy từ bảng phía CLIENT, không phải từ phản hồi.
        #
        # Mã lạ (Postgres thô như 22P02, hoặc mã ta chưa map) vẫn in ra mã: nó
        # là thứ duy nhất người vận hành có để tra log Supabase, và nó không
        # chứa PII. Cái không in là `message`.
        ma = doc_ma_loi(response)
        phan_chan_doan = ""
        if ma is not None:
            giai_thich = _THONG_DIEP_THEO_MA.get(ma)
            phan_chan_doan = (
                f" [{ma}] {giai_thich}"
                if giai_thich
                else f" [{ma}] Mã lỗi chưa được map phía client."
            )

        raise RuntimeError(
            f"{action} thất bại (HTTP {response.status_code}, "
            f"request-id {request_id}).{phan_chan_doan} "
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

    async def _nhan_lai_hay_thay_the(
        self,
        run_cu: Dict[str, Any],
        academic_year: int,
        client_token: str,
        raw_count: int,
        *,
        la_lan_chay_lai: bool,
    ) -> OpenSyncRunResult:
        """Gặp một lượt ``running`` mang ĐÚNG dấu của mình: dùng lại, hay thay?

        Câu trả lời phụ thuộc dấu đó từ đâu ra, và hai ca khác nhau hoàn toàn:

        **Token TỰ SINH** (không truyền ``--client-token``) — dấu chỉ tồn tại
        trong tiến trình này, chưa ai khác thấy nó. Một hàng mang dấu đó nghĩa
        là chính lời gọi mở lượt vừa rồi ĐÃ tới database rồi mất phản hồi trên
        đường về. Chưa ghi học viên nào. Nhận lại là đúng.

        **Token TRUYỀN TAY** — người vận hành đang chạy lại sau một lần hỏng.
        Lượt cũ đó có thể đã ghi được một phần, và những hàng ấy VẪN MANG
        ``last_seen_sync_id`` của nó. Nhận lại rồi đóng sổ bằng số liệu của lần
        chạy MỚI là trộn hai lần chạy vào một sổ:

        - cohort co lại giữa hai lần → ``v_seen`` (số hàng mang dấu lượt) lớn
          hơn ``upserted_count`` mới → P0138 từ chối hạ cờ, và lượt treo
          ``running`` khoá cứng năm học;
        - cohort giữ nguyên → tệ hơn, vì nó KHÔNG nổ: ``raw_count`` của lượt cũ
          là con số của lần chạy trước, còn ``blocked_count`` thì cộng dồn qua
          CẢ HAI lần. Sổ sách khép kín mà sai.

        Nên: đóng sổ lượt cũ, rồi mở lượt MỚI. An toàn dựa trên 1C — một lượt
        ``failed`` thì ``upsert_students_batch`` từ chối mọi lời gọi mang
        ``p_run_id`` đó (P0113), kể cả từ tiến trình cũ còn sống.
        """
        run_id_cu = run_cu["id"]

        if not la_lan_chay_lai:
            log.warning(
                "dorm_sync_run_recovered", run_id=run_id_cu, client_token=client_token
            )
            return OpenSyncRunResult(run_id_cu)

        notices = [
            DormSyncNotice(
                loai="lut_cu_dang_chay",
                run_id=run_id_cu,
                dau=_client_note(client_token),
            )
        ]
        hang = await self.mark_sync_run_failed(run_id_cu)
        trang_thai = hang.get("status")

        if trang_thai == "completed":
            # RPC cố ý KHÔNG hạ `completed` xuống `failed`. Lượt trước đã xong
            # thật; nói rõ để người vận hành biết mình đang chạy lượt thứ hai
            # chứ không phải sửa một lượt hỏng.
            notices.append(
                DormSyncNotice(loai="lut_cu_da_hoan_tat", run_id=run_id_cu)
            )
        elif trang_thai == "failed":
            notices.append(DormSyncNotice(loai="lut_cu_da_dong_so", run_id=run_id_cu))
        else:
            raise RuntimeError(
                f"Không đóng được lượt cũ #{run_id_cu}: sau khi gọi fail_sync_run "
                f"nó vẫn ở trạng thái {trang_thai!r}. Dừng để không mở lượt thứ "
                "hai chồng lên một lượt đang sống — hai lượt cùng năm sẽ vướng "
                "uq_sync_run_active_per_year, và lượt cũ vẫn nhận ghi."
            )

        # ⚠️ Mở lại với `la_lan_chay_lai=False`: từ giây phút này dấu đó thuộc
        # về lần chạy HIỆN TẠI. Giữ True sẽ đệ quy vô hạn nếu database lại trả
        # về một hàng mang dấu.
        ket_qua = await self.open_sync_run(
            academic_year, client_token, raw_count, la_lan_chay_lai=False
        )
        # Cảnh báo về lượt CŨ đứng trước cảnh báo (nếu có) của lần mở mới: đọc
        # từ trên xuống là đúng thứ tự việc đã xảy ra.
        return OpenSyncRunResult(ket_qua.run_id, tuple(notices) + ket_qua.notices)

    async def _recover_open_or_fail(
        self,
        academic_year: int,
        client_token: str,
        raw_count: int,
        *,
        ly_do: str,
        la_lan_chay_lai: bool,
    ) -> OpenSyncRunResult:
        """Sau một phản hồi MƠ HỒ ở bước mở lượt: nhận lại hàng, hoặc nói thật.

        Ba nhánh, ba thông điệp khác nhau — người vận hành cần biết mình đang ở
        nhánh nào để quyết định chạy lại hay đi kiểm database.
        """
        outcome, run = await self.find_run_by_token(academic_year, client_token)

        if outcome == "found":
            return await self._nhan_lai_hay_thay_the(
                run,
                academic_year,
                client_token,
                raw_count,
                la_lan_chay_lai=la_lan_chay_lai,
            )

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
        self,
        academic_year: int,
        client_token: str,
        raw_count: int,
        *,
        la_lan_chay_lai: bool = False,
    ) -> OpenSyncRunResult:
        """Mở một lượt đồng bộ. Chịu được ca phản hồi bị mất.

        Trả ``OpenSyncRunResult(run_id, notices)``. ``notices`` chỉ nói về
        LƯỢT GỌI NÀY: một lần mở sạch trả tuple rỗng, kể cả khi lần gọi trước
        trên cùng object đã sinh cảnh báo.

        ``la_lan_chay_lai`` = người vận hành TỰ truyền ``--client-token``. Nó
        đổi ý nghĩa của một lượt cũ mang cùng dấu — xem
        ``_nhan_lai_hay_thay_the``.

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
                academic_year,
                client_token,
                raw_count,
                ly_do="lỗi kết nối",
                la_lan_chay_lai=la_lan_chay_lai,
            )

        if response.status_code == 409:
            # Có thể chính là hàng của lần chạy này (một lời gọi trước đó đã tới
            # nơi rồi mất phản hồi). Hỏi theo dấu trước khi kết luận là của người
            # khác — nếu đúng dấu mình thì cứ dùng tiếp, không cần ai sửa tay.
            outcome, run = await self.find_run_by_token(academic_year, client_token)
            if outcome == "found":
                return await self._nhan_lai_hay_thay_the(
                    run,
                    academic_year,
                    client_token,
                    raw_count,
                    la_lan_chay_lai=la_lan_chay_lai,
                )

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
                raw_count,
                ly_do=f"HTTP {response.status_code} từ gateway",
                la_lan_chay_lai=la_lan_chay_lai,
            )

        # Còn lại là câu trả lời DỨT KHOÁT của database (400/401/403…): không có
        # hàng nào được tạo, không cần đối soát.
        self._raise_for_status(response, "Mở lượt đồng bộ")

        try:
            return OpenSyncRunResult(response.json()[0]["id"])
        except (IndexError, KeyError, TypeError, ValueError):
            # Phản hồi 2xx nhưng thân không đọc được (proxy cắt, JSON hỏng).
            # Hàng gần như chắc chắn ĐÃ được tạo — tìm lại theo dấu.
            return await self._recover_open_or_fail(
                academic_year,
                client_token,
                raw_count,
                ly_do="phản hồi không đọc được",
                la_lan_chay_lai=la_lan_chay_lai,
            )

    async def get_sync_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Đọc trạng thái hiện tại của một lượt. ``None`` = không đọc được.

        ⚠️ KIỂM HÌNH DẠNG, không chỉ lấy phần tử đầu. Hàm anh em
        ``find_run_by_token`` đã được siết đúng chỗ này; ở đây thì chưa, và một
        thân phản hồi lạ (``[{}]``, proxy cắt, JSON hỏng) ném ``KeyError`` ra
        GIỮA nhánh xử lý lỗi — nơi mọi lời gọi đều đang chạy vì có gì đó đã
        hỏng sẵn. Trả ``None`` để người gọi xử lý tử tế thay vì nổ.

        ⚠️ Kiểm cả ``id``: một phản hồi mang hàng của lượt khác mà nhận bừa thì
        mọi kết luận sau đó nói về sai lượt.
        """
        response = await self._client.get(
            f"{self._base}/sync_runs",
            headers=self._headers,
            params={
                "id": f"eq.{run_id}",
                "select": "id,status,source_count,upserted_count,deactivated_count",
            },
        )
        self._raise_for_status(response, "Đọc lượt đồng bộ")

        try:
            rows = response.json()
        except Exception:
            return None

        # ⚠️ ĐÚNG MỘT phần tử. Lọc là `id=eq.<run_id>` trên khoá chính nên
        # nhiều hơn một hàng là điều không thể xảy ra nếu mọi thứ bình thường —
        # và chính vì thế, gặp nó mà vẫn lấy `rows[0]` là bỏ qua đúng lúc phải
        # dừng. Đã tái hiện: hai hàng mâu thuẫn `completed` và `running` thì
        # nhánh phục hồi nhận hàng đầu và tuyên bố lượt đã xong.
        if not isinstance(rows, list) or len(rows) != 1:
            return None

        row = rows[0]
        if not isinstance(row, dict):
            return None

        got_id = row.get("id")
        if not isinstance(got_id, int) or isinstance(got_id, bool) or got_id != run_id:
            return None

        # Trạng thái phải nằm trong state machine. Một chuỗi bất kỳ lọt qua sẽ
        # rơi xuống nhánh "không xác định" ở người gọi — đúng, nhưng muộn hơn
        # một tầng và không nói được vì sao.
        if row.get("status") not in _TRANG_THAI_SYNC_RUN:
            return None

        return row

    async def mark_sync_run_failed(self, run_id: int) -> Dict[str, Any]:
        """Đóng sổ một lượt hỏng, qua RPC. Trả hàng ``sync_runs`` sau khi gọi.

        ⚠️ KHÔNG PATCH thẳng bảng nữa. Hai lý do, cả hai đều nghiêm trọng:

        1. Contract mới ràng ``failed ⇒ source_count IS NULL`` ở tầng database.
           Một PATCH mang theo ``source_count`` sẽ vướng CHECK, và khi đó MỌI
           lỗi sau lúc mở lượt đều để lại một lượt treo ``running`` — thứ khoá
           cứng năm học bằng ``uq_sync_run_active_per_year``.
        2. ``upserted_count`` của lượt hỏng trước đây lấy từ bộ đếm trong tiến
           trình này. Một lô đã commit rồi mất ACK, hoặc một lượt được tiến
           trình khác nhận lại, đều làm con số đó THẤP HƠN thực tế — và nó đi
           thẳng vào sổ sách. RPC đếm lại từ ``students.last_seen_sync_id``
           trong cùng transaction với việc đổi trạng thái.

        RPC cũng tự phân loại: lượt đã ``completed`` được trả nguyên hàng, không
        bị hạ cấp; lượt đã ``failed`` trả nguyên hàng và KHÔNG đếm lại.
        """
        response = await self._client.post(
            f"{self._base}/rpc/fail_sync_run",
            headers=self._headers,
            json={"p_run_id": run_id},
        )
        self._raise_for_status(response, "Đóng sổ lượt hỏng")
        return _doc_hang_sync_run(response.json(), run_id)

    async def reconcile_after_failure(
        self, run_id: int
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
            sau_khi_dong = await self.mark_sync_run_failed(run_id)
        except Exception:
            # ⚠️ Lỗi ở BƯỚC ĐÓNG SỔ cũng là trạng thái mơ hồ, y như ở bước mở
            # lượt. Mất kết nối, 408, 5xx — cả ba đều có thể xảy ra SAU khi
            # database đã commit. Trả "unknown" ngay ở đây là bỏ mất chính cái
            # cơ chế đối soát mà `open_sync_run` đã có: lượt có thể đã `failed`
            # thật, hoặc vẫn `running` và đang khoá năm học, và hai ca đó cần
            # hai hành động khác nhau.
            #
            # Hỏi lại một lần. RPC idempotent nên đọc lại là an toàn.
            try:
                lan_hai = await self.get_sync_run(run_id)
            except Exception:
                return "unknown", run

            if isinstance(lan_hai, dict):
                trang_thai_that = lan_hai.get("status")
                if trang_thai_that == "completed":
                    return "finalized", lan_hai
                if trang_thai_that == "failed":
                    # POST đã tới nơi và commit; chỉ phản hồi không về.
                    return "marked_failed", lan_hai

            # Đọc được mà vẫn `running`, hoặc thân phản hồi lạ: KHÔNG biết.
            # Tuyệt đối không tuyên bố đã đóng sổ.
            return "unknown", lan_hai if isinstance(lan_hai, dict) else run

        # ⚠️ Tin TRẠNG THÁI TRẢ VỀ, không tin việc lời gọi không ném.
        #
        # RPC tự phân loại và có nhánh trả nguyên hàng mà không đổi gì: một lượt
        # vừa `completed` xong ngay giữa lúc ta đọc và lúc ta gọi sẽ về đây với
        # `completed`. Ghi nó thành "đã đánh dấu thất bại" là ghi sai sổ sách
        # đúng ở ca dễ xảy ra nhất — mất ACK sau khi hạ cờ đã commit.
        trang_thai = sau_khi_dong.get("status")
        if trang_thai == "completed":
            return "finalized", sau_khi_dong
        if trang_thai == "failed":
            return "marked_failed", sau_khi_dong
        return "unknown", sau_khi_dong

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

        return _doc_so_lieu_lo(response.json())

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
                # ⚠️ Bỏ hồ sơ đã gỡ. Khoá secret đi vòng qua RLS, nên policy
                # che tombstone KHÔNG áp cho lời gọi này — con số ở đây sẽ cao
                # hơn danh sách cán bộ thật sự nhìn thấy, và đó đúng là con số
                # người vận hành dùng để đối soát trước khi ghi.
                "deleted_at": "is.null",
                "select": "qlts_profile_id",
                "limit": "1",
            },
        )
        self._raise_for_status(response, "Đếm học viên")

        # ⚠️ Mặc định KHÔNG được là `"*/0"`. Header `Content-Range` vắng mặt
        # nghĩa là KHÔNG ĐẾM ĐƯỢC (proxy gỡ mất `Prefer`, PostgREST không trả
        # count) — mà `"*/0"` biến đúng ca đó thành con số 0, tức "hệ KTX đang
        # rỗng". Người vận hành đọc số 0 ở bước XEM TRƯỚC sẽ kết luận ngược hẳn:
        # tưởng chưa có gì bên đích trong khi có thể đã có đủ cohort.
        #
        # Chuỗi rỗng không phải chữ số nên rơi đúng vào nhánh `None` = không
        # biết, và người gọi in "không đếm được" thay vì một con số bịa.
        total = response.headers.get("content-range", "").split("/")[-1]
        return int(total) if total.isdigit() else None

    async def fetch_target_snapshot(
        self, academic_year: int, cohort_ids: Sequence[int]
    ) -> TargetSnapshot:
        """Ảnh chụp "ai sắp mất cờ mà vẫn đang giữ giường" + dấu vân tay.

        ``cohort_ids`` là tập hồ sơ SẮP ĐƯỢC GHI ở lượt này; RPC loại họ ra rồi
        mới liệt kê phần còn lại.

        ⚠️ Truyền ĐỦ tập yêu cầu, kể cả những hàng sau đó sẽ bị chặn. Lúc đóng
        sổ, database tự dựng lại ``p_cohort_ids`` từ ``last_seen_sync_id`` — tức
        tập THỰC SỰ ghi được, hẹp hơn tập gửi đi. Hai tập vẫn cho cùng một
        fingerprint vì phần chênh lệch là hàng nằm trong blocklist tombstone,
        mà vị từ của snapshot đã loại chúng bằng ``s.deleted_at is null``.
        Không có bất biến đó thì mọi lượt có ``blocked > 0`` sẽ vấp P0192.

        ⚠️ KHÔNG gọi wrapper ``dorm_sync_target_fingerprint`` rồi lấy danh sách
        bằng một lời gọi thứ hai: hai lời gọi là hai ảnh chụp.
        """
        response = await self._client.post(
            f"{self._base}/rpc/dorm_sync_target_snapshot",
            headers=self._headers,
            json={
                "p_academic_year": academic_year,
                "p_cohort_ids": list(cohort_ids),
            },
        )
        self._raise_for_status(response, "Đọc ảnh chụp chỗ ở phía KTX")

        try:
            than = response.json()
        except (ValueError, TypeError):
            raise RuntimeError(
                "Ảnh chụp chỗ ở phía KTX không đọc được: phản hồi không phải "
                "JSON. KHÔNG chạy tiếp — giá trị này là điều kiện của bước hạ cờ."
            ) from None

        return _doc_target_snapshot(than)

    async def finalize_sync_run(
        self,
        run_id: int,
        source_count: int,
        upserted_count: int,
        expected_target_fingerprint: str,
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

        ⚠️ "Mơ hồ" gồm CẢ 408 và 5xx, không chỉ lỗi kết nối — cùng lập luận mà
        ``open_sync_run`` đã dùng: những mã đó thường đến từ gateway đứng TRƯỚC
        database. Ở bước hạ cờ thì nhầm lẫn này đắt nhất, vì coi 502 là "database
        từ chối" sẽ ghi `failed` cho một lượt đã đổi ``source_eligible`` của cả
        cohort. Gặp chúng thì ĐỐI SOÁT bằng ``get_sync_run`` rồi mới quyết định.
        """
        payload = {
            "p_run_id": run_id,
            "p_source_count": source_count,
            "p_upserted_count": upserted_count,
            # 🔴 Gửi NGUYÊN VĂN chuỗi database đã trả ở bước xem trước. Chuẩn
            # hoá, cắt khoảng trắng hay băm lại đều là dựng một công thức thứ
            # hai song song với công thức của database — và hai công thức song
            # song thì lệch nhau ngay lần sửa đầu.
            "p_expected_target_fingerprint": expected_target_fingerprint,
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

            # ⚠️ 408 và 5xx KHÔNG dứt khoát, và đây là chỗ nhầm lẫn đắt nhất
            # trong cả file: `open_sync_run` cách đây hai mươi dòng đã lập luận
            # đúng điều ngược lại — những mã đó thường đến từ gateway đứng
            # TRƯỚC database, nên transaction có thể đã commit xong rồi phản hồi
            # mới hỏng trên đường về.
            #
            # Và bước này là bước HẠ CỜ. Coi 502 là "database từ chối" sẽ đẩy
            # một lượt ĐÃ hạ cờ xong vào nhánh đóng sổ hỏng: sổ sách ghi
            # `failed` trong khi cả cohort đã bị đổi `source_eligible`. Hỏi lại
            # trước khi kết luận — hàm phía database idempotent nên đọc lại an
            # toàn.
            ma_ung_dung = doc_ma_loi(response)
            la_mo_ho = (
                response.status_code == 408
                or response.status_code >= 500
            ) and ma_ung_dung not in _MA_DUT_KHOAT_KHI_DONG_SO

            if la_mo_ho:
                hang_doi_soat = None
                try:
                    hang_doi_soat = await self.get_sync_run(run_id)
                except Exception:
                    hang_doi_soat = None

                if (
                    hang_doi_soat is not None
                    and hang_doi_soat.get("status") == "completed"
                ):
                    log.warning(
                        "dorm_sync_finalize_reconciled",
                        run_id=run_id,
                        http_status=response.status_code,
                    )
                    so_ha_co = hang_doi_soat.get("deactivated_count")
                    if not isinstance(so_ha_co, int) or isinstance(so_ha_co, bool):
                        raise RuntimeError(
                            "Kết thúc lượt đồng bộ: đối soát thấy lượt đã "
                            "`completed` nhưng `deactivated_count` không phải "
                            "số nguyên."
                        )
                    if so_ha_co < 0:
                        raise RuntimeError(
                            "Kết thúc lượt đồng bộ: đối soát thấy "
                            f"`deactivated_count` âm ({so_ha_co})."
                        )
                    return so_ha_co

                # Chưa `completed`: thử lại. Lượt vẫn `running` nghĩa là lời gọi
                # chưa tới đích, và đó đúng ca retry phục vụ.
                last_error = RuntimeError(
                    f"HTTP {response.status_code} ở bước kết thúc lượt"
                )
                log.warning("dorm_sync_finalize_retry", attempt=attempt)
                if attempt < 3:
                    await asyncio.sleep(attempt)
                continue

            # Còn lại (400/401/403/409…) là câu trả lời DỨT KHOÁT của database —
            # thử lại chỉ lặp lại đúng lỗi đó.
            self._raise_for_status(response, "Kết thúc lượt đồng bộ")
            # Đọc có kiểm: hàm này vừa HẠ CỜ, nên con số trả về đi thẳng vào
            # nhật ký đối soát. Một thân phản hồi lạ mà nhận bừa sẽ ghi sai số
            # người bị loại khỏi danh sách.
            hang = _doc_hang_sync_run(response.json(), run_id)
            if hang.get("status") != "completed":
                raise RuntimeError(
                    "Kết thúc lượt đồng bộ: lượt không ở trạng thái "
                    f"`completed` sau khi gọi ({hang.get('status')!r})."
                )
            so_ha_co = hang.get("deactivated_count")
            if not isinstance(so_ha_co, int) or isinstance(so_ha_co, bool):
                raise RuntimeError(
                    "Kết thúc lượt đồng bộ: `deactivated_count` không phải số "
                    "nguyên."
                )
            if so_ha_co < 0:
                raise RuntimeError(
                    f"Kết thúc lượt đồng bộ: `deactivated_count` âm ({so_ha_co})."
                )
            return so_ha_co

        raise RuntimeError(
            "Kết thúc lượt đồng bộ thất bại sau 3 lần thử (lỗi kết nối hoặc "
            "408/5xx, đã đối soát nhưng lượt chưa `completed`). "
            "Trạng thái lượt CHƯA rõ — kiểm bảng sync_runs trước khi chạy lại."
        ) from last_error


async def fetch_cohort(
    academic_year: int,
    *,
    verify_source: bool = False,
    expected_source_db: str = "",
    expected_system_id: str = "",
) -> List[Any]:
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
            await assert_live_source_matches(
                session, expected_source_db, expected_system_id
            )
        result = await session.execute(select_paid_hk1_cohort(academic_year))
        return result.all()




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


def assert_source_database_matches(
    expected_source_db: str, expected_system_id: str
) -> None:
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
    for ten, gia_tri in (("DORM_SYNC_SOURCE_DB", expected_source_db),
                         ("DORM_SYNC_SOURCE_SYSTEM_ID", expected_system_id)):
        if not (gia_tri or "").strip():
            raise DormSyncConfigError("Thiếu biến môi trường %s" % ten)
    expected = _chuan_hoa_dinh_danh_khai_bao(expected_source_db)
    # Bắt buộc khai từ đây, dù chỉ dùng ở lớp ba: thiếu nó mà vẫn chạy tiếp
    # nghĩa là lớp mạnh nhất im lặng không chạy.

    from app.config import settings

    actual = database_identity_from_url(settings.DATABASE_URL)

    if actual != expected:
        raise DormSyncGuardError(
            f"Từ chối ghi: QLTS đang đọc database '{actual}' nhưng file cấu "
            f"hình của hệ KTX khai báo DORM_SYNC_SOURCE_DB='{expected}'. "
            "Hai đầu lệch nhau nghĩa là đang đẩy dữ liệu của database này "
            "sang hệ ký túc xá của database khác."
        )


async def assert_live_source_matches(
    session: Any, expected_source_db: str, expected_system_id: str
) -> None:
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
    for ten, gia_tri in (("DORM_SYNC_SOURCE_DB", expected_source_db),
                         ("DORM_SYNC_SOURCE_SYSTEM_ID", expected_system_id)):
        if not (gia_tri or "").strip():
            raise DormSyncConfigError("Thiếu biến môi trường %s" % ten)
    expected_db = _chuan_hoa_dinh_danh_khai_bao(expected_source_db)
    # Tên database so KHỚP CHÍNH XÁC, không hạ chữ — xem `_ghep_dinh_danh`.
    expected_dbname = expected_db.rsplit("/", 1)[-1]
    expected_system_id = expected_system_id.strip()

    actual_dbname = (await session.execute(text("select current_database()"))).scalar()
    if (actual_dbname or "").strip() != expected_dbname:
        raise DormSyncGuardError(
            f"Từ chối ghi: database thật tên '{actual_dbname}' nhưng khai báo "
            f"DORM_SYNC_SOURCE_DB trỏ '{expected_dbname}'."
        )

    try:
        actual_system_id = (
            await session.execute(
                text("select system_identifier from pg_control_system()")
            )
        ).scalar()
    except Exception as exc:
        raise DormSyncGuardError(
            "Từ chối ghi: không đọc được `system_identifier` của cluster "
            f"({type(exc).__name__}). Đây là lớp duy nhất chứng minh đúng MÁY, "
            "nên không đọc được thì dừng — không bỏ qua."
        ) from exc

    if str(actual_system_id).strip() != expected_system_id:
        raise DormSyncGuardError(
            "Từ chối ghi: cluster nguồn có system_identifier "
            f"'{actual_system_id}' nhưng khai báo DORM_SYNC_SOURCE_SYSTEM_ID là "
            f"'{expected_system_id}'. "
            "Tên database khớp mà cluster lệch = đang đọc một BẢN SAO, không "
            "phải hệ thật."
        )
