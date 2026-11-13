# -*- coding: utf-8 -*-
"""F237 (Codex lần 9 — lượt H): NGỮ PHÁP policy của cờ quyền văn bản Hội đồng, quyết theo
matcher THẬT. Không CSDL, không mạng.

* Hàm khớp lấy từ enforcer dựng bằng ĐÚNG ``auth_model.conf`` của mã (thư viện casbin cài trong
  image) — ``enforcer.fm.get_functions()["keyMatch4"]``, cùng cách ``deps`` lấy lúc tính cờ.
* Đường route lấy từ bảng route THẬT của app (``ENDPOINT_THEO_CO``).
* Hai chiều Codex nêu: LỌT (dòng phụ thuộc id phải làm tắt cờ) và TẮT NHẦM (dòng không phụ thuộc id
  — kể cả chỉ đổi tên tham số — không được làm tắt cờ).
* Một ca so quyết định của guard với VÉT CẠN bằng hàm khớp thật trên một tập id rộng hơn tập thử
  của guard, trên một kho mẫu sinh từ route thật.

Mỗi ca một bất biến (CLAUDE.md §3). Ngữ pháp + chứng minh: khối chú thích F237 trong
``app/core/deps.py`` và SPEC phụ lục H.
"""
import itertools
import re
from pathlib import Path

import casbin
import pytest
from casbin.model import Model
from fastapi.routing import APIRoute
from starlette.requests import Request

from app.casbin_config.policy_templates import POLICY_TEMPLATES
from app.core import deps
from app.main import fastapi_app
from app.routers import council_documents as rt

pytestmark = pytest.mark.unit

MO_HINH = Path(__file__).resolve().parents[2] / "auth_model.conf"
P = "/api/admission-config/council-documents"


def _enforcer(matcher=None):
    """Enforcer đồng bộ, không adapter, model = ĐÚNG ``auth_model.conf`` (``matcher`` ⇒ thay
    dòng ``m = …`` để đo nhánh matcher khác)."""
    chu = MO_HINH.read_text(encoding="utf-8")
    if matcher is not None:
        chu, n = re.subn(r"(?m)^m = .*$", "m = " + matcher, chu)
        assert n == 1, "phép đo không hợp lệ: không thay được dòng matcher"
    m = Model()
    m.load_model_from_text(chu)
    return casbin.Enforcer(m)


ENF = _enforcer()
HAM_KHOP = ENF.fm.get_functions()["keyMatch4"]
DUONG = sorted(
    {
        r.path
        for r in fastapi_app.routes
        if isinstance(r, APIRoute) and r.endpoint in set(rt.ENDPOINT_THEO_CO.values())
    }
)


def ly_do(doi_tuong):
    return deps.ly_do_policy_ngoai_hop_dong(doi_tuong, DUONG, HAM_KHOP)


def _yeu_cau():
    return Request({"type": "http", "app": fastapi_app, "headers": []})


def _ngoai_mau(enf):
    return deps._policy_ngoai_mau_route(_yeu_cau(), enf, rt.ENDPOINT_THEO_CO)


# ═══════════════════════════ neo: phép đo có nghĩa ═══════════════════════════════════════
def test_neo_route_cua_module_co_route_hai_tham_so():
    # Các ca "vị trí tham số độc lập" chỉ có nghĩa khi module có route HAI tham số.
    assert P + "/sets/{set_id}/files/{thu_tu}" in DUONG
    assert all(p.startswith(P + "/") for p in DUONG) and len(DUONG) >= 7


def test_matcher_cua_auth_model_dung_chuoi_ngu_phap_viet_cho():
    # Đổi matcher trong auth_model.conf mà không xét lại ngữ pháp ⇒ đỏ ở đây (và lúc chạy: mọi
    # cờ tắt — ca ``test_matcher_khac_thi_moi_dong_bi_coi_vi_pham``).
    that = ENF.get_model()["m"]["m"].value
    assert "".join(that.split()) == "".join(deps.MATCHER_CO_VAN_BAN_HOI_DONG.split())


# Ngữ nghĩa của hàm khớp mà ngữ pháp dựa vào (đo trên thư viện THẬT — đổi phiên bản casbin
# làm lệch ⇒ đỏ, phải xét lại ngữ pháp).
@pytest.mark.parametrize(
    "duong,doi_tuong,mong",
    [
        ("/a/sets/57/files/9", "/a/*", True),  # "/*" ⇒ ".*" vượt nhiều đoạn
        ("/a/sets", "/a/sets/*", False),  # "/*" cần "/" thật trước nó
        ("/a/sets/57", "/a/sets/{id}", True),  # {tên} = một đoạn
        ("/a/sets/57/files", "/a/sets/{id}", False),
        ("/a/sets/2/files/2", "/a/sets/{id}/files/{id}", True),  # tên lặp ⇒ phải bằng
        ("/a/sets/57/files/2", "/a/sets/{id}/files/{id}", False),
        ("/a/sets/57", "/a/sets/:id", False),  # ":id" là CHỮ với keyMatch4
        ("/a/sets/57", "/x|.*sets/57", True),  # "|" thoát khỏi neo "^"
        ("/a/sets/57", "/a/sets/5.", True),  # "." là ký tự bất kỳ
    ],
)
def test_ngu_nghia_ham_khop_that_dung_nhu_ngu_phap_mo_ta(duong, doi_tuong, mong):
    assert HAM_KHOP(duong, doi_tuong) is mong


# ═══════════════════════════ chiều LỌT: dòng phụ thuộc id phải bị bắt ═════════════════════
def test_deny_bo_57_tep_sao_la_phu_thuoc_id():
    # Đúng ví dụ Codex lần 9: đuôi "*" KHÔNG làm dòng độc lập với id.
    assert ly_do(P + "/sets/57/files/*") == "phu_thuoc_id"


def test_allow_theo_id_cu_the_khac_1_la_phu_thuoc_id():
    assert ly_do(P + "/sets/57") == "phu_thuoc_id"


def test_id_cu_the_ngoai_tap_thu_co_dinh_van_bi_bat():
    # 12345 không thuộc {1, 57, 2147483647}: giá trị thử phải lấy cả từ CHÍNH dòng policy.
    assert "12345" not in deps.ID_DO_CO_DINH
    assert ly_do(P + "/sets/12345/ma-ho-so") == "phu_thuoc_id"


def test_tham_so_o_tien_to_la_phu_thuoc_id():
    # Không bắt đầu bằng tiền tố module ("/api/{m}/…") mà vẫn khớp route của module.
    assert ly_do("/api/{m}/council-documents/sets/57") == "phu_thuoc_id"


def test_sao_o_tien_to_la_phu_thuoc_id():
    assert ly_do("/api/*/sets/57") == "phu_thuoc_id"


def test_gop_hai_tham_so_mot_ten_la_phu_thuoc_id():
    # keyMatch4: tên lặp ⇒ chỉ khớp khi số bộ = số thứ tự tệp. Thử MỘT giá trị cho mọi vị trí
    # (như đường mẫu toàn số 1) không thấy được.
    assert ly_do(P + "/sets/{id}/files/{id}") == "phu_thuoc_id"


def test_id_o_vi_tri_tham_so_thu_hai_la_phu_thuoc_id():
    assert ly_do(P + "/sets/{set_id}/files/7") == "phu_thuoc_id"


@pytest.mark.parametrize(
    "doi_tuong",
    [P + "/sets/5[0-9]", P + "/sets/57+", "(?i)" + P + "/sets/57", P + "/sets*"],
    ids=["lop_ky_tu", "luong_tu", "co_noi_dong", "sao_dinh_chu"],
)
def test_ngoai_ngu_phap_co_the_khop_module_thi_vi_pham(doi_tuong):
    # Ngoài G: không chứng minh được độc lập với id ⇒ fail-closed (chủ ý — ghi trong ngữ pháp).
    assert ly_do(doi_tuong) == "ngoai_ngu_phap"


@pytest.mark.parametrize(
    "luong_tu, khop_that",
    [("?", True), ("*", True), ("+", False), ("{0}", False), ("{0,1}", False)],
    ids=["hoi", "sao", "cong", "ngoac_0", "ngoac_0_1"],
)
def test_luong_tu_ngay_sau_cho_lech_tien_to_thi_vi_pham(luong_tu, khop_that):
    # Lượt H2 (QH1 của người điều phối): lượng từ đứng NGAY SAU ký tự cuối trước chỗ lệch tiền tố module. "X?" / "X*"
    # làm X tuỳ chọn ⇒ dòng KHỚP route của module ⇒ khi so tiền tố phải bỏ ký tự trước lượng từ. "X+" và "{…}"
    # (keyMatch4 thay mọi "{…}" không có "/" bằng nhóm ⇒ KHÔNG phải lượng từ) đòi X ⇒ không khớp thật — vẫn vi phạm vì
    # bước 2 bảo thủ (ngữ pháp ghi: bỏ thêm một ký tự nếu là * + ? {).
    doi_tuong = (
        "/api/admission-config/council-documentsX" + luong_tu + "/sets/57/files/*"
    )
    assert HAM_KHOP(P + "/sets/57/files/1", doi_tuong) is khop_that  # ngữ nghĩa thật
    assert ly_do(doi_tuong) == "ngoai_ngu_phap"


def test_doi_tuong_khong_bat_dau_bang_gach_thi_ngoai_ngu_phap():
    # Lượt H2 (rà nhánh): phần trước "/" đầu tiên bị bỏ khi tách đoạn ⇒ nếu không đòi "/" ở đầu, nhìn trước phủ định
    # "(?!.*12345)" lọt vào G mà tập thử không có 12345 ⇒ dòng phụ thuộc id bị coi là độc lập. Ngữ nghĩa đo bằng hàm khớp thật.
    doi_tuong = "(?!.*12345)/api/*"
    assert HAM_KHOP(P + "/sets/57", doi_tuong) is True
    assert HAM_KHOP(P + "/sets/12345", doi_tuong) is False
    assert ly_do(doi_tuong) == "ngoai_ngu_phap"


def test_hai_tham_so_trong_mot_doan_ngoai_ngu_phap():
    # "{a}{b}" trong MỘT đoạn: cách tách tên khác nhau giữa các bản casbin (mẫu tham lam / không tham lam) ⇒ ngoài G.
    assert ly_do(P + "/sets/{a}{b}") == "ngoai_ngu_phap"


def test_nhanh_thay_the_thoat_neo_thi_vi_pham():
    # Phần chữ trước "|" là tiền tố module KHÁC, nhưng nhánh thứ hai khớp route của module.
    doi_tuong = "/api/leads|.*council-documents/sets/57"
    assert HAM_KHOP(P + "/sets/57", doi_tuong) is True  # phép đo hợp lệ
    assert ly_do(doi_tuong) == "ngoai_ngu_phap"


@pytest.mark.parametrize("doi_tuong", [None, 57])
def test_doi_tuong_khong_phai_chuoi_thi_vi_pham(doi_tuong):
    assert ly_do(doi_tuong) == "khong_phai_chuoi"


# ═══════════════════════════ chiều TẮT NHẦM: dòng độc lập id không bị bắt ═════════════════
@pytest.mark.parametrize(
    "doi_tuong",
    [P + "/sets/{id}", P + "/sets/{id}/files/{so}", P + "/sets/{bo}/ma-ho-so"],
)
def test_doi_ten_tham_so_khong_vi_pham(doi_tuong):
    assert ly_do(doi_tuong) is None


@pytest.mark.parametrize("doi_tuong", ["/*", "/api/*", "/api/{x}/council-documents/*"])
def test_ky_tu_dai_dien_rong_khong_vi_pham(doi_tuong):
    assert ly_do(doi_tuong) is None


@pytest.mark.parametrize(
    "doi_tuong",
    [P + "/sets/{set_id}", P + "/sets/*", P + "/*", P + "/sets/*/files/*"],
)
def test_mau_route_va_sao_cua_module_khong_vi_pham(doi_tuong):
    assert ly_do(doi_tuong) is None


@pytest.mark.parametrize(
    "doi_tuong",
    [
        "/api/files/report.pdf",
        "/api/leads/[0-9]+",
        "/api/admission-config/paths/{path_id}",
        "/api/admission-config/council-documents-cu/sets/57",
    ],
)
def test_module_khac_khong_vi_pham(doi_tuong):
    # Dòng của module khác (kể cả ngoài G) không thể khớp route của module ⇒ không tắt cờ.
    assert ly_do(doi_tuong) is None


def test_tham_so_kieu_keymatch2_la_chu_khong_vi_pham():
    # ":id" không phải tham số với keyMatch4: dòng không khớp route thật nào, đường mẫu cũng không
    # ⇒ cờ (hỏi bằng id 1) = hành vi thật ⇒ không có gì phải tắt.
    assert HAM_KHOP(P + "/sets/57", P + "/sets/:id") is False  # phép đo hợp lệ
    assert ly_do(P + "/sets/:id") is None


# ═══════════════════════════ đối chứng VÉT CẠN bằng hàm khớp thật ═══════════════════════
# Tập id vét cạn RỘNG hơn tập thử của guard (có số liền kề, số trùng nhau giữa hai vị trí);
# chứa mọi số chữ của kho mẫu (57, 12345, 7) ⇒ đủ cho kho mẫu theo cùng lập luận "kiểu giá trị".
ID_VET_CAN = ["1", "2", "3", "7", "56", "57", "58", "12345", "12346", "2147483647"]
LUA_CHON_DOAN = ["*", "{a}", "{b}", "57", "12345", "7"]


def _kho_mau():
    kho = set()
    for duong in DUONG:
        doan = duong.split("/")[1:]
        for k in (1, 2):
            for vi_tri in itertools.combinations(range(len(doan)), k):
                for chon in itertools.product(LUA_CHON_DOAN, repeat=k):
                    moi = list(doan)
                    for i, c in zip(vi_tri, chon):
                        moi[i] = c
                    kho.add("/" + "/".join(moi))
                    kho.add("/" + "/".join(moi) + "/*")
    return sorted(kho)


def _phu_thuoc_id_vet_can(doi_tuong):
    for duong in DUONG:
        doan = duong.split("/")[1:]
        vi_tri = [i for i, d in enumerate(doan) if d.startswith("{")]
        ket_qua = set()
        for bo in itertools.product(ID_VET_CAN, repeat=len(vi_tri)):
            cu_the = list(doan)
            for i, v in zip(vi_tri, bo):
                cu_the[i] = v
            ket_qua.add(bool(HAM_KHOP("/" + "/".join(cu_the), doi_tuong)))
        if len(ket_qua) > 1:
            return True
    return False


def test_quyet_dinh_bang_vet_can_tren_kho_mau_sinh_tu_route_that():
    kho = _kho_mau()
    lech = []
    dem = {"phu_thuoc_id": 0, None: 0}
    for doi_tuong in kho:
        mong = "phu_thuoc_id" if _phu_thuoc_id_vet_can(doi_tuong) else None
        that = ly_do(doi_tuong)
        dem[mong] = dem.get(mong, 0) + 1
        if that != mong:
            lech.append((doi_tuong, that, mong))
    # Kho phải có CẢ hai loại, nhiều ca mỗi loại — không thì phép so rỗng.
    assert dem["phu_thuoc_id"] >= 100 and dem[None] >= 100, dem
    assert lech == [], lech[:20]


# ═══════════════════════════ tầng đọc policy THẬT của enforcer (nối dây) ═════════════════
def test_policy_mau_cua_template_tren_enforcer_that_khong_vi_pham():
    # Đối chứng chiều tắt nhầm: MỌI dòng của MỌI template (kể cả "/*" của admin) ⇒ không vi phạm.
    enf = _enforcer()
    for mau in POLICY_TEMPLATES.values():
        for p in mau["policies"]:
            enf.add_policy(
                "role:x", p["object"], p.get("action", "GET"), p.get("eft", "allow")
            )
    assert len(enf.get_policy()) >= 100
    assert _ngoai_mau(enf) == []


def test_dong_deny_theo_id_bi_bat_khi_doc_policy_that():
    enf = _enforcer()
    enf.add_policy("role:accountant", P + "/sets/57/files/*", "GET", "deny")
    assert _ngoai_mau(enf) == [(P + "/sets/57/files/*", "phu_thuoc_id")]


def test_dong_allow_theo_id_bi_bat_khi_doc_policy_that():
    enf = _enforcer()
    enf.add_policy("role:manager", P + "/sets/12345", "GET", "allow")
    assert _ngoai_mau(enf) == [(P + "/sets/12345", "phu_thuoc_id")]


def test_matcher_khac_thi_moi_dong_bi_coi_vi_pham():
    # Ngữ pháp viết cho keyMatch4; matcher keyMatch2 (":id" là tham số) ⇒ ngữ pháp không còn đúng.
    enf = _enforcer(
        "g(r.sub, p.sub) && keyMatch2(r.obj, p.obj) && regexMatch(r.act, p.act)"
    )
    enf.add_policy("role:admin", "/*", ".*", "allow")
    assert _ngoai_mau(enf) == [("<matcher-khac>", "matcher_khac")]


def test_khong_doc_duoc_policy_thi_vi_pham(monkeypatch):
    enf = _enforcer()

    def hong():
        raise RuntimeError("giả: adapter hỏng")

    monkeypatch.setattr(enf, "get_policy", hong)
    assert _ngoai_mau(enf) == [("<khong-doc-duoc-policy>", "khong_doc_duoc_policy")]


def test_ham_khop_nem_loi_thi_vi_pham():
    # Hàm khớp ném lỗi khi thử ⇒ không chứng minh được độc lập id ⇒ fail-closed.
    def hong(duong, doi_tuong):
        raise RuntimeError("giả: hàm khớp hỏng")

    ly = deps.ly_do_policy_ngoai_hop_dong(P + "/sets/{id}", DUONG, hong)
    assert ly == "phu_thuoc_id"


def test_route_ngoai_dang_chu_tham_so_thi_vi_pham():
    # Bộ chuyển đổi ":path" cho giá trị chứa "/" ⇒ lập luận "ranh giới đoạn cố định" không còn.
    assert (
        deps.ly_do_policy_ngoai_hop_dong("/*", ["/x/{p:path}"], HAM_KHOP)
        == "route_ngoai_ngu_phap"
    )
