"""Chạy TRỌN ``import_leads_from_file_content`` với một dòng email trống.

Test ở ``test_lead_import_empty_cells.py`` kiểm helper và khoá cấu trúc — bắt được
regression ở chỗ đã sửa, nhưng KHÔNG chứng minh dòng thiếu email đi hết luồng và
tạo ra lead. Nếu mai kia có ai thêm một phép kiểm email ở tầng khác trong cùng
hàm này, những test kia vẫn xanh còn người dùng vẫn mất dòng.

Ở đây thay repository + tra cứu trạng thái bằng bản giả, nên chạy được không cần
cơ sở dữ liệu, mà vẫn đi qua đúng đoạn đọc file → làm sạch ô → dựng ``LeadCreate``
→ gom lô.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import lead_service

pytestmark = pytest.mark.unit

# Dòng 2 để trống email, education_level VÀ location — ba trường từng bị ép kiểu
# thành chuỗi "nan". Hai trường sau KHÔNG qua validator nào nên trước đây chúng
# lặng lẽ ghi rác vào cơ sở dữ liệu; phải CÓ MẶT trong CSV thì test mới chạm tới
# (thiếu cột thì `lead.get("location")` trả None và assert đúng một cách vô nghĩa).
CSV = (
    "full_name,email,phone,source,education_level,location,unit_id\n"
    "Có Email,co@example.com,0900000001,website,THPT,Đắk Lắk,14\n"
    "Không Email,,0900000002,website,,,14\n"
)


class _RepoGia:
    """Repository giả: không đụng cơ sở dữ liệu, ghi lại thứ được chèn."""

    def __init__(self, *_a, **_kw):
        self.da_chen = []
        self._id_ke_tiep = 1

    async def check_batch_email_conflict(self, *_a, **_kw):
        return set()

    async def check_batch_phone_conflict(self, *_a, **_kw):
        return set()

    async def bulk_insert_leads(self, batch):
        """Cấp id KHÔNG trùng nhau giữa các lô, y như ``RETURNING`` thật.

        🔴 Bản đầu trả ``range(1, len(batch)+1)`` cho MỌI lô, nên lô 1 và lô 2
        cùng ra id [1..50]. Khi đó test chỉ còn phân biệt được ĐỘ DÀI danh sách:
        cắt nhầm đầu danh sách thay vì cuối vẫn cho đúng 100 phần tử và mọi phép
        kiểm vẫn xanh, trong khi ngoài đời phản hồi trả về id của lô đã bị lùi.
        Id chạy liên tục thì nội dung danh sách mới nói lên điều gì.
        """
        self.da_chen.extend(batch)
        ids = list(range(self._id_ke_tiep, self._id_ke_tiep + len(batch)))
        self._id_ke_tiep += len(batch)
        return ids

    async def register_phone_identities(self, *_a, **_kw):
        return None


@pytest.fixture
def repo_gia(monkeypatch):
    holder = {}

    def _factory(*a, **kw):
        repo = holder.get("repo") or _RepoGia()
        holder["repo"] = repo
        return repo

    monkeypatch.setattr(lead_service, "LeadRepository", _factory)
    return holder


async def _chay(db_gia):
    return await lead_service.import_leads_from_file_content(
        file_content=CSV.encode("utf-8"),
        filename="thu.csv",
        db=db_gia,
        default_unit_id=14,
        auto_assign_officer_id=None,
    )


@pytest.fixture
def db_gia():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)

    # ``async with db.begin_nested()`` — AsyncMock trả coroutine chứ không phải
    # context manager, nên phải dựng tay.
    @asynccontextmanager
    async def _nested():
        yield None

    db.begin_nested = MagicMock(side_effect=lambda *a, **kw: _nested())
    return db


async def test_dong_thieu_email_van_tao_duoc_lead(repo_gia, db_gia):
    """Ca thật: 7/211 thí sinh không có email vẫn phải vào được hệ thống.

    ``Lead.email`` nullable, ``LeadCreate.email`` Optional, và 2425/2535 lead trên
    production không có email — nên dòng thiếu email là chuyện BÌNH THƯỜNG, không
    phải lỗi dữ liệu.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await _chay(db_gia)

    ket_qua = res[0] if isinstance(res, tuple) else res
    assert ket_qua.successful_imports == 2, (
        f"dòng thiếu email bị loại: {ket_qua.errors}"
    )
    assert ket_qua.failed_imports == 0

    da_chen = repo_gia["repo"].da_chen
    assert len(da_chen) == 2
    # ``bulk_insert_leads`` nhận list DICT (pg_insert().values(...)), không phải model
    emails = [x.get("email") if isinstance(x, dict) else getattr(x, "email", None)
              for x in da_chen]
    assert emails[0] == "co@example.com"
    assert emails[1] is None, (
        f"email trống phải là None, đang là {emails[1]!r} — chuỗi 'nan' quay lại"
    )


async def test_khong_dong_nao_mang_chuoi_nan(repo_gia, db_gia):
    """Không trường chuỗi nào được mang giá trị 'nan' vào cơ sở dữ liệu.

    🔴 Bản đầu của ca này PASS cả trên code chưa sửa, vì hai lẽ: CSV lúc đó không
    có cột ``education_level``/``location`` để mà kiểm, và trên code cũ dòng thiếu
    email bị loại từ vòng validate nên danh sách chèn chỉ còn dòng đầy đủ — không
    còn ô trống nào để lộ chuỗi "nan". Nay CSV có đủ hai cột đó và ca này khẳng
    định **cả hai dòng** đều được chèn.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await _chay(db_gia)

    # Đọc KẾT QUẢ SERVICE TRẢ VỀ, không chỉ danh sách của repo giả: `da_chen`
    # được append ngay trong `bulk_insert_leads`, tức TRƯỚC mọi thứ có thể hỏng
    # sau đó, nên một mình nó không chứng minh service báo cáo đúng.
    kq = res[0] if isinstance(res, tuple) else res
    assert kq.successful_imports == 2, f"service báo {kq.successful_imports}: {kq.errors}"
    assert kq.failed_imports == 0
    assert len(kq.created_lead_ids) == 2

    da_chen = repo_gia["repo"].da_chen
    assert len(da_chen) == 2, (
        f"phải chèn CẢ HAI dòng mới chạm được ô trống; đang chèn {len(da_chen)}"
    )
    # Quét MỌI khoá của bản ghi sắp chèn, không theo một danh sách trường viết
    # sẵn: thêm cột mới vào vòng lặp mà quên xử lý ô trống là đúng cách lỗi này
    # ra đời, và danh sách viết sẵn thì không bao giờ biết về cột mới đó.
    for lead in da_chen:
        cap = lead.items() if isinstance(lead, dict) else vars(lead).items()
        for truong, gia_tri in cap:
            assert gia_tri != "nan", f"{truong} mang chuỗi 'nan'"

    # Dòng 2 để trống ba trường — chúng phải là None, không phải "nan" cũng không
    # phải chuỗi rỗng lửng lơ.
    dong_trong = da_chen[1]
    for truong in ("email", "education_level", "location"):
        gia_tri = (dong_trong.get(truong) if isinstance(dong_trong, dict)
                   else getattr(dong_trong, truong, None))
        assert gia_tri is None, f"{truong} phải là None, đang là {gia_tri!r}"


CSV_THIEU_BAT_BUOC = (
    "full_name,email,phone,source,unit_id\n"
    "Có Tên,a@example.com,0900000001,website,14\n"
    ",b@example.com,0900000002,website,14\n"        # full_name TRỐNG
    "Thiếu Nguồn,c@example.com,0900000003,,14\n"    # source TRỐNG
)


async def test_o_bat_buoc_trong_thi_bao_loi_chu_khong_tao_lead_ten_nan(repo_gia, db_gia):
    """ĐỔI HÀNH VI có chủ đích: ô bắt buộc trống nay báo lỗi dòng.

    Trước bản vá, ``full_name``/``source`` trống được ép thành chuỗi "nan" và
    **lọt qua validator** — hệ thống nhận về một lead tên "nan", nguồn "nan".
    Nhập được, nhưng nhập rác: cái tên đó rồi sẽ hiện trên màn hình officer và
    trong báo cáo nguồn tuyển sinh.

    Nay chúng thành chuỗi rỗng nên validator bắt được và người import biết dòng
    nào hỏng để sửa. Đây là ĐÁNH ĐỔI: hai dòng kiểu này chuyển từ "nhập được"
    sang "bị loại" — cố ý, và chỉ ảnh hưởng dòng đó chứ không hỏng cả file.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await lead_service.import_leads_from_file_content(
            file_content=CSV_THIEU_BAT_BUOC.encode("utf-8"),
            filename="thieu.csv", db=db_gia,
            default_unit_id=14, auto_assign_officer_id=None,
        )

    kq = res[0] if isinstance(res, tuple) else res
    assert kq.successful_imports == 1, f"chỉ dòng đầy đủ được nhận: {kq.errors}"
    assert kq.failed_imports == 2

    loi = " ".join(e.error_message for e in kq.errors)
    assert "'nan'" not in loi, "ô trống vẫn bị ép thành chuỗi 'nan'"

    # Và tuyệt đối không có lead nào mang tên/nguồn "nan" lọt vào lô chèn.
    for lead in repo_gia["repo"].da_chen:
        for truong in ("full_name", "source"):
            gt = lead.get(truong) if isinstance(lead, dict) else getattr(lead, truong, None)
            assert gt != "nan", f"{truong} = 'nan' — rác lọt vào cơ sở dữ liệu"


CSV_KHONG_CO_COT_EMAIL = (
    "full_name,phone,source,unit_id\n"
    "Không Cột Email,0900000001,website,14\n"
    "Cũng Không,0900000002,website,14\n"
)


async def test_file_khong_co_cot_email_van_nhap_duoc(repo_gia, db_gia):
    """File THIẾU HẲN cột email vẫn phải nhập được.

    Ô email trống đã xử lý ở các ca trên; đây là ca khác: cột không tồn tại. Bắt
    buộc phải có cột `email` nghĩa là chính nhóm đông nhất — 2425/2535 lead trên
    production không có email — lại là nhóm không lập nổi file import.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await lead_service.import_leads_from_file_content(
            file_content=CSV_KHONG_CO_COT_EMAIL.encode("utf-8"),
            filename="khong_cot_email.csv", db=db_gia,
            default_unit_id=14, auto_assign_officer_id=None,
        )

    kq = res[0] if isinstance(res, tuple) else res
    assert kq.successful_imports == 2, f"bị từ chối vì thiếu cột email: {kq.errors}"
    for lead in repo_gia["repo"].da_chen:
        gt = lead.get("email") if isinstance(lead, dict) else getattr(lead, "email", None)
        assert gt is None


# ---------------------------------------------------------------------------
# Báo cáo trả về phải khớp thứ THẬT SỰ nằm trong cơ sở dữ liệu
# ---------------------------------------------------------------------------

CSV_HAI_LO = "full_name,email,phone,source,unit_id\n" + "".join(
    f"Người {i},nguoi{i}@example.com,09{i:08d},website,14\n" for i in range(1, 151)
)


class _RepoLoHaiHong(_RepoGia):
    """Lô đầu ghi được; lô thứ hai chèn xong mới nổ.

    🔑 Lỗi phải nổ SAU ``bulk_insert_leads``: nếu cho chính ``bulk_insert_leads``
    raise thì service chưa kịp cầm ``batch_ids`` nào, danh sách không thể nhiễm,
    và test sẽ pass cả trên code chưa sửa (đã mắc đúng lỗi này ở bản đầu). Ngoài
    đời cũng nổ muộn như vậy: ``register_phone_identities`` chỉ ``db.add(...)``
    nên lần ghi thật xảy ra lúc THOÁT savepoint.

    ``loai_loi`` để dựng được cả hai họ lỗi. Đó là điểm mấu chốt: bản vá đầu chỉ
    dọn dẹp trong nhánh ``except IntegrityError``, nên mọi lỗi cơ sở dữ liệu KHÁC
    vẫn để lọt id của lô đã lùi.
    """

    def __init__(self, loai_loi=None, *a, **kw):
        super().__init__(*a, **kw)
        self.so_lo = 0
        self.loai_loi = loai_loi

    async def bulk_insert_leads(self, batch):
        self.so_lo += 1
        return await super().bulk_insert_leads(batch)

    async def register_phone_identities(self, *a, **kw):
        if self.so_lo >= 2 and self.loai_loi is not None:  # lô thứ hai
            raise self.loai_loi("INSERT ...", {}, Exception("lỗi cơ sở dữ liệu"))
        return None


async def _chay_hai_lo(monkeypatch, db_gia, loai_loi):
    holder = {}
    monkeypatch.setattr(
        lead_service, "LeadRepository",
        lambda *a, **kw: holder.setdefault("repo", _RepoLoHaiHong(loai_loi)),
    )
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await lead_service.import_leads_from_file_content(
            file_content=CSV_HAI_LO.encode("utf-8"), filename="hai_lo.csv",
            db=db_gia, default_unit_id=14, auto_assign_officer_id=None,
        )
    return res[0] if isinstance(res, tuple) else res


async def test_lo_bi_rollback_khong_duoc_dem_la_da_nhap(monkeypatch, db_gia):
    """Lô nổ IntegrityError phải BIẾN MẤT khỏi báo cáo, không chỉ ghi thêm dòng lỗi.

    ``created_lead_ids.extend()`` từng nằm TRONG savepoint: khi savepoint lùi, cơ
    sở dữ liệu quay lại còn danh sách Python thì không. Trước bản vá, 150 dòng
    chia hai lô mà lô hai hỏng vẫn báo 150 thành công, và router phát
    ``LEAD_IMPORTED`` kèm 50 id không tồn tại.
    """
    from sqlalchemy.exc import IntegrityError

    kq = await _chay_hai_lo(monkeypatch, db_gia, IntegrityError)

    # Lô 1 (100 dòng) ghi được, lô 2 (50 dòng) rollback.
    assert kq.successful_imports == 100, (
        f"đang đếm cả lô đã rollback: {kq.successful_imports}"
    )
    # 🔴 So NỘI DUNG, không so độ dài. Repo giả cấp id chạy liên tục 1..150, nên
    # lô sống là [1..100] và lô đã lùi là [101..150]. Nếu chỉ kiểm ``len == 100``
    # thì một bản vá cắt nhầm đầu danh sách (giữ [51..150]) vẫn xanh, trong khi
    # phản hồi trả về 50 id không tồn tại.
    assert kq.created_lead_ids == list(range(1, 101)), (
        f"trả về id của lô đã bị lùi: {kq.created_lead_ids[:3]}…{kq.created_lead_ids[-3:]}"
    )


async def test_lo_hong_vi_loi_KHAC_IntegrityError_cung_khong_duoc_ro_id(
    monkeypatch, db_gia
):
    """Lỗi cơ sở dữ liệu KHÔNG phải ``IntegrityError`` cũng không được để lọt id.

    🔴 Đây là kẽ hở của chính bản vá trước: phần dọn dẹp chỉ nằm trong nhánh
    ``except IntegrityError``, mà ``DataError`` (một ô dài quá cột — ví dụ
    ``education_level`` khai ``Optional[str]`` không giới hạn trong khi cột là
    ``String(100)``) và ``OperationalError`` (deadlock, hết giờ câu lệnh) là ANH
    EM của ``IntegrityError`` chứ không phải con. Chúng rơi xuống ``except
    Exception`` bên ngoài — nơi bản vá đã cố ý bỏ dòng xoá danh sách — nên lô vừa
    bị savepoint lùi lại vẫn nằm nguyên trong báo cáo.
    """
    from sqlalchemy.exc import DataError

    kq = await _chay_hai_lo(monkeypatch, db_gia, DataError)

    assert kq.successful_imports == 100, (
        f"lô bị lùi vì DataError vẫn được đếm: {kq.successful_imports}"
    )
    assert kq.created_lead_ids == list(range(1, 101)), (
        "phản hồi mang id của lô đã rollback — router sẽ phát LEAD_IMPORTED theo "
        f"những id không tồn tại: {kq.created_lead_ids[-3:]}"
    )


async def test_ba_con_so_trong_bao_cao_phai_cong_khop(monkeypatch, db_gia):
    """``tổng = thành công + thất bại`` phải đúng, kể cả khi mất nguyên một lô.

    ``failed_imports`` từng là ``len(errors)``, mà cả lô 50 dòng bị lùi chỉ sinh
    MỘT mục lỗi → báo cáo nói "150 dòng, 100 thành công, 1 thất bại". Người nhập
    đọc thông báo "bỏ qua 1 dòng" rồi đi tìm một dòng hỏng, trong khi 50 lead đã
    lặng lẽ biến mất. ``total_rows_processed`` không hiện ở đâu trên giao diện nên
    không có cách nào đối chiếu.
    """
    from sqlalchemy.exc import IntegrityError

    kq = await _chay_hai_lo(monkeypatch, db_gia, IntegrityError)

    assert kq.total_rows_processed == 150
    assert kq.successful_imports + kq.failed_imports == kq.total_rows_processed, (
        f"ba con số không cộng khớp: {kq.total_rows_processed} ≠ "
        f"{kq.successful_imports} + {kq.failed_imports}"
    )
    assert kq.failed_imports == 50, f"đếm thiếu dòng đã mất: {kq.failed_imports}"

    # Và phải chỉ ra ĐÚNG NHỮNG DÒNG nào mất, không phải một câu "lô 2 lỗi".
    dong_bao_loi = {e.row_number for e in kq.errors}
    assert dong_bao_loi == set(range(102, 152)), (
        "không nêu được dòng nào bị mất; người nhập không biết nhập lại phần nào: "
        f"{sorted(dong_bao_loi)[:5]}"
    )


# ---------------------------------------------------------------------------
# Cột trùng tên sau chuẩn hoá
# ---------------------------------------------------------------------------

CSV_COT_TRUNG = (
    "Full Name,full_name,email,phone,source,unit_id\n"
    "Tên A,Tên B,a@example.com,0900000001,website,14\n"
)


async def test_cot_trung_sau_chuan_hoa_bi_tu_choi_ro_rang(repo_gia, db_gia):
    """Hai cột hoá trùng tên phải bị từ chối bằng thông báo đọc được, không phải 500.

    "Full Name" và "full_name" cùng ra "full_name" sau chuẩn hoá. Khi đó
    ``df['email']`` trả DataFrame chứ không phải Series, và ``.dropna().astype(str)``
    ở đoạn gom email ném ``AttributeError`` NGOÀI mọi try/except của vòng lặp dòng
    → người dùng nhận HTTP 500 trống trơn. Ngoài ra ``row.to_dict()`` âm thầm bỏ
    mất một trong hai cột, tức dữ liệu biến mất không dấu vết.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        with pytest.raises(ValueError) as exc:
            await lead_service.import_leads_from_file_content(
                file_content=CSV_COT_TRUNG.encode("utf-8"), filename="trung.csv",
                db=db_gia, default_unit_id=14, auto_assign_officer_id=None,
            )

    tin = str(exc.value)
    assert "trùng tên" in tin, f"thông báo không nói rõ vấn đề: {tin}"
    assert "full_name" in tin, "phải chỉ đúng cột nào trùng"
    # 🔴 Bản đầu viết ``assert X == [] if "repo" in repo_gia else True``. Theo thứ
    # tự ưu tiên của Python đó là ``assert (X == []) if (...) else True`` — mà
    # ``repo_gia`` chỉ có khoá "repo" sau khi service dựng ``LeadRepository``,
    # tức SAU chỗ ném lỗi này. Điều kiện luôn sai ⇒ ``assert True`` mọi lần chạy,
    # không bao giờ kiểm điều nó khai là kiểm.
    assert repo_gia.get("repo") is None or repo_gia["repo"].da_chen == [], (
        "đã chèn lead trước khi từ chối file — phải chặn từ lúc đọc cột"
    )


CSV_TRUNG_COT_EMAIL = (
    "full_name,Email,email,phone,source,unit_id\n"
    "Tên A,a@example.com,b@example.com,0900000001,website,14\n"
)


async def test_trung_cot_email_khong_con_no_HTTP_500(repo_gia, db_gia):
    """Trùng đúng cột ``email`` là ca nổ nặng nhất — phải thành lỗi đọc được.

    "Email" và "email" cùng ra "email". Đoạn gom email để kiểm trùng chạy
    ``df['email'].dropna().astype(str).tolist()`` — với cột trùng, ``df['email']``
    là DataFrame nên ``.tolist()`` ném ``AttributeError``. Chỗ đó nằm NGOÀI mọi
    try/except của vòng lặp dòng, nên nó thoát thẳng ra router thành HTTP 500
    trống trơn, không nói người dùng phải sửa gì.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        with pytest.raises(ValueError) as exc:
            await lead_service.import_leads_from_file_content(
                file_content=CSV_TRUNG_COT_EMAIL.encode("utf-8"),
                filename="trung_email.csv", db=db_gia,
                default_unit_id=14, auto_assign_officer_id=None,
            )

    # ValueError → router đổi thành 400 kèm thông báo; AttributeError thì thành 500.
    # (``pytest.raises(ValueError)`` ở trên đã loại AttributeError rồi — khẳng
    # định lại điều đó chỉ là đúng theo định nghĩa, không kiểm được gì thêm.)
    tin = str(exc.value)
    assert "trùng tên" in tin
    assert "email" in tin, f"phải chỉ đúng cột email là cột trùng: {tin}"
    assert repo_gia.get("repo") is None or repo_gia["repo"].da_chen == []


CSV_KY_TU_DAU_DAC_BIET = (
    "full_name,email,phone,source,location,unit_id\n"
    "-Trang Nguyễn,a@example.com,0900000001,website,-,14\n"
    "+Minh Hoàng,b@example.com,0900000002,website,=A1,14\n"
)


async def test_khong_chen_dau_nhay_vao_du_lieu_luc_nhap(repo_gia, db_gia):
    """Dữ liệu vào cơ sở dữ liệu phải NGUYÊN VẸN, không bị chèn dấu nháy.

    ``sanitize_csv_cell`` là hàng rào của tầng XUẤT: nó thêm dấu ' trước các ký tự
    mở đầu công thức (``= + - @``) để bảng tính không diễn giải ô đó. Áp vào lúc
    NHẬP thì dữ liệu bẩn vĩnh viễn — người tên "-Trang" thành "'-Trang" trên mọi
    màn hình, `location` ghi "-" (nghĩa là không có) thành "'-" — mà chẳng bảo vệ
    được gì, vì đường xuất (``routers/leads.py``) vốn đã sanitize.

    ``payment_import_service`` ghi rõ cùng quy ước ở bước ingest của nó.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        await lead_service.import_leads_from_file_content(
            file_content=CSV_KY_TU_DAU_DAC_BIET.encode("utf-8"),
            filename="dac_biet.csv", db=db_gia,
            default_unit_id=14, auto_assign_officer_id=None,
        )

    da_chen = repo_gia["repo"].da_chen
    assert len(da_chen) == 2, "cả hai dòng phải vào được"
    lay = lambda d, k: d.get(k) if isinstance(d, dict) else getattr(d, k, None)

    assert lay(da_chen[0], "full_name") == "-Trang Nguyễn"
    assert lay(da_chen[0], "location") == "-"
    assert lay(da_chen[1], "full_name") == "+Minh Hoàng"
    assert lay(da_chen[1], "location") == "=A1"

    for lead in da_chen:
        for truong in ("full_name", "source", "location"):
            gt = lay(lead, truong)
            assert not (gt or "").startswith("'"), (
                f"{truong} bị chèn dấu nháy lúc nhập: {gt!r}"
            )


# ---------------------------------------------------------------------------
# Hàng tiêu đề không phải chuỗi (.xlsx)
# ---------------------------------------------------------------------------

def _xlsx(tieu_de, cac_dong) -> bytes:
    """Dựng .xlsx thật, giữ NGUYÊN kiểu của từng ô tiêu đề.

    Không dùng ``DataFrame.to_excel`` vì pandas ép tên cột về chuỗi khi ghi —
    đúng cái kiểu dữ liệu mà ca này cần giữ lại.
    """
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(list(tieu_de))
    for dong in cac_dong:
        ws.append(list(dong))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _chay_bytes(db_gia, noi_dung: bytes, ten: str):
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await lead_service.import_leads_from_file_content(
            file_content=noi_dung, filename=ten, db=db_gia,
            default_unit_id=14, auto_assign_officer_id=None,
        )
    return res[0] if isinstance(res, tuple) else res


async def test_tieu_de_la_o_so_khong_lam_no_HTTP_500(repo_gia, db_gia):
    """Cột tiêu đề kiểu SỐ không được làm sập đường nhập.

    🔴 ``dtype=str`` lúc đọc file áp cho DỮ LIỆU, không áp cho hàng tiêu đề. Một
    .xlsx có cột tên 2026/2027 (rất thường gặp: cột năm, cột ngày) cho tên cột
    kiểu ``int``; ``df.columns.str.lower()`` trên nó trả ``NaN``, hai cột cùng
    thành ``NaN`` nên khối kiểm cột trùng coi là trùng rồi ném
    ``TypeError: sequence item 0: expected str instance, float found`` — NGOÀI mọi
    try/except, tức HTTP 500 trống trơn. Trớ trêu là khối đó sinh ra để CHẶN đúng
    kiểu 500 này.
    """
    noi_dung = _xlsx(
        ["full_name", "phone", "source", 2026, 2027],
        [["Nguyễn Văn A", "0900000001", "website", "x", "y"]],
    )
    kq = await _chay_bytes(db_gia, noi_dung, "tieu_de_so.xlsx")

    assert kq.successful_imports == 1, f"dòng hợp lệ bị loại: {kq.errors}"


async def test_tieu_de_so_lan_voi_cot_trung_that_van_bao_loi_doc_duoc(repo_gia, db_gia):
    """Có cả cột tiêu đề số LẪN cột trùng thật thì vẫn phải là 400 đọc được.

    Nhánh nổ khác ca trên: ``sorted`` trên tập lẫn ``float`` với ``str`` ném
    ``TypeError: '<' not supported between instances of 'float' and 'str'``.

    🔑 Phải có ĐÚNG HAI cột tiêu đề kiểu số. Một cột thôi thì nó chỉ xuất hiện
    một lần nên không lọt vào tập cột-trùng, ``sorted`` vẫn chạy và ca này xanh
    cả trên code chưa sửa — bản đầu của test này mắc đúng lỗi đó. Hai cột số
    cùng hoá ``NaN`` mới thành "trùng", và ``NaN`` lẫn vào tập cùng ``full_name``
    mới làm ``sorted`` nổ.
    """
    noi_dung = _xlsx(
        ["Full Name", "full_name", "phone", "source", 2026, 2027],
        [["Tên A", "Tên B", "0900000001", "website", "x", "y"]],
    )
    with pytest.raises(ValueError) as exc:
        await _chay_bytes(db_gia, noi_dung, "vua_so_vua_trung.xlsx")

    assert "trùng tên" in str(exc.value)
    assert "full_name" in str(exc.value)


# ---------------------------------------------------------------------------
# Cột email gõ sai tên
# ---------------------------------------------------------------------------

CSV_COT_EMAIL_GO_SAI = (
    "full_name,Email Address,phone,source,unit_id\n"
    "Nguyễn Văn A,a@example.com,0900000001,website,14\n"
    "Trần Thị B,b@example.com,0900000002,website,14\n"
)


async def test_cot_email_go_sai_ten_bi_chan_chu_khong_nhap_am_tham(repo_gia, db_gia):
    """Header email gõ sai phải bị CHẶN, không được nhập im lặng với email rỗng.

    ``email`` thôi bắt buộc là đúng — nhưng cái giá kèm theo là header gõ sai
    không còn bị chặn nữa: "Email Address" chuẩn hoá thành ``email_address``, cột
    ``email`` vắng mặt, mọi dòng vào với email NULL, phép kiểm trùng email bị bỏ
    qua hoàn toàn, ``errors`` rỗng và giao diện báo xanh 100%. Trước đây file này
    ăn 400 "missing required columns: email" và người dùng sửa header trong 5
    giây; mất im lặng email của 211 dòng thì không ai phát hiện ra.
    """
    with pytest.raises(ValueError) as exc:
        await _chay_bytes(db_gia, CSV_COT_EMAIL_GO_SAI.encode("utf-8"), "go_sai.csv")

    tin = str(exc.value)
    assert "email_address" in tin, f"phải chỉ đúng tên cột đáng ngờ: {tin}"
    assert "email" in tin
    assert repo_gia.get("repo") is None or repo_gia["repo"].da_chen == [], (
        "đã chèn lead rồi mới từ chối"
    )


# ---------------------------------------------------------------------------
# SĐT giữ số 0 đầu (W9-N.1.2) — khoá bằng HÀNH VI, không bằng chuỗi mã nguồn
# ---------------------------------------------------------------------------

CSV_SDT_SO_0_DAU = (
    "full_name,phone,source,unit_id\n"
    "Nguyễn Văn A,0900000111,website,14\n"
)


async def test_sdt_giu_duoc_so_0_dau_qua_duong_nhap(repo_gia, db_gia):
    """Số 0 đầu của SĐT phải sống sót qua trọn đường nhập.

    Không có ``dtype=str`` lúc đọc file, pandas suy cột phone thành int64:
    ``0900000111`` thành ``900000111``, còn 9 chữ số, trượt regex SĐT Việt Nam
    ``^0(3|5|7|8|9|2)\\d{8,9}$`` ⇒ mọi file CSV xuất chuẩn bị loại sạch.

    Ca này thay cho phép so chuỗi mã nguồn ở
    ``tests/api/test_qa_wave9_lead_import_and_w8a32.py``: nó khoá KẾT QUẢ nên
    không đỏ oan khi ai đó đổi cách viết lời gọi ``pd.read_csv``.
    """
    kq = await _chay_bytes(db_gia, CSV_SDT_SO_0_DAU.encode("utf-8"), "sdt.csv")

    assert kq.successful_imports == 1, f"SĐT bị loại: {kq.errors}"
    lead = repo_gia["repo"].da_chen[0]
    sdt = lead.get("phone") if isinstance(lead, dict) else getattr(lead, "phone", None)
    assert sdt == "0900000111", f"SĐT bị cắt số 0 đầu: {sdt!r}"


CSV_COT_MAIL_KHONG_PHAI_EMAIL = (
    "full_name,phone,source,unit_id,mail_sent_at\n"
    "Nguyễn Văn A,0900000001,website,14,2026-07-30\n"
)


async def test_cot_ten_co_chu_mail_nhung_khong_chua_dia_chi_thi_khong_can(
    repo_gia, db_gia
):
    """Phép chặn phải HẸP: chỉ tên cột có "mail" thì chưa đủ để từ chối cả file.

    Cột ``mail_sent_at`` không chứa ký tự "@" nào — nó là cột ngày, không phải cột
    email. Chặn theo mỗi cái tên thì lại dựng lên một rào cản mới đúng chỗ vừa gỡ.
    """
    kq = await _chay_bytes(
        db_gia, CSV_COT_MAIL_KHONG_PHAI_EMAIL.encode("utf-8"), "mail_sent.csv"
    )

    assert kq.successful_imports == 1, f"bị chặn oan: {kq.errors}"
    lead = repo_gia["repo"].da_chen[0]
    assert (lead.get("email") if isinstance(lead, dict) else None) is None
