"""Hop dong cua shadow classifier — moi ca khoa DUNG MOT bat bien.

Tep nay KHONG nam trong `Backend_FastAPI/tests/`, va do la chu y. Cong PR hien
hanh chon tep bang allowlist tuong minh `matrix.include[*].tests`; mot tep test
moi khong co ten trong do thi KHONG lat nao chay ma required check `pytest` van
xanh (memory `ci-allowlist-tep-khong-duoc-gac`). Dat canh script va goi bang mot
lenh tuong minh trong job `classifier-contract` thi khong tang nao co the "quen
chon" no. Tien le dang chay san trong kho: `dependency-audit.yml` goi
`node --test .github/scripts/audit-dev-delta.test.js` vi dung ly do do.

Danh sach nodeid bat buoc nam trong BUOC CONG cua workflow, KHONG nam o day:
neu hang so o trong chinh tep test thi cung mot PR vua xoa ca vua xoa dong hang,
va cong tu mien tru. So luong khong phai hop dong — no la `len()` cua danh sach,
va tang theo so bat bien can canh.

Fixture la hang so viet tay — khong git, khong mang, khong GitHub API.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_GOC = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pr_classify", _GOC / "pr_classify.py")
C = importlib.util.module_from_spec(_spec)
# Phai dang ky TRUOC `exec_module`: `@dataclass` giai chu thich kieu qua
# `sys.modules[cls.__module__].__dict__`, va `from __future__ import annotations`
# lam moi chu thich thanh chuoi. Thieu dong nay thi module nem AttributeError
# ngay luc nap — do that tren Python 3.12.
sys.modules[_spec.name] = C
_spec.loader.exec_module(C)


BE = "Backend_FastAPI/"


def _domain(paths, tests, **kw):
    goc = {"paths": paths, "tests": tests, "isolation": "shared",
           "expected_seconds": 10, "critical": True, "owner": "o", "reason": "r"}
    goc.update(kw)
    return goc


def _manifest() -> dict:
    """Manifest toi thieu hop le. Moi ca chi doi dung thu no can."""
    return {
        "domains": {
            "finance": _domain([BE + "app/services/fee_service.py"],
                               [BE + "tests/services/test_fee.py"]),
            "admission": _domain([BE + "app/services/admission_service.py"],
                                 [BE + "tests/services/test_admission.py"]),
            # Mot mien co anh xa duong FRONTEND — de phan biet "frontend khong
            # duoc map" voi "frontend duoc map".
            "contract": _domain(["frontend/src/lib/api/"],
                                [BE + "tests/api/test_contract.py"]),
        }
    }


UNIVERSE = {
    BE + "tests/services/test_fee.py",
    BE + "tests/services/test_admission.py",
    BE + "tests/api/test_contract.py",
    BE + "tests/unit/test_moi_toanh.py",
}


def _r(status, path, old=None):
    return C.BanGhi(status, path, old)


def _classify(records, mb=None, mh=None, universe=None, changed_files=None):
    return C.classify(records,
                      _manifest() if mb is None else mb,
                      _manifest() if mh is None else mh,
                      UNIVERSE if universe is None else universe,
                      changed_files=changed_files)


# === BON nguon BROAD, moi nguon MOT ca =====================================
# Ca cu chi di qua mot nhanh; ba nhanh kia doi `selected_tests = []` van xanh.

def test_broad_unknown_backend_khong_rong_va_dung_ly_do():
    ke = _classify([_r("M", BE + "scripts/khong_ai_map.py")])
    assert ke.classification == C.BROAD
    assert ke.selected_tests, "BROAD than rong la fail-open doi lot fail-closed"
    assert any(x.startswith("unknown_backend_path:") for x in ke.fallback_reasons)


def test_broad_self_change_khong_rong_va_dung_ly_do():
    ke = _classify([_r("M", ".github/scripts/pr_classify.py")])
    assert ke.classification == C.BROAD
    assert ke.selected_tests
    assert any(x.startswith("self_change:") for x in ke.fallback_reasons)


def test_broad_shared_test_surface_khong_rong_va_dung_ly_do():
    """`tests/fixtures/builders.py` duoc rat nhieu tep test import."""
    ke = _classify([_r("M", BE + "tests/fixtures/builders.py")])
    assert ke.classification == C.BROAD
    assert ke.selected_tests
    assert any(x.startswith("shared_test_surface:") for x in ke.fallback_reasons)


def test_broad_empty_plan_guard_khong_rong_va_dung_ly_do():
    """Mien khop nhung universe khong con tep nao cua no."""
    ke = _classify([_r("M", BE + "app/services/fee_service.py")],
                   universe={BE + "tests/unit/test_moi_toanh.py"})
    assert ke.classification == C.BROAD
    assert ke.selected_tests
    assert "empty_plan_guard" in ke.fallback_reasons


# === ke hoach la HOP base | head ===========================================

def test_ke_hoach_gom_ca_domain_chi_co_o_base():
    """PR sua manifest de tu mien tru: noi long chi hieu luc tu luot SAU."""
    head = {"domains": {k: v for k, v in _manifest()["domains"].items()
                        if k != "finance"}}
    ke = _classify([_r("M", BE + "app/services/fee_service.py")],
                   mb=_manifest(), mh=head)
    assert "finance" in ke.domains


def test_ke_hoach_gom_ca_domain_chi_co_o_head():
    base = {"domains": {k: v for k, v in _manifest()["domains"].items()
                        if k != "admission"}}
    ke = _classify([_r("M", BE + "app/services/admission_service.py")],
                   mb=base, mh=_manifest())
    assert "admission" in ke.domains


# === tep test bi sua =======================================================

def test_tep_test_bi_sua_thi_chinh_no_duoc_chon():
    p = BE + "tests/unit/test_moi_toanh.py"
    ke = _classify([_r("M", BE + "app/services/fee_service.py"), _r("M", p)])
    assert p in ke.selected_tests


def test_test_only_chua_map_chon_chinh_no_khong_broad():
    """PR CHI sua mot `test_*.py` chua map: chay dung tep do, KHONG BROAD.

    ⚠️ Hoi quy that: khi `PRODUCT_PREFIXES` duoc mo ra ca `Backend_FastAPI/`,
    tep test cung thanh "duong san pham" nen vap `unknown_backend_path` TRUOC
    khi luat "test doi thi chay chinh no" kip co hieu luc — do that: BROAD keo
    tron universe. Day dung la thu kien truc adaptive sinh ra de tranh.
    """
    p = BE + "tests/unit/test_moi_toanh.py"
    ke = _classify([_r("M", p)])
    assert ke.classification != C.BROAD, "test-only khong duoc keo tron universe"
    assert ke.selected_tests == [p]


# === self-change: toan bo `.github/**` + HAI dang conftest =================

def test_cham_manifest_thi_broad():
    assert _classify([_r("M", ".github/scripts/domains.yml")]).classification == C.BROAD


def test_cham_workflow_gate_thi_broad():
    assert _classify([_r("M", ".github/workflows/backend-test.yml")]).classification == C.BROAD


def test_cham_github_actions_thi_broad():
    """`.github/actions/**` cung la bo may quyet dinh."""
    assert _classify([_r("M", ".github/actions/setup/action.yml")]).classification == C.BROAD


def test_conftest_goc_cay_test_thi_broad():
    """`tests/conftest.py` la fixture GOC — moi tep dung `client` phu thuoc.

    Khang dinh ca NHAN ly do: neu chi kiem `classification == BROAD` thi mot dot
    bien doi duong di cua conftest sang nhanh khac van xanh (da do that).
    """
    ke = _classify([_r("M", BE + "tests/conftest.py")])
    assert ke.classification == C.BROAD
    assert any(x.startswith("shared_test_surface:") for x in ke.fallback_reasons)


def test_conftest_long_nhau_thi_broad():
    """`tests/unit/conftest.py` — conftest long nhau, cung be mat dung chung."""
    ke = _classify([_r("M", BE + "tests/unit/conftest.py")])
    assert ke.classification == C.BROAD
    assert any(x.startswith("shared_test_surface:") for x in ke.fallback_reasons)


# === rename / delete =======================================================

def test_rename_lien_mien_hop_ca_hai_domain():
    """Dot bien 'chi phan loai path MOI' lot qua moi ca khac — ke ca ca co
    rename ma hai ve roi vao cung mot bucket. Chi ca lien mien nay nhin thay."""
    ke = _classify([_r("R091", BE + "app/services/admission_service.py",
                       BE + "app/services/fee_service.py")])
    assert set(ke.domains) >= {"finance", "admission"}


def test_rename_path_co_khoang_trang_khong_bi_tach_sai():
    """31 duong dan tracked chua khoang trang, 5 duoi `frontend/**` — do that."""
    cu = "frontend/docs/upgrade lead detail/current-ui.png"
    moi = "frontend/docs/upgrade lead detail/current-ui-v2.png"
    ban_ghi = C.phan_tich_name_status_z("R100\0" + cu + "\0" + moi + "\0")
    assert len(ban_ghi) == 1
    assert ban_ghi[0].cac_duong_dan == (cu, moi)


def test_xoa_tep_van_chon_domain_cua_path_cu():
    ke = _classify([_r("D", BE + "app/services/fee_service.py")])
    assert "finance" in ke.domains
    assert BE + "tests/services/test_fee.py" in ke.selected_tests


# === dau vao hong ==========================================================

def test_diff_rong_thi_block_khong_phai_no_backend_impact():
    """Gop 'khong co gi doi' voi 'toi khong doc duoc gi' la fail-open.

    ⚠️ Ban truoc gop BA bat bien vao mot ca (parser raise + kiem_sha raise +
    classify rong) — do thi khong biet vi cai nao. Hai bat bien kia nay co ca
    rieng ben duoi.
    """
    ke = _classify([])
    assert ke.classification == C.BLOCK
    assert ke.sentinel is None


def test_parser_tu_choi_truong_trang_thai_khong_phai_chu():
    """Luong NUL hong phai NEM, khong duoc im lang nuot.

    Do that khi go phep kiem: `"1\\0a.py\\0"` thanh `('1', None, 'a.py')` —
    mot ban ghi bia ra, fail-OPEN tren dau vao hong.
    """
    with pytest.raises(C.LoiDiff):
        C.phan_tich_name_status_z("1\0" + BE + "app/a.py\0")
    with pytest.raises(C.LoiDiff):
        C.phan_tich_name_status_z("M\0")  # thieu duong dan


def test_kiem_sha_tu_choi_duoi_bam_va_xuong_dong():
    """"40 hex, khong gi khac" phai dung nghia den.

    `<40hex>^{tree}` doi han cay duoc diff. Va `$` khop CA TRUOC `\\n` cuoi
    chuoi — do that: `"a"*40 + "\\n"` tung duoc CHAP NHAN. Phai la `\\Z`.
    """
    C.kiem_sha("a" * 40)  # ban dung khong duoc nem
    for xau in ("a" * 40 + "^{tree}", "a" * 40 + "\n", "A" * 40, "a" * 39):
        with pytest.raises(C.LoiDiff):
            C.kiem_sha(xau)


def test_record_it_hon_changed_files_thi_block():
    ke = _classify([_r("M", BE + "app/services/fee_service.py")], changed_files=2)
    assert ke.classification == C.BLOCK
    assert "record_count_mismatch" in ke.fallback_reasons


def test_record_nhieu_hon_changed_files_thi_block():
    """Chieu NGUOC LAI — day moi la chieu that su xay ra.

    `--no-renames` / `diff.renameLimit` tach 1 rename thanh `A`+`D`:
    records = 2, changed_files = 1. Git canh bao ra stderr roi **thoat 0**.
    Ca chi thu chieu `<` se de dot bien `!=` -> `<` lot luoi.
    """
    ke = _classify([_r("A", BE + "app/services/fee_service.py"),
                    _r("D", BE + "app/services/fee_service_cu.py")],
                   changed_files=1)
    assert ke.classification == C.BLOCK
    assert "record_count_mismatch" in ke.fallback_reasons


# === khong tac dong backend / frontend =====================================

def test_docs_only_tra_sentinel_no_backend_impact_tuong_minh():
    ke = _classify([_r("M", "Documents/PRODUCTION_DEPLOY_GUIDE.md")])
    assert ke.classification == C.NO_BACKEND_IMPACT
    assert ke.sentinel == "no-backend-impact"
    assert ke.selected_tests == []


def test_frontend_ui_thuan_tra_no_backend_impact():
    """Muc tieu chinh cua ca kien truc: sua UI nho KHONG keo tron backend.

    ⚠️ Ban truoc tra BROAD qua `empty_plan_guard` — di nguoc han muc tieu.
    """
    ke = _classify([_r("M", "frontend/src/components/Button.tsx")])
    assert ke.classification == C.NO_BACKEND_IMPACT
    assert ke.sentinel == "no-backend-impact"
    assert ke.selected_tests == []


def test_frontend_duoc_manifest_anh_xa_thi_chay_domain():
    """Frontend cham HOP DONG (api client / zod) thi phai keo bundle contract."""
    ke = _classify([_r("M", "frontend/src/lib/api/client.ts")])
    assert ke.classification == C.DOMAIN
    assert ke.domains == ["contract"]
    assert BE + "tests/api/test_contract.py" in ke.selected_tests


def test_pr_tron_frontend_backend_theo_backend():
    """Sentinel khong duoc lam mat ke hoach backend."""
    ke = _classify([_r("M", "frontend/src/components/Button.tsx"),
                    _r("M", BE + "app/services/fee_service.py")])
    assert ke.classification == C.DOMAIN
    assert ke.sentinel is None
    assert BE + "tests/services/test_fee.py" in ke.selected_tests


# === luoc do manifest ======================================================

def _man_text(**ghi_de):
    # ⚠️ `paths` mac dinh phai nam tren mot BE MAT DUOC TRA MIEN. Truoc day la
    # `['a']` — nay bi `nap_manifest` tu choi, dung theo thiet ke moi.
    truong = {"paths": "['Backend_FastAPI/app/x.py']", "tests": "['t']",
              "isolation": "shared",
              "expected_seconds": "1", "critical": "true", "owner": "o",
              "reason": "r"}
    truong.update(ghi_de)
    return ("domains:\n  finance:\n"
            + "".join("    %s: %s\n" % (k, v) for k, v in truong.items()))


def _yaml_domain(than: dict) -> str:
    """Dung YAML tu mot dict than domain — de thu tung khoa bi thieu."""
    import json as _j
    return ("domains:\n  finance:\n"
            + "".join("    %s: %s\n" % (k, _j.dumps(v)) for k, v in than.items()))


def test_manifest_trung_khoa_bi_tu_choi():
    """`yaml.safe_load` nuot im lang khoa trung va giu ban cuoi (PyYAML 6.0.3)."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text() + _man_text().split("domains:\n")[1])


def test_manifest_gia_tri_bool_yaml_bi_tu_choi():
    """`owner: NO` -> False. Mot owner ten 'No' bien thanh bool."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(owner="NO"))


def test_manifest_so_co_so_0_bi_tu_choi():
    """`090` -> chuoi; `017` -> 15 (bat phan)."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(expected_seconds="'090'"))


def test_manifest_bool_khong_lot_cong_kiem_int():
    """`isinstance(True, int)` la True — phai dung `type(...) is`."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(expected_seconds="true"))


def test_manifest_rong_bi_tu_choi_khong_phai_bootstrap():
    """Manifest TON TAI nhung rong khong phai bootstrap.

    Bootstrap la khi tep KHONG ton tai va `ls-tree` xac nhan. Tra `{}` cho mot
    manifest bi cat trang bien no thanh 'khong co mien nao' — fail-open cam.
    """
    with pytest.raises(C.LoiManifest):
        C.nap_manifest("")


def test_selector_manifest_khong_khop_tep_nao_thi_do():
    """Selector go sai lam pytest thu 0 ca cho bundle do — va do lai la XANH."""
    m = {"domains": {"x": _domain([BE + "app/a.py"],
                                  [BE + "tests/services/test_go_sai.py"])}}
    with pytest.raises(C.LoiManifest):
        C.kiem_selector_manifest(m, UNIVERSE)
    C.kiem_selector_manifest(_manifest(), UNIVERSE)  # ban dung thi khong nem


def test_manifest_thieu_khoa_bat_buoc_nem_loi_manifest():
    """Thieu khoa phai la `LoiManifest`, KHONG duoc la `KeyError`.

    `main()` chi bat `(LoiDiff, LoiManifest, CalledProcessError)`. Mot `KeyError`
    thoat ra ngoai lam mat luon artifact chan doan — dung thu ma
    `test_cli_tra_ma_khac_0_khi_block` sinh ra de bao ve.
    """
    for thieu in C.KHOA_BAT_BUOC:
        con = {k: v for k, v in _manifest()["domains"]["finance"].items()
               if k != thieu}
        with pytest.raises(C.LoiManifest):
            C.nap_manifest(_yaml_domain(con))


def test_manifest_chuoi_rong_trong_paths_bi_tu_choi():
    """`paths: ['']` lam `startswith('')` khop MOI duong ⇒ mot mien nuot ca kho."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(paths="['']"))
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(tests="['   ']"))


def test_manifest_path_thoat_kho_bi_tu_choi():
    """Glob thoat khoi kho thi khop bua."""
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(paths="['../../etc/']"))
    with pytest.raises(C.LoiManifest):
        C.nap_manifest(_man_text(tests="['/etc/passwd']"))


def test_manifest_critical_khong_phai_bool_that_bi_tu_choi():
    """Chi bool THAT duoc qua — chuoi `'false'` la cai bay nguy hiem nhat.

    `critical: 'false'` la CHUOI, ma moi chuoi khong rong deu truthy trong
    Python ⇒ mot mien tac gia co y danh dau KHONG critical se duoc doi xu nhu
    critical. Chieu nguoc lai (`critical: 1`) thi lot cong `isinstance(x, int)`.

    ⚠️ `yes`/`no`/`on`/`off` KHONG nam trong danh sach nay: YAML 1.1 dung chung
    thanh bool THAT, nen chung hop le. Da do — them chung vao day lam ca nay do
    vi kỳ vong sai, khong phai vi ma sai.
    """
    for xau in ("1", "0", "'true'", "'false'", "null", "1.0", "[]"):
        with pytest.raises(C.LoiManifest):
            C.nap_manifest(_man_text(critical=xau))


# === bat bien cua chinh ke hoach + git + CLI ===============================

def test_be_mat_da_biet_ngoai_backend_van_duoc_khop_mien():
    """`scripts/`, `nginx/` la be mat DA BIET — khop mien thi phai chay mien do.

    ⚠️ Go `scripts/` khoi `KNOWN_NON_BACKEND_PREFIXES` thi `scripts/deploy.sh`
    tut tu `DOMAIN[infra]/3 test` xuong `NO_BACKEND_IMPACT`/0 test — do that tren
    `domains.yml` THAT. Fixture chi anh xa `frontend/` nen mu truoc ca nay.
    """
    m = {"domains": {"infra": _domain(["scripts/", "nginx/"],
                                      [BE + "tests/unit/test_moi_toanh.py"])}}
    for p in ("scripts/deploy.sh", "nginx/Dockerfile"):
        ke = C.classify([_r("M", p)], m, m, UNIVERSE)
        assert ke.classification == C.DOMAIN, "%r phai ra DOMAIN" % (p,)
        assert ke.domains == ["infra"]
        assert BE + "tests/unit/test_moi_toanh.py" in ke.selected_tests


def test_ke_hoach_khong_tru_bot_tep_ung_vien_isolated():
    """`CANDIDATE_FOR_ISOLATED_PER_PR` la NHAN, khong phai danh sach loai tru.

    Tru chung khoi ke hoach la mat test IM LANG: do that tren universe that,
    mot PR sua `app/security/` di tu `DOMAIN/1 test` xuong con thieu dung tep
    ung vien.
    """
    ung_vien = C.CANDIDATE_FOR_ISOLATED_PER_PR[0]
    universe = {ung_vien, BE + "tests/unit/test_moi_toanh.py"}
    m = {"domains": {"x": _domain([BE + "app/a.py"], [BE + "tests/unit/"])}}
    ke = C.classify([_r("M", BE + "app/a.py")], m, m, universe)
    assert ung_vien in ke.selected_tests, (
        "tep ung vien bi tru khoi ke hoach — day la waiver ngam, khong phai nhan")


def test_record_count_dem_record_khong_dem_path_o_pr_rename():
    """Rename la MOT record nhung HAI path. Dem path thay record lam MOI PR co
    rename BLOCK oan.

    ⚠️ `test_rename_lien_mien_*` truyen `changed_files=None` nen mu truoc lo nay.
    """
    ke = _classify([_r("R091", BE + "app/services/admission_service.py",
                       BE + "app/services/fee_service.py")],
                   changed_files=1)
    assert ke.classification != C.BLOCK, (
        "PR rename hop le bi BLOCK — dang dem path thay vi dem record")
    assert "record_count_mismatch" not in ke.fallback_reasons


def test_git_hong_khong_bi_coi_la_manifest_vang(monkeypatch):
    """"git hong" KHAC "manifest vang".

    Gop hai ca do lam BASE mat sach mien ma khong ai bao — dung duong fail-open
    ma docstring cua module tuyen bo cam. `ls-tree` tra 0 va output RONG cho
    duong khong co, nen hai ca PHAN BIET duoc rach roi.
    """
    import subprocess as _sp

    def _no(*a, **k):
        raise _sp.CalledProcessError(128, "git")

    monkeypatch.setattr(C, "_git", _no)
    with pytest.raises(_sp.CalledProcessError):
        C.nap_manifest_tai("a" * 40, "x.yml", cho_phep_vang=True)


# === ngu nghia CLI: ma thoat + chan doan ===================================

def test_pr_cham_backend_khong_bao_gio_sinh_ke_hoach_rong():
    """⚠️ Ban dau ca nay chi thu ba duong `app/`, `scripts/`, `alembic/` — ca ba
    deu nam SAN trong be mat backend, nen no MU truoc chinh lo no tuyen bo khoa:
    cac duong backend khac roi vao NO_BACKEND_IMPACT voi ke hoach rong.
    """
    for p in (BE + "app/services/fee_service.py",
              BE + "scripts/tool.py",
              BE + "alembic/versions/abc_migration.py",
              BE + "tests/fixtures/builders.py",
              BE + "tests/security/ratelimit_wrong_order_allowlist.txt",
              BE + "auth_model.conf",
              BE + "docker-entrypoint.sh",
              BE + "tests/VISIBILITY_LEDGER.yml"):
        ke = _classify([_r("M", p)])
        assert ke.classification != C.NO_BACKEND_IMPACT, (
            "duong backend %r bi phan loai NO_BACKEND_IMPACT" % (p,))
        assert ke.selected_tests, "duong %r sinh ke hoach RONG" % (p,)


def test_ke_hoach_khong_tro_toi_tep_da_xoa():
    """Universe lay o HEAD. Ke hoach tro tep da xoa lam pytest thoat ma 4."""
    da_xoa = BE + "tests/services/test_fee.py"
    universe = {p for p in UNIVERSE if p != da_xoa}
    ke = _classify([_r("M", BE + "app/services/fee_service.py"),
                    _r("D", da_xoa)], universe=universe)
    assert da_xoa not in ke.selected_tests


def test_cli_tra_ma_khac_0_khi_block(tmp_path):
    """SHADOW nghia la ket qua PHAN LOAI khong quyet dinh lat nao chay — KHONG
    nghia la moi ket cuc deu RC=0. Mot luot khong phan loai duoc ma tra 0 lam
    workflow xanh cam.

    Va chan doan phai duoc GHI TRUOC khi thoat: luot BLOCK moi la luot can
    dieu tra nhat.
    """
    out = tmp_path / "plan.json"
    rc = C.main(["--base-sha", "khong-phai-sha", "--merge-sha", "0" * 40,
                 "--out", str(out), "--khong-kiem-dinh-danh"])
    assert rc != 0, "BLOCK phai cho ma thoat khac 0"
    assert out.exists(), "phai ghi chan doan TRUOC khi thoat"
    import json
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["classification"] == C.BLOCK
    assert d["block_reason"]


# === be mat DA BIET moi + luoc do `paths:` fail-closed =====================

def test_docker_compose_va_env_example_khop_mien_thay_vi_no_backend_impact():
    """`docker-compose*.yml` va `.env*.example` phai la be mat DA BIET.

    ⚠️ Do that truoc khi va: PR chi sua `docker-compose.yml` ra
    `NO_BACKEND_IMPACT`/0 test — trong khi `tests/unit/test_nginx_template_packaging.py`
    khai `_DUONG_GUARD_DOC` ma PHAN TU DAU TIEN la `"docker-compose.yml"`. Kho
    nay da vap dung lo nay o bo loc `paths:` cua `backend-test.yml` (13-08-2026);
    day la nhanh anh em, dung `va-mot-nhanh-con-bon`.
    """
    m = {"domains": {"infra": _domain(["docker-compose", ".env"],
                                      [BE + "tests/unit/test_nginx.py"])}}
    uni = {BE + "tests/unit/test_nginx.py"}
    for duong in ("docker-compose.yml", "docker-compose.rollback.yml",
                  ".env.production.example"):
        ke = C.classify([_r("M", duong)], m, m, uni)
        assert ke.classification == C.DOMAIN, (duong, ke.classification)
        assert ke.selected_tests == sorted(uni), duong


def test_tests_e2e_va_tai_lieu_van_hanh_khong_roi_xuong_unknown():
    """`tests-e2e/**` la VAN HANH, `Documents/**` la AN TOAN — ca hai deu phai
    co CO HOI duoc anh xa mien.

    Nam o nhanh mac dinh thi `_khop_domain` khong bao gio duoc tra cho chung,
    nen dat chung vao `paths:` la NO-OP im lang.
    """
    assert C._loai_be_mat("tests-e2e/nginx-packaging/docker-compose.nginx-test.yml") == C.OPS
    assert C._loai_be_mat("Documents/PRODUCTION_DEPLOY_GUIDE.md") == C.SAFE


# === fail-closed cho duong CHUA BIET ======================================

def test_duong_top_level_la_hoac_ra_broad_khong_phai_no_backend_impact():
    """`new_worker/consumer.py` — mot thu muc dich vu MOI — phai BROAD.

    ⚠️ Do that truoc khi va: no ra `NO_BACKEND_IMPACT`/0 test. Do la fail-OPEN.
    Mot worker moi hoan toan co the la thu duy nhat trong PR, va cai gia cua
    "khong biet no la gi" phai la chay THEM, khong phai chay IT hon.
    """
    ke = _classify([_r("A", "new_worker/consumer.py")])
    assert ke.classification == C.BROAD
    assert any(x.startswith("unknown_repo_path:") for x in ke.fallback_reasons), \
        ke.fallback_reasons
    assert ke.selected_tests == sorted(UNIVERSE)


def test_moi_duong_trong_github_deu_la_self_ke_ca_dependabot():
    """`.github/dependabot.yml` phai BROAD.

    ⚠️ Do that truoc khi va: `SELF_PREFIXES` chi liet ke
    `workflows/ actions/ scripts/`, nen `dependabot.yml` roi xuong nhanh mac
    dinh ⇒ `NO_BACKEND_IMPACT`/0 test. Ma no chinh la tep quyet dinh phien ban
    moi phu thuoc — mot trong nhung tep co suc pha hoai lon nhat kho nay.
    """
    for duong in (".github/dependabot.yml", ".github/CODEOWNERS",
                  ".github/ISSUE_TEMPLATE/bug.md"):
        assert C._loai_be_mat(duong) == C.SELF, duong
    ke = _classify([_r("M", ".github/dependabot.yml")])
    assert ke.classification == C.BROAD
    assert any(x.startswith("self_change:") for x in ke.fallback_reasons)


def test_readme_goc_la_be_mat_an_toan_va_ra_no_backend_impact():
    """Allowlist an toan phai THAT SU im lang — neu khong thi ca thiet ke vo
    nghia va moi PR deu BROAD."""
    for duong in ("README.md", "CLAUDE.md", "LICENSE"):
        assert C._loai_be_mat(duong) == C.SAFE, duong
    ke = _classify([_r("M", "README.md")])
    assert ke.classification == C.NO_BACKEND_IMPACT
    assert ke.sentinel == "no-backend-impact"


def test_tron_AN_TOAN_voi_CHUA_BIET_thi_BROAD_khong_duoc_im_lang():
    """Nua dau an toan KHONG mua duoc su im lang cho nua sau.

    Phep kiem `UNKNOWN` phai dat TRUOC phep gan mien; neu dat sau, mot PR tron
    `README.md` voi mot thu muc la se di theo nhanh "khong keo mien nao" va ra
    `NO_BACKEND_IMPACT`.
    """
    ke = _classify([_r("M", "README.md"), _r("A", "new_worker/consumer.py")])
    assert ke.classification == C.BROAD
    assert any("new_worker/consumer.py" in x for x in ke.fallback_reasons)


def test_be_mat_VAN_HANH_khong_khop_mien_thi_BROAD_khong_phai_thoi():
    """`nginx/`, `scripts/`, `tests-e2e/`, compose, `.env*.example` khac
    `frontend/`: mat mot anh xa o day la mat GUARD.

    ⚠️ Truoc day chung chung mot ro voi `frontend/`, va luat cua ro do la
    "khong khop mien thi thoi". Nghia la go `scripts/` khoi `infra.paths` bien
    mot PR sua `scripts/deploy.sh` thanh `NO_BACKEND_IMPACT`/0 test — im lang.
    """
    m = {"domains": {"finance": _domain([BE + "app/x.py"],
                                        [BE + "tests/services/test_fee.py"])}}
    for duong in ("scripts/deploy.sh", "nginx/Dockerfile",
                  "docker-compose.yml", ".env.production.example",
                  "tests-e2e/nginx-packaging/README.md"):
        ke = C.classify([_r("M", duong)], m, m, UNIVERSE)
        assert ke.classification == C.BROAD, (duong, ke.classification)
        assert any(x.startswith("unmapped_ops_path:") for x in ke.fallback_reasons), \
            (duong, ke.fallback_reasons)


def test_manifest_paths_ngoai_be_mat_duoc_tra_bi_tu_choi():
    """Them mot `paths:` vao be mat KHONG duoc tra mien la no-op — phai DO.

    ⚠️ Do that: them `Documents/` vao `infra.paths` khi `Documents/` con o
    `OTHER` thi manifest van hop le, cong van xanh, va **khong doi gi ca**. Im
    lang la dang hong te nhat.
    """
    # ⚠️ `README.md` KHONG nam trong danh sach nay: `SAFE_RE` khien `.md` o goc
    # tro thanh be mat DUOC TRA MIEN, nen khai no la hop le va co tac dung. Ban
    # dau danh sach tien to go tay lai TU CHOI no — hai hang so mau thuan nhau,
    # va hau qua la `CLAUDE.md` (runbook, co guard doc that) khong the map.
    for xau in ("['.github/workflows/']", "['.github/dependabot.yml']",
                "['khong-ton-tai-be-mat-nao/']", "['.agent/']",
                "['dev.sh']", "['.dockerignore']"):
        with pytest.raises(C.LoiManifest):
            C.nap_manifest(_man_text(paths=xau))


def test_manifest_paths_tren_be_mat_AN_TOAN_duoc_chap_nhan():
    """Doi chung cua ca tren — neu khong thi phep tu choi co the dang tu choi
    HET, va ta khong biet.

    `CLAUDE.md` la ca that: `test_nginx_template_packaging.py` mo no bang
    `_CLAUDE_MD` va khang dinh ve noi dung. No PHAI khai duoc trong `paths:`.
    """
    for xau in ("['CLAUDE.md']", "['frontend/src/lib/zod/finance.ts']",
                "['Documents/PRODUCTION_DEPLOY_GUIDE.md']",
                "['docker-compose']", "['.env']", "['nginx/']",
                "['Backend_FastAPI/']"):
        C.nap_manifest(_man_text(paths=xau))


def test_manifest_paths_tro_vao_cay_test_bi_tu_choi():
    """Cay test co luat RIENG (TEST_FILE/TEST_SHARED) — khong qua khop mien.

    ⚠️ Phep cu la `startswith(TEST_PREFIX)`, lech dung MOT ky tu:
    `Backend_FastAPI/tests` (khong dau `/` cuoi) duoc CHAP NHAN, khop hang tram
    tep that, va khong tep nao di qua `_khop_domain`. Ma dang khong-dau-gach
    chinh la dang nguoi viet se go — moi selector trong manifest deu bo dau `/`.
    """
    for xau in ("['Backend_FastAPI/tests/services/']", "['Backend_FastAPI/tests']",
                "['Backend_FastAPI/test']"):
        with pytest.raises(C.LoiManifest):
            C.nap_manifest(_man_text(paths=xau))


def test_paths_go_sai_khop_0_duong_thi_do():
    """CHIEU XUOI: `paths:` khong khop duong nao la mien da CHET tren thuc te.

    An toan (moi thu roi ve BROAD) nhung CAM: mien van "song" tren giay. Doi
    xung voi `kiem_selector_manifest`, va la nga duy nhat phat hien mot `paths:`
    go sai mot chu cai.
    """
    m = {"domains": {"finance": _domain([BE + "app/services/admision"],
                                        [BE + "tests/services/test_fee.py"])}}
    moi_duong = {BE + "app/services/admission_service.py", "README.md"}
    with pytest.raises(C.LoiManifest, match="khong khop duong nao"):
        C.kiem_paths_manifest(m, moi_duong)
    m["domains"]["finance"]["paths"] = [BE + "app/services/admission"]
    C.kiem_paths_manifest(m, moi_duong)


def test_domain_khong_keo_mien_nao_duoc_danh_dau_test_only_self_select():
    """`DOMAIN` + `bundles == []` la hop le nhung DE DOC NHAM.

    Consumer o pha thang hang fan-out theo `bundles` se dung 0 job trong khi
    nhan van la DOMAIN. Phai co dau tuong minh trong artifact.
    """
    tep = BE + "tests/services/test_chua_ai_map.py"
    ke = _classify([_r("M", tep)], universe=UNIVERSE | {tep})
    assert ke.classification == C.DOMAIN
    assert ke.bundles == []
    assert "test_only_self_select" in ke.fallback_reasons


def test_dem_phu_song_dem_dung_so_tep_mo_coi():
    """Chieu XUOI (tep -> mien) khong ai kiem; `kiem_selector_manifest` chi kiem
    chieu nguoc. Con so nay di vao artifact de tieu chi thang hang duoc quyet
    bang do luong.
    """
    m = {"domains": {"finance": _domain([BE + "app/x.py"],
                                        [BE + "tests/services/test_fee"])}}
    uni = {BE + "tests/services/test_fee.py",
           BE + "tests/services/test_fee_extra.py",
           BE + "tests/services/test_lead.py"}
    d = C.dem_phu_song(m, uni)
    assert d == {"test_universe_count": 3, "test_covered_count": 2,
                 "test_orphan_count": 1}


@pytest.fixture
def kho_merge(tmp_path, monkeypatch):
    """Kho that voi MOT merge commit: parent1 = dinh base, parent2 = dinh nhanh.

    ⚠️ Ba ca CLI ban dau truyen `--base-sha HEAD --merge-sha HEAD`. Do that:
    `main()` dut o `kiem_sha` ("HEAD" khong phai 40 hex) TRUOC khi cham
    manifest — nen chung BLOCK vi mot ly do KHAC voi ly do ten chung hua, va
    `records` luon rong. Ca "van giu records" khi ay xanh ca khi handler dat
    `records = []`, con ca "bat moi ngoai le" thi bat dung `LoiDiff` — mot
    trong ba lop DA BIET. Hai sentinel khoa hai thu khong khoa gi.
    """
    import subprocess as sp

    kho = tmp_path / "kho"
    kho.mkdir()

    def g(*args):
        return sp.run(("git",) + args, cwd=kho, check=True,
                      capture_output=True, text=True).stdout.strip()

    g("init", "-q", "-b", "main")
    g("config", "user.email", "x@y.z")
    g("config", "user.name", "x")
    (kho / "a.txt").write_text("1", encoding="utf-8")
    # `nap_manifest_tai` doc manifest TU CAY GIT o SHA, khong tu dia — nen kho
    # tam phai co ca manifest lan mot tep test that, neu khong moi ca CLI se
    # dung o "manifest khong ton tai" thay vi o dieu no dinh kiem.
    tt = kho / "Backend_FastAPI" / "tests" / "services"
    tt.mkdir(parents=True)
    (tt / "test_fee.py").write_text("def test_x(): pass" + chr(10), encoding="utf-8")
    gs = kho / ".github" / "scripts"
    gs.mkdir(parents=True)
    (gs / "domains.yml").write_text(
        _man_text(paths="['Backend_FastAPI/app/services/']",
                  tests="['Backend_FastAPI/tests/services/test_fee.py']"),
        encoding="utf-8")
    # Ban HONG: selector khong khop tep nao — dung cho ca kiem `LoiManifest`.
    (gs / "domains_hong.yml").write_text(
        _man_text(paths="['Backend_FastAPI/app/services/']",
                  tests="['khong-khop-tep-nao/']"),
        encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "goc")
    g("checkout", "-q", "-b", "nhanh")
    duong = kho / "Backend_FastAPI" / "app" / "services"
    duong.mkdir(parents=True)
    (duong / "fee_service.py").write_text("x = 1\n", encoding="utf-8")
    (kho / "b.txt").write_text("2", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "nhanh")
    head = g("rev-parse", "HEAD")
    g("checkout", "-q", "main")
    (kho / "c.txt").write_text("3", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "base nhich")
    base = g("rev-parse", "HEAD")
    g("merge", "-q", "--no-ff", "-m", "merge", "nhanh")
    merge = g("rev-parse", "HEAD")
    monkeypatch.chdir(kho)
    return {"kho": kho, "base": base, "head": head, "merge": merge}


def test_cli_block_van_giu_records_va_change_record_count(tmp_path, kho_merge):
    """Ngoai le KHONG duoc xoa `records` da phan tich.

    ⚠️ Ban dau handler dat `records = []`: mot manifest go sai selector cho JSON
    `records: []` / `change_record_count: 0` — KHONG phan biet duoc voi "diff
    rong", dung thu ma phep so voi `changed_files` dung ra de phan biet.

    Ca nay chi co gia tri khi diff THUC SU chay xong roi manifest moi hong —
    nen no dung kho merge that va khang dinh `change_record_count > 0`.
    """
    import json
    out = tmp_path / "plan.json"
    rc = C.main(["--base-sha", kho_merge["base"], "--head-sha", kho_merge["head"],
                 "--merge-sha", kho_merge["merge"],
                 "--manifest", ".github/scripts/domains_hong.yml",
                 "--out", str(out)])
    assert rc != 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["classification"] == C.BLOCK
    assert "exception:LoiManifest" in d["fallback_reasons"], d["fallback_reasons"]
    assert d["change_record_count"] > 0, "records da phan tich bi xoa mat"
    assert d["records"], "artifact mat danh sach record — khong phan biet duoc voi diff RONG"


def test_cli_bat_moi_ngoai_le_chu_khong_chi_ba_lop_da_biet(tmp_path, kho_merge):
    """Luoi `except` phai RONG.

    ⚠️ Ban dau chi bat `(LoiDiff, LoiManifest, CalledProcessError)`. `OSError`
    khi ghi `--out` va moi loi lap trinh xuyen thang qua ⇒ traceback ⇒ **khong
    artifact nao duoc ghi**, dung luot can dieu tra nhat lai la luot khong de
    lai gi.

    Ca nay nem mot loai NGOAI danh sach da biet — `ZeroDivisionError` — tu
    trong `classify`, de no chi xanh khi luoi that su rong.
    """
    import json
    out = tmp_path / "plan.json"

    def no(*a, **k):
        raise ZeroDivisionError("loi lap trinh gia dinh")

    goc = C.classify
    C.classify = no
    try:
        rc = C.main(["--base-sha", kho_merge["base"], "--head-sha", kho_merge["head"],
                     "--merge-sha", kho_merge["merge"], "--out", str(out)])
    finally:
        C.classify = goc
    assert rc != 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["classification"] == C.BLOCK
    assert "exception:ZeroDivisionError" in d["fallback_reasons"], d["fallback_reasons"]
    assert d["change_record_count"] > 0


# === dinh danh ba SHA =====================================================
# Cac ca THUAN duoi day chay tren raw commit object viet tay — khong git,
# khong mang. Ca CUOI la ca DAY NOI: no dung git that de chung minh `main()`
# co GOI phep kiem, chu khong chi la mot ham dep nam khong.

_RAW_MERGE = (
    "tree 1111111111111111111111111111111111111111\n"
    "parent " + "a" * 40 + "\n"
    "parent " + "b" * 40 + "\n"
    "author x <x@y.z> 1 +0000\n"
    "committer x <x@y.z> 1 +0000\n"
    "\n"
    "Merge pull request #1\n"
)


def test_doc_parents_doc_dung_hai_parent_theo_dung_thu_tu():
    assert C.doc_parents(_RAW_MERGE) == ["a" * 40, "b" * 40]


def test_doc_parents_khong_bi_lua_boi_chu_parent_trong_THONG_DIEP():
    """Phai dung o dong trong dau tien.

    Mot thong diep commit hoan toan co the chua dong bat dau bang `parent ` —
    vd khi ai do dan raw object vao mo ta PR. Doc ca tep se dem ra BA parent va
    phep kiem `len == 2` do vi ly do sai.
    """
    gia = _RAW_MERGE + "parent " + "c" * 40 + "\n"
    assert C.doc_parents(gia) == ["a" * 40, "b" * 40]


def test_doc_parents_tu_choi_object_khong_phai_commit():
    with pytest.raises(C.LoiDinhDanh):
        C.doc_parents("100644 blob 1234\tREADME.md\n")


def test_dinh_danh_parent1_sai_thi_nem():
    """parent1 phai la dinh nhanh BASE. Sai parent1 nghia la merge duoc dung
    tren mot base khac — moi phep diff sau do noi ve cap cay KHAC."""
    with pytest.raises(C.LoiDinhDanh, match="parent1"):
        C.kiem_dinh_danh_merge("f" * 40, "b" * 40, "d" * 40, _RAW_MERGE, "d" * 40)


def test_dinh_danh_parent2_sai_thi_nem():
    with pytest.raises(C.LoiDinhDanh, match="parent2"):
        C.kiem_dinh_danh_merge("a" * 40, "f" * 40, "d" * 40, _RAW_MERGE, "d" * 40)


def test_dinh_danh_commit_khong_phai_merge_thi_nem():
    """Ca hai chieu: MOT parent (commit thuong) va BA parent (octopus)."""
    mot = ("tree 1111111111111111111111111111111111111111\n"
           "parent " + "a" * 40 + "\nauthor x <x@y.z> 1 +0000\n\nmsg\n")
    ba = (_RAW_MERGE.split("author")[0] + "parent " + "c" * 40 + "\n"
          "author x <x@y.z> 1 +0000\n\nmsg\n")
    for raw in (mot, ba):
        with pytest.raises(C.LoiDinhDanh, match="parent"):
            C.kiem_dinh_danh_merge("a" * 40, "b" * 40, "d" * 40, raw, "d" * 40)


def test_dinh_danh_checkout_khong_phai_merge_thi_nem():
    """Cay dang do phai LA cay ma ke hoach noi toi.

    `universe_tai`/`nap_manifest_tai` doc theo SHA nen van dung, nhung mot
    checkout lech la dau hieu workflow dang truyen sai SHA — va lan sau no se
    lech ca cho khong doc theo SHA.
    """
    with pytest.raises(C.LoiDinhDanh, match="checkout"):
        C.kiem_dinh_danh_merge("a" * 40, "b" * 40, "d" * 40, _RAW_MERGE, "e" * 40)


def test_dinh_danh_tu_choi_sha_khong_phai_40_hex():
    for base, head, merge, co in (
        ("HEAD", "b" * 40, "d" * 40, "d" * 40),
        ("a" * 40, "b" * 39, "d" * 40, "d" * 40),
        ("a" * 40, "b" * 40, "D" * 40, "D" * 40),
        ("a" * 40, "b" * 40, "d" * 40, ""),
    ):
        with pytest.raises(C.LoiDinhDanh, match="40 hex"):
            C.kiem_dinh_danh_merge(base, head, merge, _RAW_MERGE, co)


def test_cli_THUC_SU_goi_kiem_dinh_danh(tmp_path, kho_merge):
    """Ca DAY NOI — dung git that.

    Cac ca thuan o tren chung minh HAM dung. Ca nay chung minh `main()` GOI
    no: dung
    mot kho co merge commit that (parent1 = dinh base, parent2 = dinh nhanh,
    y het `refs/pull/N/merge`), roi truyen head-sha SAI. Neu day noi bi thao,
    ca nay xanh trong khi tam ca kia van xanh.
    """
    import json

    base, head, merge = (kho_merge["base"], kho_merge["head"],
                          kho_merge["merge"])
    assert C.doc_parents(C.doc_raw_commit(merge)) == [base, head], \
        "kho dung sai — parent1 phai la base, parent2 phai la nhanh"

    out = tmp_path / "plan.json"
    rc = C.main(["--base-sha", base, "--head-sha", "0" * 40,
                 "--merge-sha", merge, "--out", str(out)])
    assert rc != 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["classification"] == C.BLOCK
    assert "exception:LoiDinhDanh" in d["fallback_reasons"], d["fallback_reasons"]
    assert "parent2" in d["block_reason"]


def test_artifact_ghi_lai_parent_QUAN_SAT_ke_ca_khi_dinh_danh_DO(tmp_path, kho_merge):
    """Luot BLOCK vi dinh danh phai de lai DU LIEU, khong chi loi.

    ⚠️ Do that tren 23 PR MO con merge ref (05-09-2026): `parent2 == head.sha`
    dung 23/23, nhung `parent1 == base.sha` chi dung **1/23** — vi
    `refs/pull/N/merge` mang parent1 la dinh SONG cua nhanh base va duoc GitHub
    dung lai theo yeu cau, con `base.sha` dong cung tai `synchronize` gan nhat.
    Cap trong CUNG mot payload duoc ky vong nhat quan, nhung dieu do CHUA duoc
    do. Ba truong `merge_parents` / `head_checkout` / `base_la_parent1` la cach
    duy nhat de moi luot CI that tu tra loi cau hoi ay, thay vi suy dien.
    """
    import json
    out = tmp_path / "plan.json"
    rc = C.main(["--base-sha", kho_merge["base"], "--head-sha", "0" * 40,
                 "--merge-sha", kho_merge["merge"], "--out", str(out)])
    assert rc != 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["classification"] == C.BLOCK
    assert d["merge_parents"] == [kho_merge["base"], kho_merge["head"]], \
        "artifact mat parent quan sat duoc — luot BLOCK thanh vo dung"
    assert d["head_checkout"] == kho_merge["merge"]
    assert d["base_la_parent1"] is True


# ⚠️ Da GO ca `test_doi_chieu_sentinel_bao_do_khi_thieu_mot_nodeid`.
# No khang dinh so hoc tap hop tren HANG CUC BO `{"a","b","c"}`, khong import
# logic doi chieu that (logic ay nam trong heredoc cua `backend-test.yml`, khong
# import duoc tu day). Doi `CAN - got` -> `CAN & got` trong workflow thi no van
# XANH — tai-lieu-dang-test, khong phai guard.
# Bat bien ay nay duoc canh o `test_ci_test_visibility.py`, noi doc duoc YAML
# cua workflow: `test_cong_sentinel_dung_HIEU_tap_khong_dung_giao`.
