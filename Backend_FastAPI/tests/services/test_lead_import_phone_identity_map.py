# -*- coding: utf-8 -*-
"""Bản đồ ``lead_id ↔ SĐT`` ở đường nhập hàng loạt không được dựa vào thứ tự
``RETURNING``.

``bulk_insert_leads`` chạy ``INSERT … VALUES (…),(…) RETURNING id`` rồi trả một
danh sách id TRẦN; ``import_leads_from_file_content`` ghép lại bằng
``zip(batch, batch_ids)``. Chuẩn SQL KHÔNG hứa thứ tự các hàng ``RETURNING``
trùng thứ tự trong ``VALUES``. Khi thứ tự lệch, SĐT của lead A được đăng ký cho
lead B — và hậu quả không dừng ở một hàng sai trong bảng phụ: cả sổ khoá số
(``lead_phone_identity``) lẫn đường thả số lúc xoá mềm đều đi theo bản đồ ấy.

Ba ca ở đây đo ba tầng khác nhau của CÙNG một sự cố:

* ``test_moi_hang_identity_phai_thuoc_dung_lead`` — bất biến CẤU TRÚC.
* ``test_xoa_mem_mot_lead_chi_tha_so_cua_chinh_no`` — hậu quả NGHIỆP VỤ. Ca này
  giá trị hơn: nó không nhắc tới ``zip``, ``RETURNING`` hay tên cột nào của cách
  cài đặt, nên một bản vá đúng theo cách khác vẫn xanh.
* ``test_returning_thieu_hang_thi_huy_ca_lo_khong_dang_ky_nua_voi`` — hậu điều
  kiện fail-closed. Hai ca trên chỉ HOÁN VỊ nên multiset không đổi và không
  chạm tới nó; thiếu ca này thì gỡ hẳn hậu điều kiện vẫn xanh.
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.lead_phone import LeadPhoneIdentity
from app.repositories.lead_repository import LeadRepository
from app.services import lead_service
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# =============================================================================
# DỮ LIỆU — bốn số RỜI NHAU, và thứ tự của chúng KHÔNG trùng thứ tự chèn
# =============================================================================
#
# ⚠️ Bốn ràng buộc của bộ số này, mỗi cái vá một kiểu xanh-giả:
#
# 1. BỐN số phân biệt. ``uq_lead_phone_active`` là index UNIQUE trên
#    ``phone_normalized`` MỘT MÌNH (không kèm ``lead_id``/``slot``). Dùng lại
#    một số ở hai lead ⇒ ``IntegrityError`` nổ NGAY trong ``begin_nested`` của
#    lô, cả lô bị lùi, ``errors`` có 2 dòng và assertion dưới không bao giờ
#    chạy — ca "đỏ" mà không đo gì.
# 2. Cả hai lead đều có ``phone2``. Để ``None`` là mất một nửa phép đo: bản đồ
#    lệch chỉ còn lộ ra ở slot ``phone``.
# 3. Thứ tự SỐ ngược thứ tự CHÈN ở slot ``phone`` (A=098… > B=036…) và xuôi ở
#    slot ``phone2`` (A=038… < B=097…). ``TRUNCATE … RESTART IDENTITY`` khiến id
#    lead luôn tăng dần theo thứ tự chèn — nếu SĐT cũng tăng cùng chiều thì "sắp
#    theo id" và "sắp theo SĐT" cho cùng một dãy, và một hoán vị trở thành VÔ
#    HÌNH với mọi assertion kiểu sắp-xếp-rồi-so. Trộn hai chiều ở hai slot ⇒
#    không tồn tại phép sắp xếp nào cứu được phép ghép sai.
# 4. Số của A ở dạng ``+84…`` trong tệp. Nó buộc đường chuẩn hoá chạy thật, và
#    chứng minh assertion dưới (so CỘT với CỘT, không so với literal trong tệp)
#    không phụ thuộc dạng nhập.

A_TEN = "Nguyễn Thị Lệch A"
A_PHONE_TRONG_TEP = "+84987000001"   # → 0987000001
A_PHONE = "0987000001"
A_PHONE2 = "0388000002"

B_TEN = "Trần Văn Lệch B"
B_PHONE = "0366000003"
B_PHONE2 = "0977000004"

BON_SO = [A_PHONE, A_PHONE2, B_PHONE, B_PHONE2]


def _csv_hai_lead(unit_id: int) -> bytes:
    return (
        "full_name,phone,phone2,source,unit_id\n"
        f"{A_TEN},{A_PHONE_TRONG_TEP},{A_PHONE2},website,{unit_id}\n"
        f"{B_TEN},{B_PHONE},{B_PHONE2},website,{unit_id}\n"
    ).encode("utf-8")


@pytest_asyncio.fixture
async def import_ready_deps(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Đóng dấu ``legacy_status='new'`` + ``is_final=false`` cho TTHV000.

    ``import_leads_from_file_content`` tra trạng thái ban đầu qua
    ``StatusHelper.get_initial_status(db)`` — truy vấn đúng hai cột này.
    ``seeded_dependencies`` để chúng NULL (suite khác phụ thuộc điều đó), nên
    thiếu fixture này thì import ném ``ValueError`` trước khi chạm INSERT và ca
    test "đỏ" vì lý do hoàn toàn khác. Bản sao CÓ CHỦ Ý của fixture cùng tên ở
    ``test_lead_phase1_hardening.py`` — fixture ấy file-local, không import chéo.
    """
    await db.execute(
        text(
            "UPDATE consultation_status SET legacy_status = 'new', is_final = false "
            "WHERE id = :sid"
        ),
        {"sid": INITIAL_LEAD_STATUS_ID},
    )
    await db.flush()
    return seeded_dependencies


# =============================================================================
# HOOK — đảo thứ tự HÀNG ``RETURNING``, không giả lập gì khác
# =============================================================================


class _KetQuaDaoHang:
    """Bọc kết quả THẬT, chỉ đảo thứ tự các HÀNG.

    Không giả lập CSDL: lệnh INSERT đã chạy thật, khoá ngoại thật, id thật do
    sequence cấp. Vật này mô phỏng đúng MỘT điều — CSDL trả các hàng
    ``RETURNING`` theo thứ tự khác thứ tự trong ``VALUES``.

    Hiểu ``fetchall()``, ``all()``, ``scalars()`` và phép lặp — đủ cho CẢ cách
    tiêu thụ hiện tại (``result.scalars().all()``) LẪN cách một bản vá nhiều
    khả năng dùng (``.returning(id, phone, phone2)`` rồi ``fetchall()``). Mọi
    thuộc tính khác thì fail-LOUD: nếu mã sản phẩm đổi cách đọc kết quả, ta muốn
    biết ngay chứ không muốn ca test âm thầm ngừng đo.
    """

    def __init__(self, hang):
        self._hang = list(hang)

    def fetchall(self):
        return list(self._hang)

    def all(self):
        return list(self._hang)

    def __iter__(self):
        return iter(list(self._hang))

    def scalars(self):
        return _ScalarsDaoHang(self._hang)

    def __getattr__(self, ten):
        raise AssertionError(
            f"`bulk_insert_leads` gọi `result.{ten}` — vật bọc này chỉ hiểu "
            "`fetchall()` / `all()` / `scalars()` / lặp. Cập nhật vật bọc, "
            "ĐỪNG bỏ ca test."
        )


class _ScalarsDaoHang:
    """``ScalarResult`` giả: cột đầu của mỗi hàng, giữ nguyên thứ tự đã đảo."""

    def __init__(self, hang):
        self._hang = list(hang)

    def all(self):
        return [h[0] for h in self._hang]

    def __iter__(self):
        return iter([h[0] for h in self._hang])

    def __getattr__(self, ten):
        raise AssertionError(
            f"`bulk_insert_leads` gọi `result.scalars().{ten}` — vật bọc này "
            "chỉ hiểu `all()` và lặp. Cập nhật vật bọc, ĐỪNG bỏ ca test."
        )


def _hook_dao_thu_tu_returning(monkeypatch, db) -> dict:
    """Đảo thứ tự HÀNG ``RETURNING`` của lệnh INSERT vào bảng ``lead``.

    🔴 Đặt ở ``db.execute``, KHÔNG bọc ``LeadRepository.bulk_insert_leads``.
    Đây là khác biệt quyết định. Sau bản vá, chính ``bulk_insert_leads`` là nơi
    ràng buộc SĐT với id — mỗi phần tử nó trả về TỰ MÔ TẢ. Bọc bên NGOÀI nó là
    đảo những cặp đã tự mô tả: vô hại theo định nghĩa. Một đột biến bên TRONG
    (giữ nguyên kiểu trả về mới nhưng ghép lại bằng ``zip(batch, rows)``, vẫn
    qua mọi cổng độ dài) sẽ KHÔNG bị bắt. Ở tầng ``db.execute`` thì bị.

    Chỉ chạm đúng ``Insert`` vào bảng ``lead``: mọi ``SELECT``/``UPDATE`` của
    ``check_batch_phone_conflict``, ``calculate_lead_score``, ``StatusHelper``,
    ``unregister_phone_identities``… đi qua nguyên vẹn. Các hàng
    ``lead_phone_identity`` do ``db.add`` sinh ra đi theo đường flush của ORM,
    KHÔNG qua ``db.execute``, nên không bị vật này chạm tới.
    """
    from sqlalchemy.sql.dml import Insert

    that = db.execute
    trang_thai = {"so_lan_dao": 0, "so_hang_dao": 0}

    async def _bao_boc(statement, *a, **k):
        ket = await that(statement, *a, **k)
        bang = getattr(statement, "table", None)
        if not isinstance(statement, Insert) or bang is None:
            return ket
        if bang.name != models.Lead.__tablename__:
            return ket
        hang = list(ket.fetchall())
        if len(hang) < 2:
            # Đảo danh sách < 2 phần tử là phép ĐỒNG NHẤT — KHÔNG đếm, để phép
            # kiểm tiền đề bên dưới bắt được ca vô nghĩa.
            return _KetQuaDaoHang(hang)
        trang_thai["so_lan_dao"] += 1
        trang_thai["so_hang_dao"] = len(hang)
        return _KetQuaDaoHang(reversed(hang))

    monkeypatch.setattr(db, "execute", _bao_boc)
    return trang_thai


def _hook_bo_bot_hang_returning(monkeypatch, db) -> dict:
    """Bỏ BỚT một hàng ``RETURNING`` của lệnh INSERT vào bảng ``lead``.

    Mô phỏng ca CSDL/driver trả về THIẾU hàng. Khác hẳn hoán vị: ở đây tập
    cặp SĐT trả về không còn khớp tập đã gửi, nên đây là ca duy nhất chạm
    tới hậu điều kiện ``Counter`` trong ``bulk_insert_leads``. Không có ca
    này thì gỡ hẳn hậu điều kiện ấy vẫn xanh — một guard không phép kiểm
    nào canh được.

    Lệnh INSERT vẫn chạy THẬT và cả hai hàng lead đã nằm trong savepoint;
    chỉ phần kết quả trả về là bị cắt. Đó đúng là hình dạng nguy hiểm: nếu
    không ai chặn, chỗ gọi đăng ký danh tính cho MỘT lead rồi commit lead
    còn lại mà KHÔNG khoá số của nó.
    """
    from sqlalchemy.sql.dml import Insert

    that = db.execute
    trang_thai = {"so_lan_cat": 0}

    async def _bao_boc(statement, *a, **k):
        ket = await that(statement, *a, **k)
        bang = getattr(statement, "table", None)
        if not isinstance(statement, Insert) or bang is None:
            return ket
        if bang.name != models.Lead.__tablename__:
            return ket
        hang = list(ket.fetchall())
        if len(hang) < 2:
            return _KetQuaDaoHang(hang)
        trang_thai["so_lan_cat"] += 1
        return _KetQuaDaoHang(hang[:-1])

    monkeypatch.setattr(db, "execute", _bao_boc)
    return trang_thai


# =============================================================================
# TIỆN ÍCH
# =============================================================================


async def _nhap_hai_lead(db: AsyncSession, unit_id: int, monkeypatch) -> dict:
    """Nhập CSV hai lead với thứ tự ``RETURNING`` bị đảo. Trả về ``{tên: id}``.

    Hook đặt SAU khi fixture đã seed xong — ta chỉ muốn nó chạm lệnh INSERT của
    lượt nhập, không chạm phần dựng dữ liệu nền.
    """
    hook = _hook_dao_thu_tu_returning(monkeypatch, db)

    ket_qua, _ = await lead_service.import_leads_from_file_content(
        file_content=_csv_hai_lead(unit_id),
        filename="hai_lead.csv",
        db=db,
        default_unit_id=unit_id,
    )

    # --- TIỀN ĐỀ: không có mấy dòng này thì mọi assertion dưới đều vô nghĩa ---
    assert ket_qua.failed_imports == 0, (
        "Tiền đề hỏng: có dòng bị từ chối nên lô không đủ hai lead. "
        f"errors={[e.error_message for e in ket_qua.errors]}"
    )
    assert ket_qua.successful_imports == 2, (
        f"Tiền đề hỏng: mong 2 lead được tạo, đo được {ket_qua.successful_imports}"
    )
    assert hook["so_lan_dao"] == 1, (
        "Tiền đề hỏng: không lần INSERT nào vào `lead` bị đảo ⇒ ca này không đo "
        f"gì (so_lan_dao={hook['so_lan_dao']}). Kiểm lại `batch_size` — nếu hai "
        "lead rơi vào hai lô thì mỗi lô chỉ có 1 hàng và hoán vị là phép đồng nhất."
    )
    assert hook["so_hang_dao"] == 2, (
        f"Tiền đề hỏng: đảo {hook['so_hang_dao']} hàng là phép đồng nhất"
    )

    # 🔴 Tra id theo `full_name`, TUYỆT ĐỐI không theo `created_lead_ids[i]`.
    # Danh sách ấy được dựng từ chính thứ tự `RETURNING` mà ta vừa đảo — lấy
    # `[0]` làm "lead A" là để phép đo tự trôi theo thứ đang bị nghi ngờ.
    hang = (await db.execute(
        select(models.Lead.id, models.Lead.full_name)
        .where(models.Lead.full_name.in_([A_TEN, B_TEN]))
    )).fetchall()
    theo_ten = {ten: lid for lid, ten in hang}
    assert set(theo_ten) == {A_TEN, B_TEN}, (
        f"Tiền đề hỏng: mong hai lead {A_TEN!r}/{B_TEN!r}, đo được {sorted(theo_ten)}"
    )
    return theo_ten


# =============================================================================
# CA 1 — bất biến CẤU TRÚC
# =============================================================================


async def test_moi_hang_identity_phai_thuoc_dung_lead(
    db: AsyncSession, import_ready_deps: dict, monkeypatch,
):
    """MỌI hàng ``lead_phone_identity`` phải mang SĐT của CHÍNH lead nó trỏ tới.

    Bất biến DUY NHẤT: với mỗi hàng identity, ``phone_normalized`` bằng
    ``lead.phone`` (slot ``'phone'``) hoặc ``lead.phone2`` (slot ``'phone2'``)
    của đúng ``lead_id`` ghi trên hàng đó.

    Phép so là CỘT với CỘT (``lead_phone_identity`` JOIN ``lead``), không so với
    literal trong tệp CSV: ``LeadCreate`` đã chuẩn hoá ``+84…`` → ``0…`` trước
    khi ghi, nên so với literal sẽ đỏ vì lý do sai. Hai vế đều là bản đã chuẩn
    hoá và ``normalize_vietnam_phone`` luỹ đẳng trên số đã chuẩn ⇒ so ``==``
    trần là đúng.
    """
    theo_ten = await _nhap_hai_lead(db, import_ready_deps["unit_id"], monkeypatch)

    # Đếm GIỚI HẠN vào đúng hai lead vừa nhập, không đếm toàn bảng: một fixture
    # khác có lead mang SĐT sẽ làm phép đếm toàn cục lệch vì lý do vô can.
    tong = (await db.execute(
        select(func.count()).select_from(LeadPhoneIdentity)
        .where(
            LeadPhoneIdentity.lead_id.in_(list(theo_ten.values())),
            LeadPhoneIdentity.deleted_at.is_(None),
        )
    )).scalar_one()
    assert tong == 4, (
        f"Tiền đề hỏng: mong ĐÚNG 4 hàng identity còn sống (2 lead × 2 slot), "
        f"đo được {tong}. 0 nghĩa là bước đăng ký không chạy — khi đó phép kiểm "
        "lệch bên dưới xanh một cách rỗng."
    )

    lech = (await db.execute(text("""
        SELECT i.lead_id, i.slot, i.phone_normalized, l.phone, l.phone2
        FROM lead_phone_identity i
        JOIN lead l ON l.id = i.lead_id
        WHERE i.deleted_at IS NULL
          AND i.phone_normalized IS DISTINCT FROM
              (CASE i.slot WHEN 'phone' THEN l.phone
                           WHEN 'phone2' THEN l.phone2 END)
    """))).fetchall()

    assert not lech, (
        "Sổ khoá số ghi SĐT vào NHẦM lead. (lead_id, slot, phone_normalized, "
        f"lead.phone, lead.phone2) = {[tuple(r) for r in lech]!r}. Bản đồ "
        "lead↔SĐT đang dựa vào THỨ TỰ của `RETURNING`, thứ không có bảo đảm "
        "hình thức nào."
    )


# =============================================================================
# CA 2 — hậu quả NGHIỆP VỤ (giá trị cao hơn ca cấu trúc)
# =============================================================================


async def test_xoa_mem_mot_lead_chi_tha_so_cua_chinh_no(
    db: AsyncSession, import_ready_deps: dict, admin_user: models.User, monkeypatch,
):
    """Xoá mềm lead A phải thả SĐT của A và GIỮ KHOÁ SĐT của B.

    Đây là điều người dùng thật chạm phải: sau khi xoá A, nhân viên nhập lại số
    của A thì phải được, còn nhập số của B thì phải bị chặn. Với bản đồ lệch,
    ``unregister_phone_identities(A)`` soft-delete những hàng TRỎ VỀ A — mà
    chúng đang mang số của B ⇒ hệ thống thả nhầm số của một lead CÒN SỐNG và
    khoá vĩnh viễn số của lead đã xoá. Đảo ngược đúng 100%.

    Đo bằng ``check_batch_phone_conflict`` — nó đọc ``lead_phone_identity``,
    nguồn chuẩn của quy tắc "một số thuộc tối đa một lead sống".

    🔴 KHÔNG đo bằng ``check_phone_conflict``: hàm đó đọc CỘT ``lead.phone`` /
    ``lead.phone2``, mà hai cột ấy do chính lệnh INSERT ghi nên KHÔNG BAO GIỜ
    lệch. Dùng nó ở đây cho xanh trên cả mã hỏng — đúng nghĩa bẫy xanh giả.
    """
    theo_ten = await _nhap_hai_lead(db, import_ready_deps["unit_id"], monkeypatch)
    repo = LeadRepository(db)

    # --- TIỀN ĐỀ: trước khi xoá, CẢ BỐN số đều đang bị khoá ---
    # Không có mốc này thì một lượt "khoá 0 số" cũng thoả khẳng định phủ định
    # bên dưới, và ta không phân biệt được "thả đúng" với "chưa khoá bao giờ".
    truoc = await repo.check_batch_phone_conflict(BON_SO)
    assert truoc == set(BON_SO), (
        f"Tiền đề hỏng: mong cả 4 số đang bị khoá, đo được {sorted(truoc)}"
    )

    await lead_service.delete_lead(db, theo_ten[A_TEN], deleted_by=admin_user)
    await db.flush()

    sau = await repo.check_batch_phone_conflict(BON_SO)

    assert sau == {B_PHONE, B_PHONE2}, (
        f"Sau khi xoá mềm lead A, tập số CÒN BỊ KHOÁ = {sorted(sau)}, "
        f"đáng lẽ = {sorted({B_PHONE, B_PHONE2})}.\n"
        f"  · số của A ({A_PHONE}, {A_PHONE2}) còn khoá ⇒ không ai nhập lại "
        "được lead vừa xoá.\n"
        f"  · số của B ({B_PHONE}, {B_PHONE2}) đã thả ⇒ hệ thống cho phép tạo "
        "lead trùng SĐT với một lead ĐANG SỐNG.\n"
        "Cả hai đều là hệ quả của việc bản đồ lead↔SĐT bám vào thứ tự "
        "`RETURNING`."
    )


# =============================================================================
# CA 3 — hậu điều kiện fail-closed của ``bulk_insert_leads``
# =============================================================================


async def test_returning_thieu_hang_thi_huy_ca_lo_khong_dang_ky_nua_voi(
    db: AsyncSession, import_ready_deps: dict, monkeypatch,
):
    """``RETURNING`` trả thiếu hàng ⇒ huỷ TRỌN lô, không đăng ký nửa vời.

    Đây là ca kiểm ngược của hậu điều kiện ``Counter`` trong
    ``bulk_insert_leads``. Hai ca trên chỉ HOÁN VỊ các hàng nên multiset
    không đổi và không chạm tới hậu điều kiện ấy; gỡ nó đi chúng vẫn xanh.

    Nếu hậu điều kiện bị gỡ: lệnh INSERT đã chèn CẢ HAI lead, nhưng vòng lặp
    chỉ thấy MỘT hàng nên chỉ một lead được khoá số. Lead còn lại vào cơ sở
    dữ liệu với SĐT KHÔNG có mặt trong ``lead_phone_identity`` — tức quy tắc
    "một số thuộc tối đa một lead sống" bị thủng im lặng, và lượt nhập sau
    tạo được lead thứ hai trùng số.

    Đo bằng trạng thái NGOÀI: số lead thật sự nằm trong bảng và kết quả trả
    về cho người nhập — không bắt ``pytest.raises`` quanh ngoại lệ nội bộ.
    Cách này còn đúng nếu ngày mai bản vá đổi sang một cơ chế chặn khác.
    """
    hook = _hook_bo_bot_hang_returning(monkeypatch, db)

    ket_qua, _ = await lead_service.import_leads_from_file_content(
        file_content=_csv_hai_lead(import_ready_deps["unit_id"]),
        filename="hai_lead.csv",
        db=db,
        default_unit_id=import_ready_deps["unit_id"],
    )

    assert hook["so_lan_cat"] == 1, (
        "Tiền đề hỏng: không lần INSERT nào bị cắt bớt hàng ⇒ ca này không "
        f"đo gì (so_lan_cat={hook['so_lan_cat']})"
    )

    # --- Lô phải bị huỷ TRỌN, không lead nào sống sót ---
    con_lai = (await db.execute(
        select(func.count()).select_from(models.Lead)
        .where(models.Lead.full_name.in_([A_TEN, B_TEN]))
    )).scalar_one()
    assert con_lai == 0, (
        f"Mong 0 lead sống sót khi `RETURNING` trả thiếu hàng, đo được "
        f"{con_lai}. Một lead lọt vào cơ sở dữ liệu mà không ai khoá SĐT "
        "của nó là lỗ thủng im lặng của quy tắc một-số-một-lead."
    )
    assert ket_qua.successful_imports == 0, (
        f"Mong 0 dòng thành công, đo được {ket_qua.successful_imports}"
    )
    assert ket_qua.created_lead_ids == [], (
        f"Mong không id nào được trả về, đo được {ket_qua.created_lead_ids}"
    )
    _muc_loi = [(e.row_number, e.error_message) for e in ket_qua.errors]
    assert any(so == -1 for so, _ in _muc_loi), (
        "Mong một mục lỗi cấp LÔ (row_number=-1) báo cho người nhập biết "
        f"cả lô không ghi được; đo được {_muc_loi!r}"
    )

    # Không hàng identity nào của bốn số này được để lại.
    con_identity = (await db.execute(
        select(func.count()).select_from(LeadPhoneIdentity)
        .where(LeadPhoneIdentity.phone_normalized.in_(BON_SO))
    )).scalar_one()
    assert con_identity == 0, (
        f"Mong 0 hàng identity sót lại, đo được {con_identity}"
    )
