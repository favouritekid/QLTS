"""Sổ HÀNH ĐỘNG: `--action-begin` / `--action-end` và bộ chụp ảnh `anh_chup`.

Vì sao tệp này tồn tại
----------------------
`registry.bat_dau_action()`/`ket_thuc_action()` có từ đầu nhưng KHÔNG có caller
vận hành — chỉ unit test gọi. Nghĩa là hợp đồng §A05 của runbook ("khai dự kiến
TRƯỚC mỗi mutation") không thi hành được: bấm nút trên trình duyệt thì DB đổi
trước, sổ ghi sau, và không gì chứng minh được rằng chỉ đúng những hàng đã khai
mới đổi. `smoke_lib/cli.py` nay là caller ấy; các ca dưới đây khoá nó lại.

Không cần Docker, không cần database: `ChayLenh` được thay bằng stub trả sẵn
đầu ra psql, đúng cách các ca `--baseline`/`--cleanup` đã làm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

from scripts.smoke_lib import anh_chup, cli, registry  # noqa: E402

_SID = "7674453993076482083"
_CID = "b" * 64


# ---------------------------------------------------------------------------
# anh_chup — bộ chụp ảnh
# ---------------------------------------------------------------------------
def test_cau_lenh_chup_loai_updated_at_va_khong_ghep_chuoi_tho():
    sql = anh_chup.cau_lenh_anh_chup("payment")
    assert "to_jsonb(t) - 'updated_at'" in sql
    assert "FROM payment t" in sql
    # JSON, không phải tách theo dấu phân cách: giá trị thật chứa `|` là chuyện
    # thường (ghi chú, lý do từ chối).
    assert "json_agg" in sql


def test_bang_ngoai_BANG_THEO_DOI_bi_chan():
    with pytest.raises(anh_chup.LoiAnhChup, match="BANG_THEO_DOI"):
        anh_chup.chup(["bang_la"], lambda sql: "[]")


def test_khong_khai_bang_nao_thi_chan():
    with pytest.raises(anh_chup.LoiAnhChup, match="rỗng không phải quan sát"):
        anh_chup.chup([], lambda sql: "[]")


def test_stdout_RONG_khong_duoc_hieu_la_bang_rong():
    """Lệnh psql hỏng và bảng rỗng cho CÙNG một stdout rỗng.

    Nếu coi rỗng là "bảng không có hàng nào", một lệnh hỏng sẽ biến thành ảnh
    chụp nói rằng mọi hàng đã biến mất — và `ket_thuc_action` sẽ báo "mất hàng
    ngoài dự kiến" thay vì báo hỏng.
    """
    with pytest.raises(anh_chup.LoiAnhChup, match="không trả gì"):
        anh_chup.chup(["payment"], lambda sql: "   ")


def test_bang_rong_that_su_thi_ra_dict_rong():
    assert anh_chup.chup(["payment"], lambda sql: "[]") == {"payment": {}}


def test_id_trung_trong_ket_qua_thi_chan():
    tho = json.dumps([{"id": "1", "v": {"a": 1}}, {"id": "1", "v": {"a": 2}}])
    with pytest.raises(anh_chup.LoiAnhChup, match="id trùng"):
        anh_chup.chup(["payment"], lambda sql: tho)


def test_van_tay_doi_khi_noi_dung_hang_doi():
    a = anh_chup.chup(["payment"], lambda s: json.dumps([{"id": "1", "v": {"status": "pending"}}]))
    b = anh_chup.chup(["payment"], lambda s: json.dumps([{"id": "1", "v": {"status": "verified"}}]))
    assert a["payment"]["1"] != b["payment"]["1"], "đổi status mà vân tay không đổi"


def test_doc_cap_va_doc_so_luong_fail_closed():
    assert anh_chup.doc_cap(["payment=1,2"], ten_co="--them") == {"payment": ["1", "2"]}
    assert anh_chup.doc_so_luong(["payment=2"], ten_co="--them-so-luong") == {"payment": 2}
    for xau in ("payment", "payment=", "bang_la=1"):
        with pytest.raises(anh_chup.LoiAnhChup):
            anh_chup.doc_cap([xau], ten_co="--them")
    for xau in ("payment=x", "payment=-1", "bang_la=1"):
        with pytest.raises(anh_chup.LoiAnhChup):
            anh_chup.doc_so_luong([xau], ten_co="--them-so-luong")


# ---------------------------------------------------------------------------
# CLI action — dựng sổ giả rồi chạy hai chế độ
# ---------------------------------------------------------------------------
def _so_that(tmp_path: Path, *, pack: str = "P1") -> Path:
    thu_muc = tmp_path / "evidence"
    reg = registry.Registry.mo(
        thu_muc, run_id="RUN1", git_sha="a" * 40, pack=pack,
        project="qltssmoke", database="qlts_smoke",
    )
    reg.ghi_baseline(
        duong_dump=str(tmp_path / "R1.dump"), sha256="a" * 64,
        alembic_head="ovp20260811", van_tay_metrics="b" * 64,
        danh_tinh={"container_id": _CID, "project": "qltssmoke",
                   "system_identifier": _SID},
        van_tay_model="c" * 64,
    )
    return thu_muc


class _Chay:
    """Stub `ChayLenh`: trả đầu ra tuỳ theo lệnh, ghi lại thứ tự đã gọi."""

    def __init__(self, anh: dict):
        self.anh = anh
        self.da_goi = []

    def __call__(self, argv):
        self.da_goi.append(argv)
        noi = " ".join(argv)
        if "pg_control_system" in noi:
            return _SID + "\n"
        if "docker inspect" in noi or argv[:2] == ["docker", "inspect"]:
            return "com.docker.compose.project=qltssmoke\ncom.docker.compose.service=postgres\n"
        # CLI nay chụp CẢ 13 bảng, nên stub phải trả lời cho mọi bảng — bảng
        # không khai trong `self.anh` thì rỗng.
        for bang in registry.BANG_THEO_DOI:
            if f"FROM {bang} t" in noi:
                hang = self.anh.get(bang, {})
                return json.dumps([{"id": k, "v": v} for k, v in hang.items()])
        raise AssertionError(f"lệnh không lường trước: {noi}")


def test_begin_roi_end_khong_doi_gi_thi_DAT(tmp_path):
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"status": "pending"}}})
    chi_so = cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1",
    )
    assert chi_so == 0
    cli.chay_action_ket_thuc(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0,
    )


def test_khai_them_mot_hang_ma_khong_co_gi_xay_ra_thi_CHAN(tmp_path):
    """Đây là nửa hay bị bỏ quên: thay đổi ĐÃ KHAI mà KHÔNG xảy ra cũng là lệch.

    Một sổ chỉ chặn "thay đổi ngoài dự kiến" sẽ xanh cho ca mà hệ thống không
    làm gì cả — tức xanh cho đúng thứ ca ấy sinh ra để bắt.
    """
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"status": "pending"}}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1", them_so_luong={"payment": 1},
    )
    with pytest.raises(registry.LoiRegistry, match="LỆCH"):
        cli.chay_action_ket_thuc(
            chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0,
        )


def test_hang_doi_NGOAI_du_kien_thi_CHAN(tmp_path):
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"status": "pending"}}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1",
    )
    chay.anh = {"payment": {"1": {"status": "verified"}}}  # đổi mà không khai
    with pytest.raises(registry.LoiRegistry, match="LỆCH"):
        cli.chay_action_ket_thuc(
            chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0,
        )


def test_pack_LECH_thi_chan_truoc_khi_chup_anh(tmp_path):
    """Cổng `pack` — lỗ đã có thật: sổ chỉ kiểm project và database.

    Seeder P1 vì thế chạy được trên sổ mở cho P2: fixture gói này ghi vào sổ gói
    kia, rồi cleanup restore theo baseline của gói kia.
    """
    thu_muc = _so_that(tmp_path, pack="P1")
    chay = _Chay({"payment": {}})
    with pytest.raises(registry.LoiRegistry, match="pack"):
        cli.chay_action_bat_dau(
            chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P2", cid=_CID,
            ten="FIN-02.a1",
        )
    assert not any("FROM payment t" in " ".join(a) for a in chay.da_goi), \
        "đã chụp ảnh trước khi kiểm pack — cổng đặt sau việc nó canh"


def test_thieu_pack_thi_chan(tmp_path):
    thu_muc = _so_that(tmp_path)
    with pytest.raises(cli.LoiCLI, match="--pack"):
        cli.chay_action_bat_dau(
            chay=_Chay({"payment": {}}), thu_muc=thu_muc, run_id="RUN1", pack="",
            cid=_CID, ten="FIN-02.a1",
        )


def test_so_chua_co_baseline_thi_chan(tmp_path):
    thu_muc = tmp_path / "evidence"
    registry.Registry.mo(
        thu_muc, run_id="RUN1", git_sha="a" * 40, pack="P1",
        project="qltssmoke", database="qlts_smoke",
    )
    with pytest.raises(cli.LoiCLI, match="baseline"):
        cli.chay_action_bat_dau(
            chay=_Chay({"payment": {}}), thu_muc=thu_muc, run_id="RUN1", pack="P1",
            cid=_CID, ten="FIN-02.a1",
        )


def test_chup_CA_13_bang_khong_de_nguoi_chay_chon_pham_vi(tmp_path):
    """Phạm vi quan sát không phải lựa chọn của người chạy.

    Bản trước nhận `--bang`: thay đổi ở bảng bị bỏ sót thành VÔ HÌNH. Một ca như
    FIN-02 chạm `fee`, `invoice`, `admission_profile`, `audit_log`,
    `notification` chứ không chỉ `payment` — và người vận hành sẽ quên.
    """
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1",
    )
    da_chup = {b for b in registry.BANG_THEO_DOI
               if any(f"FROM {b} t" in " ".join(a) for a in chay.da_goi)}
    assert da_chup == set(registry.BANG_THEO_DOI), \
        f"thiếu bảng: {sorted(set(registry.BANG_THEO_DOI) - da_chup)}"


def test_thay_doi_o_bang_KHONG_khai_van_bi_bat(tmp_path):
    """Đây là hệ quả đáng giá nhất của việc chụp cả 13 bảng."""
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}, "entity_audit_log": {}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1", them_so_luong={"payment": 0},
    )
    # Không ai khai `entity_audit_log`, nhưng một hàng xuất hiện ở đó.
    chay.anh = {"payment": {"1": {"s": "p"}}, "entity_audit_log": {"9": {"x": 1}}}
    with pytest.raises(registry.LoiRegistry, match="LỆCH"):
        cli.chay_action_ket_thuc(
            chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0)


def test_end_chup_dung_tap_bang_da_chup_o_begin(tmp_path):
    """Bảng của ảnh SAU lấy từ ảnh TRƯỚC, không nhận lại từ dòng lệnh."""
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}, "invoice": {"9": {"s": "i"}}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1",
    )
    chay.da_goi.clear()
    cli.chay_action_ket_thuc(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0,
    )
    da_chup = {b for b in registry.BANG_THEO_DOI
               if any(f"FROM {b} t" in " ".join(a) for a in chay.da_goi)}
    assert da_chup == set(registry.BANG_THEO_DOI)


def test_ket_thuc_hai_lan_thi_chan(tmp_path):
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID,
        ten="FIN-02.a1",
    )
    cli.chay_action_ket_thuc(
        chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0)
    with pytest.raises(registry.LoiRegistry, match="hai lần"):
        cli.chay_action_ket_thuc(
            chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1", cid=_CID, chi_so=0)


def test_chi_so_khong_ton_tai_thi_chan(tmp_path):
    thu_muc = _so_that(tmp_path)
    with pytest.raises(cli.LoiCLI, match="chỉ số"):
        cli.chay_action_ket_thuc(
            chay=_Chay({"payment": {}}), thu_muc=thu_muc, run_id="RUN1", pack="P1",
            cid=_CID, chi_so=99)


# ---------------------------------------------------------------------------
# Trạng thái SỔ: một LỆCH là dừng, không phải ghi chú
# ---------------------------------------------------------------------------
def test_con_action_DANG_CHAY_thi_khong_mo_action_moi(tmp_path):
    """Hai action chồng nhau có thể cùng nhận công một mutation."""
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                            cid=_CID, ten="FIN-02.a1")
    with pytest.raises(registry.LoiRegistry, match="DANG_CHAY"):
        cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                                cid=_CID, ten="FIN-02.a2")


def test_da_co_LECH_thi_KHONG_chay_tiep(tmp_path):
    """Đã xảy ra thật ở BL20260816B: a1 LECH rồi sổ vẫn nhận a2 và ghi DAT."""
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                            cid=_CID, ten="FIN-02.a1", them_so_luong={"payment": 1})
    with pytest.raises(registry.LoiRegistry, match="LỆCH"):
        cli.chay_action_ket_thuc(chay=chay, thu_muc=thu_muc, run_id="RUN1",
                                 pack="P1", cid=_CID, chi_so=0)
    with pytest.raises(registry.LoiRegistry, match="LỆCH"):
        cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                                cid=_CID, ten="FIN-02.a2")


def test_ten_action_phai_duy_nhat(tmp_path):
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                            cid=_CID, ten="FIN-02.a1")
    cli.chay_action_ket_thuc(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                             cid=_CID, chi_so=0)
    with pytest.raises(registry.LoiRegistry, match="duy nhất"):
        cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                                cid=_CID, ten="FIN-02.a1")


# ---------------------------------------------------------------------------
# Biên CLI — qua main(argv), không chỉ gọi helper
# ---------------------------------------------------------------------------
def _argv(*duoi, thu_muc: Path):
    return ["--run-id", "RUN1", "--thu-muc", str(thu_muc), "--pack", "P1",
            "--container", _CID, *duoi]


def test_main_action_end_tu_choi_co_cua_che_do_begin(tmp_path, capsys):
    thu_muc = _so_that(tmp_path)
    rc = cli.main(_argv("--action-end", "--chi-so", "0", "--them", "payment=7",
                        thu_muc=thu_muc))
    assert rc != 0
    assert "--them" in capsys.readouterr().err


def test_main_action_begin_tu_choi_chi_so(tmp_path, capsys):
    thu_muc = _so_that(tmp_path)
    rc = cli.main(_argv("--action-begin", "--ten", "FIN-02.a1", "--chi-so", "0",
                        thu_muc=thu_muc))
    assert rc != 0
    assert "--chi-so" in capsys.readouterr().err


def test_main_chi_so_am_bi_tu_choi(tmp_path, capsys):
    """`--chi-so -1` chọn action CUỐI theo indexing Python — gõ nhầm là kết thúc
    nhầm action mà không báo gì."""
    thu_muc = _so_that(tmp_path)
    rc = cli.main(_argv("--action-end", "--chi-so", "-1", thu_muc=thu_muc))
    assert rc != 0
    assert "am" in capsys.readouterr().err.lower() or "âm" in capsys.readouterr().err


def test_main_action_begin_thieu_ten_bi_tu_choi(tmp_path, capsys):
    thu_muc = _so_that(tmp_path)
    rc = cli.main(_argv("--action-begin", thu_muc=thu_muc))
    assert rc != 0
    assert "--ten" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# BANG_THEO_DOI phải nói về những bảng CÓ THẬT
# ---------------------------------------------------------------------------
def test_moi_bang_theo_doi_deu_ton_tai_trong_models():
    """Danh sách canh không được chứa bảng ma.

    `BANG_THEO_DOI` khai `"audit_log"` từ đầu — một bảng KHÔNG tồn tại; tên thật
    là `entity_audit_log`. Không ai phát hiện suốt nhiều tháng vì chưa có ai chụp
    cả 13 bảng, và `bat_dau_action` chỉ kiểm "tên có nằm trong danh sách", không
    kiểm "bảng có thật". Ca này khoá danh sách vào `__tablename__` của models —
    không cần database, chạy được ở mọi shard.
    """
    import re

    ten_that = set()
    for f in (_GOC / "app" / "models").rglob("*.py"):
        ten_that |= set(
            re.findall(r'__tablename__\s*=\s*["\']([a-z_]+)["\']',
                       f.read_text(encoding="utf-8"))
        )
    assert ten_that, "không đọc được __tablename__ nào — phép kiểm này vô nghĩa"
    ma = sorted(b for b in registry.BANG_THEO_DOI if b not in ten_that)
    assert not ma, f"BANG_THEO_DOI chứa bảng không có trong models: {ma}"


def test_ChayLenh_giai_ma_UTF8_chu_khong_theo_locale():
    """`text=True` để Python chọn codec theo locale — cp1252 trên Windows.

    PostgreSQL trả UTF-8 và dữ liệu thật của hệ này là tiếng Việt, nên một
    `SELECT` chạm bảng có chữ Việt sẽ ném `UnicodeDecodeError: can't decode byte
    0x90`. Đã đo trên bảng `notification` của `qlts_smoke` ngày 16-08-2026.
    Trước đó không lộ vì mọi lệnh psql của harness chỉ trả ASCII.

    Ca này chạy một tiến trình THẬT in tiếng Việt, thay vì khẳng định về tham số
    truyền cho `subprocess` — tham số đúng mà codec vẫn sai thì lời khẳng định ấy
    không cứu được gì.
    """
    # Ma con KHONG chua dau thoat nao: mot ky tu thoat bi nuot khi soan
    # tep la du de bien ca nay thanh 'lenh con syntax error'.
    # du de bien ca nay thanh "lenh con syntax error", va ta di tim nham cho.
    # Ma con thuan ASCII (dung `chr()`) de ket qua khong phu thuoc vao viec
    # soan tep co giu duoc ky tu tieng Viet hay khong. Thu can kiem la CHUOI
    # TRA VE: `chr(273)+chr(7911)` = 'du' co dau, cp1252 khong giai ma noi.
    ma = "import sys; sys.stdout.buffer.write((chr(273)+chr(7911)).encode('utf-8'))"
    ra = cli.ChayLenh(in_lenh=False)([sys.executable, "-c", ma])
    assert isinstance(ra, str)
    assert ra == chr(273) + chr(7911)


def test_ChayLenh_truyen_encoding_utf8_chu_khong_de_locale_quyet():
    """Khang dinh CAU TRUC, vi ca hanh vi khong the do trong CI.

    Container CI la Linux, locale UTF-8 — `text=True` giai ma dung o do. Loi chi
    hien tren host Windows (cp1252), tuc noi harness nay that su chay. Mot ca chi
    kiem hanh vi vi the se XANH o CI ke ca khi ai do tra ve `text=True`, va hoi quy
    di thang toi may nguoi dung.

    Vi vay kiem THAM SO truyen cho `subprocess.run`: no phai khai codec TUONG MINH,
    khong de locale quyet.
    """
    import subprocess as sp

    goi = {}
    that = sp.run

    def gia(argv, **kw):
        goi.update(kw)
        return that([sys.executable, "-c", "pass"], **{**kw, "check": False})

    sp.run = gia
    try:
        cli.ChayLenh(in_lenh=False)([sys.executable, "-c", "pass"])
    finally:
        sp.run = that

    assert goi.get("encoding") == "utf-8", (
        f"encoding={goi.get('encoding')!r} — phai la 'utf-8'. `text=True` de "
        "Python chon codec theo locale; tren Windows la cp1252 va moi chuoi "
        "tieng Viet tu PostgreSQL se nem UnicodeDecodeError."
    )
    assert goi.get("errors") == "strict", (
        "errors phai la 'strict': thay ky tu hong bang dau thay the se doi van "
        "tay hang mot cach am tham, va khi ay anh chup noi doi."
    )
    assert not goi.get("text"), "dung `encoding=` thay cho `text=True`"


# ---------------------------------------------------------------------------
# `cleanup` là trạng thái ĐÓNG SỔ
# ---------------------------------------------------------------------------
def _da_cleanup(thu_muc: Path) -> registry.Registry:
    reg = registry.Registry.doc(thu_muc, "RUN1")
    reg.ghi_cleanup(trang_thai="DAT", van_tay_sau="d" * 64)
    return reg


def test_da_cleanup_thi_KHONG_mo_action_moi(tmp_path):
    """Database đã restore về baseline — quan sát nó là quan sát một thứ khác.

    `ghi_cleanup` ghi trạng thái kết thúc, nhưng hai hàm action không đọc nó, nên
    một run SẠCH vẫn append được action sau cleanup.
    """
    thu_muc = _so_that(tmp_path)
    _da_cleanup(thu_muc)
    with pytest.raises(registry.LoiRegistry, match="cleanup"):
        cli.chay_action_bat_dau(
            chay=_Chay({"payment": {}}), thu_muc=thu_muc, run_id="RUN1", pack="P1",
            cid=_CID, ten="FIN-02.a1")


def test_da_cleanup_thi_KHONG_ket_thuc_action_dang_chay(tmp_path):
    """Ca này tệ hơn ca trên: kết thúc SAU khi restore thì ảnh chụp SAU là
    trạng thái baseline, và delta thành 'mất sạch hàng' — một lời buộc tội sai
    được ghi thẳng vào sổ như bằng chứng."""
    thu_muc = _so_that(tmp_path)
    chay = _Chay({"payment": {"1": {"s": "p"}}})
    cli.chay_action_bat_dau(chay=chay, thu_muc=thu_muc, run_id="RUN1", pack="P1",
                            cid=_CID, ten="FIN-02.a1")
    _da_cleanup(thu_muc)
    with pytest.raises(registry.LoiRegistry, match="cleanup"):
        cli.chay_action_ket_thuc(chay=chay, thu_muc=thu_muc, run_id="RUN1",
                                 pack="P1", cid=_CID, chi_so=0)
