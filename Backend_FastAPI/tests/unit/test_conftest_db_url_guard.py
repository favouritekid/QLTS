# -*- coding: utf-8 -*-
"""Cổng an toàn CSDL của bộ test: fail-CLOSED và KHÔNG in credential.

Hai nợ mà tệp này khoá lại, cả hai đều nằm ở ``tests/conftest.py``:

``N4.01`` — guard fail-OPEN. Nhánh ``APP_ENV`` gọi ``pytest.fail``; nhánh
``DATABASE_URL`` ngay bên dưới chỉ ``log.warning`` rồi rơi thẳng xuống dòng
``print("Safety check passed")`` in VÔ ĐIỀU KIỆN. Chạy pytest trỏ vào CSDL
production sẽ in một dòng cảnh báo, tự tuyên bố đã kiểm xong, rồi
``setup_test_database`` DROP SCHEMA. Đo 23-09 trong worktree sạch: container
dev mang ``DATABASE_URL=...@postgres:5432/qlts_dev`` và bản cũ in đúng chữ
"Safety check passed" — không phải nguy cơ lý thuyết.

``N5.01`` — URL bị in thô. Ba chỗ in ``DATABASE_URL``; chỗ nguy hiểm nhất
chính là nhánh fail-open, vì nó nội suy NGUYÊN URL không cắt. Kho này PUBLIC
⇒ log GitHub Actions ai cũng đọc, mà URL có dạng
``postgresql+asyncpg://user:password@host/db``.

``N4.02`` — vị từ an toàn chưa thực thi đúng hợp đồng đã ghi.
``Backend_FastAPI/.env.test.example`` nói ``DATABASE_URL MUST contain "test" in
database name``, nhưng bản đầu kiểm ``"test" in db_url.lower()`` — một phép tìm
chuỗi con trên TOÀN URL. Đo thật trên SQLAlchemy 2.0: bốn URL trỏ thẳng vào
``qlts_production`` vẫn LỌT chỉ vì chữ "test" nằm ở username, password, host
hoặc query. Nặng nhất là fragment: ``make_url`` KHÔNG mô hình hoá ``#``, nên
``…/qlts_production#test`` phân giải ra ``database='qlts_production#test'`` và
sẽ lọt cả phép kiểm theo tên CSDL nếu không chặn riêng. Mục 5 dưới đây khoá
lại: chữ "test" đặt ngoài tên CSDL KHÔNG cứu được URL production.

⚠️ VÌ SAO KHÔNG IMPORT ``conftest.py``

``conftest.py`` chạy ở thời điểm COLLECT — import lại nó trong một ca kiểm là
chạy lần thứ hai mọi tác dụng phụ (đặt ``os.environ``, vá Redis, import app).
Nên tệp này kiểm theo hai đường tách bạch:

* logic ⇒ test HÀM THUẦN trong ``tests/fixtures/database.py``;
* nối dây ⇒ đọc ``conftest.py`` như VĂN BẢN và soi AST.

Đường thứ hai là thứ chặn ca "hàm đúng mà nơi dùng thì không".
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests.fixtures.database import (
    che_url_csdl,
    kiem_url_csdl_test,
    verify_test_database_safety,
)

_THU_MUC_TESTS = pathlib.Path(__file__).resolve().parents[1]
DUONG_CONFTEST = _THU_MUC_TESTS / "conftest.py"
DUONG_FIXTURE_DB = _THU_MUC_TESTS / "fixtures" / "database.py"

#: URL mẫu có userinfo RÕ RÀNG. Cố ý không dùng chữ "qlts"/"test" trong phần
#: user/password, để một khẳng định "không lộ" không vô tình đúng nhờ trùng
#: chuỗi với tên CSDL.
URL_PROD = "postgresql+asyncpg://nguoidung:matkhau_rat_bi_mat@db.noi-bo:5432/qlts_production"
URL_TEST_CI = "postgresql+asyncpg://test:test@localhost:5432/qlts_test"
#: ⚠️ user/password/host cố ý là fixture TỔNG HỢP (`.invalid` là TLD dành
#: riêng cho ví dụ, RFC 2606 — không phân giải được ở đâu cả). Bản trước
#: lấy thẳng cặp user/mật khẩu có thật trong `.env`
#: dev thật (ở máy này mật khẩu dev TRÙNG tên CSDL dev); kho PUBLIC nên hằng
#: của một ca kiểm không được lấy giá trị
#: thật. Chỉ `qlts_dev` ở vị trí TÊN CSDL là bắt buộc giữ — nó chính là thứ
#: ca kiểm đòi phải bị chặn.
URL_DEV = "postgresql+asyncpg://fixture_user:fixture_password@db.example.invalid:5432/qlts_dev"
URL_SQLITE_MEMORY = "sqlite+aiosqlite:///:memory:"


# ===========================================================================
# Tiện ích đọc AST — dùng chung cho các ca "nối dây"
# ===========================================================================


def _nguon(duong: pathlib.Path) -> str:
    return duong.read_text(encoding="utf-8")


def _chuoi_hang_trong(nut: ast.AST) -> str:
    """Nối mọi hằng chuỗi nằm trong một nút — để tìm thông điệp của print."""
    return "".join(
        con.value
        for con in ast.walk(nut)
        if isinstance(con, ast.Constant) and isinstance(con.value, str)
    )


def _ten_bien_giu_ly_do(than: list[ast.stmt]) -> str | None:
    """Tên biến được gán từ ``kiem_url_csdl_test(...)`` ở cấp module."""
    for nut in than:
        if not isinstance(nut, ast.Assign) or not isinstance(nut.value, ast.Call):
            continue
        ham = nut.value.func
        if isinstance(ham, ast.Name) and ham.id == "kiem_url_csdl_test":
            dich = nut.targets[0]
            if isinstance(dich, ast.Name):
                return dich.id
    return None


def _chi_so_if_chan(than: list[ast.stmt], ten_bien: str) -> int | None:
    """Vị trí câu ``if`` xét ``ten_bien`` VÀ có gọi ``pytest.fail`` bên trong."""
    for i, nut in enumerate(than):
        if not isinstance(nut, ast.If):
            continue
        ten_trong_dieu_kien = {
            n.id for n in ast.walk(nut.test) if isinstance(n, ast.Name)
        }
        if ten_bien not in ten_trong_dieu_kien:
            continue
        for con in ast.walk(nut):
            if (
                isinstance(con, ast.Call)
                and isinstance(con.func, ast.Attribute)
                and con.func.attr == "fail"
            ):
                return i
    return None


def _chi_so_print_passed(than: list[ast.stmt]) -> int | None:
    """Vị trí câu lệnh ``print(... "Safety check passed" ...)`` ở cấp module."""
    for i, nut in enumerate(than):
        if not isinstance(nut, ast.Expr) or not isinstance(nut.value, ast.Call):
            continue
        ham = nut.value.func
        if not (isinstance(ham, ast.Name) and ham.id == "print"):
            continue
        if "Safety check passed" in _chuoi_hang_trong(nut.value):
            return i
    return None


_TEN_HAM_IN_NAME = {"print", "pytest_fail"}
_TEN_HAM_IN_ATTR = {
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "exception",
    "fail",
}


def _la_loi_goi_in(ham: ast.AST) -> bool:
    if isinstance(ham, ast.Name):
        return ham.id in _TEN_HAM_IN_NAME
    if isinstance(ham, ast.Attribute):
        return ham.attr in _TEN_HAM_IN_ATTR
    return False


def _cac_bieu_thuc_duoc_in(nguon: str) -> list[tuple[int, str]]:
    """Mọi biểu thức thật sự ĐƯỢC IN RA, ở mức từng đối số / từng ô f-string.

    Độ mịn "từng ô" là cố ý: nếu chỉ soi cả lời gọi thì một lệnh vừa gọi
    ``che_url_csdl`` vừa nội suy URL thô ở ô bên cạnh sẽ lọt.
    """
    cay = ast.parse(nguon)
    ket: list[tuple[int, str]] = []
    for nut in ast.walk(cay):
        if not isinstance(nut, ast.Call) or not _la_loi_goi_in(nut.func):
            continue
        for doi_so in nut.args:
            if isinstance(doi_so, ast.JoinedStr):
                for phan in doi_so.values:
                    if isinstance(phan, ast.FormattedValue):
                        ket.append(
                            (
                                phan.lineno,
                                ast.get_source_segment(nguon, phan.value) or "",
                            )
                        )
            else:
                ket.append(
                    (doi_so.lineno, ast.get_source_segment(nguon, doi_so) or "")
                )
    return ket


# ===========================================================================
# 1. BẤT BIẾN: DATABASE_URL không đạt tiêu chí ⇒ pytest DỪNG
#    Kiểm ngược: gỡ dòng `pytest.fail` trong nhánh ấy ⇒ các ca dưới đỏ.
# ===========================================================================


class TestGuardFailClosed:
    def test_url_production_bi_tu_choi(self):
        assert kiem_url_csdl_test(URL_PROD) is not None, (
            "URL production được chấp nhận — đây đúng là lỗ N4.01: guard chỉ "
            "cảnh báo thay vì chặn"
        )

    def test_url_dev_bi_tu_choi(self):
        assert kiem_url_csdl_test(URL_DEV) is not None, (
            "URL CSDL dev (qlts_dev) được chấp nhận — bộ test sẽ DROP SCHEMA "
            "trên CSDL dev"
        )

    def test_url_rong_bi_tu_choi(self):
        assert kiem_url_csdl_test("") is not None, (
            "DATABASE_URL rỗng được coi là an toàn — thiếu cấu hình phải "
            "fail-closed, không fail-open"
        )

    def test_conftest_that_su_goi_ham_kiem(self):
        """Chống ca 'hàm đúng mà nơi dùng thì không'."""
        than = ast.parse(_nguon(DUONG_CONFTEST)).body
        assert _ten_bien_giu_ly_do(than) is not None, (
            "conftest.py không gán kết quả `kiem_url_csdl_test(...)` ở cấp "
            "module — hàm kiểm có thể đúng nhưng conftest không gọi nó"
        )

    def test_conftest_chan_bang_pytest_fail(self):
        than = ast.parse(_nguon(DUONG_CONFTEST)).body
        ten = _ten_bien_giu_ly_do(than)
        assert ten is not None, "conftest.py không gọi `kiem_url_csdl_test`"
        assert _chi_so_if_chan(than, ten) is not None, (
            "conftest.py có gọi `kiem_url_csdl_test` nhưng KHÔNG có câu `if` "
            "nào xét kết quả ấy rồi `pytest.fail` — guard fail-OPEN"
        )

    def test_sibling_fixture_cung_chan(self):
        """§6 — vá một nhánh thì còn bốn nhánh: nhánh fixture phải cùng luật."""
        da_goi: list[str] = []
        moi_truong = type("S", (), {"APP_ENV": "test", "DATABASE_URL": URL_PROD})()
        verify_test_database_safety(moi_truong, lambda msg: da_goi.append(msg))
        assert da_goi, (
            "verify_test_database_safety() chấp nhận URL production — hai nơi "
            "hỏi cùng một câu hỏi phải cho cùng một câu trả lời"
        )


# ===========================================================================
# 2. BẤT BIẾN: không in "Safety check passed" khi phép kiểm chưa qua
#    Kiểm ngược (biến thể TINH VI): giữ nguyên `pytest.fail` nhưng DỜI dòng
#    print LÊN TRƯỚC nó ⇒ ca dưới phải đỏ.
# ===========================================================================


class TestKhongTuyenBoPassedSom:
    def test_dong_passed_nam_sau_guard(self):
        nguon = _nguon(DUONG_CONFTEST)
        than = ast.parse(nguon).body
        ten = _ten_bien_giu_ly_do(than)
        assert ten is not None, "conftest.py không gọi `kiem_url_csdl_test`"

        i_guard = _chi_so_if_chan(than, ten)
        i_print = _chi_so_print_passed(than)
        assert i_guard is not None, "không tìm thấy câu `if` chặn bằng pytest.fail"
        assert i_print is not None, (
            "không tìm thấy dòng print 'Safety check passed' ở cấp module "
            "conftest.py — nếu đã đổi lời văn thì phải cập nhật phép kiểm này"
        )
        assert i_print > i_guard, (
            "dòng 'Safety check passed' (câu lệnh #%d) đứng TRƯỚC guard (câu "
            "lệnh #%d) ⇒ nó được in cả khi phép kiểm chưa chạy. Một dòng chữ "
            "nói ổn trong khi không kiểm gì còn nguy hiểm hơn việc không kiểm."
            % (i_print, i_guard)
        )


# ===========================================================================
# 3. BẤT BIẾN: không chỗ nào in userinfo
#    Kiểm ngược: trả MỘT chỗ về `{settings.DATABASE_URL}` thô ⇒ ca dưới đỏ.
# ===========================================================================


class TestKhongInCredential:
    def test_che_bo_user_va_password(self):
        ra = che_url_csdl(URL_PROD)
        assert "nguoidung" not in ra and "matkhau_rat_bi_mat" not in ra, (
            "che_url_csdl() vẫn để lọt userinfo: %r" % ra
        )

    def test_van_giu_host_va_ten_csdl(self):
        """Che mà mất sạch thông tin chẩn đoán thì không ai dùng."""
        ra = che_url_csdl(URL_PROD)
        assert "db.noi-bo" in ra and "qlts_production" in ra, (
            "che_url_csdl() cắt mất host/tên CSDL, không còn phân biệt được "
            "qlts_test với qlts_production: %r" % ra
        )

    @pytest.mark.parametrize(
        "mat_khau",
        ["co@cho", "co/cho", "co?cho", "co@va/va?cho"],
        ids=["at", "slash", "hoi", "ca-ba"],
    )
    def test_mat_khau_chua_ky_tu_phan_cach_van_khong_lot(self, mat_khau):
        """Mật khẩu chứa '@', '/', '?' là ca mà mọi cách cắt ngây thơ đều rò."""
        url = f"postgresql+asyncpg://u:{mat_khau}@host:5432/qlts_test"
        ra = che_url_csdl(url)
        assert mat_khau not in ra, (
            "mật khẩu %r lọt qua che_url_csdl(): %r" % (mat_khau, ra)
        )

    def test_khong_phan_giai_duoc_thi_khong_tra_nguyen_van(self):
        bi_mat = "mot-chuoi-la-khong-phai-url"
        assert bi_mat not in che_url_csdl(bi_mat), (
            "che_url_csdl() trả nguyên văn chuỗi không phân giải được — chuỗi "
            "lạ vẫn có thể là secret, đường che cũng phải fail-closed"
        )

    def test_sqlite_memory_van_doc_duoc(self):
        assert che_url_csdl(URL_SQLITE_MEMORY) == URL_SQLITE_MEMORY

    @pytest.mark.parametrize(
        "duong",
        [DUONG_CONFTEST, DUONG_FIXTURE_DB],
        ids=["conftest", "fixtures-database"],
    )
    def test_khong_noi_suy_database_url_tho(self, duong):
        """Mọi biểu thức ĐƯỢC IN mà chạm DATABASE_URL đều phải đi qua helper.

        Bắt được cả ``{settings.DATABASE_URL}``, ``{url[:30]}``, ``{url[:60]}``
        lẫn ``log.info("%s", settings.DATABASE_URL)``. Cắt ngắn KHÔNG phải
        biện pháp che: 30 ký tự đầu đã lộ user và 5 ký tự đầu mật khẩu.
        """
        nguon = _nguon(duong)
        vi_pham = [
            (dong, doan)
            for dong, doan in _cac_bieu_thuc_duoc_in(nguon)
            if "DATABASE_URL" in doan and "che_url_csdl" not in doan
        ]
        assert vi_pham == [], (
            "%s in DATABASE_URL không qua che_url_csdl():\n  "
            % duong.name
            + "\n  ".join("dòng %d: %s" % (d, s) for d, s in vi_pham)
        )


# ===========================================================================
# 4. BẤT BIẾN: KHÔNG đỏ oan — URL test hợp lệ thì mọi thứ vẫn chạy
# ===========================================================================


class TestKhongDoOan:
    @pytest.mark.parametrize(
        "url",
        [
            URL_TEST_CI,
            URL_SQLITE_MEMORY,
            "postgresql+asyncpg://u:p@h:5432/my_test_db",
            "postgresql+asyncpg://u:p@h:5432/test_database",
            "postgresql+asyncpg://u:p@h:5432/db_test",
        ],
        ids=[
            "ci-qlts_test",
            "sqlite-memory",
            "test-giua-ten",
            "test-dau-ten",
            "test-cuoi-ten",
        ],
    )
    def test_url_hop_le_duoc_chap_nhan(self, url):
        assert kiem_url_csdl_test(url) is None, (
            "URL test hợp lệ %r bị từ chối — guard siết quá tay sẽ chặn cả CI"
            % url
        )

    def test_sibling_fixture_khong_bao_loi_voi_url_test(self):
        da_goi: list[str] = []
        moi_truong = type(
            "S", (), {"APP_ENV": "test", "DATABASE_URL": URL_TEST_CI}
        )()
        verify_test_database_safety(moi_truong, lambda msg: da_goi.append(msg))
        assert da_goi == [], (
            "verify_test_database_safety() báo lỗi với URL test hợp lệ: %r"
            % da_goi
        )
# ===========================================================================
# 5. BẤT BIẾN: quyền cho phép chỉ phụ thuộc TÊN CSDL ĐÃ PHÂN GIẢI
#    Kiểm ngược (M3): đổi vị từ về `":memory:" in thap or "test" in thap` trên
#    TOÀN URL ⇒ mọi ca trong `URL_TEST_SAI_CHO` và ca `:memory:` phải đỏ.
# ===========================================================================

#: Năm URL trỏ vào CÙNG một CSDL production. Chúng chỉ khác nhau ở CHỖ đặt chữ
#: "test" — và không chỗ nào trong số đó là tên CSDL. Mọi ca ở đây phải TỪ
#: CHỐI, nếu không thì `DROP SCHEMA` chạy trên `qlts_production`.
URL_TEST_SAI_CHO = {
    "username": "postgresql+asyncpg://test:matkhau@db.noi-bo:5432/qlts_production",
    "password": "postgresql+asyncpg://nguoidung:test123@db.noi-bo:5432/qlts_production",
    "host": "postgresql+asyncpg://nguoidung:matkhau@testing-host:5432/qlts_production",
    "query": "postgresql+asyncpg://nguoidung:matkhau@db.noi-bo:5432/qlts_production?mode=test",
    "fragment": "postgresql+asyncpg://nguoidung:matkhau@db.noi-bo:5432/qlts_production#test",
}


class TestChiTenCsdlQuyetDinh:
    @pytest.mark.parametrize("cho", sorted(URL_TEST_SAI_CHO), ids=sorted(URL_TEST_SAI_CHO))
    def test_chu_test_dat_ngoai_ten_csdl_khong_cuu_duoc_url_production(self, cho):
        url = URL_TEST_SAI_CHO[cho]
        # Tiền đề của chính ca kiểm: URL này THẬT SỰ có chữ "test". Không có
        # dòng này thì ca vẫn xanh cả khi ai đó sửa hằng thành một URL không
        # còn chữ "test" nào — lúc ấy nó không còn kiểm cái gì.
        assert "test" in url.lower(), (
            "hằng URL_TEST_SAI_CHO[%r] không còn chứa chữ 'test' ⇒ ca kiểm "
            "này đã mất đối tượng" % cho
        )
        assert kiem_url_csdl_test(url) is not None, (
            "URL trỏ vào qlts_production được chấp nhận chỉ vì chữ 'test' nằm "
            "ở %s. Hợp đồng ở .env.test.example là 'test in database NAME', "
            "không phải 'test ở đâu đó trong URL'." % cho
        )

    def test_postgres_ten_csdl_memory_bi_tu_choi(self):
        """``:memory:`` chỉ có nghĩa với sqlite; miễn theo TÊN là lỗ."""
        assert (
            kiem_url_csdl_test(
                "postgresql+asyncpg://u:p@db.noi-bo:5432/:memory:"
            )
            is not None
        ), (
            "một CSDL PostgreSQL tên ':memory:' được miễn — lối miễn phải gắn "
            "với BACKEND sqlite, không gắn với chuỗi tên"
        )

    def test_url_hong_ma_co_chu_test_bi_tu_choi(self):
        assert kiem_url_csdl_test("khong phai url nhung co chu test") is not None, (
            "chuỗi không phân giải được mà vẫn được chấp nhận vì có chữ "
            "'test' — không phân giải được thì không biết nó trỏ vào đâu"
        )

    def test_thieu_ten_csdl_bi_tu_choi(self):
        for url in ("postgresql+asyncpg://u:p@h:5432/", "sqlite://"):
            assert kiem_url_csdl_test(url) is not None, (
                "URL %r không nêu tên CSDL mà vẫn được chấp nhận" % url
            )

    def test_backend_khong_xac_dinh_bi_tu_choi(self):
        """Kiểu CSDL lạ ⇒ từ chối, kể cả khi tên CSDL có chữ 'test'."""
        assert kiem_url_csdl_test("mysql+aiomysql://u:p@h:3306/qlts_test") is not None, (
            "backend ngoài danh sách biết được vẫn qua — guard đang đoán ngữ "
            "nghĩa tên CSDL của một hệ nó chưa từng thấy"
        )

    def test_sibling_fixture_cung_tu_choi_test_dat_sai_cho(self):
        """§6 — nhánh fixture phải cùng luật, không chỉ hàm thuần."""
        da_goi: list[str] = []
        moi_truong = type(
            "S",
            (),
            {"APP_ENV": "test", "DATABASE_URL": URL_TEST_SAI_CHO["username"]},
        )()
        verify_test_database_safety(moi_truong, lambda msg: da_goi.append(msg))
        assert da_goi, (
            "verify_test_database_safety() chấp nhận URL production chỉ vì "
            "username là 'test'"
        )

    def test_thong_diep_cua_fixture_khong_lo_credential(self):
        """Thông điệp từ chối phải đi qua `che_url_csdl`, không in URL thô."""
        da_goi: list[str] = []
        moi_truong = type(
            "S", (), {"APP_ENV": "test", "DATABASE_URL": URL_TEST_SAI_CHO["password"]}
        )()
        verify_test_database_safety(moi_truong, lambda msg: da_goi.append(msg))
        assert da_goi, "fixture không từ chối URL production"
        assert "test123" not in " ".join(da_goi), (
            "mật khẩu lọt vào thông điệp từ chối: %r" % da_goi
        )
