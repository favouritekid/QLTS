# -*- coding: utf-8 -*-
"""Danh sách gỡ ``GO_SAU_*`` của các test migration GĐ2 phủ ĐỦ mọi revision nối sau (rà đoàn 3 J''3 — đoàn 3b).

Các test migration GĐ2 (``tests/integration/test_gd2a_migration.py``, ``test_gd2b_migration.py``,
``test_gd2c_c1_migration.py``, ``test_gd2c_c2_migration.py``, ``test_thcs_danh_muc_migration.py``,
``test_thcs_mapping_migration.py``) dựng CSDL "ở revision ngay trước R" bằng ``create_all()`` của model HIỆN TẠI rồi gỡ
(``DROP``) phần của R và của MỌI revision nối sau R. Quên gỡ phần của một migration mới nối sau thì test cũ KHÔNG đỏ:
migration mới đi nhánh "đã có, khớp định nghĩa" (``create_all`` dựng khớp) thay vì nhánh TẠO như production — mất đúng
phép đo đường tạo mà không ai biết. Tệp này khoá điều ấy, KHÔNG cần CSDL, KHÔNG chạy fixture (đọc tệp + AST):

1. Đoạn chuỗi Alembic sau :data:`MOC` là chuỗi THẲNG tới head duy nhất, và MỌI revision trên đoạn ấy có danh sách gỡ
   riêng ở ``test_gd2a_migration.py`` — migration mới nối sau head mà chưa khai ⇒ ĐỎ, kèm tên revision.
2. Mỗi ``GO_SAU_<R>`` = ghép ĐÚNG danh sách gỡ của mọi revision nối sau R, từ MỚI tới cũ (gỡ ngược chuỗi).
3. Fixture của từng test migration chạy ĐÚNG (mọi phần nối sau R) + (phần của R), theo thứ tự mã.

Mỗi ca kiểm MỘT bất biến.
"""
import ast
import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]
THU_MUC_MIGRATION = GOC / "alembic" / "versions"
#: Revision cuối mà ``GO_GD2A`` gỡ GỘP với phần GĐ2-A (trigger luật B ``gd2f20261119`` thay hàm + trigger của GĐ2-A).
#: Mọi revision nối SAU mốc này phải có danh sách gỡ riêng ở :func:`_danh_sach_go`.
MOC = "gd2f20261119"
#: Một câu gỡ: ``DROP …`` hoặc ``ALTER TABLE <bảng> DROP …``.
_MAU_CAU_GO = r"^(DROP |ALTER TABLE \S+ DROP )"


def _chuoi_alembic():
    """``{revision: (down_revision, …)}`` đọc thẳng từ tệp (khuôn ``test_gd2a_quota_ddl_lockin.test_mot_head_alembic``)."""
    cha = {}
    for p in THU_MUC_MIGRATION.glob("*.py"):
        s = p.read_text(encoding="utf-8")
        r = re.search(r"^revision\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]", s, re.M)
        if not r:
            continue
        d = re.search(r"^down_revision\s*(?::[^=]+)?=\s*(\([^)]*\)|[^\n]+)", s, re.M | re.S)
        cha[r.group(1)] = tuple(re.findall(r"['\"]([^'\"]+)['\"]", d.group(1))) if d else ()
    return cha


def _sau_moc():
    """Các revision nối SAU :data:`MOC`, từ head (MỚI) về cũ. Đoạn này phải THẲNG: một head, mỗi bước đúng một cha."""
    cha = _chuoi_alembic()
    co_con = {d for ds in cha.values() for d in ds}
    heads = sorted(set(cha) - co_con)
    assert len(heads) == 1, heads
    ket = []
    r = heads[0]
    while r != MOC:
        ds = cha.get(r, ())
        assert len(ds) == 1, "đoạn sau %s phải là chuỗi thẳng: %s có down_revision %r" % (MOC, r, ds)
        ket.append(r)
        r = ds[0]
        assert len(ket) <= len(cha), "chuỗi Alembic có vòng"
    return ket


def _gd2a():
    return importlib.import_module("tests.integration.test_gd2a_migration")


def _danh_sach_go():
    """Danh sách gỡ của TỪNG revision nối sau :data:`MOC` — MỘT nguồn ở ``test_gd2a_migration.py``. Migration mới nối sau
    head ⇒ thêm danh sách gỡ của nó ở ``test_gd2a_migration.py``, khai ở đây, và vào ĐẦU mọi ``GO_SAU_*``."""
    m = _gd2a()
    return {
        "gd2b20261121": tuple(m.GO_GD2B),
        "gd2c20261122": tuple(m.GO_GD2C_C1),
        "gd2cs20261122": tuple(m.GO_GD2C_C2),
        "thcsnb20261122": tuple(m.GO_THCS_NB),
        "thcsmap20261122": tuple(m.GO_THCS_MAP),
    }


def _ghep_sau(revision):
    """Ghép danh sách gỡ của mọi revision nối SAU ``revision``, từ MỚI tới cũ (``()`` nếu là head; :data:`MOC` ⇒ cả đoạn)."""
    chuoi = _sau_moc()
    go = _danh_sach_go()
    den = chuoi.index(revision) if revision in chuoi else len(chuoi)
    out = ()
    for r in chuoi[:den]:
        out += go[r]
    return out


def _cau_go_cua_fixture(ten_mod, ten_ham):
    """Các câu gỡ mà fixture ``ten_ham`` của ``tests/integration/<ten_mod>.py`` chạy, THEO THỨ TỰ MÃ: vòng
    ``for s in <biểu thức>`` (tính biểu thức trên không gian tên của module) và lời gọi ``execute(<chuỗi / f-chuỗi>)`` trực
    tiếp có câu gỡ. Đọc AST — KHÔNG chạy fixture."""
    mod = importlib.import_module("tests.integration." + ten_mod)
    cay = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    ham = [
        n
        for n in ast.walk(cay)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == ten_ham
    ]
    assert len(ham) == 1, (ten_mod, ten_ham, len(ham))
    vi_tri = []
    for n in ast.walk(ham[0]):
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "s":
            gia_tri = eval(ast.unparse(n.iter), vars(mod))  # noqa: S307 — biểu thức của chính tệp test trong repo
            vi_tri.append(((n.lineno, n.col_offset), tuple(gia_tri)))
        elif (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "execute"
            and n.args
            and isinstance(n.args[0], (ast.Constant, ast.JoinedStr))
        ):
            nguon = ast.unparse(n.args[0])
            try:
                gia_tri = eval(nguon, vars(mod))  # noqa: S307 — chuỗi của chính tệp test trong repo
            except NameError:
                gia_tri = "?KHONG-TINH-DUOC: " + nguon
                if "DROP" not in nguon:
                    continue
            if isinstance(gia_tri, str) and (re.match(_MAU_CAU_GO, gia_tri) or gia_tri.startswith("?")):
                vi_tri.append(((n.lineno, n.col_offset), (gia_tri,)))
    return tuple(c for _, nhom in sorted(vi_tri) for c in nhom)


def test_moi_revision_sau_moc_deu_co_danh_sach_go():
    """Migration mới nối sau head (hoặc chèn giữa đoạn) mà chưa khai danh sách gỡ ⇒ ĐỎ, kèm tên."""
    chuoi = _sau_moc()
    go = _danh_sach_go()
    thieu = [r for r in chuoi if r not in go]
    thua = sorted(set(go) - set(chuoi))
    assert not thieu and not thua, (
        "revision nối sau %s chưa có danh sách gỡ: %s; danh sách gỡ của revision KHÔNG còn trên đoạn: %s — thêm phần gỡ "
        "vào tests/integration/test_gd2a_migration.py, khai ở _danh_sach_go và vào ĐẦU mọi GO_SAU_*" % (MOC, thieu, thua)
    )


def test_moi_danh_sach_go_khong_rong_va_chi_gom_cau_go():
    sai = {r: ds for r, ds in _danh_sach_go().items() if not ds or not all(re.match(_MAU_CAU_GO, c) for c in ds)}
    assert not sai, sai


@pytest.mark.parametrize(
    ("ten", "revision"),
    [
        ("GO_SAU_GD2B", "gd2b20261121"),
        ("GO_SAU_GD2C_C1", "gd2c20261122"),
        ("GO_SAU_GD2C_C2", "gd2cs20261122"),
    ],
)
def test_go_sau_bang_ghep_moi_revision_noi_sau(ten, revision):
    assert tuple(getattr(_gd2a(), ten)) == _ghep_sau(revision)


@pytest.mark.parametrize(
    ("ten_mod", "ten_ham", "revision"),
    [
        ("test_gd2b_migration", "csdl_gd2f", "gd2b20261121"),
        ("test_gd2c_c1_migration", "csdl_truoc", "gd2c20261122"),
        ("test_gd2c_c2_migration", "csdl_truoc", "gd2cs20261122"),
        ("test_thcs_danh_muc_migration", "csdl_truoc_nb", "thcsnb20261122"),
        ("test_thcs_mapping_migration", "csdl_truoc_map", "thcsmap20261122"),
    ],
)
def test_fixture_go_moi_phan_noi_sau_roi_phan_cua_revision(ten_mod, ten_ham, revision):
    """CSDL "ở revision ngay trước R" = ``create_all`` trừ (mọi phần nối sau R) rồi (phần của R) — đúng thứ tự gỡ ngược."""
    assert _cau_go_cua_fixture(ten_mod, ten_ham) == _ghep_sau(revision) + _danh_sach_go()[revision]


def test_fixture_gd2a_go_moi_phan_noi_sau_moc_truoc_phan_gd2a():
    """``test_gd2a_migration`` nâng tới ``head``: CSDL trước nâng cấp phải gỡ MỌI phần nối sau :data:`MOC` trước tiên."""
    sau = _ghep_sau(MOC)
    assert _cau_go_cua_fixture("test_gd2a_migration", "csdl_truoc")[: len(sau)] == sau
