#!/usr/bin/env python3
"""Phan loai thay doi cua mot PR thanh ke hoach test — CHE DO SHADOW.

O PR nay classifier KHONG quyet dinh lat nao chay. No chi tinh mot ke hoach va
ghi ra artifact de doi chieu ve sau. Moi cong test hien hanh giu nguyen.

Ba luat fail-closed, moi luat ra doi tu mot lo da do duoc tren nguyen mau:

* Duong dan san pham KHONG khop mien nao => ``BROAD``. Khong bao gio => tap rong.
  Do that: ``Backend_FastAPI/scripts/`` la diem mu hoan toan, 3/100 PR cho ke
  hoach rong trong khi co cham backend.
* Cham chinh classifier / manifest / workflow cong => ``BROAD``. Nguyen mau tra
  ``DOMAIN`` hoac ``SKIP_BE`` cho 36/51 luot self-change — PR tu thu hep pham vi
  kiem tra chinh thu minh dang sua.
* Chinh sach doc ``base | head``. Chi doc head thi mot PR sua manifest co the tu
  mien tru ngay trong luot do.

Va hai luat ve du lieu vao:

* ``universe`` test lay o **HEAD**. Nguyen mau lay o BASE nen 0/104 tep test
  THEM MOI co the duoc chon, con tep da xoa thi van bi dua vao ke hoach.
* Rename la **mot** change record nhung **hai** duong dan: ca ``old_path`` lan
  ``new_path`` deu phai duoc phan loai.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Hang
# --------------------------------------------------------------------------

BROAD = "BROAD"
DOMAIN = "DOMAIN"
NO_BACKEND_IMPACT = "NO_BACKEND_IMPACT"
BLOCK = "BLOCK"

#: TOAN BO `.github/**` => BROAD. Khong chi workflows/actions/scripts.
#:
#: ⚠️ Do that: `.github/dependabot.yml` truoc day roi xuong `OTHER` ⇒
#: `NO_BACKEND_IMPACT`/0 test. Ma `dependabot.yml` doi phien ban phu thuoc — no
#: la mot trong nhung tep co suc pha hoai lon nhat kho nay. Bo may quyet dinh
#: khong chi la workflow: no gom moi thu dieu khien CI.
SELF_PREFIXES = (
    ".github/",
)

#: BE MAT BACKEND. Moi thu duoi `Backend_FastAPI/` **tru** cay test.
#:
#: ⚠️ Ban dau chi liet ke `{app,alembic,scripts}/`. Do (snapshot `7b02278c`,
#: 05-09-2026): mot so duong backend roi thang xuong `NO_BACKEND_IMPACT` voi ke
#: hoach RONG — trong do co `tests/fixtures/*.py` (nhieu tep test import),
#: `tests/security/ratelimit_wrong_order_allowlist.txt` (waiver BAO MAT),
#: `tests/VISIBILITY_LEDGER.yml`, `auth_model.conf`, `docker-entrypoint.sh`.
#:
#: ⚠️⚠️ Nhung mo thang ra `Backend_FastAPI/` lai de ra mot HOI QUY khac: tep test
#: cung thanh "duong san pham", nen mot PR CHI sua mot `test_*.py` chua map se
#: vap `unknown_backend_path` va ra BROAD — keo tron universe. Vi the cay test
#: duoc tach ra thanh be mat RIENG, xu ly o `_loai_be_mat`.
BACKEND_PREFIX = "Backend_FastAPI/"
TEST_PREFIX = "Backend_FastAPI/tests/"

#: BE MAT VAN HANH. Anh xa duoc mien; **khong anh xa thi BROAD**, khong phai
#: "thoi khong dong gop". Day la nhung be mat quyet dinh he thong CHAY THE NAO:
#: nginx, script deploy, compose, bien moi truong mau, E2E ha tang.
#:
#: ⚠️ Truoc day chung nam chung mot ro voi `frontend/` duoi ten `KNOWN`, va luat
#: cua ro do la "khong khop mien thi thoi". Nghia la go `scripts/` khoi
#: `infra.paths` se bien mot PR sua `scripts/deploy.sh` thanh
#: `NO_BACKEND_IMPACT`/0 test — im lang. Tach ro ra de mat mot anh xa la DO,
#: khong phai la yen lang.
OPS_PREFIXES = (
    "nginx/",
    "scripts/",
    "tests-e2e/",
)

OPS_RE = (
    re.compile(r"^docker-compose[^/]*\.ya?ml\Z"),
    re.compile(r"^\.env[^/]*\.example\Z"),
)

#: BE MAT AN TOAN — **allowlist tuong minh**, va la NGA DUY NHAT dan toi
#: `NO_BACKEND_IMPACT`. Anh xa duoc mien thi van chay mien do (vd
#: `frontend/src/types/finance.types.ts` -> `finance`); khong anh xa thi thoi.
#:
#: ⚠️ Day la cho de fail-open nhat trong ca tep. Chi them vao day thu nao CHUNG
#: MINH duoc la khong the anh huong backend. Moi thu KHONG co ten o day —
#: `.agent/`, `.dockerignore`, `dev.sh`, `seed_data_template.xlsx`, mot thu muc
#: dich vu moi — deu la `UNKNOWN` va deu BROAD.
SAFE_PREFIXES = (
    "frontend/",
    "Documents/",
)

SAFE_RE = (
    re.compile(r"^[^/]+\.md\Z"),
    re.compile(r"^LICENSE(\.[^/]+)?\Z"),
)

#: Goc hop le cho `paths:` cua manifest. `_khop_domain` CHI duoc tra cho ba be
#: mat `BACKEND`, `OPS`, `SAFE`; mot `paths:` tro toi `.github/**` (SELF) hay
#: `Backend_FastAPI/tests/**` (TEST_FILE/TEST_SHARED) la NO-OP IM LANG —
#: manifest hop le, cong xanh, va khong tac dung gi. Do that: them `Documents/`
#: vao `infra.paths` khi `Documents/` con o `OTHER` thi khong doi gi ca.
GOC_TIEN_TO_HOP_LE = (
    (BACKEND_PREFIX,) + OPS_PREFIXES + SAFE_PREFIXES + ("docker-compose", ".env")
)

#: ⚠️ `$` khop CA TRUOC `\n` cuoi chuoi — do that: `kiem_sha("a"*40 + "\n")` bi
#: CHAP NHAN. Phai dung `\Z` (hoac `fullmatch`) de "40 hex, khong gi khac" dung
#: nghia den. Cung lop voi lo `<40hex>^{tree}`.
SHA_RE = re.compile(r"^[0-9a-f]{40}\Z")

#: Tam tep co hanh vi pha trang thai toan cuc. Bang chung hien co (doc tinh +
#: ket qua nightly 12 lat) CHI du de goi chung la ung vien. Chay per-PR la dong
#: cu khac — chinh chien dich nightly da cho thay doi dong cu lam lo loi tiem an.
CANDIDATE_FOR_ISOLATED_PER_PR = (
    "Backend_FastAPI/tests/unit/test_vn_school_search.py",
    "Backend_FastAPI/tests/security/test_websocket_security.py",
    "Backend_FastAPI/tests/api/test_admission_submit_requires_verified_docs.py",
    "Backend_FastAPI/tests/unit/test_fixture_enum_coverage.py",
    "Backend_FastAPI/tests/utils/test_config_loading.py",
    "Backend_FastAPI/tests/unit/test_m_p0a_selected_subject_group_id.py",
    "Backend_FastAPI/tests/unit/test_phase1_19c5_lowercase_migration.py",
    "Backend_FastAPI/tests/unit/test_null_orphan_tpl_admission_reminder_migration.py",
)

ISOLATION_HOP_LE = {"shared", "dedicated", "oneoff"}


class LoiManifest(Exception):
    """Manifest sai luoc do. Luon fail-closed — khong bao gio tra ``{}``."""


class LoiDiff(Exception):
    """Khong doc duoc diff. Khac han 'diff rong vi PR khong doi gi'."""


# --------------------------------------------------------------------------
# YAML — loader tu choi khoa trung
# --------------------------------------------------------------------------

class _LoaderNghiemNgat(yaml.SafeLoader):
    """``yaml.safe_load`` NUOT IM LANG khoa trung va giu ban cuoi.

    Do tren PyYAML 6.0.3: mot mapping khai ``finance`` hai lan nap ra MOT
    domain, khong loi, khong canh bao. Ba domain khai bao chi con hai.
    """


def _map_khong_trung(loader, node, deep=False):
    ket_qua = {}
    for khoa_node, gia_tri_node in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in ket_qua:
            raise LoiManifest("khoa trung trong manifest: %r" % (khoa,))
        ket_qua[khoa] = loader.construct_object(gia_tri_node, deep=deep)
    return ket_qua


_LoaderNghiemNgat.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _map_khong_trung
)


def _la_chuoi_that(v) -> bool:
    # ``owner: NO`` -> False (Norway). ``owner: 2026-09-04`` -> datetime.date.
    return type(v) is str and v.strip() != ""


def _la_so_that(v) -> bool:
    # ``isinstance(True, int)`` la True => phai dung ``type(...) is``.
    # ``090`` -> chuoi; ``017`` -> 15 (bat phan); ``12:30`` -> 750 (luc thap phan).
    return type(v) in (int, float) and v > 0


KHOA_BAT_BUOC = ("paths", "tests", "isolation", "expected_seconds",
                 "critical", "owner", "reason")


def nap_manifest(text: str) -> dict:
    """Nap va **xac thuc** manifest. Sai luoc do => nem, khong tra rong."""
    try:
        doc = yaml.load(text, Loader=_LoaderNghiemNgat)
    except LoiManifest:
        raise
    except yaml.YAMLError as e:
        raise LoiManifest("manifest khong phai YAML hop le: %s" % (e,))

    if doc is None:
        # Manifest TON TAI nhung rong KHONG phai bootstrap. Bootstrap la khi tep
        # khong ton tai va `ls-tree` xac nhan dieu do. Tra `{}` o day bien mot
        # manifest bi cat trang thanh "khong co mien nao" — fail-open cam.
        raise LoiManifest("manifest ton tai nhung RONG — day khong phai bootstrap")
    if not isinstance(doc, dict) or "domains" not in doc:
        raise LoiManifest("manifest phai la mapping co khoa 'domains'")
    domains = doc["domains"]
    if not isinstance(domains, dict) or not domains:
        raise LoiManifest("'domains' phai la mapping khac rong")

    for ten, than in domains.items():
        if not _la_chuoi_that(ten):
            raise LoiManifest("ten domain phai la chuoi khac rong: %r" % (ten,))
        if not isinstance(than, dict):
            raise LoiManifest("domain %r phai la mapping" % (ten,))
        for khoa in KHOA_BAT_BUOC:
            if khoa not in than:
                raise LoiManifest("domain %r thieu khoa bat buoc %r" % (ten, khoa))
        for khoa in ("paths", "tests"):
            v = than[khoa]
            if not isinstance(v, list) or not v:
                raise LoiManifest("domain %r: %r phai la list khac rong" % (ten, khoa))
            for phan_tu in v:
                if not _la_chuoi_that(phan_tu):
                    raise LoiManifest(
                        "domain %r: %r chua phan tu khong phai chuoi: %r"
                        % (ten, khoa, phan_tu))
                if phan_tu.startswith("/") or ".." in phan_tu:
                    raise LoiManifest(
                        "domain %r: %r phai neo trong kho: %r" % (ten, khoa, phan_tu))
                if khoa == "paths":
                    _kiem_mot_paths(ten, phan_tu)
        if than["isolation"] not in ISOLATION_HOP_LE:
            raise LoiManifest(
                "domain %r: isolation phai thuoc %s, nhan %r"
                % (ten, sorted(ISOLATION_HOP_LE), than["isolation"]))
        if not _la_so_that(than["expected_seconds"]):
            raise LoiManifest(
                "domain %r: expected_seconds phai la so duong THAT (bool va chuoi "
                "deu bi tu choi), nhan %r (%s)"
                % (ten, than["expected_seconds"],
                   type(than["expected_seconds"]).__name__))
        if type(than["critical"]) is not bool:
            raise LoiManifest(
                "domain %r: critical phai la bool THAT, nhan %r (%s)"
                % (ten, than["critical"], type(than["critical"]).__name__))
        for khoa in ("owner", "reason"):
            if not _la_chuoi_that(than[khoa]):
                raise LoiManifest(
                    "domain %r: %r phai la chuoi khac rong, nhan %r (%s) — luu y "
                    "YAML ep 'NO'/'off' thanh bool"
                    % (ten, khoa, than[khoa], type(than[khoa]).__name__))
    return doc


# --------------------------------------------------------------------------
# Diff — parser may truot
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BanGhi:
    status: str
    path: str
    old_path: str | None = None

    @property
    def cac_duong_dan(self) -> tuple:
        """Rename la MOT record nhung HAI duong dan — phai phan loai ca hai."""
        if self.old_path:
            return (self.old_path, self.path)
        return (self.path,)


def phan_tich_name_status_z(raw: str):
    """Doc luong NUL cua ``git diff --name-status -z``.

    Khung truong KHONG dong nhat: ``A``/``M``/``D`` la 2 truong, con ``R``/``C``
    la **3** truong. Parser doc cap cung se lech pha tu record rename tro di va
    bien duong dan ke tiep thanh 'ma trang thai' — im lang danh roi tep.

    Git khong bao gio phat chu ``R`` tran; luon kem diem tuong dong (``R100``,
    ``R091``...). Vi the phai so ``st[0]``, khong so ``st ==``.
    """
    truong = [t for t in raw.split("\0") if t != ""]
    ban_ghi = []
    i = 0
    while i < len(truong):
        st = truong[i]
        if not st or not st[0].isalpha():
            raise LoiDiff("truong trang thai khong hop le o vi tri %d: %r" % (i, st))
        if st[0] in ("R", "C"):
            if i + 2 >= len(truong):
                raise LoiDiff("record %r thieu duong dan (can 3 truong)" % (st,))
            ban_ghi.append(BanGhi(st, truong[i + 2], truong[i + 1]))
            i += 3
        else:
            if i + 1 >= len(truong):
                raise LoiDiff("record %r thieu duong dan (can 2 truong)" % (st,))
            ban_ghi.append(BanGhi(st, truong[i + 1]))
            i += 2
    return ban_ghi


# --------------------------------------------------------------------------
# Phan loai — HAM THUAN
# --------------------------------------------------------------------------

@dataclass
class KeHoach:
    classification: str
    domains: list = field(default_factory=list)
    bundles: list = field(default_factory=list)
    selected_tests: list = field(default_factory=list)
    fallback_reasons: list = field(default_factory=list)
    change_record_count: int = 0
    block_reason: str = None
    sentinel: str = None


def _la_tep_test(p: str) -> bool:
    return (p.startswith(TEST_PREFIX)
            and p.rsplit("/", 1)[-1].startswith("test_")
            and p.endswith(".py"))


def _la_tu_thay_doi(p: str) -> bool:
    # ⚠️ `CONFTEST_RE` TUNG nam o day. Sau khi be mat `TEST_SHARED` ra doi,
    # `tests/**/conftest.py` da ra BROAD qua nhanh do roi, nen dieu kien conftest
    # o day thanh MA CHET: dot bien go no van cho 35 ca xanh vi phan loai khong
    # doi (chi nhan ly do doi). Go han de dot bien tren nhanh nay tro lai co
    # nghia, va de conftest duoc goi dung ten: ha tang test dung chung.
    return any(p.startswith(x) for x in SELF_PREFIXES)


#: BAY loai be mat. Moi duong dan roi vao DUNG MOT loai.
SELF = "self"                 # .github/**                                    -> BROAD
TEST_SHARED = "test_shared"   # trong cay test nhung KHONG phai test_*.py     -> BROAD
TEST_FILE = "test_file"       # test_*.py                                     -> chinh no
BACKEND = "backend"           # Backend_FastAPI/** ngoai cay test             -> mien; khong map => BROAD
OPS = "ops"                   # nginx/scripts/tests-e2e/compose/.env.example  -> mien; khong map => BROAD
SAFE = "safe"                 # frontend/, Documents/, *.md goc, LICENSE      -> mien neu map; khong thi thoi
UNKNOWN = "unknown"           # MOI THU CON LAI                               -> BROAD


def _loai_be_mat(p: str) -> str:
    """Phan loai MOT duong dan vao dung mot be mat.

    Thu tu quan trong: `SELF` truoc het (bo may quyet dinh dang doi thi ket qua
    cua no chua duoc kiem chung), roi cay test, roi backend, roi van hanh, roi
    allowlist an toan. **Khong co nhanh mac dinh im lang**: thu gi khong ten
    trong NAM nhom tren la `UNKNOWN`, va `UNKNOWN` keo BROAD.

    ⚠️ Ban truoc co be mat `OTHER` lam nhanh mac dinh, va `OTHER` **khong dong
    gop gi** ⇒ mot duong la nhu `new_worker/consumer.py` hay
    `.github/dependabot.yml` ra `NO_BACKEND_IMPACT`/0 test. Do la fail-OPEN: cai
    gia cua "khong biet" phai la chay THEM, khong phai chay IT hon.
    """
    if _la_tu_thay_doi(p):
        return SELF
    if p.startswith(TEST_PREFIX):
        # `test_*.py` chay chinh no; MOI THU KHAC trong cay test la ha tang dung
        # chung (fixtures, ledger, allowlist bao mat, du lieu mau) va phai BROAD.
        return TEST_FILE if _la_tep_test(p) else TEST_SHARED
    if p.startswith(BACKEND_PREFIX):
        return BACKEND
    if any(p.startswith(x) for x in OPS_PREFIXES):
        return OPS
    if any(rx.match(p) for rx in OPS_RE):
        return OPS
    if any(p.startswith(x) for x in SAFE_PREFIXES):
        return SAFE
    if any(rx.match(p) for rx in SAFE_RE):
        return SAFE
    return UNKNOWN


def _khop_domain(p: str, manifest: dict):
    ket_qua = []
    for ten, than in (manifest.get("domains") or {}).items():
        for mau in than["paths"]:
            # ``mau`` la TIEN TO, path la TOAN HANG. Khong bao gio dung pattern
            # TU path — kho co hang tram duong chua ``[...]`` va ``(...)``,
            # nen coi path la pattern se khop bua (snapshot `7b02278c`, 05-09-2026).
            if p == mau or p.startswith(mau):
                ket_qua.append(ten)
                break
    return ket_qua


def hop_chinh_sach(manifest_base: dict, manifest_head: dict) -> dict:
    """Hop ``base | head``. Noi long chi co hieu luc tu luot SAU."""
    hop = {"domains": {}}
    for nguon in (manifest_base, manifest_head):
        for ten, than in (nguon.get("domains") or {}).items():
            cu = hop["domains"].setdefault(
                ten, {"paths": [], "tests": [], "isolation": than["isolation"],
                      "expected_seconds": than["expected_seconds"],
                      "critical": than["critical"], "owner": than["owner"],
                      "reason": than["reason"]})
            for khoa in ("paths", "tests"):
                for v in than[khoa]:
                    if v not in cu[khoa]:
                        cu[khoa].append(v)
    return hop


def _tests_cua(domains, chinh_sach: dict, universe_head):
    """Chi chon tep CON TON TAI o HEAD — ke hoach tro tep da xoa lam pytest RC=4."""
    ra = set()
    for ten in domains:
        for t in chinh_sach["domains"][ten]["tests"]:
            for tep in universe_head:
                if tep == t or tep.startswith(t):
                    ra.add(tep)
    return sorted(ra)


def classify(records, manifest_base, manifest_head, universe_head,
             changed_files=None) -> KeHoach:
    """Ham THUAN. Khong I/O, khong git, khong mang."""
    universe_head = set(universe_head)
    chinh_sach = hop_chinh_sach(manifest_base, manifest_head)
    ke = KeHoach(classification=BLOCK, change_record_count=len(records))

    if changed_files is not None and len(records) != changed_files:
        # So RECORD voi ``changed_files`` — KHONG so so path duy nhat. Hai ben
        # dem hai don vi khac nhau; lech dung bang so rename. Phep nay con bat
        # duoc suy bien im lang cua git (``--no-renames`` / ``renameLimit``)
        # khi git van thoat 0.
        ke.block_reason = ("so change record (%d) khac PR.changed_files (%d) — "
                           "co the git da bo phat hien rename"
                           % (len(records), changed_files))
        ke.fallback_reasons.append("record_count_mismatch")
        return ke

    if not records:
        ke.block_reason = "diff rong — base ref sai, fetch qua nong, hoac parser hong"
        ke.fallback_reasons.append("empty_diff")
        return ke

    moi_duong_dan = []
    for r in records:
        moi_duong_dan.extend(r.cac_duong_dan)

    theo_loai = {}
    for p in moi_duong_dan:
        theo_loai.setdefault(_loai_be_mat(p), []).append(p)

    ten_domains = sorted((chinh_sach.get("domains") or {}).keys())

    def _broad(ly_do: str):
        ke.classification = BROAD
        ke.domains = ten_domains
        ke.bundles = ten_domains
        ke.selected_tests = sorted(universe_head)
        ke.fallback_reasons.append(ly_do)
        # BROAD ma than RONG la fail-open doi lot fail-closed. Universe rong chi
        # xay ra khi cay test bien mat — do la BLOCK, khong phai BROAD.
        if not ke.selected_tests:
            ke.classification = BLOCK
            ke.block_reason = "BROAD nhung universe HEAD rong — cay test bien mat?"
            ke.fallback_reasons.append("broad_universe_empty")
        return ke

    # (1) Bo may quyet dinh dang doi ⇒ ket qua cua no chua duoc luot nao kiem
    #     chung ⇒ khong co tu cach thu hep.
    if SELF in theo_loai:
        return _broad("self_change:" + ",".join(sorted(set(theo_loai[SELF]))))

    # (2) Ha tang test dung chung (fixtures, ledger, allowlist bao mat…). Mot
    #     tep trong `tests/fixtures/` duoc rat nhieu tep test import.
    if TEST_SHARED in theo_loai:
        return _broad("shared_test_surface:"
                      + ",".join(sorted(set(theo_loai[TEST_SHARED]))))

    # (3) Duong KHONG THUOC be mat nao ⇒ BROAD. Day la nga fail-closed cho moi
    #     thu chua ai phan loai: mot thu muc dich vu moi, mot tep cau hinh la,
    #     mot ha tang moi. Cai gia cua "khong biet" phai la chay THEM.
    #
    #     ⚠️ Phai dat TRUOC phep gan mien: mot PR tron `README.md` (SAFE) voi
    #     `new_worker/consumer.py` (UNKNOWN) khong duoc phep im lang chi vi nua
    #     dau an toan.
    if UNKNOWN in theo_loai:
        return _broad("unknown_repo_path:"
                      + ",".join(sorted(set(theo_loai[UNKNOWN]))))

    duong_backend = theo_loai.get(BACKEND, [])
    duong_ops = theo_loai.get(OPS, [])
    duong_safe = theo_loai.get(SAFE, [])
    duong_test = theo_loai.get(TEST_FILE, [])

    domains = set()
    chua_map = []
    for p in duong_backend:
        khop = _khop_domain(p, chinh_sach)
        if khop:
            domains.update(khop)
        else:
            chua_map.append(p)
    # BE MAT VAN HANH: khop mien thi keo mien; KHONG khop thi BROAD, khong phai
    # "thoi". Mat mot anh xa o day la mat guard, phai DO chu khong duoc yen lang.
    ops_chua_map = []
    for p in duong_ops:
        khop = _khop_domain(p, chinh_sach)
        if khop:
            domains.update(khop)
        else:
            ops_chua_map.append(p)
    # BE MAT AN TOAN: khop mien thi keo mien, khong khop thi THOI. Day la cho
    # mot PR sua UI hoac sua tai lieu khong keo tron backend.
    for p in duong_safe:
        domains.update(_khop_domain(p, chinh_sach))

    # (4) Duong BACKEND khong khop mien nao ⇒ BROAD. Chi ap cho backend: mot
    #     `test_*.py` chua map thi da co luat rieng o (7).
    if chua_map:
        return _broad("unknown_backend_path:" + ",".join(sorted(set(chua_map))))

    # (5) Duong VAN HANH khong khop mien nao ⇒ BROAD.
    if ops_chua_map:
        return _broad("unmapped_ops_path:" + ",".join(sorted(set(ops_chua_map))))

    # (6) Khong cham backend, khong cham tep test, khong keo mien nao ⇒ tuyen bo
    #     TUONG MINH la khong tac dong backend. Nga NAY chi con dat duoc khi MOI
    #     duong deu thuoc allowlist `SAFE` va khong duong nao anh xa mien —
    #     `UNKNOWN` da bi chan o (3), `OPS` chua map bi chan o (5).
    if not duong_backend and not duong_test and not domains:
        ke.classification = NO_BACKEND_IMPACT
        ke.sentinel = "no-backend-impact"
        return ke

    chon = set(_tests_cua(sorted(domains), chinh_sach, universe_head))
    # (7) Tep test bi sua/them/doi ten PHAI duoc chon — ke ca khi khong mien nao
    #     nhan no. Tep da XOA thi khong (no khong con o HEAD ⇒ pytest thoat ma 4).
    for p in duong_test:
        if p in universe_head:
            chon.add(p)

    if not chon:
        return _broad("empty_plan_guard")

    ke.classification = DOMAIN
    ke.domains = sorted(domains)
    ke.bundles = sorted(domains)
    ke.selected_tests = sorted(chon)
    if not ke.bundles:
        # DOMAIN ma `bundles` RONG la hop le nhung DE BI DOC NHAM: ke hoach chi
        # gom cac `test_*.py` bi sua (luat 5). Consumer o pha thang hang fan-out
        # theo `bundles` se dung 0 job trong khi nhan van la "DOMAIN". Danh dau
        # tuong minh de doc artifact khong phai suy.
        ke.fallback_reasons.append("test_only_self_select")
    return ke


# --------------------------------------------------------------------------
# Git plumbing — chi dung o CLI
# --------------------------------------------------------------------------

def _git(*args) -> str:
    return subprocess.run(("git",) + args, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def kiem_sha(sha: str) -> str:
    """40 hex, khong gi khac — truoc khi dua vao tham so git."""
    if not SHA_RE.match(sha or ""):
        raise LoiDiff("SHA khong hop le (can 40 ky tu hex thuong): %r" % (sha,))
    return sha


class LoiDinhDanh(Exception):
    """Ba SHA khong tao thanh mot merge commit hop le cua DUNG PR nay."""


def doc_parents(raw: str) -> list:
    """Doc danh sach parent tu **raw commit object** (`git cat-file -p <sha>`).

    Dinh dang commit object: cac dong tieu de (`tree`, `parent`*, `author`,
    `committer`, ...), MOT dong trong, roi den thong diep. Parents nam theo DUNG
    THU TU ghi trong object.

    ⚠️ Phai dung o dong trong dau tien. Mot thong diep commit hoan toan co the
    chua dong bat dau bang `parent ` (vd khi ai do dan raw object vao mo ta PR);
    doc ca tep se dem nham.

    ⚠️⚠️ Dung `cat-file` chu KHONG dung `rev-list`/`rev-parse ^1`: tren checkout
    NONG, graft cua `.git/shallow` lam phep duyet DUNG o bien va parent bi giau,
    trong khi byte cua chinh object van ghi du parent. Do la ly do ky thuat de
    chon `cat-file`, khong phai so thich.
    """
    if not raw.startswith("tree "):
        raise LoiDinhDanh(
            "object khong phai commit (khong bat dau bang 'tree '): %r"
            % raw[:60])
    ra = []
    for dong in raw.splitlines():
        if not dong.strip():
            break
        if dong.startswith("parent "):
            ra.append(dong[len("parent "):].strip())
    return ra


def kiem_dinh_danh_merge(base_sha: str, head_sha: str, merge_sha: str,
                         raw_merge: str, head_checkout: str) -> None:
    """Chung minh ba SHA thuoc CUNG MOT PR truoc khi tin bat ky phep diff nao.

    Hop dong cua `pull_request`: `github.sha` la commit merge tam
    (`refs/pull/N/merge`) voi DUNG hai cha, parent1 = dinh nhanh base,
    parent2 = dinh nhanh PR.

    Truoc do artifact chi GHI LAI ba SHA. Ghi lai khong phai chung minh: mot
    workflow truyen nham `head.sha` vao `--merge-sha`, mot re-run tren ref da
    doi, hay mot checkout khong phai merge deu cho ra ke hoach "hop le" tren mot
    cap cay KHAC voi cap ma cong dang noi toi.
    """
    for ten, gia_tri in (("base", base_sha), ("head", head_sha),
                         ("merge", merge_sha), ("HEAD checkout", head_checkout)):
        if not SHA_RE.match(gia_tri or ""):
            raise LoiDinhDanh("%s-sha khong phai 40 hex thuong: %r"
                              % (ten, gia_tri))

    if head_checkout != merge_sha:
        raise LoiDinhDanh(
            "checkout HEAD (%s) KHAC merge-sha (%s) — cay dang do khong phai "
            "cay ma ke hoach noi toi" % (head_checkout, merge_sha))

    parents = doc_parents(raw_merge)
    if len(parents) != 2:
        raise LoiDinhDanh(
            "merge-sha %s co %d parent, phai co dung 2 — day khong phai commit "
            "merge cua mot PR (%r)" % (merge_sha, len(parents), parents))
    if parents[0] != base_sha:
        raise LoiDinhDanh(
            "parent1 cua merge la %s, khac base-sha %s" % (parents[0], base_sha))
    if parents[1] != head_sha:
        raise LoiDinhDanh(
            "parent2 cua merge la %s, khac head-sha %s" % (parents[1], head_sha))


def doc_raw_commit(sha: str) -> str:
    """Byte cua chinh commit object. `--no-replace-objects` de mot `refs/replace`
    khong the dung ra mot cha khac."""
    return _git("--no-replace-objects", "cat-file", "-p", kiem_sha(sha))


def head_dang_checkout() -> str:
    return _git("rev-parse", "HEAD").strip()


def doc_diff(base: str, merge: str):
    kiem_sha(base)
    kiem_sha(merge)
    # ``-c diff.renames=true`` + ``-M`` ghim HAI lop: config kho co the dat
    # ``diff.renames=copies`` va lat hanh vi sau lung.
    raw = _git("-c", "diff.renames=true", "diff", "--name-status", "-z", "-M",
               base, merge)
    return phan_tich_name_status_z(raw)


def duong_dan_co_trong_cay(sha: str, duong: str) -> bool:
    """``ls-tree`` tra 0 va output RONG cho duong dan khong co — nen 'khong ton
    tai' phan biet duoc rach roi voi 'git hong'. Nhap nhang hai ca do chinh la
    cach fail-open len vao."""
    kiem_sha(sha)
    return _git("ls-tree", "--name-only", sha, "--", duong).strip() != ""


def nap_manifest_tai(sha: str, duong: str, cho_phep_vang: bool = False) -> dict:
    """Nap manifest tai mot SHA.

    ``cho_phep_vang`` CHI duoc bat cho BASE (ca bootstrap: PR dau tien them
    manifest). Manifest o HEAD **bat buoc ton tai** — thieu no nghia la duong
    ``--manifest`` sai, hoac ai do vua xoa manifest, va ca hai deu phai do.
    """
    kiem_sha(sha)
    if not duong_dan_co_trong_cay(sha, duong):
        # ``ls-tree`` tra 0 va output RONG cho duong khong co, nen "khong ton
        # tai" phan biet duoc rach roi voi "git hong".
        if cho_phep_vang:
            return {"domains": {}}
        raise LoiManifest(
            "manifest %r KHONG ton tai o %s — duong --manifest sai, hoac manifest "
            "vua bi xoa. Chi BASE moi duoc phep vang (ca bootstrap)." % (duong, sha[:8]))
    return nap_manifest(_git("show", "%s:%s" % (sha, duong)))


def dem_phu_song(manifest: dict, universe_head) -> dict:
    """Do CHIEU XUOI: bao nhieu tep test duoc mot mien nao do nhan.

    `kiem_selector_manifest` va `kiem_paths_manifest` kiem hai chieu cua
    MANIFEST (selector/paths co khop duong that khong). Phep nay do mot thu
    khac: phan cay test **khong mien nao nhan**. Mot tep MO COI chi chay khi bi
    sua: PR sua `fee_repository.py` se khong keo no vao, im lang, xanh. Do la
    dung hinh dang `ci-allowlist-tep-khong-duoc-gac`, chi doi co che.

    ⚠️ KHONG chep con so hien thoi vao day. Census la dai luong DONG; mot con so
    go tay trong comment se cu the them mot chut moi tuan cho toi khi no sai han.
    Ba truong `test_universe_count` / `test_covered_count` / `test_orphan_count`
    duoc SINH moi luot va di vao artifact — do la noi duy nhat con so duoc phep
    song, va la co so de quyet `PROMOTION_CRITERION` bang do luong.
    """
    uni = set(universe_head)
    phu = set()
    for than in (manifest.get("domains") or {}).values():
        for mau in than["tests"]:
            phu |= {u for u in uni if u == mau or u.startswith(mau)}
    return {"test_universe_count": len(uni),
            "test_covered_count": len(phu),
            "test_orphan_count": len(uni - phu)}


def _la_mau_cay_test(mau: str) -> bool:
    """`mau` chi co the khop nhung duong NAM TRONG cay test?

    ⚠️ Phep cu la `mau.startswith(TEST_PREFIX)`, lech dung MOT ky tu:
    `Backend_FastAPI/tests` (khong dau `/` cuoi) duoc CHAP NHAN, khop hang tram
    tep that, va **khong tep nao** di qua `_khop_domain` — no-op im lang. Ma dang
    khong-dau-gach chinh la dang nguoi viet se go: van phong cua manifest bo dau
    `/` cuoi o moi selector (`.../test_auth`, `.../app/services/admission`).

    Chieu nguoc lai cung phai dung: `Backend_FastAPI/` la mot `paths:` HOP LE
    (anh xa ca backend), nen khong duoc tu choi chi vi `TEST_PREFIX` bat dau
    bang no.
    """
    if mau.startswith(TEST_PREFIX):
        return True
    return (TEST_PREFIX.startswith(mau)
            and mau.startswith(BACKEND_PREFIX)
            and len(mau) > len(BACKEND_PREFIX))


def _kiem_mot_paths(ten_domain: str, mau: str) -> None:
    """Mot `paths:` chi hop le khi no NAM TREN be mat duoc tra mien.

    `_khop_domain` chi duoc goi cho `BACKEND`, `OPS`, `SAFE`. Mot `paths:` tro
    toi `.github/**` (SELF) hay cay test la NO-OP IM LANG: manifest hop le, cong
    xanh, khong tac dung gi.

    ⚠️ Phep cu la mot danh sach TIEN TO go tay, va no lech voi `_loai_be_mat`:
    `SAFE_RE` bien `CLAUDE.md` thanh be mat duoc tra mien, nhung danh sach tien
    to lai TU CHOI khai `CLAUDE.md` trong `paths:`. Hai hang so mau thuan nhau
    ⇒ mot fail-open (0 test cho mot tep runbook ma guard doc that) khong the va
    duoc bang manifest. Nay hoi thang `_loai_be_mat` — MOT nguon chuan.
    """
    if _la_mau_cay_test(mau):
        raise LoiManifest(
            "domain %r: paths %r nam trong cay TEST — cay test co luat rieng "
            "(TEST_FILE/TEST_SHARED), khong bao gio di qua phep khop mien. "
            "Dat o day la no-op im lang." % (ten_domain, mau))
    if _loai_be_mat(mau) in (BACKEND, OPS, SAFE):
        return
    # `mau` la TIEN TO, nen no co the chua phai mot duong hoan chinh:
    # `docker-compose` chua khop `OPS_RE` (thieu `.yml`) nhung `docker-compose.yml`
    # thi khop. Chap nhan khi mau la tien to cua mot be mat duoc tra mien.
    for goc in GOC_TIEN_TO_HOP_LE:
        if goc.startswith(mau) or mau.startswith(goc):
            return
    raise LoiManifest(
        "domain %r: paths %r khong nam tren be mat nao duoc tra mien "
        "(BACKEND, OPS hoac SAFE) — `_loai_be_mat` tra %r. Them vao day khong "
        "co tac dung; muon dung thi phai mo rong OPS_PREFIXES/OPS_RE hoac "
        "SAFE_PREFIXES/SAFE_RE truoc."
        % (ten_domain, mau, _loai_be_mat(mau)))


def kiem_paths_manifest(manifest: dict, moi_duong) -> None:
    """CHIEU XUOI: moi `paths:` phai khop it nhat MOT duong co that o HEAD.

    Doi xung voi `kiem_selector_manifest`. Khong co phep nay thi mot `paths:` go
    sai (`.../services/admision` thieu chu `s`) van hop le, khop 0 tep, va mien
    do **lang le ngung bat**: moi thu roi ve `unknown_backend_path`/BROAD. An
    toan, nhung cam — mien van "song" tren giay trong khi thuc te da chet.
    """
    moi_duong = set(moi_duong)
    hong = []
    for ten, than in (manifest.get("domains") or {}).items():
        for mau in than["paths"]:
            if not any(d == mau or d.startswith(mau) for d in moi_duong):
                hong.append("%s: %s" % (ten, mau))
    if hong:
        raise LoiManifest(
            "cac `paths:` sau khong khop duong nao o HEAD (manifest da cu, hoac "
            "go sai): %s" % ", ".join(sorted(hong)))


def kiem_selector_manifest(manifest: dict, universe_head) -> None:
    """Moi mau trong ``tests:`` phai khop it nhat MOT tep o HEAD.

    Mot selector go sai khien pytest thu 0 ca cho bundle do — va do lai la
    **xanh**. Day dung hinh dang `ci-allowlist-tep-khong-duoc-gac`, chi doi cho.
    """
    universe_head = set(universe_head)
    hong = []
    for ten, than in (manifest.get("domains") or {}).items():
        for mau in than["tests"]:
            if not any(t == mau or t.startswith(mau) for t in universe_head):
                hong.append("%s -> %s" % (ten, mau))
    if hong:
        raise LoiManifest(
            "selector `tests:` khong khop tep nao o HEAD (go sai, hoac tep da "
            "doi ten/bi xoa ma manifest chua duoc cap nhat cung PR). Sua "
            "`.github/scripts/domains.yml`: " + "; ".join(hong))


def universe_tat_ca_tai(sha: str):
    """MOI duong tracked o `sha` — dung cho phep kiem chieu XUOI cua `paths:`."""
    kiem_sha(sha)
    return {d.strip() for d in _git("ls-tree", "-r", "--name-only", sha).splitlines()
            if d.strip()}


def universe_tai(sha: str):
    kiem_sha(sha)
    ra = set()
    for d in _git("ls-tree", "-r", "--name-only", sha, "--", TEST_PREFIX).splitlines():
        d = d.strip()
        if _la_tep_test(d):
            ra.add(d)
    return ra


def _sha256_tep(p: str) -> str:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shadow classifier — chi in ke hoach")
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--merge-sha", required=True)
    ap.add_argument("--manifest", default=".github/scripts/domains.yml")
    ap.add_argument("--changed-files", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--pr-number", default="")
    ap.add_argument("--head-sha", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--run-attempt", default="")
    ap.add_argument("--event", default="")
    # ⚠️ Kiem dinh danh MAC DINH BAT. Co duy nhat mot ngã tat: `--khong-kiem-dinh-danh`,
    # danh cho chay tay ngoai ngu canh merge cua PR (vd doi chieu hai commit bat
    # ky). Workflow KHONG duoc phep truyen no, va dieu do duoc khoa bang neo
    # `test_workflow_shadow_khong_tat_kiem_dinh_danh` o
    # `tests/unit/test_ci_test_visibility.py` — mot tep o cay khac.
    ap.add_argument("--khong-kiem-dinh-danh", action="store_true",
                    help="BO QUA chung minh ba SHA cung mot PR. Chi dung khi "
                         "chay tay; CI khong bao gio duoc dung.")
    a = ap.parse_args(argv)

    records = []
    phu_song = {}
    # ⚠️ QUAN SAT, khong phai khang dinh. Do that tren 23 PR MO con merge ref
    # (agent doc-only, 05-09-2026): `parent2 == head.sha` dung 23/23, nhung
    # `parent1 == base.sha` chi dung **1/23**. Co che: `refs/pull/N/merge` mang
    # parent1 = dinh SONG cua nhanh base va duoc GitHub DUNG LAI theo yeu cau
    # (18/23 ref doi SHA trong 9 phut), con `base.sha` la anh chup DONG CUNG tai
    # `opened`/`synchronize` gan nhat. Cap trong CUNG mot payload webhook duoc
    # ky vong nhat quan — nhung dieu do CHUA duoc do. Ba truong duoi day de moi
    # luot CI that tu dung corpus tra loi, thay vi suy dien.
    quan_sat = {"merge_parents": [], "head_checkout": ""}
    try:
        # (0) Chung minh ba SHA thuoc CUNG MOT PR **truoc** khi tin bat ky phep
        #     diff nao. Ghi lai ba SHA vao artifact khong phai chung minh.
        if not a.khong_kiem_dinh_danh:
            raw_merge = doc_raw_commit(a.merge_sha)
            # Ghi lai TRUOC khi kiem: mot luot BLOCK vi dinh danh la luot mang
            # nhieu thong tin nhat, va `merge_parents` la thu duy nhat noi duoc
            # merge ref dang tro vao dau.
            quan_sat["merge_parents"] = doc_parents(raw_merge)
            quan_sat["head_checkout"] = head_dang_checkout()
            kiem_dinh_danh_merge(a.base_sha, a.head_sha, a.merge_sha,
                                 raw_merge, quan_sat["head_checkout"])
        records = doc_diff(a.base_sha, a.merge_sha)
        uni = universe_tai(a.merge_sha)
        # BASE duoc phep vang (bootstrap); HEAD thi khong.
        mb = nap_manifest_tai(a.base_sha, a.manifest, cho_phep_vang=True)
        mh = nap_manifest_tai(a.merge_sha, a.manifest, cho_phep_vang=False)
        kiem_selector_manifest(mh, uni)
        kiem_paths_manifest(mh, universe_tat_ca_tai(a.merge_sha))
        phu_song = dem_phu_song(mh, uni)
        ke = classify(records, mb, mh, uni, changed_files=a.changed_files)
    except Exception as e:  # noqa: BLE001 — co y bat RONG, xem ghi chu duoi
        # ⚠️ Ban dau chi bat `(LoiDiff, LoiManifest, CalledProcessError)`. Ba nga
        # do that van xuyen qua: `UnicodeDecodeError` tu `_git(..., text=True)`
        # khi diff chua ten tep khong phai UTF-8, `OSError` khi ghi `--out`, va
        # bat ky loi lap trinh nao. Xuyen qua = traceback = **khong co artifact**,
        # dung luot can dieu tra nhat lai la luot khong de lai gi. Bat rong roi
        # ghi `exception:<Ten>` vao `fallback_reasons` giu duoc ca hai: van do
        # (RC=1) va van co chan doan.
        ke = KeHoach(classification=BLOCK, block_reason="%s: %s" % (type(e).__name__, e))
        ke.fallback_reasons.append("exception:" + type(e).__name__)
        ke.change_record_count = len(records)
        # Loai da luong truoc (`LoiDinhDanh`, `LoiDiff`, `LoiManifest`,
        # `CalledProcessError`) chi can thong diep. Moi loai KHAC la loi lap
        # trinh: in nguyen traceback ra stderr, vi `block_reason` mot dong
        # khong du de sua no.
        if not isinstance(e, (LoiDinhDanh, LoiDiff, LoiManifest,
                              subprocess.CalledProcessError)):
            traceback.print_exc(file=sys.stderr)
        # ⚠️ KHONG xoa `records`. Ban dau dat `records = []` o day, va do that:
        # mot manifest go sai selector cho ra JSON `records: []` /
        # `change_record_count: 0` — KHONG phan biet duoc voi "diff rong", dung
        # thu ma phep so voi `changed_files` dung ra de phan biet.

    ra = {
        "schema_version": 1,
        "pr_number": a.pr_number,
        "event": a.event,
        "base_sha": a.base_sha,
        "head_sha": a.head_sha,
        "merge_sha": a.merge_sha,
        "run_id": a.run_id,
        "run_attempt": a.run_attempt,
        "classifier_sha256": _sha256_tep(__file__),
        "manifest_sha256": _sha256_tep(a.manifest),
        "change_record_count": ke.change_record_count,
        "records": [{"status": r.status, "path": r.path, "old_path": r.old_path}
                    for r in records],
        "classification": ke.classification,
        "domains": ke.domains,
        "bundles": ke.bundles,
        "selected_tests": ke.selected_tests,
        "fallback_reasons": ke.fallback_reasons,
        "block_reason": ke.block_reason,
        "sentinel": ke.sentinel,
        "candidate_for_isolated_per_pr": list(CANDIDATE_FOR_ISOLATED_PER_PR),
    }
    # Do luong cho tieu chi thang hang — SHADOW chi do, khong chan.
    ra.update(phu_song)
    ra.update(quan_sat)
    ra["base_la_parent1"] = (bool(quan_sat["merge_parents"])
                             and quan_sat["merge_parents"][0] == a.base_sha)
    # ⚠️ GIOI HAN THAT, noi cho dung: chan doan chi ton tai khi **con ghi
    # duoc**. Ba nga duoi day KHONG co artifact, va khong cach nao lam khac:
    #
    #   * `json.dumps` nem (kieu khong serialize duoc do mot loi lap trinh);
    #   * `write_text` nem (`OSError`: dia day, khong co quyen, duong dan sai);
    #   * runner sap hoac lượt bi cancel giua chung.
    #
    # Ca ba deu cho RC khac 0 (hoac job chet han), nen cong VAN do — nhung dung
    # noi "moi BLOCK deu co artifact". Cau dung la: **ngoai le xay ra TRUOC buoc
    # ghi va con ghi duoc thi co chan doan**. Chinh vi the buoc upload giu
    # `if: always()` + `if-no-files-found: error`: khong co tep thi ĐỎ, khong
    # phai bo qua im lang.
    try:
        text = json.dumps(ra, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        print("::error::khong serialize duoc ke hoach thanh JSON", file=sys.stderr)
        return 1

    if a.out:
        try:
            Path(a.out).write_text(text + "\n", encoding="utf-8")
        except OSError:
            traceback.print_exc(file=sys.stderr)
            print("::error::khong ghi duoc %r — luot nay khong de lai chan doan"
                  % a.out, file=sys.stderr)
            return 1
    print(text)

    # SHADOW nghia la ket qua PHAN LOAI khong quyet dinh lat nao chay — KHONG
    # nghia la moi ket cuc deu RC=0. Ba nhan hop le (DOMAIN/BROAD/
    # NO_BACKEND_IMPACT) => 0. BLOCK, loi dinh danh, loi git, loi manifest, diff
    # lech `changed_files` => KHAC 0, de buoc job do thay vi xanh cam.
    if ke.classification == BLOCK:
        print("::error::classifier khong sinh duoc ke hoach hop le: %s"
              % (ke.block_reason or "khong ro"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
