"""Canh bộ chia lát của ``Nightly Backend Pytest``.

Thứ đang được canh **không phải** là cách chia lát cho đều — chia lệch thì chỉ
chậm, không sai. Thứ được canh là **cổng độ phủ**: nếu một test biến mất khỏi
mọi lát, hoặc chạy ở hai lát, thì ``verify`` phải ĐỎ.

Vì sao cần một bộ test cho một script CI: chính cổng độ phủ là thứ duy nhất
đứng giữa "8.652 test đều được chạy" và "một tệp lặng lẽ rơi ra ngoài mà
required check vẫn xanh". Một cổng canh không ai canh lại thì chẳng canh gì.

Hai ca kiểm ngược ở đây là hai ca chủ hệ thống nêu đích danh:
``test_bo_mot_node_id_thi_do`` và ``test_mot_lat_chet_hoan_toan_thi_do``.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# Script nằm ở ``.github/scripts/`` — ngoài cây gói ``app``, nên nạp bằng đường
# dẫn thay vì ``import``. Nạp theo đường dẫn tương đối tính từ CHÍNH tệp này,
# không từ thư mục làm việc: pytest có thể được gọi từ nhiều chỗ.
_SCRIPT = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "pytest_shard_inventory.py"
)


@pytest.fixture(scope="module")
def inv():
    if not _SCRIPT.exists():
        pytest.fail(
            "Khong tim thay %s — bo chia lat cua nightly da bi di chuyen hoac xoa. "
            "Neu that su bo di, xoa luon te.p test nay; de nguyen mot test skip "
            "im lang la cach cong do phu bien mat ma khong ai biet." % _SCRIPT
        )
    spec = importlib.util.spec_from_file_location("pytest_shard_inventory", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pytest_shard_inventory"] = module
    spec.loader.exec_module(module)
    return module


# Bản kiểm kê giả: cố ý trải trên nhiều thư mục có hệ số chi phí khác nhau, để
# nhánh cân tải thật sự được đi qua chứ không phải một đường thẳng.
KIEM_KE = [
    "tests/api/test_a.py::TestX::test_one",
    "tests/api/test_a.py::TestX::test_two",
    "tests/api/test_b.py::test_three",
    "tests/unit/test_c.py::test_four",
    "tests/unit/test_c.py::test_five",
    "tests/unit/test_c.py::test_six",
    "tests/services/test_d.py::TestY::test_seven",
    "tests/integration/test_e.py::test_eight",
]


def _ghi(duong: Path, node_ids):
    duong.write_text("\n".join(node_ids) + "\n", encoding="utf-8")


def _dung_thu_muc_lat(inv, tmp_path: Path, so_lat: int, kiem_ke=None):
    """Dựng đủ bộ: tệp kiểm kê + thư mục chứa kết quả từng lát."""
    kiem_ke = list(kiem_ke if kiem_ke is not None else KIEM_KE)
    tep_kk = tmp_path / "collected.txt"
    _ghi(tep_kk, kiem_ke)

    lat = inv.chia_lat(kiem_ke, so_lat)

    thu_muc = tmp_path / "shards"
    thu_muc.mkdir()
    theo_tep = {}
    for nid in kiem_ke:
        theo_tep.setdefault(nid.split("::", 1)[0], []).append(nid)

    for i, tep_list in enumerate(lat, start=1):
        cua_lat = []
        for tep in tep_list:
            cua_lat.extend(theo_tep[tep])
        _ghi(thu_muc / ("shard-%02d.txt" % i), cua_lat)

    return tep_kk, thu_muc


class TestChiaLat:
    def test_phu_het_va_khong_trung(self, inv):
        lat = inv.chia_lat(KIEM_KE, 3)
        phang = [t for x in lat for t in x]
        assert sorted(phang) == sorted(set(phang)), "mot tep roi vao hai lat"
        assert set(phang) == {n.split("::", 1)[0] for n in KIEM_KE}

    def test_tat_dinh(self, inv):
        """Cùng đầu vào phải cho cùng kết quả.

        Không tất định thì kiểm kê và các lát có thể lệch nhau giữa hai lần
        collect, và cổng độ phủ đỏ vì lý do chẳng liên quan tới độ phủ.
        """
        assert inv.chia_lat(KIEM_KE, 3) == inv.chia_lat(KIEM_KE, 3)
        assert inv.chia_lat(KIEM_KE, 3) == inv.chia_lat(list(reversed(KIEM_KE)), 3)

    def test_khong_cat_doi_mot_tep(self, inv):
        """Mọi node id của cùng một tệp phải nằm trong CÙNG một lát.

        Nhiều tệp có fixture phạm vi module và dữ liệu dùng chung; cắt đôi là
        tự chuốc lấy lỗi phụ thuộc thứ tự chỉ hiện ở một lát.
        """
        lat = inv.chia_lat(KIEM_KE, 4)
        o_lat = {}
        for i, tep_list in enumerate(lat):
            for tep in tep_list:
                assert tep not in o_lat
                o_lat[tep] = i
        assert o_lat["tests/api/test_a.py"] == o_lat["tests/api/test_a.py"]

    def test_nhieu_lat_hon_so_tep_thi_bao_loi(self, inv, tmp_path):
        """Lát rỗng chạy ``pytest`` không đối số ⇒ quét CẢ KHO ⇒ trùng với mọi
        lát khác. Phải chặn ở bước ``plan``, đừng để phát hiện sau cả đêm."""
        tep_kk = tmp_path / "collected.txt"
        _ghi(tep_kk, KIEM_KE)
        args = _args(inv, "plan", collected=str(tep_kk), shards=99,
                     out=str(tmp_path / "m.json"))
        assert inv.lenh_plan(args) == 1


def _args(inv, lenh, **kw):
    import argparse

    ns = argparse.Namespace(lenh=lenh)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


class TestPlan:
    def test_sinh_ma_tran_dung_dinh_dang(self, inv, tmp_path):
        tep_kk = tmp_path / "collected.txt"
        _ghi(tep_kk, KIEM_KE)
        ra = tmp_path / "matrix.json"

        rc = inv.lenh_plan(_args(inv, "plan", collected=str(tep_kk), shards=3, out=str(ra)))
        assert rc == 0

        ma_tran = json.loads(ra.read_text(encoding="utf-8"))
        assert len(ma_tran) == 3
        for muc in ma_tran:
            assert muc["tests"].strip(), "lat rong lot qua"
            assert set(muc) == {"index", "name", "tests"}


class TestVerify:
    def test_day_du_thi_dat(self, inv, tmp_path):
        tep_kk, thu_muc = _dung_thu_muc_lat(inv, tmp_path, 3)
        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 0

    def test_bo_mot_node_id_thi_do(self, inv, tmp_path):
        """KIỂM NGƯỢC 1 — bỏ ĐÚNG MỘT node id khỏi một lát thì cổng phải ĐỎ.

        Đây là biến thể tinh vi nhất: không xoá tệp, không đổi tên, chỉ thiếu
        một dòng. Nếu cổng chỉ so SỐ LƯỢNG tệp lát hay chỉ kiểm "lát nào cũng
        có nội dung" thì ca này lọt.
        """
        tep_kk, thu_muc = _dung_thu_muc_lat(inv, tmp_path, 3)

        # Tìm một lát có >= 2 node id rồi bỏ dòng cuối của nó.
        for duong in sorted(thu_muc.iterdir()):
            dong = duong.read_text(encoding="utf-8").strip().split("\n")
            if len(dong) >= 2:
                duong.write_text("\n".join(dong[:-1]) + "\n", encoding="utf-8")
                bi_bo = dong[-1]
                break
        else:
            pytest.fail("khong dung duoc lat co >= 2 node id")

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1, "cong do phu KHONG bat duoc node id bi bo: %s" % bi_bo

    def test_mot_lat_chet_hoan_toan_thi_do(self, inv, tmp_path):
        """KIỂM NGƯỢC 2 — một lát không nộp gì (bị huỷ / chết lúc collect)."""
        tep_kk, thu_muc = _dung_thu_muc_lat(inv, tmp_path, 3)
        sorted(thu_muc.iterdir())[0].unlink()

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1

    def test_mot_node_id_o_hai_lat_thi_do(self, inv, tmp_path):
        """Trùng lặp cũng phải đỏ: nó nghĩa là phép chia đã hỏng, và số liệu
        'đã chạy hết' được đắp lên bằng công chạy hai lần."""
        tep_kk, thu_muc = _dung_thu_muc_lat(inv, tmp_path, 3)
        cac_lat = sorted(thu_muc.iterdir())
        dong_dau = cac_lat[0].read_text(encoding="utf-8").strip().split("\n")[0]
        with cac_lat[1].open("a", encoding="utf-8") as fh:
            fh.write(dong_dau + "\n")

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1

    def test_lat_co_node_id_ngoai_kiem_ke_thi_do(self, inv, tmp_path):
        """Hai lần collect cho kết quả khác nhau cũng là hỏng — im lặng chấp
        nhận nghĩa là kiểm kê không còn là nguồn chuẩn."""
        tep_kk, thu_muc = _dung_thu_muc_lat(inv, tmp_path, 3)
        with sorted(thu_muc.iterdir())[0].open("a", encoding="utf-8") as fh:
            fh.write("tests/unit/test_ma.py::test_khong_co_trong_kiem_ke\n")

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1

    def test_khong_co_tep_lat_nao_thi_do(self, inv, tmp_path):
        """Thư mục lát rỗng: mọi lát đều chết, hoặc artifact tải hụt. Không
        được coi là 'không có gì sai'."""
        tep_kk = tmp_path / "collected.txt"
        _ghi(tep_kk, KIEM_KE)
        thu_muc = tmp_path / "shards"
        thu_muc.mkdir()

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1

    def test_kiem_ke_rong_thi_do(self, inv, tmp_path):
        """Kiểm kê rỗng mà so với lát rỗng thì 'khớp' — đúng kiểu xanh giả."""
        tep_kk = tmp_path / "collected.txt"
        tep_kk.write_text("", encoding="utf-8")
        thu_muc = tmp_path / "shards"
        thu_muc.mkdir()
        _ghi(thu_muc / "shard-01.txt", [])

        rc = inv.lenh_verify(
            _args(inv, "verify", collected=str(tep_kk), shard_dir=str(thu_muc))
        )
        assert rc == 1


class TestDocNodeIds:
    def test_bo_qua_dong_khong_phai_node_id(self, inv, tmp_path):
        """Đầu ra ``--collect-only -q`` còn kèm dòng tổng kết và cảnh báo."""
        tep = tmp_path / "raw.txt"
        tep.write_text(
            "tests/api/test_a.py::test_one\n"
            "\n"
            "8652 tests collected in 42.13s\n"
            "warning: something\n"
            "tests/unit/test_b.py::test_two\n",
            encoding="utf-8",
        )
        assert inv.doc_node_ids(str(tep)) == [
            "tests/api/test_a.py::test_one",
            "tests/unit/test_b.py::test_two",
        ]

    def test_chuan_hoa_dau_gach_cheo(self, inv, tmp_path):
        """Người phát triển chạy Windows; một ``\\`` lọt vào so sánh chuỗi làm
        cổng đỏ vì lý do chẳng liên quan gì tới độ phủ."""
        tep = tmp_path / "raw.txt"
        tep.write_text("tests\\api\\test_a.py::test_one\n", encoding="utf-8")
        assert inv.doc_node_ids(str(tep)) == ["tests/api/test_a.py::test_one"]
