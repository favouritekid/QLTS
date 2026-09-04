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

    Vì sao phải có user CHỨNG KIẾN: nó khoá PHẠM VI ghi, không khoá hình
    dạng body. `synced_count == 1` một mình có thể bị một implementation
    "đếm đúng, ghi thừa" qua mặt; chỉ khẳng định "chứng kiến KHÔNG đổi" mới
    phân biệt được "sync đúng tập" với "sync tất cả rồi đếm nhầm".

    (Lối hỏng qua TÊN KHOÁ nay đã có cổng riêng: `SyncUsersRequest` fail-closed
    — `extra="forbid"`, `user_ids` bắt buộc, không rỗng, id > 0 — và
    `test_payload_sai_bi_tu_choi_o_ca_hai_duong` gác nó. Trước bản vá ấy,
    `userIds` bị Pydantic nuốt im lặng ⇒ `user_ids=None` ⇒ sync TẤT CẢ.)

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
        f"đã KHÔNG tới được implementation — service đang sync TẤT CẢ thay "
        f"vì đúng danh sách. Nếu là 0 thì endpoint là no-op."
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


# =============================================================================
# MA TRẬN FAIL-CLOSED — payload sai KHÔNG được mở rộng phạm vi mutation
# =============================================================================
# Bản trước của `SyncUsersRequest` khai `Optional[List[int]] = None` và không
# cấm field lạ. Đo được trên chính lớp ấy::
#
#     {}                  -> user_ids=None
#     {"userId": [123]}   -> user_ids=None      (khoá lạ bị Pydantic NUỐT)
#     {"user_ids": []}    -> user_ids=[]
#
# Cả ba đều falsy, mà service rẽ nhánh bằng truthiness ⇒ cả ba rơi vào
# `repo.get_all()`. Một lỗi gõ phím biến "đồng bộ hai user" thành "ghi lên
# TOÀN BỘ user", và vẫn trả 200. Không phải vượt quyền (vẫn cần admin), nhưng
# là fail-open: sai sót của người gọi làm RỘNG THÊM tác động.
#
# Ma trận dưới đây khoá cả hai mặt: mặt TỪ CHỐI (payload sai ⇒ 422 đúng chỗ)
# và mặt HIỆU ỨNG (payload đúng ⇒ ghi đúng phạm vi, đo bằng session mới).

URL_SYNC_CANONICAL = "/api/admin/users/sync"

# Hai đường viết THẲNG, không sinh từ hằng chung: alias tự khai
# `sync_request: schemas.SyncUsersRequest` (sync.py:56) và uỷ quyền xuống
# canonical bằng LỜI GỌI HÀM Python (sync.py:74). Nghĩa là validate của
# canonical KHÔNG hề chạy trên request đi qua alias, và ngược lại. Suy một
# đường từ đường kia là bỏ sót đúng một nửa bề mặt.
CA_HAI_DUONG_SYNC = [URL_SYNC_ALIAS, URL_SYNC_CANONICAL]


def _loi_422(response, mo_ta: str) -> list:
    """Trả danh sách lỗi validation, sau khi khẳng định 422 ĐÚNG KIỂU.

    Bốn tầng, không rút gọn được tầng nào:
      1. không 404 — phân biệt "route chết" với "body sai";
      2. đúng 422;
      3. đúng envelope `VALIDATION_ERROR` — chặn 422 đến từ handler khác;
      4. không lỗi nào ở `query`/`path` — đó là vân tay của lỗi
         `organization.py` (dependency bị nâng thành tham số bắt buộc), đúng
         lớp lỗi mà tệp này sinh ra để bắt.
    """
    assert response.status_code != 404, (
        f"{mo_ta}: nhận 404 — route CHẾT, không phải body sai. "
        f"Thân: {response.text[:300]}"
    )
    assert response.status_code == 422, (
        f"{mo_ta}: kỳ vọng 422, nhận {response.status_code}. "
        f"Thân: {response.text[:300]}"
    )
    body = response.json()
    assert body.get("error_code") == "VALIDATION_ERROR", (
        f"{mo_ta}: 422 nhưng error_code là {body.get('error_code')!r} — "
        f"422 này đến từ handler khác. Thân: {response.text[:300]}"
    )
    loi = body.get("errors")
    assert isinstance(loi, list) and loi, (
        f"{mo_ta}: `errors` phải là list không rỗng, nhận {loi!r}"
    )
    sai_cho = [e for e in loi if (e.get("loc") or [None])[0] in ("query", "path")]
    assert not sai_cho, (
        f"{mo_ta}: có lỗi ở query/path — dependency đã bị nâng thành tham số "
        f"bắt buộc (đúng lỗi organization.py): {sai_cho!r}"
    )
    return loi


# (ten, payload, type kỳ vọng, loc kỳ vọng)
#
# Hai ca đánh dấu ⚑ là ca PHÂN GIẢI, không phải ca thừa:
#
#  ⚑ `khoa-la-kem-user_ids-hop-le`: nếu chỉ có `khoa-la-userId`, đột biến "bỏ
#    `extra=forbid`" VẪN SỐNG SÓT — vì `user_ids` bắt buộc nên `{"userId":[1]}`
#    vẫn 422 do `missing`. Ở ca này `user_ids` hợp lệ, nên 422 CHỈ CÓ THỂ đến
#    từ `extra="forbid"`. Đo được: payload ấy cho đúng MỘT lỗi.
#
#  ⚑ `id-am-o-vi-tri-thu-hai`: khoá `loc` tới đúng CHỈ SỐ phần tử, chống bản vá
#    nửa vời chỉ kiểm phần tử đầu tiên.
MA_TRAN_TU_CHOI = [
    ("thieu-khoa", {}, "missing", ["body", "user_ids"]),
    ("khoa-la-userId", {"userId": [1]}, "extra_forbidden", ["body", "userId"]),
    ("khoa-la-kem-user_ids-hop-le",
     {"user_ids": [1], "userId": [1]}, "extra_forbidden", ["body", "userId"]),
    ("mang-rong", {"user_ids": []}, "too_short", ["body", "user_ids"]),
    ("id-bang-khong", {"user_ids": [0]}, "greater_than", ["body", "user_ids", 0]),
    ("id-am", {"user_ids": [-1]}, "greater_than", ["body", "user_ids", 0]),
    ("id-am-o-vi-tri-thu-hai",
     {"user_ids": [1, -5]}, "greater_than", ["body", "user_ids", 1]),
    ("khong-phai-list",
     {"user_ids": "khong-phai-mot-danh-sach"}, "list_type", ["body", "user_ids"]),

    # ── KIỂU JSON của TỪNG PHẦN TỬ ──────────────────────────────────────────
    # Ca `khong-phai-list` chỉ khoá kiểu của CONTAINER. Không có bốn ô dưới
    # đây, một phần tử sai kiểu vẫn bị Pydantic ÉP thành ID hợp lệ. Đo qua
    # JSON, đúng đường HTTP đi, trước khi có `strict=True`::
    #
    #     [true]     -> [1]      bool thành user ID 1
    #     ["7"]      -> [7]
    #     [7.0]      -> [7]
    #     [1, true]  -> [1, 1]   trùng lặp âm thầm
    #
    # `true -> 1` là ca xấu nhất: nó luôn trỏ vào user có id nhỏ nhất, thường
    # là tài khoản quản trị đầu tiên. Không còn mở rộng ra toàn bộ user như
    # lỗi trước, nhưng là mutation NHẦM ĐỐI TƯỢNG.
    ("bool-bi-ep-thanh-id",
     {"user_ids": [True]}, "int_type", ["body", "user_ids", 0]),
    ("chuoi-so-bi-ep",
     {"user_ids": ["7"]}, "int_type", ["body", "user_ids", 0]),
    ("float-tron-bi-ep",
     {"user_ids": [7.0]}, "int_type", ["body", "user_ids", 0]),
    # ⚑ Phần tử hỏng ở VỊ TRÍ THỨ HAI: chống bản vá chỉ kiểm phần tử đầu.
    ("bool-o-vi-tri-thu-hai",
     {"user_ids": [1, True]}, "int_type", ["body", "user_ids", 1]),
    # ⚑ Ca THỨ TỰ CỔNG: chuỗi "-1" phải chết ở cổng KIỂU (`int_type`),
    # KHÔNG phải ở cổng giá trị (`greater_than`). Nếu ai "sửa" bằng cách
    # thêm validator giá trị thay vì siết kiểu, ca này đỏ — vì lúc ấy
    # "-1" được ép thành -1 rồi mới bị `gt=0` bắt.
    ("chuoi-am-phai-chet-o-cong-KIEU",
     {"user_ids": ["-1"]}, "int_type", ["body", "user_ids", 0]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ten,payload,type_mong_doi,loc_mong_doi",
    MA_TRAN_TU_CHOI,
    ids=[m[0] for m in MA_TRAN_TU_CHOI],
)
async def test_payload_sai_bi_tu_choi_o_ca_hai_duong(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    ten: str,
    payload: Dict[str, Any],
    type_mong_doi: str,
    loc_mong_doi: list,
):
    """Payload sai phải 422 ở ĐÚNG chỗ, trên CẢ alias lẫn canonical.

    Lặp hai đường BÊN TRONG một ca thay vì parametrize thêm một chiều: các ca
    từ chối không đổi trạng thái, nên dựng fixture hai lần chỉ tốn truncate +
    lifespan + login mà không thêm sức phân giải nào.

    ⚠️ Mọi request đều mang `admin_token_headers`. Auth giải TRƯỚC validate
    body (`deps.py`), nên thiếu token là đo nhầm 403 rồi tưởng đã kiểm 422.
    """
    for url in CA_HAI_DUONG_SYNC:
        mo_ta = f"[{ten}] POST {url}"
        response = await client.post(url, json=payload, headers=admin_token_headers)
        loi = _loi_422(response, mo_ta)

        cap = [(e.get("type"), list(e.get("loc") or [])) for e in loi]
        assert (type_mong_doi, loc_mong_doi) in cap, (
            f"{mo_ta}: không thấy lỗi (type={type_mong_doi!r}, "
            f"loc={loc_mong_doi!r}). Các lỗi thực tế: {cap!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CA_HAI_DUONG_SYNC)
async def test_null_tuong_minh_dong_bo_TOAN_BO_user_lech(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: Dict[str, Any],
    regular_user_in_db: Dict[str, Any],
    test_user_in_db: Dict[str, Any],
    url: str,
):
    """`{"user_ids": null}` = đồng bộ toàn bộ — và phải đo được là TOÀN BỘ.

    Dựng HAI user lệch chứ không một. Với một user, đột biến "chỉ sync phần tử
    đầu" hoặc "sync đúng một" vẫn xanh; hai user mới phân biệt được "toàn bộ"
    với "một phần".
    """
    id_a = regular_user_in_db["id"]
    id_b = test_user_in_db["id"]
    id_admin = admin_user_in_db["id"]
    assert len({id_a, id_b, id_admin}) == 3, "ba user phải phân biệt"

    await _dat_role_trong_db(id_a, "officer")
    await _dat_role_trong_db(id_b, "officer")

    # Tiền điều kiện: lệch nằm trong CSDL THẬT, không phải trong identity map.
    assert await _doc_role_bang_session_moi(id_a) == "officer"
    assert await _doc_role_bang_session_moi(id_b) == "officer"

    truoc = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    assert truoc.status_code == 200, truoc.text
    lech_truoc = _map_mismatched_theo_id(truoc.json())
    assert set(lech_truoc) == {id_a, id_b}, (
        "tiền đề hỏng: Casbin phải nói 'user' cho cả hai. Đang lệch: "
        f"{sorted(lech_truoc)}; kỳ vọng {sorted({id_a, id_b})}"
    )
    assert id_admin not in lech_truoc, (
        "admin phải KHỚP — nếu admin cũng lệch thì `synced_count` kỳ vọng sai, "
        "và ca này sẽ đổi quyền của chính token đang dùng"
    )

    response = await client.post(
        url, json={"user_ids": None}, headers=admin_token_headers
    )
    _khong_duoc_la_route_chet(response, f"POST {url} với user_ids=null")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["failed_count"] == 0 and data["failed_users"] == [], data
    assert data["synced_count"] == 2, (
        f"null tường minh phải kéo CẢ HAI user lệch; nhận "
        f"synced_count={data['synced_count']}. 1 ⇒ chỉ sync một; "
        f"0 ⇒ no-op. Thân: {data}"
    )

    assert await _doc_role_bang_session_moi(id_a) == "user"
    assert await _doc_role_bang_session_moi(id_b) == "user", (
        "user THỨ HAI không được kéo về — đây đúng là đột biến mà một user lệch "
        "không bao giờ bắt được"
    )
    assert await _doc_role_bang_session_moi(id_admin) == "admin", (
        "sync toàn bộ không được phá quyền của chính actor"
    )

    sau = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    assert sau.json()["out_of_sync_count"] == 0, sau.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CA_HAI_DUONG_SYNC)
async def test_danh_sach_khong_rong_chi_dong_bo_dung_muc_tieu(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: Dict[str, Any],
    regular_user_in_db: Dict[str, Any],
    test_user_in_db: Dict[str, Any],
    url: str,
):
    """Mảng không rỗng = đúng tập ấy, không hơn. User CHỨNG KIẾN giữ nguyên.

    Khẳng định chứng kiến là thứ duy nhất khoá được PHẠM VI: `synced_count`
    một mình có thể bị một implementation "đếm đúng, ghi thừa" qua mặt.
    """
    id_muc_tieu = regular_user_in_db["id"]
    id_chung_kien = test_user_in_db["id"]

    await _dat_role_trong_db(id_muc_tieu, "officer")
    await _dat_role_trong_db(id_chung_kien, "officer")
    assert await _doc_role_bang_session_moi(id_chung_kien) == "officer"

    truoc = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    assert set(_map_mismatched_theo_id(truoc.json())) == {id_muc_tieu, id_chung_kien}

    response = await client.post(
        url, json={"user_ids": [id_muc_tieu]}, headers=admin_token_headers
    )
    _khong_duoc_la_route_chet(response, f"POST {url} với một mục tiêu")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["failed_count"] == 0, data
    assert data["synced_count"] == 1, (
        f"chỉ được sync ĐÚNG một user; nhận {data['synced_count']}. 2 ⇒ body "
        f"`user_ids` không tới được implementation. Thân: {data}"
    )

    assert await _doc_role_bang_session_moi(id_muc_tieu) == "user"
    assert await _doc_role_bang_session_moi(id_chung_kien) == "officer", (
        "user CHỨNG KIẾN bị đổi — phạm vi ghi đã rộng hơn danh sách được chỉ định"
    )
    assert await _doc_role_bang_session_moi(admin_user_in_db["id"]) == "admin"

    sau = await client.get(URL_STATUS_ALIAS, headers=admin_token_headers)
    assert set(_map_mismatched_theo_id(sau.json())) == {id_chung_kien}


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CA_HAI_DUONG_SYNC)
async def test_mang_rong_bi_tu_choi_va_KHONG_ghi_gi(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: Dict[str, Any],
    url: str,
):
    """`[]` là ca LAI: về hình thức là từ chối, chế độ hỏng lại là sync-ALL.

    Nếu `min_length=1` bị gỡ, `[]` đi lọt và `if user_ids is not None:` ở
    service sẽ gọi `get_by_ids([])` — no-op. Nhưng nếu ai đó ĐỒNG THỜI khôi
    phục truthiness cũ (`if user_ids:`), `[]` lại thành "toàn bộ". Nên ngoài
    422, ca này còn khẳng định user lệch VẪN LỆCH sau lời gọi.
    """
    id_a = regular_user_in_db["id"]
    await _dat_role_trong_db(id_a, "officer")
    assert await _doc_role_bang_session_moi(id_a) == "officer"

    response = await client.post(
        url, json={"user_ids": []}, headers=admin_token_headers
    )
    loi = _loi_422(response, f"POST {url} với mảng rỗng")
    cap = [(e.get("type"), list(e.get("loc") or [])) for e in loi]
    assert ("too_short", ["body", "user_ids"]) in cap, cap

    assert await _doc_role_bang_session_moi(id_a) == "officer", (
        "mảng rỗng bị từ chối NHƯNG server vẫn ghi — 422 trả về sau khi đã "
        "thay đổi trạng thái là kiểu hỏng tệ nhất trong nhóm này"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CA_HAI_DUONG_SYNC)
@pytest.mark.parametrize(
    "nhan,bien_doi",
    [("chuoi", lambda i: str(i)), ("float", lambda i: float(i))],
    ids=["id-that-dang-chuoi", "id-that-dang-float"],
)
async def test_id_that_sai_kieu_bi_tu_choi_va_KHONG_ghi_gi(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: Dict[str, Any],
    test_user_in_db: Dict[str, Any],
    url: str,
    nhan: str,
    bien_doi,
):
    """ID có THẬT nhưng sai kiểu JSON: 422, và CSDL không được đổi.

    Khác các ô ma trận ở chỗ id ở đây TỒN TẠI. Nếu coercion còn sống, request
    không chỉ 200 — nó GHI THẬT lên đúng user ấy. Nên ca này đo hai điều mà
    một ô 422 thuần không đo được:

      1. server từ chối TRƯỚC khi chạm CSDL (không phải "422 sau khi đã ghi");
      2. user chứng kiến cũng không bị đụng, tức phạm vi không bị nới.
    """
    id_muc_tieu = regular_user_in_db["id"]
    id_chung_kien = test_user_in_db["id"]

    await _dat_role_trong_db(id_muc_tieu, "officer")
    await _dat_role_trong_db(id_chung_kien, "officer")
    assert await _doc_role_bang_session_moi(id_muc_tieu) == "officer"

    response = await client.post(
        url,
        json={"user_ids": [bien_doi(id_muc_tieu)]},
        headers=admin_token_headers,
    )
    loi = _loi_422(response, f"POST {url} với id thật dạng {nhan}")
    cap = [(e.get("type"), list(e.get("loc") or [])) for e in loi]
    assert ("int_type", ["body", "user_ids", 0]) in cap, (
        f"id thật dạng {nhan} phải bị từ chối bằng `int_type` ở đúng chỉ số 0; "
        f"các lỗi thực tế: {cap!r}"
    )

    assert await _doc_role_bang_session_moi(id_muc_tieu) == "officer", (
        f"id dạng {nhan} bị ép thành int rồi GHI THẬT lên user {id_muc_tieu} — "
        "coercion đã biến một kiểu JSON sai thành lệnh ghi hợp lệ"
    )
    assert await _doc_role_bang_session_moi(id_chung_kien) == "officer", (
        "user chứng kiến bị đụng — phạm vi ghi rộng hơn cả danh sách sai kiểu"
    )
