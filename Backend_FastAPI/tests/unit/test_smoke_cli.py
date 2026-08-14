"""CLI của harness smoke — chạy trọn hai lệnh bằng stub, không cần Docker/DB.

Tệp này kiểm **trình tự** và **các nhánh hỏng**, vì đó là chỗ một cleanup có thể
làm đúng từng bước mà vẫn sai toàn cục: drop trước khi kiểm archive, mở lại dịch
vụ sau khi restore hỏng, hay bỏ qua bước xác nhận 0 session.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
if not (_GOC / "scripts" / "smoke_lib").is_dir():
    pytest.fail(f"thiếu {_GOC / 'scripts' / 'smoke_lib'} — harness không tồn tại")
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

from scripts.smoke_lib import baseline, cli, registry  # noqa: E402

_CID = "a1b2c3d4e5f6"
_SID = "7412598630145236"
_TOC = "\n".join(
    f"34{i:02d}; 0 164{i:02d} TABLE DATA public {t} qlts"
    for i, t in enumerate(baseline.BANG_TRONG_YEU)
)
_DEM = "\n".join(f"{t}|3" for t in baseline.BANG_TRONG_YEU)


_ND_DUMP = b"PGDMP" + bytes(64)
_SHA_DUMP = hashlib.sha256(_ND_DUMP).hexdigest()

# Container id giả phải là HEX như thật: `_inspect_container` đòi
# `^[0-9a-f]{64}\|\d+\|\S*$`, nên một id kiểu "backendid0" bị chặn đúng luật
# nhưng khiến ca test nói về chuyện khác.
_CID_SV = {
    "backend": "aaaaaaaaaaaa",
    "celery-worker": "bbbbbbbbbbbb",
    "celery-beat": "cccccccccccc",
    "frontend": "dddddddddddd",
}
_SV_THEO_CID = {v: k for k, v in _CID_SV.items()}
_CID_ONEOFF = "eeeeeeeeeeee"
_CID_KHAC = "ffffffffffff"


def _full(cid: str) -> str:
    return (cid + "0" * 64)[:64]


class StubChay:
    """Giả `ChayLenh`: ghi lại argv, trả kết quả theo kịch bản."""

    def __init__(self, tmp: Path, **kb):
        self.lenh: list[list[str]] = []
        self.tmp = tmp
        self.sid = kb.get("sid", _SID)
        self.nhan_service = kb.get("nhan_service", "postgres")
        self.toc = kb.get("toc", _TOC)
        self.session = kb.get("session", "0")
        self.dem = kb.get("dem", _DEM)
        self.alembic = kb.get("alembic", "ovp20260811")
        self.sha_container = kb.get("sha_container", _SHA_DUMP)
        self.service_chay = kb.get("service_chay", list(cli.SERVICE_UNG_DUNG))
        self.git_head = kb.get("git_head", "0" * 40)
        self.git_ban = kb.get("git_ban", "")
        self.health = kb.get("health", {"backend": "healthy", "frontend": "healthy"})
        self.crashloop = set(kb.get("crashloop", ()))
        self.oneoff = set(kb.get("oneoff", ()))     # id container của `compose run`
        self.ps_them = list(kb.get("ps_them", ()))  # dòng `ps` phụ thêm
        self._restart = {}
        self._lan_ps = 0
        self.no_o = kb.get("no_o")  # chuỗi con: gặp thì ném lỗi

    def __call__(self, argv) -> str:
        self.lenh.append(list(argv))
        ghep = " ".join(argv)
        if self.no_o and self.no_o in ghep:
            raise cli.LoiCLI(f"stub cố ý hỏng ở: {self.no_o}")
        # ⚠️ Nhánh RestartCount phải đứng TRƯỚC nhánh nhãn generic. Bản trước
        # đặt ngược, nên lệnh hỏi RestartCount nhận về danh sách nhãn và parser
        # bỏ qua — stub "mô phỏng" một thứ chưa bao giờ được gọi tới.
        if "inspect" in argv and "RestartCount" in ghep:
            cid_hoi = argv[-1]
            s = _SV_THEO_CID.get(cid_hoi, "")
            if s in self.crashloop:
                rs = self._restart.get(s, 0) + 1
                self._restart[s] = rs
            else:
                rs = self._restart.get(s, 0)
            oneoff = "true" if cid_hoi in self.oneoff else "false"
            return f"{_full(cid_hoi)}|{rs}|{oneoff}\n"
        if "inspect" in argv and "--format" in argv:
            return (
                "com.docker.compose.project=qltssmoke\n"
                f"com.docker.compose.service={self.nhan_service}\n"
            )
        if "pg_control_system" in ghep:
            return self.sid + "\n"
        if argv[0] == "git" and "rev-parse" in argv:
            return self.git_head + "\n"
        if argv[0] == "git" and "status" in argv:
            return self.git_ban + "\n" if self.git_ban else ""
        if "sha256sum" in argv:
            return f"{self.sha_container}  {argv[-1]}\n"
        if "ps" in argv:
            # Compose CHỈ trả 4 trường — `.RestartCount` không tồn tại trong
            # `formatter.ContainerContext`. Stub bản trước tự bịa thêm trường
            # ấy, nên 176 ca vẫn xanh trong khi lệnh thật đổ `template parsing
            # error`. Nay stub phản ánh đúng giới hạn của Compose.
            assert "RestartCount" not in ghep, (
                "template `docker compose ps` KHÔNG được chứa .RestartCount"
            )
            self._lan_ps += 1
            dong = []
            for s in cli.SERVICE_UNG_DUNG:
                st = "running" if s in self.service_chay else "exited"
                # ID GIỮ NGUYÊN qua các nhịp — ca crashloop phổ biến nhất là
                # cùng container, `RestartCount` tăng dần (xem nhánh inspect).
                dong.append(f"{s}|{st}|{self.health.get(s, '')}|{_CID_SV[s]}")
            dong.extend(self.ps_them)
            return "\n".join(dong) + "\n"
        if "--list" in argv:
            return self.toc
        if "pg_stat_activity" in ghep and "count(*)" in ghep:
            return self.session + "\n"
        # `UNION ALL` phải xét TRƯỚC `alembic_version`: câu lệnh vân tay có chứa
        # chuỗi `alembic_version` vì đó là một trong các bảng trọng yếu, nên xét
        # ngược thứ tự sẽ trả nhầm alembic head cho phép đếm.
        if "UNION ALL" in ghep:
            return self.dem
        if "alembic_version" in ghep:
            return self.alembic + "\n"
        if argv[:2] == ["docker", "cp"]:
            # `docker cp` từ container ra host: tạo tệp dump giả.
            dich = Path(argv[3])
            if not str(argv[2]).startswith("/"):
                dich.parent.mkdir(parents=True, exist_ok=True)
                dich.write_bytes(_ND_DUMP)
        return ""

    def co(self, *manh: str) -> bool:
        return any(all(m in " ".join(l) for m in manh) for l in self.lenh)

    def thu_tu(self, *manh: str) -> list[int]:
        vt = []
        for m in manh:
            vt.append(next(i for i, l in enumerate(self.lenh) if m in " ".join(l)))
        return vt


def _baseline(tmp_path: Path, stub: StubChay, run_id="SMK1"):
    return cli.chay_baseline(
        chay=stub, thu_muc=tmp_path / "reg", run_id=run_id, git_sha="0" * 40,
        pack="P2", cid=_CID, thu_muc_dump=tmp_path / "dumps", app_env="development",
    )


# =============================================================================
# --baseline
# =============================================================================
def test_baseline_ghi_du_bon_truong(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    stub = StubChay(tmp_path)
    duong = _baseline(tmp_path, stub)

    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    bl = reg.du_lieu["baseline"]
    assert Path(bl["duong_dump"]) == duong
    assert len(bl["sha256"]) == 64 and len(bl["van_tay_metrics"]) == 64
    assert bl["alembic_head"] == "ovp20260811"
    assert reg.du_lieu["danh_tinh"]["system_identifier"] == _SID


def test_baseline_kiem_archive_NGAY_sau_khi_dump(tmp_path, monkeypatch):
    """Dump hỏng phát hiện lúc này là phiền; lúc cleanup là mất database."""
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    stub = StubChay(tmp_path, toc="")  # pg_restore --list không in gì
    with pytest.raises(baseline.ChanLai, match="rỗng nội dung"):
        _baseline(tmp_path, stub)


def test_baseline_thieu_co_destructive_thi_dung_truoc_moi_lenh(tmp_path, monkeypatch):
    monkeypatch.delenv("SMOKE_ALLOW_DESTRUCTIVE", raising=False)
    stub = StubChay(tmp_path)
    with pytest.raises(baseline.ChanLai, match="SMOKE_ALLOW_DESTRUCTIVE"):
        _baseline(tmp_path, stub)
    assert stub.lenh == [], "không được chạy lệnh nào trước khi qua hàng rào"


def test_baseline_container_sai_service_thi_dung(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    stub = StubChay(tmp_path, nhan_service="backend")
    with pytest.raises(baseline.ChanLai, match="service"):
        _baseline(tmp_path, stub)
    assert not stub.co("pg_dump"), "đã dump dù danh tính chưa đạt"


# =============================================================================
# --cleanup
# =============================================================================
def _chuan_bi(tmp_path, monkeypatch, **kb):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    _baseline(tmp_path, StubChay(tmp_path))
    return StubChay(tmp_path, **kb)


def test_cleanup_dat_thi_mo_lai_dich_vu(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch)
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "DAT"
    assert stub.co("compose", "start")


def test_cleanup_dung_thu_tu_bat_buoc(tmp_path, monkeypatch):
    """stop → đếm session → kiểm archive → drop → restore → start."""
    stub = _chuan_bi(tmp_path, monkeypatch)
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    # "pg_restore" không phân biệt được: nó khớp cả `pg_restore --list` ở bước
    # kiểm archive. Dùng cờ chỉ có ở lệnh restore thật.
    vt = stub.thu_tu("compose -p qltssmoke stop", "pg_stat_activity",
                     "pg_restore --list", "DROP DATABASE",
                     "pg_restore --no-owner", "compose -p qltssmoke start")
    assert vt == sorted(vt), f"sai thứ tự: {vt}"


def test_cleanup_con_session_thi_KHONG_drop(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch, session="2")
    with pytest.raises(cli.LoiCLI, match="còn 2 session"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert not stub.co("DROP DATABASE")


def test_cleanup_archive_hong_thi_KHONG_drop(tmp_path, monkeypatch):
    """Lỗi archive nay được bọc thành LoiCLI vì nó xảy ra SAU khi đã stop service."""
    stub = _chuan_bi(tmp_path, monkeypatch, toc="rác không phải TOC")
    with pytest.raises(cli.LoiCLI, match="thiếu bảng trọng yếu"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert not stub.co("DROP DATABASE"), "drop trước khi archive được chứng minh dùng được"


def test_cleanup_danh_tinh_doi_thi_KHONG_drop(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch, sid="9" * 16)
    with pytest.raises(baseline.ChanLai, match="ĐÃ ĐỔI"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert not stub.co("DROP DATABASE")


def test_cleanup_restore_hong_thi_ghi_HONG_va_GIU_DICH_VU_DONG(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch, no_o="--no-owner --no-privileges --exit-on-error")
    with pytest.raises(cli.LoiCLI, match="KHÔNG xác định"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "HONG"
    assert not stub.co("compose", "start"), "đã mở lại dịch vụ dù restore hỏng"


def test_cleanup_doi_soat_lech_thi_ghi_HONG_va_GIU_DICH_VU_DONG(tmp_path, monkeypatch):
    """Restore chạy xong nhưng vân tay lệch — vẫn phải giữ dịch vụ đóng."""
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    _baseline(tmp_path, StubChay(tmp_path))
    stub = StubChay(tmp_path, dem="\n".join(f"{t}|999" for t in baseline.BANG_TRONG_YEU))
    with pytest.raises(cli.LoiCLI, match="KHÔNG xác định"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "HONG"
    assert not stub.co("compose", "start")


def test_cleanup_alembic_lech_thi_ghi_HONG(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    _baseline(tmp_path, StubChay(tmp_path))
    stub = StubChay(tmp_path, alembic="mkchk20260811")
    with pytest.raises(cli.LoiCLI):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert not stub.co("compose", "start")


def test_cleanup_khong_co_baseline_thi_dung(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    registry.Registry.mo(
        tmp_path / "reg", run_id="SMK9", git_sha="0" * 40, pack="P2",
        project="qltssmoke", database="qlts_smoke",
    )
    stub = StubChay(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="chưa có baseline"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK9", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert stub.lenh == []


# =============================================================================
# bất biến chung
# =============================================================================
def test_moi_lenh_deu_la_argv_khong_qua_shell(tmp_path, monkeypatch):
    """Không lệnh nào được ghép thành chuỗi — `shell=False` chỉ đúng khi argv là list."""
    stub = _chuan_bi(tmp_path, monkeypatch)
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    for l in stub.lenh:
        assert isinstance(l, list) and all(isinstance(x, str) for x in l)
        assert l[0] == "docker"


def test_chay_lenh_that_dung_shell_false_va_check_true():
    """Bất biến của lớp bọc, kiểm bằng cách gọi một lệnh không tồn tại."""
    import subprocess as sp

    goi = {}
    that = sp.run

    def gia(argv, **kw):
        goi.update(kw)
        goi["argv"] = argv
        return that([sys.executable, "-c", "pass"], **{**kw, "check": False})

    sp.run, cli.subprocess.run = gia, gia
    try:
        cli.ChayLenh(in_lenh=False)(["docker", "ps"])
    finally:
        sp.run = that
        cli.subprocess.run = that

    assert goi["shell"] is False
    assert goi["check"] is True
    assert isinstance(goi["argv"], list)


# =============================================================================
# P0 — tệp được HASH phải là tệp được RESTORE
# =============================================================================
def test_sha_trong_container_lech_thi_KHONG_drop(tmp_path, monkeypatch):
    """Host đúng checksum, nhưng bản trong container là archive KHÁC.

    Đây là ca mà kiểm-trên-host một mình không thấy: `pg_restore` đọc bản trong
    container, còn ta lại đi hash bản trên host.
    """
    stub = _chuan_bi(tmp_path, monkeypatch, sha_container="b" * 64)
    with pytest.raises(cli.LoiCLI, match="TRONG CONTAINER"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    assert not stub.co("DROP DATABASE"), "đã drop dù bản sắp restore là archive khác"


def test_cleanup_co_hash_ban_trong_container(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch)
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    assert stub.co("sha256sum", "/tmp/SMK1.dump")


# =============================================================================
# P1 — DAT chỉ được ghi khi dịch vụ ĐÃ chạy lại
# =============================================================================
def test_start_hong_thi_KHONG_ghi_DAT(tmp_path, monkeypatch):
    stub = _chuan_bi(tmp_path, monkeypatch, no_o="qltssmoke start")
    with pytest.raises(cli.LoiCLI, match="mở lại dịch vụ hỏng"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "HONG"
    gc = reg.du_lieu["cleanup"]["ghi_chu"]
    assert "DB đã về nền" in gc
    assert "stop lại cả bốn service" in gc, "phải cố đóng lại service đã lên"


def test_service_khong_len_lai_du_start_thanh_cong_thi_KHONG_ghi_DAT(tmp_path, monkeypatch):
    """`start` trả 0 nhưng container không chạy — đúng lớp 'lệnh trả 0 mà việc không xảy ra'."""
    stub = _chuan_bi(tmp_path, monkeypatch, service_chay=["backend"])
    with pytest.raises(cli.LoiCLI, match="chưa sẵn sàng"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "HONG"


# =============================================================================
# P1 — preflight hỏng sau khi đã stop: phải ghi lại, không để cleanup=None
# =============================================================================
@pytest.mark.parametrize(
    "kb,mau", [({"session": "3"}, "còn 3 session"), ({"toc": "rác"}, "preflight")]
)
def test_preflight_hong_ghi_BO_QUA_va_noi_ro_service_dang_dong(tmp_path, monkeypatch, kb, mau):
    stub = _chuan_bi(tmp_path, monkeypatch, **kb)
    with pytest.raises((cli.LoiCLI, baseline.ChanLai)):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    cl = reg.du_lieu["cleanup"]
    assert cl["trang_thai"] == "BO_QUA"
    assert "ĐÓNG" in cl["ghi_chu"] and "nguyên vẹn" in cl["ghi_chu"]
    assert not stub.co("DROP DATABASE")


# =============================================================================
# P1 — --git-sha phải là 40 hex VÀ khớp HEAD
# =============================================================================
@pytest.mark.parametrize("sha", ["banana", "", "abc", "0" * 39, "g" * 40, "0" * 41])
def test_git_sha_khong_hop_le_BLOCK(tmp_path, monkeypatch, sha):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    stub = StubChay(tmp_path)
    with pytest.raises(cli.LoiCLI, match="40 ký tự hex"):
        cli.chay_baseline(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK2", git_sha=sha,
            pack="P2", cid=_CID, thu_muc_dump=tmp_path / "dumps",
            app_env="development",
        )
    assert stub.lenh == []


def test_git_sha_khong_khop_HEAD_BLOCK(tmp_path, monkeypatch):
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    stub = StubChay(tmp_path, git_head="f" * 40)
    with pytest.raises(cli.LoiCLI, match="HEAD đang checkout"):
        cli.chay_baseline(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK2", git_sha="0" * 40,
            pack="P2", cid=_CID, thu_muc_dump=tmp_path / "dumps",
            app_env="development",
        )
    assert not stub.co("pg_dump")


def test_ChayLenh_khong_con_escape_hatch():
    """`cho_phep_loi` từng đổi `check=True` thành `check=False`."""
    import inspect

    tham_so = inspect.signature(cli.ChayLenh.__call__).parameters
    assert "cho_phep_loi" not in tham_so, "escape hatch đã quay lại"


# =============================================================================
# BỐN ĐỐI CHỨNG SWEEP HẬU-START
# =============================================================================
@pytest.mark.parametrize("thieu", ["backend", "frontend"])
def test_health_RONG_khong_duoc_coi_la_san_sang(tmp_path, monkeypatch, thieu):
    """`running` + Health="" từng đi lọt: healthcheck chưa xong ≠ sẵn sàng."""
    hl = {"backend": "healthy", "frontend": "healthy"}
    hl[thieu] = ""
    stub = _chuan_bi(tmp_path, monkeypatch, health=hl)
    with pytest.raises(cli.LoiCLI, match="chưa sẵn sàng"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )
    reg = registry.Registry.doc(tmp_path / "reg", "SMK1")
    assert reg.du_lieu["cleanup"]["trang_thai"] == "HONG"


def test_celery_crashloop_khong_duoc_coi_la_on_dinh(tmp_path, monkeypatch):
    """`running` hai nhịp liên tiếp nhưng là HAI container khác nhau."""
    stub = _chuan_bi(tmp_path, monkeypatch, crashloop={"celery-worker"})
    with pytest.raises(cli.LoiCLI, match="chưa sẵn sàng|chưa ổn định"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )


def test_stop_hong_thi_BO_QUA_noi_KHONG_XAC_DINH(tmp_path, monkeypatch):
    """Chính lệnh stop hỏng ⇒ không được khẳng định 'service đang đóng'."""
    stub = _chuan_bi(tmp_path, monkeypatch, no_o="qltssmoke stop")
    with pytest.raises(cli.LoiCLI):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )
    gc = registry.Registry.doc(tmp_path / "reg", "SMK1").du_lieu["cleanup"]["ghi_chu"]
    assert "KHÔNG XÁC ĐỊNH" in gc
    assert "đang ĐÓNG" not in gc


def test_HONG_luu_van_tay_HAU_start_chu_khong_phai_truoc(tmp_path, monkeypatch):
    """Startup làm lệch DB ⇒ ô `van_tay_sau` phải là số ĐO SAU start.

    Ghi số đo trước start vào ô ấy khiến người điều tra so nhầm và kết luận
    database vẫn đúng nền.
    """
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    _baseline(tmp_path, StubChay(tmp_path))

    class StubLech(StubChay):
        """Vân tay đúng nền tới khi service chạy lại, rồi lệch — như entrypoint ghi DB."""

        def __init__(self, tmp, **kb):
            super().__init__(tmp, **kb)
            self.da_start = False

        def __call__(self, argv):
            if "start" in argv and "compose" in argv:
                self.da_start = True
            if self.da_start and "UNION ALL" in " ".join(argv):
                self.dem = "\n".join(f"{t}|999" for t in baseline.BANG_TRONG_YEU)
            return super().__call__(argv)

    stub = StubLech(tmp_path)
    with pytest.raises(cli.LoiCLI):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
        )

    cl = registry.Registry.doc(tmp_path / "reg", "SMK1").du_lieu["cleanup"]
    bl = registry.Registry.doc(tmp_path / "reg", "SMK1").du_lieu["baseline"]
    assert cl["trang_thai"] == "HONG"
    vt_nen = bl["van_tay_metrics"]
    vt_lech = registry.van_tay({t: 999 for t in baseline.BANG_TRONG_YEU})
    assert cl["van_tay_sau"] == vt_lech, "phải lưu vân tay ĐO SAU start"
    assert cl["van_tay_sau"] != vt_nen, "không được lưu vân tay đo trước start"


# =============================================================================
# TƯƠNG THÍCH RUNTIME — template phải được chính Docker chấp nhận
# =============================================================================
# Stub không thể chứng minh điều này: nó trả bất cứ gì ta bảo nó trả. Bản trước
# tự bịa `.RestartCount` nên cả bộ test xanh trong khi lệnh thật đổ
# `template parsing error: can't evaluate field RestartCount in type
# *formatter.ContainerContext`.
import shutil  # noqa: E402
import subprocess as _sp  # noqa: E402
import uuid  # noqa: E402

_CO_DOCKER = shutil.which("docker") is not None

# Bản trước hỏi một compose project KHÔNG tồn tại. Đo trên CI 14-08 (PR #555) và
# trên Docker host, cùng một template:
#
#   project rỗng      -> rc=0, stdout rỗng, stderr rỗng
#   project 1 container -> rc=1, `template parsing error … RestartCount`
#
# `compose ps --format` chỉ đánh giá template khi CÓ HÀNG để format. Không hàng
# thì ca kiểm ngược không thấy lỗi (đỏ oan) và — nặng hơn — ca thuận XANH với
# BẤT KỲ template nào. Nên hai ca dưới tự dựng một container sentinel.
#
# Chọn `postgres:16-alpine` vì runner CI đã kéo sẵn nó cho service container của
# shard này ⇒ `--pull never` không cần mạng. Chỉ `create`, KHÔNG start: `ps -a`
# vẫn thấy hàng, mà không tốn tiến trình và không mở cổng nào.
_ANH_SENTINEL = "postgres:16-alpine"
_YAML_SENTINEL = f"services:\n  sentinel:\n    image: {_ANH_SENTINEL}\n"


def _lenh_compose(du_an: str, tep: str, *duoi: str):
    return ["docker", "compose", "-p", du_an, "-f", tep, *duoi]


@pytest.fixture
def du_an_sentinel(tmp_path):
    """Compose project tạm, tên ngẫu nhiên, có đúng một container đã `create`."""
    du_an = "qltstpl" + uuid.uuid4().hex[:12]
    tep = tmp_path / "docker-compose.yml"
    tep.write_text(_YAML_SENTINEL, encoding="utf-8")
    try:
        ket = _sp.run(
            _lenh_compose(du_an, str(tep), "create", "--pull", "never"),
            shell=False, capture_output=True, text=True, timeout=180,
        )
        assert ket.returncode == 0, (
            f"không dựng được sentinel (rc={ket.returncode}); ảnh {_ANH_SENTINEL} "
            f"phải có sẵn trong daemon:\n{((ket.stderr or '') + (ket.stdout or ''))[:400]}"
        )
        yield du_an, str(tep)
    finally:
        don = _sp.run(
            _lenh_compose(du_an, str(tep), "down", "--volumes", "--remove-orphans"),
            shell=False, capture_output=True, text=True, timeout=180,
        )
        # Bỏ qua mã thoát ở đây là để ngỏ đúng cái ta đang chống: cleanup hỏng mà
        # ca test vẫn XANH, bỏ lại container/network cho lượt sau. `down` trên
        # project chưa từng tạo trả 0 (đã đo), nên khác 0 luôn là hỏng thật —
        # kể cả khi setup đã đứt trước đó.
        assert don.returncode == 0, (
            f"dọn project sentinel {du_an} HỎNG (rc={don.returncode}):\n"
            f"stdout={(don.stdout or '')[:400]!r}\nstderr={(don.stderr or '')[:400]!r}"
        )


def _bat_buoc_dung_mot_hang_sentinel(du_an: str, tep: str):
    """Tiền đề của cả hai ca dưới: thiếu hàng thì ĐỎ, tuyệt đối không skip.

    "Không quan sát được gì" không được đọc thành "không có gì sai" — đây đúng
    chỗ bản trước im lặng.
    """
    ket = _sp.run(
        _lenh_compose(du_an, tep, "ps", "-a", "--format", "{{.Service}}"),
        shell=False, capture_output=True, text=True, timeout=60,
    )
    hang = [d.strip() for d in (ket.stdout or "").splitlines() if d.strip()]
    assert ket.returncode == 0 and hang == ["sentinel"], (
        "phải thấy ĐÚNG MỘT service `sentinel` trước khi thử template — "
        f"rc={ket.returncode}, hàng={hang!r}, lỗi={(ket.stderr or '')[:300]!r}"
    )


def _thu_template(tmpl: str, du_an: str, tep: str):
    return _sp.run(
        _lenh_compose(du_an, tep, "ps", "-a", "--format", tmpl),
        shell=False, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để kiểm formatter thật")
def test_runtime_template_ps_duoc_docker_chap_nhan(du_an_sentinel):
    du_an, tep = du_an_sentinel
    _bat_buoc_dung_mot_hang_sentinel(du_an, tep)

    ket = _thu_template(cli.TEMPLATE_PS, du_an, tep)
    loi = (ket.stderr or "") + (ket.stdout or "")
    assert ket.returncode == 0, f"docker trả mã {ket.returncode}: {loi[:400]}"

    dong = [d for d in (ket.stdout or "").splitlines() if d.strip()]
    assert len(dong) == 1, f"chờ đúng MỘT dòng sentinel, nhận {dong!r}"

    truong = dong[0].split("|")
    assert len(truong) == 4, (
        f"template {cli.TEMPLATE_PS!r} phải cho đủ bốn trường, nhận {truong!r}"
    )
    assert truong[0] == "sentinel", f"trường Service sai: {truong!r}"
    # `.Health` rỗng là hợp lệ với container mới `create`; `.State`/`.ID` thì
    # không — chúng rỗng nghĩa là template không hề được đánh giá.
    assert truong[1].strip() and truong[3].strip(), (
        f"State/ID rỗng ⇒ template không được đánh giá: {truong!r}"
    )


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để kiểm formatter thật")
def test_kiem_nguoc_dua_RestartCount_vao_template_compose_thi_DO(du_an_sentinel):
    """Chứng minh phép kiểm trên thật sự canh: thêm lại trường cũ phải đỏ."""
    du_an, tep = du_an_sentinel
    _bat_buoc_dung_mot_hang_sentinel(du_an, tep)

    ket = _thu_template(cli.TEMPLATE_PS + "|{{.RestartCount}}", du_an, tep)
    loi = (ket.stderr or "") + (ket.stdout or "")
    # Không neo vào nguyên văn "template parsing error": chuỗi ấy là chi tiết
    # nội bộ của Docker, đổi bản là vỡ. Bất biến thật là "bị từ chối" + "nêu
    # đích danh trường".
    assert ket.returncode != 0, (
        f"Docker LẼ RA phải từ chối .RestartCount trong `compose ps` (rc={ket.returncode}); "
        f"nếu bản Docker mới đã hỗ trợ, gộp lại một lệnh và bỏ ca này. Output: {loi[:400]}"
    )
    assert "RestartCount" in loi, (
        f"lỗi phải nêu đích danh trường bị từ chối, nhận: {loi[:400]}"
    )


def test_template_ps_khong_chua_RestartCount():
    """Kiểm tĩnh, chạy được cả khi không có Docker."""
    assert "RestartCount" not in cli.TEMPLATE_PS


def test_lay_restart_count_bang_docker_inspect_rieng(tmp_path, monkeypatch):
    """Snapshot phải gồm cả hai nguồn: Compose cho danh sách, inspect cho count."""
    stub = _chuan_bi(tmp_path, monkeypatch)
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    assert stub.co("compose", "ps", "-a", cli.TEMPLATE_PS)
    assert stub.co("docker", "inspect", "{{.Id}}|{{.RestartCount}}")


# =============================================================================
# GHÉP HAI NGUỒN — one-off, bội số, và output inspect fail-closed
# =============================================================================
def test_container_oneoff_bi_loai_khoi_snapshot(tmp_path, monkeypatch):
    """Mỗi `docker compose run` để lại một container one-off cùng tên service.

    Đo trên stack dev thật: `backend|running|4df6…` và `backend|exited|7fbf…`,
    cái sau `oneoff=True`. Gán theo thứ tự dòng thì dòng sau ghi đè dòng trước.
    """
    stub = _chuan_bi(
        tmp_path, monkeypatch,
        ps_them=[f"backend|exited||{_CID_ONEOFF}"],
        oneoff={_CID_ONEOFF},
    )
    cli.chay_cleanup(
        chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
        thu_muc_dump=tmp_path / "dumps", app_env="development", ngu=lambda _: None,
    )
    assert registry.Registry.doc(tmp_path / "reg", "SMK1").du_lieu["cleanup"][
        "trang_thai"
    ] == "DAT"


def test_oneoff_RUNNING_khong_duoc_che_container_chinh_DA_CHET(tmp_path, monkeypatch):
    """Ca xanh giả thật sự: container chính exited, one-off running xếp sau."""
    stub = _chuan_bi(
        tmp_path, monkeypatch,
        service_chay=["celery-worker", "celery-beat", "frontend"],  # backend exited
        ps_them=[f"backend|running|healthy|{_CID_ONEOFF}"],
        oneoff={_CID_ONEOFF},
    )
    with pytest.raises(cli.LoiCLI, match="chưa sẵn sàng"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )


def test_hai_container_khong_oneoff_cung_service_thi_BLOCK(tmp_path, monkeypatch):
    stub = _chuan_bi(
        tmp_path, monkeypatch,
        ps_them=[f"backend|running|healthy|{_CID_KHAC}"],  # KHÔNG phải one-off
    )
    with pytest.raises(cli.LoiCLI, match="container không phải one-off"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )


def test_crashloop_CUNG_ID_nhung_RestartCount_tang_thi_BLOCK(tmp_path, monkeypatch):
    """Ca phổ biến hơn ca đổi ID: container giữ nguyên, số lần restart tăng."""
    stub = _chuan_bi(tmp_path, monkeypatch, crashloop={"celery-worker"})
    with pytest.raises(cli.LoiCLI, match="chưa sẵn sàng|chưa ổn định"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )


class _StubInspectXau(StubChay):
    def __init__(self, tmp, tra, **kb):
        super().__init__(tmp, **kb)
        self.tra = tra

    def __call__(self, argv):
        if "inspect" in argv and "RestartCount" in " ".join(argv):
            self.lenh.append(list(argv))
            return self.tra
        return super().__call__(argv)


@pytest.mark.parametrize(
    "tra",
    [
        "",                                   # rỗng
        "khong-phai-dinh-dang\n",             # không có dấu |
        "abc|0|false\n",                      # id không đủ 64 hex
        "a" * 64 + "|x|false\n",              # restart không phải số
        "f" * 64 + "|0|false\n",              # id không khớp id Compose
    ],
)
def test_output_inspect_sai_dang_thi_BLOCK(tmp_path, monkeypatch, tra):
    """`so_restart=""` từng đi lọt: hai nhịp cùng rỗng bằng nhau ⇒ 'ổn định'."""
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    _baseline(tmp_path, StubChay(tmp_path))
    stub = _StubInspectXau(tmp_path, tra)
    with pytest.raises(cli.LoiCLI, match="không đúng dạng|không bắt đầu bằng"):
        cli.chay_cleanup(
            chay=stub, thu_muc=tmp_path / "reg", run_id="SMK1", cid=_CID,
            thu_muc_dump=tmp_path / "dumps", app_env="development",
            ngu=lambda _: None, han_cho_giay=9,
        )
