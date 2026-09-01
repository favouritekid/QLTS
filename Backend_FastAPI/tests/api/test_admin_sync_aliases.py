# Backend_FastAPI/tests/api/test_admin_sync_aliases.py
"""
Khoá HAI alias `sync` của admin bằng REQUEST HTTP THẬT đi hết vòng ASGI.

VÌ SAO PHẢI LÀ REQUEST THẬT
---------------------------
`app/routers/admin/sync.py` chỉ khai hai alias uỷ quyền (gọi hàm trực tiếp)
sang `app/routers/admin/users.py`. Đọc decorator bằng mắt và kiểm policy
Casbin KHÔNG chứng minh được rằng alias:

  1. bind đúng dependency (`db` + `current_admin`) — không bị FastAPI hiểu
     nhầm thành tham số query bắt buộc;
  2. nhận được BODY và truyền nguyên vẹn xuống implementation;
  3. thực sự gọi tới implementation — chứ không phải một no-op trả 200.

Đây đúng lớp lỗi vừa gặp ở `organization.py`: một `Depends(lambda ...)` trông
hợp lệ trên giấy nhưng FastAPI nâng tham số của lambda thành QUERY bắt buộc
⇒ endpoint LUÔN 422 trong khi mọi phép kiểm tĩnh vẫn xanh. Chỉ một request
thật mới phân biệt được "route sống" với "route chết".

ĐƯỜNG ĐO (đọc từ mã, không từ tài liệu)
---------------------------------------
  GET  /api/admin/sync/status  → app/routers/admin/sync.py:31 (`@router.get("/status")`)
                → users.get_sync_status()   (app/routers/admin/users.py:573)
  POST /api/admin/sync         → app/routers/admin/sync.py:53 (`@router.post("")`)
                → users.sync_users()        (app/routers/admin/users.py:628)

Cả hai alias uỷ quyền bằng LỜI GỌI HÀM (`from . import users` rồi
`await users.<fn>(...)`), không phải `include_router` cũng không phải
redirect — nên đường HTTP của alias và của canonical phải cho CÙNG một kết
quả; `test_alias_va_canonical_tra_cung_ket_qua` khoá đúng điều đó.

KHÔNG MOCK
----------
Không mock alias, không mock `users.get_sync_status` / `users.sync_users`,
không mock Casbin enforcer, không mock repository. Mock bất kỳ cái nào trong
số đó là bỏ qua đúng giao ước cần đo. Bộ này không cần mock gì cả — enforcer
thật do lifespan dựng, DB thật là `qlts_test`.

CẢNH BÁO CHO NGƯỜI SỬA VỀ SAU
-----------------------------
Đường dẫn dưới đây được viết THẲNG dạng chuỗi, cố ý không dùng hằng số dùng
chung: chuỗi ĐÓ CHÍNH LÀ giao ước. Nếu alias đổi path, ca kiểm phải đỏ chứ
không được đổi theo.
"""
import logging
from typing import Any, Dict

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)


# Giao ước đường dẫn — viết thẳng, KHÔNG lấy từ hằng số dùng chung.
URL_STATUS_ALIAS = "/api/admin/sync/status"
URL_SYNC_ALIAS = "/api/admin/sync"
# Đường CANONICAL mà alias uỷ quyền tới (app/routers/admin/users.py).
URL_STATUS_CANONICAL = "/api/admin/users/sync/status"

# Role dùng để tạo LỆCH giữa DB và Casbin. Cả hai user trong ca drift đều
# được Casbin coi là "user" (một user có g-rule `role:user`, một user KHÔNG
# có g-rule nào nên rơi vào fallback "user" — xem
# `user_service.get_highest_priority_role_from_casbin`). Ghi "officer" vào
# cột `user.role` của DB ⇒ DB lệch Casbin ở CẢ HAI.
ROLE_LECH = "officer"
ROLE_THEO_CASBIN = "user"


# ============================================================================
# HELPERS
# ============================================================================


def _khong_duoc_la_route_chet(response, mo_ta: str) -> None:
    """
    404 và 422 là DẤU VÂN TAY của hai kiểu alias hỏng KHÁC NHAU — tách riêng
    hai khẳng định để lúc đỏ còn biết đỏ vì gì.

    * 404 ⇒ route không được đăng ký (sai path trong decorator, sai prefix
      router, hoặc router không được include).
    * 422 trên một request KHÔNG có lỗi dữ liệu ⇒ FastAPI đã nâng một
      dependency thành tham số bắt buộc (ca `organization.py`).
    """
    assert response.status_code != 404, (
        f"{mo_ta} trả 404 — alias KHÔNG được đăng ký. Kiểm path trong "
        f"decorator + prefix của router `sync`. Body: {response.text}"
    )
    assert response.status_code != 422, (
        f"{mo_ta} trả 422 trong khi request KHÔNG hề sai dữ liệu — đây là "
        f"dấu vân tay của lỗi dependency bị FastAPI nâng thành tham số "
        f"query/body bắt buộc (đúng ca `organization.py`). "
        f"Body: {response.text}"
    )


def _la_so_nguyen(gia_tri: Any) -> bool:
    """`bool` là subclass của `int` trong Python — loại nó ra tường minh."""
    return isinstance(gia_tri, int) and not isinstance(gia_tri, bool)


def _khang_dinh_contract_status(data: Any) -> None:
    """Bốn khoá + kiểu của GET /api/admin/sync/status."""
    assert isinstance(data, dict), f"Response phải là object, nhận: {type(data)}"

    for khoa in (
        "total_users", "synced_count", "out_of_sync_count", "mismatched_users",
    ):
        assert khoa in data, f"Thiếu khoá `{khoa}` trong response. Có: {sorted(data)}"

    for khoa in ("total_users", "synced_count", "out_of_sync_count"):
        assert _la_so_nguyen(data[khoa]), (
            f"`{khoa}` phải là số nguyên, nhận {type(data[khoa]).__name__} "
            f"= {data[khoa]!r}"
        )

    assert isinstance(data["mismatched_users"], list), (
        f"`mismatched_users` phải là list, nhận "
        f"{type(data['mismatched_users']).__name__}"
    )


async def _dat_role_trong_db(user_id: int, role: str) -> None:
    """Ghi thẳng `user.role` bằng MỘT session riêng và commit."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = await session.get(models.User, user_id)
            assert user is not None, f"Không tìm thấy user id={user_id} để dựng lệch"
            user.role = role


async def _doc_role_bang_session_moi(user_id: int) -> str:
    """
    Đọc lại `user.role` bằng session HOÀN TOÀN MỚI.

    Bắt buộc phải là session mới: session cũ giữ identity map, đọc lại trên
    nó có thể trả về giá trị trong bộ nhớ chứ không phải giá trị đã nằm
    trong CSDL — tức là chứng minh nhầm.
    """
    async with AsyncSessionLocal() as session:
        user = await session.get(models.User, user_id)
        assert user is not None, f"Không tìm thấy user id={user_id} khi đọc lại"
        return user.role


def _map_mismatched_theo_id(data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {muc["user_id"]: muc for muc in data["mismatched_users"]}


# ============================================================================
# CA 1 — GET /api/admin/sync/status
# ============================================================================


@pytest.mark.asyncio
async def test_alias_get_sync_status_song_va_dung_contract(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Alias GET còn sống và trả ĐÚNG contract.

    Khẳng định:
      - KHÔNG 404 (route chết) và KHÔNG 422 (dependency bị nâng thành query);
      - status 200;
      - có đủ 4 khoá `total_users`, `synced_count`, `out_of_sync_count`,
        `mismatched_users`;
      - ba khoá đầu là số nguyên (loại `bool`), khoá cuối là list.
    """
    log.info("--- Running: test_alias_get_sync_status_song_va_dung_contract ---")

    response = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)

    _khong_duoc_la_route_chet(response, f"GET {URL_STATUS_ALIAS}")
    assert response.status_code == 200, (
        f"GET {URL_STATUS_ALIAS} phải trả 200, nhận {response.status_code}. "
        f"Body: {response.text}"
    )

    _khang_dinh_contract_status(response.json())


# ============================================================================
# CA 2 — POST /api/admin/sync
# ============================================================================


@pytest.mark.asyncio
async def test_alias_post_sync_nhan_body_va_dung_contract(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: Dict[str, Any],
):
    """
    Alias POST còn sống, NHẬN được body JSON, và trả ĐÚNG contract.

    Khẳng định:
      - KHÔNG 404 và KHÔNG 422 — 422 ở đây đặc biệt đắt giá: body gửi lên
        hợp lệ với `schemas.SyncUsersRequest`, nên 422 chỉ có thể đến từ một
        tham số mà FastAPI hiểu nhầm;
      - status 200;
      - có đủ 3 khoá `synced_count`, `failed_count`, `failed_users` với đúng
        kiểu;
      - `failed_count == 0` và `failed_users` rỗng — hai vế phải nhất quán.
    """
    log.info("--- Running: test_alias_post_sync_nhan_body_va_dung_contract ---")

    response = await client.post(
        URL_SYNC_ALIAS,
        json={"user_ids": [regular_user_in_db["id"]]},
        headers=admin_token_headers,
    )

    _khong_duoc_la_route_chet(response, f"POST {URL_SYNC_ALIAS}")
    assert response.status_code == 200, (
        f"POST {URL_SYNC_ALIAS} phải trả 200, nhận {response.status_code}. "
        f"Body: {response.text}"
    )

    data = response.json()
    assert isinstance(data, dict), f"Response phải là object, nhận {type(data)}"

    for khoa in ("synced_count", "failed_count", "failed_users"):
        assert khoa in data, f"Thiếu khoá `{khoa}` trong response. Có: {sorted(data)}"

    for khoa in ("synced_count", "failed_count"):
        assert _la_so_nguyen(data[khoa]), (
            f"`{khoa}` phải là số nguyên, nhận {type(data[khoa]).__name__} "
            f"= {data[khoa]!r}"
        )

    assert isinstance(data["failed_users"], list), (
        f"`failed_users` phải là list, nhận {type(data['failed_users']).__name__}"
    )
    assert data["failed_count"] == 0, (
        f"Sync một user hợp lệ mà vẫn có lỗi: failed_count="
        f"{data['failed_count']}, failed_users={data['failed_users']}"
    )
    assert data["failed_users"] == [], (
        f"`failed_count`=0 nhưng `failed_users` không rỗng — hai vế mâu "
        f"thuẫn: {data['failed_users']}"
    )


# ============================================================================
# CA 3 — HIỆU ỨNG THẬT: alias POST kéo role lệch về, ĐÚNG user được chỉ định
# ============================================================================


@pytest.mark.asyncio
async def test_alias_post_sync_keo_role_lech_ve_dung_user_duoc_chi_dinh(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: Dict[str, Any],
    test_user_in_db: Dict[str, Any],
):
    """
    Ca QUAN TRỌNG NHẤT của tệp: chứng minh alias có HIỆU ỨNG THẬT, và body
    `user_ids` được TÔN TRỌNG.

    Chỉ khẳng định `status == 200` thì một endpoint no-op cũng xanh. Ở đây
    dựng LỆCH thật giữa DB và Casbin cho HAI user, rồi chỉ sync MỘT:

      * user MỤC TIÊU  (`regular_user_in_db`, Casbin `role:user`)
      * user CHỨNG KIẾN (`test_user_in_db`, KHÔNG có g-rule ⇒ Casbin
        fallback "user")

    Vì sao phải có user CHỨNG KIẾN: `SyncUsersRequest.user_ids` là
    `Optional[List[int]] = None` và Pydantic v2 mặc định BỎ QUA field lạ.
    Nếu chỉ có một user, đổi tên khoá body (`user_ids` → `userIds`) sẽ khiến
    `user_ids=None` ⇒ sync TẤT CẢ ⇒ user duy nhất kia vẫn được kéo về ⇒ ca
    kiểm VẪN XANH dù giao ước body đã hỏng. User chứng kiến làm hai khẳng
    định `synced_count == 1` và "chứng kiến KHÔNG đổi" trở thành hàng rào
    thật cho tên khoá body.

    Đọc lại bằng session MỚI (không phải qua chính response) để giá trị đến
    từ CSDL chứ không từ identity map.
    """
    log.info(
        "--- Running: test_alias_post_sync_keo_role_lech_ve_dung_user_duoc_chi_dinh ---"
    )

    id_muc_tieu = regular_user_in_db["id"]
    id_chung_kien = test_user_in_db["id"]
    assert id_muc_tieu != id_chung_kien, "Hai fixture phải là hai user khác nhau"

    # --- Dựng LỆCH: DB nói "officer", Casbin nói "user" -------------------
    await _dat_role_trong_db(id_muc_tieu, ROLE_LECH)
    await _dat_role_trong_db(id_chung_kien, ROLE_LECH)

    # Tiền điều kiện: lệch phải THẬT SỰ nằm trong CSDL. Không có bước này,
    # một endpoint no-op vẫn có thể xanh chỉ vì dữ liệu vào quá yếu.
    assert await _doc_role_bang_session_moi(id_muc_tieu) == ROLE_LECH
    assert await _doc_role_bang_session_moi(id_chung_kien) == ROLE_LECH

    # --- Alias GET phải NHÌN THẤY lệch đó (nó đọc DB + Casbin thật) -------
    truoc = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    _khong_duoc_la_route_chet(truoc, f"GET {URL_STATUS_ALIAS}")
    assert truoc.status_code == 200, (
        f"GET {URL_STATUS_ALIAS} phải trả 200, nhận {truoc.status_code}. "
        f"Body: {truoc.text}"
    )
    data_truoc = truoc.json()
    _khang_dinh_contract_status(data_truoc)

    assert data_truoc["out_of_sync_count"] == 2, (
        f"Vừa dựng lệch cho ĐÚNG 2 user nhưng endpoint báo "
        f"out_of_sync_count={data_truoc['out_of_sync_count']}. "
        f"mismatched_users={data_truoc['mismatched_users']}"
    )
    assert len(data_truoc["mismatched_users"]) == data_truoc["out_of_sync_count"], (
        "`out_of_sync_count` không khớp độ dài `mismatched_users` — response "
        "tự mâu thuẫn"
    )
    assert (
        data_truoc["synced_count"] + data_truoc["out_of_sync_count"]
        == data_truoc["total_users"]
    ), (
        f"synced_count + out_of_sync_count phải bằng total_users: "
        f"{data_truoc['synced_count']} + {data_truoc['out_of_sync_count']} "
        f"!= {data_truoc['total_users']}"
    )

    lech_truoc = _map_mismatched_theo_id(data_truoc)
    assert set(lech_truoc) == {id_muc_tieu, id_chung_kien}, (
        f"Tập user lệch phải đúng là {{{id_muc_tieu}, {id_chung_kien}}}, "
        f"nhận {sorted(lech_truoc)}"
    )
    for user_id in (id_muc_tieu, id_chung_kien):
        assert lech_truoc[user_id]["db_role"] == ROLE_LECH, (
            f"user {user_id}: db_role phải là {ROLE_LECH!r}, nhận "
            f"{lech_truoc[user_id]['db_role']!r}"
        )
        assert lech_truoc[user_id]["casbin_role"] == ROLE_THEO_CASBIN, (
            f"user {user_id}: casbin_role phải là {ROLE_THEO_CASBIN!r}, nhận "
            f"{lech_truoc[user_id]['casbin_role']!r} — tiền đề của ca kiểm sai"
        )

    # --- Sync CHỈ user mục tiêu ------------------------------------------
    response = await client.post(
        URL_SYNC_ALIAS,
        json={"user_ids": [id_muc_tieu]},
        headers=admin_token_headers,
    )
    _khong_duoc_la_route_chet(response, f"POST {URL_SYNC_ALIAS}")
    assert response.status_code == 200, (
        f"POST {URL_SYNC_ALIAS} phải trả 200, nhận {response.status_code}. "
        f"Body: {response.text}"
    )

    data = response.json()
    assert data["failed_count"] == 0, (
        f"Sync thất bại: failed_users={data.get('failed_users')}"
    )
    assert data["synced_count"] == 1, (
        f"Phải sync ĐÚNG 1 user (user_ids=[{id_muc_tieu}]) nhưng "
        f"synced_count={data['synced_count']}. Nếu là 2 thì body `user_ids` "
        f"đã KHÔNG tới được implementation (Pydantic bỏ qua field lạ ⇒ "
        f"user_ids=None ⇒ sync tất cả). Nếu là 0 thì endpoint là no-op."
    )

    # --- Đọc lại bằng SESSION MỚI: nguồn sự thật là CSDL ------------------
    role_muc_tieu = await _doc_role_bang_session_moi(id_muc_tieu)
    assert role_muc_tieu == ROLE_THEO_CASBIN, (
        f"user mục tiêu {id_muc_tieu}: sau sync, `user.role` trong CSDL phải "
        f"được kéo về {ROLE_THEO_CASBIN!r} (Casbin là nguồn chân lý), nhưng "
        f"vẫn là {role_muc_tieu!r} — endpoint trả 200 mà KHÔNG ghi gì."
    )

    role_chung_kien = await _doc_role_bang_session_moi(id_chung_kien)
    assert role_chung_kien == ROLE_LECH, (
        f"user chứng kiến {id_chung_kien} KHÔNG nằm trong `user_ids` nên phải "
        f"giữ nguyên {ROLE_LECH!r}, nhưng đã thành {role_chung_kien!r} — "
        f"endpoint đã sync TẤT CẢ, tức body `user_ids` bị bỏ qua."
    )

    # --- Alias GET phản ánh đúng trạng thái sau khi sync -------------------
    sau = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    assert sau.status_code == 200, (
        f"GET {URL_STATUS_ALIAS} (lượt sau) phải trả 200, nhận "
        f"{sau.status_code}. Body: {sau.text}"
    )
    data_sau = sau.json()
    _khang_dinh_contract_status(data_sau)
    assert set(_map_mismatched_theo_id(data_sau)) == {id_chung_kien}, (
        f"Sau khi sync user {id_muc_tieu}, chỉ còn user {id_chung_kien} lệch; "
        f"endpoint báo {sorted(_map_mismatched_theo_id(data_sau))}"
    )


# ============================================================================
# CA 4 — Alias và canonical phải là CÙNG một implementation
# ============================================================================


@pytest.mark.asyncio
async def test_alias_va_canonical_tra_cung_ket_qua(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: Dict[str, Any],
):
    """
    `sync.py` uỷ quyền bằng LỜI GỌI HÀM tới `users.get_sync_status()`, nên
    alias và canonical phải trả về CÙNG một payload.

    Ca này bắt kiểu hỏng mà ba ca trên bỏ lọt: alias được viết lại thành một
    bản cài đặt RIÊNG (copy-paste) rồi trôi khỏi canonical. Cả hai đều là
    request HTTP thật; cả hai đều chỉ đọc, không đổi trạng thái, nên so sánh
    hai payload là hợp lệ.
    """
    log.info("--- Running: test_alias_va_canonical_tra_cung_ket_qua ---")

    alias = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    _khong_duoc_la_route_chet(alias, f"GET {URL_STATUS_ALIAS}")
    assert alias.status_code == 200, (
        f"GET {URL_STATUS_ALIAS} phải trả 200, nhận {alias.status_code}. "
        f"Body: {alias.text}"
    )

    canonical = await client.get(URL_STATUS_CANONICAL, headers=admin_token_headers)
    assert canonical.status_code == 200, (
        f"GET {URL_STATUS_CANONICAL} (đường canonical) phải trả 200, nhận "
        f"{canonical.status_code}. Body: {canonical.text}"
    )

    assert alias.json() == canonical.json(), (
        f"Alias {URL_STATUS_ALIAS} và canonical {URL_STATUS_CANONICAL} trả "
        f"khác nhau — alias đã không còn uỷ quyền tới cùng implementation.\n"
        f"alias     = {alias.json()}\n"
        f"canonical = {canonical.json()}"
    )


# ============================================================================
# CA 5 — 422 ĐÚNG phải đến từ BODY, không phải từ dependency bị nâng nhầm
# ============================================================================


@pytest.mark.asyncio
async def test_alias_post_sync_bat_body_sai_kieu_bang_422_tu_body(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Mặt còn lại của bốn ca trên: chứng minh alias THỰC SỰ khai một body model
    (`schemas.SyncUsersRequest`), và phân biệt 422 ĐÚNG với 422 SAI.

    * Nếu alias quên khai tham số body, FastAPI sẽ BỎ QUA payload ⇒ request
      sai kiểu vẫn trả 200 ⇒ ca này đỏ.
    * Nếu alias mắc lỗi kiểu `organization.py` (dependency bị nâng thành tham
      số bắt buộc), 422 sẽ trỏ vào `query` chứ không phải `body` ⇒ ca này đỏ
      ở khẳng định `loc`.

    Nhờ vậy, "422" ở tệp này không còn là một tín hiệu mù: bốn ca trên cấm
    422, ca này ĐÒI 422 và bắt nó phải trỏ đúng vào `body.user_ids`.
    """
    log.info("--- Running: test_alias_post_sync_bat_body_sai_kieu_bang_422_tu_body ---")

    response = await client.post(
        URL_SYNC_ALIAS,
        json={"user_ids": "khong-phai-mot-danh-sach"},
        headers=admin_token_headers,
    )

    assert response.status_code != 404, (
        f"POST {URL_SYNC_ALIAS} trả 404 — alias KHÔNG được đăng ký. "
        f"Body: {response.text}"
    )
    assert response.status_code == 422, (
        f"Body sai kiểu (`user_ids` là chuỗi, không phải list[int]) phải bị "
        f"chặn bằng 422. Nhận {response.status_code} — nghĩa là alias KHÔNG "
        f"khai body model nên payload bị bỏ qua. Body: {response.text}"
    )

    chi_tiet = response.json()
    loi = chi_tiet.get("errors")
    assert isinstance(loi, list) and loi, (
        f"Response 422 phải kèm danh sách `errors`, nhận: {chi_tiet}"
    )
    vi_tri = [tuple(muc.get("loc", ())) for muc in loi]
    assert any(vt and vt[0] == "body" for vt in vi_tri), (
        f"422 phải đến từ BODY. `loc` bắt đầu bằng `query`/`path` là dấu vân "
        f"tay của dependency bị FastAPI nâng thành tham số bắt buộc — đúng "
        f"lỗi của `organization.py`. loc nhận được: {vi_tri}"
    )
    assert any("user_ids" in vt for vt in vi_tri), (
        f"422 phải trỏ đích danh field `user_ids` của "
        f"`schemas.SyncUsersRequest`. loc nhận được: {vi_tri}"
    )
