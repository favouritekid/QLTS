# -*- coding: utf-8 -*-
"""Khoá luật ignore cho bộ xuất hồ sơ chứa PII (`scripts/export-hoso-excel/`).

Kho `favouritekid/QLTS` là **PUBLIC**. Thư mục ``scripts/export-hoso-excel/`` là
bộ chạy tay trên dữ liệu THẬT của 969 hồ sơ: ngoài script còn có log chạy thật
(``out.txt``/``err.txt``), bản kê, và tài liệu bàn giao.

Đo 19-09-2026 TRÊN CHÍNH commit 87a68ae5, TRƯỚC bản vá: ``.gitignore`` có 386
dòng và ``grep -i export-hoso`` khớp **0 dòng**; dựng lại trong một repo tạm với
đúng bản ấy thì ``git add -An -- scripts/export-hoso-excel`` **VẪN CHỌN** tệp.
Thứ che được một phần chỉ là tình cờ: ``*.sql`` (dòng 90) và ``__pycache__/``
(dòng 6) — không quy tắc nào nhắm vào thư mục này.

Ba điều được khoá, và luật thứ ba là lý do tệp này tồn tại:

1. đường dẫn đại diện trong thư mục ấy **BỊ** ignore;
2. hàng xóm KHÔNG nhạy cảm (``scripts/deploy.sh``, ``scripts/nginx-apply.sh``,
   ``scripts/fe-check.sh``, …) **KHÔNG** bị ignore — đây là phép canh chống
   pattern quá rộng kiểu ``scripts/export*``, thứ sẽ biến một lỗ PII thành một
   lỗ "mã vận hành lặng lẽ rơi khỏi git";
3. ``git add -A --dry-run`` **không chọn** đường dẫn nhạy cảm nào, kể cả khi
   các tệp ấy CÓ THẬT trên đĩa.

⚠️ HAI CÁI BẪY ĐÃ TRẢ GIÁ, đừng "dọn gọn" chúng đi:

* ``git check-ignore -v`` gọi trên CHÍNH thư mục (``scripts/export-hoso-excel/``)
  đã được quan sát trả **rc=0 với trường pattern RỖNG**, trỏ một dòng trống của
  ``.gitignore`` — tức một phép kiểm XANH cho một thư mục KHÔNG hề được che.
  ⚠️ Quan sát ấy đến từ một NHÁNH KHÁC của kho; trên 87a68ae5 nó KHÔNG tái hiện
  (lệnh trả rc=1). Đừng trích nó như sự thật của commit này. Phòng thủ vẫn giữ
  vì nó rẻ: hỏi trên **từng tệp**, và bắt buộc **pattern khác rỗng**.
* ``check-ignore`` có **ba** mã thoát (0 = ignore, 1 = không, 128 = git lỗi).
  Viết ``returncode != 0`` để nghĩa là "không ignore" sẽ tính mã 128 thành PASS.
* 🔴 ``check-ignore -v`` trả **rc=0 cả khi pattern khớp là PHỦ ĐỊNH**, tức khi
  tệp sẽ ĐƯỢC commit. Đo 19-09 trên git thật: với ``scripts/export-hoso-excel/**``
  cộng ``!scripts/export-hoso-excel/BAN-GIAO.md``, ``-v`` cho rc=0 trên
  ``BAN-GIAO.md`` trong khi ``git add -An`` VẪN chọn nó. Nên câu hỏi "có bị
  ignore không" chỉ được hỏi bằng ``-q``; ``-v`` chỉ dùng để biết quy tắc NÀO.

⭐ Vì sao luật viết dạng THƯ MỤC (``scripts/export-hoso-excel/``) chứ không phải
glob ``scripts/export-hoso-excel/**``: git KHÔNG cho phép ``!`` kéo lại một tệp
nằm dưới một thư mục đã bị loại. Đo được cả hai chiều — dạng thư mục làm ngoại
lệ ``!.../BAN-GIAO.md`` VÔ HIỆU, dạng glob thì ngoại lệ ấy CÓ tác dụng và tệp
lọt vào ``git add``. Dạng thư mục vì thế fail-closed hơn một bậc.

Mọi phép kiểm HÀNH VI chạy trong một repo **tạm, cô lập** (``git init`` ở
``tmp_path``) chỉ chứa bản sao ``.gitignore`` thật. Hai lý do, cả hai đều từ sự
cố có thật:

* trong container backend, ``/repo`` là worktree mà ``.git`` chỉ là tệp trỏ sang
  đường dẫn Windows không được mount ⇒ MỌI lệnh git trả 128, và một ca dựa vào
  cây thật khi ấy đỏ vì môi trường chứ không vì lỗi nó canh;
* phép kiểm ``git add`` cần **tệp có thật** trong thư mục nhạy cảm. Tạo tệp
  trong cây làm việc THẬT là ghi vào đúng thư mục đang giữ PII — cấm tuyệt đối.
  Repo tạm cho phép dựng tệp mồi vô hại mà không chạm một byte PII nào.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


GOC = pathlib.Path(__file__).resolve().parents[3]
DUONG_GITIGNORE = GOC / ".gitignore"

#: Luật NEO — đúng chỗ thư mục đang nằm. Cố ý HẸP tới đúng tên thư mục.
#: ⚠️ Nó KHÔNG thêm lá chắn: ``LUAT_DI_DOI`` bao trùm nó hoàn toàn (đo: gỡ dòng
#: neo ⇒ 0/10 đường hở). Vai trò của nó là ĐỌC-RA-Ý-ĐỊNH — giữ cho
#: ``check-ignore -v`` trỏ đúng luật chủ đích ở đường hiện tại — và là dòng dự
#: phòng nếu ``LUAT_DI_DOI`` bị sửa về sau.
LUAT_NEO = "scripts/export-hoso-excel/"

#: Luật DI DỜI — cùng tên thư mục nhưng ở BẤT KỲ độ sâu nào. ĐÂY là dòng gánh
#: lá chắn. Không có nó, một `git mv` sang `tools/` hay `Backend_FastAPI/scripts/`
#: là thư mục hết được che mà git không cảnh báo gì. Đo 19-09: luật neo một mình
#: che 1/5 vị trí; thêm dòng này thành 5/5, dương tính giả vẫn 0/15.
LUAT_DI_DOI = "**/export-hoso-excel/"

#: Tập quy tắc CHỦ ĐÍCH. Phép kiểm chiều xuôi đòi đường dẫn bị che bởi MỘT
#: TRONG HAI dòng này — không phải bởi một quy tắc TÌNH CỜ (`*.sql`,
#: `__pycache__/`), thứ sẽ biến mất cùng lần dọn `.gitignore` tiếp theo.
#: Dùng TẬP chứ không phải một chuỗi vì hai luật CHỒNG NHAU: dòng `**/` bao
#: trùm dòng neo, nên dòng nào "thắng" phụ thuộc thứ tự trong tệp — và thứ tự
#: không phải là bất biến đáng khoá, quy tắc nào che mới là.
LUAT_HOP_LE = {LUAT_NEO, LUAT_DI_DOI}

#: Đường dẫn ĐẠI DIỆN trong thư mục nhạy cảm. Đây chỉ là chuỗi — không tệp nào
#: trong số này được mở, đọc, hay sao chép ở bất kỳ đâu trong tệp test này.
DUONG_NHAY_CAM = [
    "scripts/export-hoso-excel/chay.py",
    "scripts/export-hoso-excel/out.txt",
    "scripts/export-hoso-excel/err.txt",
    "scripts/export-hoso-excel/BAN-GIAO.md",
    "scripts/export-hoso-excel/lib/nested.md",
    "scripts/export-hoso-excel/__pycache__/x.pyc",
]

#: Đường dẫn DI DỜI — cùng thư mục ấy nhưng ở chỗ khác. Chỉ ``LUAT_DI_DOI`` che
#: được chúng; ``LUAT_NEO`` một mình thì KHÔNG (đo 19-09: 1/5).
DUONG_DI_DOI = [
    "export-hoso-excel/chay.py",                          # lên thẳng gốc kho
    "Backend_FastAPI/scripts/export-hoso-excel/chay.py",  # sang cây backend
    "tools/export-hoso-excel/chay.py",                    # sang thư mục mới
    "Documents/export-hoso-excel/BAN-GIAO.md",            # lẫn vào tài liệu
]

#: GIỚI HẠN ĐÃ ĐO của cả hai luật: ĐỔI TÊN thư mục thì không dòng nào bắt được.
#: Ghi ra thành ca kiểm để giới hạn này HIỆN RA trong báo cáo test, thay vì nằm
#: im như một giả định không ai kiểm.
DUONG_DOI_TEN_VAN_LOT = [
    "scripts/export-hoso-excel-2026/chay.py",
    "scripts/xuat-hoso-excel/chay.py",
]

#: Hàng xóm hợp pháp. Bốn mục cuối là mồi chống pattern quá rộng:
#: `scripts/export*` nuốt hai mục đầu trong số đó; một luật quên neo biên
#: thư mục sẽ nuốt `export-hoso-excel.md` (TỆP, không phải thư mục) và
#: `export-hoso-excel-backup/` (tên DÀI HƠN, thư mục khác).
DUONG_LANH = [
    "scripts/deploy.sh",
    "scripts/nginx-apply.sh",
    "scripts/nginx-verify.sh",
    "scripts/fe-check.sh",
    "scripts/fe-check.cmd",
    "scripts/rollback-preflight.sh",
    "scripts/lib/healthchecks.sh",
    "scripts/attest-frontend-runtime.sh",
    "scripts/backup-with-offsite.sh",
    "scripts/setup-ssl.sh",
    "scripts/exporter.py",
    "scripts/export_something_else.sh",
    "scripts/export-hoso.md",
    "scripts/export-hoso-excel.md",
    "scripts/export-hoso-excel-backup/x.txt",
]


def _doc_gitignore() -> str:
    return DUONG_GITIGNORE.read_text(encoding="utf-8")


def _git(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            # Repo tạm phải KHÔNG thừa kế cấu hình của máy: một `core.excludesFile`
            # toàn cục có thể che thêm, biến phép kiểm chiều ngược thành xanh giả.
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(cwd),
            "USERPROFILE": str(cwd),
            "PATH": __import__("os").environ.get("PATH", ""),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
    )


@pytest.fixture(scope="module")
def repo_tam(tmp_path_factory) -> pathlib.Path:
    """Repo git tạm, cô lập, chỉ mang bản sao `.gitignore` THẬT."""
    if shutil.which("git") is None:
        pytest.skip("không có git ở môi trường này — tầng kiểm tĩnh vẫn chạy")

    goc = tmp_path_factory.mktemp("gitignore_export_pii")
    (goc / ".gitignore").write_text(_doc_gitignore(), encoding="utf-8")

    ket = _git("init", "-q", cwd=goc)
    if ket.returncode != 0:
        pytest.skip(f"git init hỏng: {(ket.stderr or '').strip()[:160]}")
    return goc


# ---------------------------------------------------------------------------
# Tầng 1 — kiểm TĨNH, LUÔN chạy (không cần git)
# ---------------------------------------------------------------------------

def test_luat_neo_co_mat_nguyen_van():
    """Dòng neo là chốt ĐỌC-RA-Ý-ĐỊNH, KHÔNG phải một lá chắn thứ hai.

    ⚠️ ĐỌC TRƯỚC KHI HOẢNG: ca này đỏ **không** có nghĩa là PII đang rò.
    ``LUAT_DI_DOI`` (``**/export-hoso-excel/``) bao trùm hoàn toàn dòng neo —
    đo hai lượt độc lập: gỡ dòng neo thì **0/10 đường hở ra**, mọi đường vẫn
    ``-q`` rc=0 và ``git add -An`` vẫn không chọn gì.

    Vậy ca này canh cái gì? Canh phòng-thủ-chiều-sâu và dấu vết ý định:

    * ``check-ignore -v`` sẽ thôi chỉ ra luật chủ đích cho đường HIỆN TẠI mà
      chỉ còn trỏ một glob chung, nên người điều tra sau mất đầu mối vì sao
      thư mục này bị canh;
    * nếu sau này ``LUAT_DI_DOI`` bị nới, sửa, hay gỡ, dòng neo là thứ còn
      lại — mất cả hai cùng lúc mới là thủng, và khi đó các ca HÀNH VI đỏ.

    ⚠️ Cách sửa khi đỏ là **đặt lại dòng neo**, KHÔNG phải gỡ nốt
    ``LUAT_DI_DOI`` cho "nhất quán". Đọc ``test_luat_di_doi_co_mat_nguyen_van``
    để biết dòng nào mới thật sự gánh lá chắn.
    """
    dong = [d.strip() for d in _doc_gitignore().splitlines()]
    assert LUAT_NEO in dong, (
        f"thiếu dòng neo `{LUAT_NEO}` trong .gitignore. ⚠️ KHÔNG có tệp nào hở "
        f"vì việc này — `{LUAT_DI_DOI}` che hết (đo: 0/10 đường hở). Mất ở đây "
        "là mất CHỐT ĐỌC-RA-Ý-ĐỊNH: `check-ignore -v` thôi chỉ đúng luật chủ "
        "đích cho đường hiện tại, và không còn dòng thứ hai đỡ nếu luật di dời "
        "bị sửa sau này. Sửa bằng cách ĐẶT LẠI dòng neo — đừng gỡ nốt luật di "
        "dời cho 'nhất quán'."
    )


def test_luat_di_doi_co_mat_nguyen_van():
    """Không có dòng này thì `git mv` thư mục = mất lá chắn, git không báo gì.

    Đây là dòng GÁNH LÁ CHẮN, và ca này KHÔNG đứng một mình: gỡ ``LUAT_DI_DOI``
    làm đỏ thêm 4 ca ``test_duong_di_doi_bi_ignore`` và
    ``test_git_add_khong_chon_duong_nhay_cam`` — đo 19-09, tổng 6 đỏ.

    ⚠️ Đối xứng KHÔNG đúng, đừng suy từ ca này sang ca kia. Gỡ ``LUAT_NEO`` thì
    **0/10 đường hở** và **không ca hành vi nào đỏ**, vì ``**/`` bao trùm dòng
    neo; khi ấy chỉ ``test_luat_neo_co_mat_nguyen_van`` đỏ, và nó đỏ vì lý do
    ĐỌC-RA-Ý-ĐỊNH chứ không phải vì rò rỉ. Ghi ra để không ai đọc nhầm hai ca
    tĩnh này thành cùng một mức nghiêm trọng.
    """
    dong = [d.strip() for d in _doc_gitignore().splitlines()]
    assert LUAT_DI_DOI in dong, (
        f"thiếu dòng `{LUAT_DI_DOI}` ⇒ luật chỉ khớp ĐÚNG MỘT chỗ. Đo 19-09: "
        "luật neo một mình che 1/5 vị trí di dời — `tools/`, "
        "`Backend_FastAPI/scripts/`, `Documents/`, và gốc kho đều LỌT."
    )


def test_khong_co_ngoai_le_phu_dinh_mo_lai_thu_muc():
    """Một dòng `!scripts/export-hoso-excel/...` mở lại đúng thứ vừa đóng.

    ⚠️ GIỚI HẠN CỦA CHÍNH CA NÀY, đã đo: bộ lọc dưới đây bắt theo CHUỖI CON
    ``"export-hoso-excel"``, nên một dòng phủ định RỘNG mà không chứa chuỗi ấy
    — ``!scripts/**``, ``!scripts/*``, ``!tools/**`` — **lọt qua ca tĩnh này**
    (đo: 1–2 tệp vào được ``git add``).

    Đó KHÔNG phải một lỗ, vì ca tĩnh này không phải tuyến chịu lực. Tầng HÀNH
    VI bắt trọn cả ba biến thể ấy — đo lần lượt 7 đỏ · 7 đỏ · 2 đỏ qua
    ``test_duong_nhay_cam_bi_ignore`` (``-q``) và
    ``test_git_add_khong_chon_duong_nhay_cam`` (``git add -An``).

    Nói cách khác: ca này là phép chặn SỚM và đọc được cho biến thể thường gặp
    nhất; ``-q`` + ``add -An`` mới là thứ gánh lá chắn. Đừng mở rộng bộ lọc
    chuỗi ở đây thành một phép so khớp pattern tự chế — đó là viết lại engine
    gitignore bằng tay, và nó sẽ sai theo cách không ai kiểm được.
    """
    xau = [
        d.strip()
        for d in _doc_gitignore().splitlines()
        if d.strip().startswith("!") and "export-hoso-excel" in d
    ]
    assert not xau, (
        f"có ngoại lệ phủ định mở lại thư mục PII: {xau!r}. Mọi tệp trong đó "
        "phải được đọc và làm sạch bằng tay trước khi xin đưa vào git."
    )


# ---------------------------------------------------------------------------
# Tầng 2 — kiểm HÀNH VI trong repo tạm, CẢ HAI CHIỀU
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("duong", DUONG_NHAY_CAM)
def test_duong_nhay_cam_bi_ignore(repo_tam, duong):
    # Câu hỏi "có bị ignore không" CHỈ được trả lời bằng `-q` (KHÔNG có `-v`).
    # Đo 19-09 trên git thật: với `scripts/export-hoso-excel/**` +
    # `!scripts/export-hoso-excel/BAN-GIAO.md`, lệnh `-v` trả **rc=0** cho
    # `BAN-GIAO.md` — trong khi `git add -An` VẪN chọn tệp ấy để commit. Lý do:
    # ở chế độ verbose, rc=0 nghĩa là "có pattern KHỚP", kể cả pattern PHỦ ĐỊNH.
    # Một ca chỉ đọc mã thoát của `-v` vì thế báo XANH cho một tệp sắp bị đẩy
    # lên kho public.
    ket_q = _git("check-ignore", "-q", "--no-index", duong, cwd=repo_tam)
    assert ket_q.returncode in (0, 1), (
        f"git lỗi (mã {ket_q.returncode}): {(ket_q.stderr or '').strip()[:160]}"
    )
    assert ket_q.returncode == 0, f"{duong} KHÔNG bị ignore trên một kho PUBLIC"

    # `-v` chỉ để biết quy tắc NÀO che, không dùng mã thoát của nó làm câu trả
    # lời. Định dạng: `<tệp nguồn>:<dòng>:<pattern>\t<đường dẫn>`.
    ket = _git("check-ignore", "-v", "--no-index", duong, cwd=repo_tam)
    assert ket.returncode == 0 and ket.stdout.strip(), (
        f"`-q` nói bị ignore nhưng `-v` không chỉ ra quy tắc nào "
        f"(mã {ket.returncode}): {ket.stdout!r}"
    )
    nguon, so_dong, con_lai = ket.stdout.split(":", 2)
    pattern = con_lai.split("\t", 1)[0].strip()

    # Trường pattern RỖNG = git khớp một DÒNG TRỐNG. Đã quan sát thật trên một
    # nhánh khác của kho này (rc=0, pattern rỗng, trỏ một dòng trống).
    assert pattern, (
        f"pattern RỖNG (nguồn {nguon!r}, dòng {so_dong!r}) — `check-ignore` trỏ "
        "một dòng trống mà vẫn trả 0; đó không phải bằng chứng đã che"
    )
    assert pattern in LUAT_HOP_LE, (
        f"{duong} bị che bởi `{pattern}`, không phải một trong hai luật chủ đích "
        f"{sorted(LUAT_HOP_LE)} — nghĩa là nó đang dựa vào một quy tắc TÌNH CỜ "
        "(ví dụ `*.sql`), thứ sẽ biến mất cùng lần dọn .gitignore tiếp theo"
    )


@pytest.mark.parametrize("duong", DUONG_DI_DOI)
def test_duong_di_doi_bi_ignore(repo_tam, duong):
    """Thư mục ấy bị `git mv` đi chỗ khác thì lá chắn phải ĐI THEO."""
    ket_q = _git("check-ignore", "-q", "--no-index", duong, cwd=repo_tam)
    assert ket_q.returncode in (0, 1), (
        f"git lỗi (mã {ket_q.returncode}): {(ket_q.stderr or '').strip()[:160]}"
    )
    assert ket_q.returncode == 0, (
        f"{duong} KHÔNG bị ignore. Luật neo gốc khớp tên ở ĐÚNG MỘT chỗ, nên di "
        f"dời thư mục là mất lá chắn lặng lẽ; `{LUAT_DI_DOI}` là thứ bịt việc đó."
    )

    ket = _git("check-ignore", "-v", "--no-index", duong, cwd=repo_tam)
    pattern = ket.stdout.split(":", 2)[2].split("\t", 1)[0].strip()
    assert pattern == LUAT_DI_DOI, (
        f"{duong} bị che bởi `{pattern}` chứ không phải `{LUAT_DI_DOI}`. Chỉ luật "
        "di dời mới che được đường này — quy tắc nào khác đang che là tình cờ."
    )


@pytest.mark.parametrize("duong", DUONG_DOI_TEN_VAN_LOT)
def test_gioi_han_da_biet_doi_ten_thu_muc_van_lot(repo_tam, duong):
    """GIỚI HẠN ĐÃ ĐO, ghi ra để nó không nằm im như một giả định.

    Hai luật hiện có bắt theo TÊN thư mục. Đổi tên (`...-2026`, `xuat-hoso-...`)
    thì cả hai đều thua. Đây KHÔNG phải lỗi cần vá bằng cách nới pattern: mọi
    pattern đủ rộng để bắt chúng đều bắt đầu nuốt tệp lành — đã đo
    `scripts/export-hoso-excel.md` và `scripts/export-hoso-excel-backup/` nằm
    sát ngay bên cạnh.

    ⚠️ Ca này ĐỎ nghĩa là ai đó vừa MỞ RỘNG luật. Nếu đó là chủ ý, hãy kiểm lại
    chiều ngược (`DUONG_LANH`) rồi bỏ đường tương ứng khỏi danh sách này —
    đừng nới danh sách hàng xóm lành để ép ca này xanh trở lại.
    """
    ket_q = _git("check-ignore", "-q", "--no-index", duong, cwd=repo_tam)
    assert ket_q.returncode in (0, 1), (
        f"git lỗi (mã {ket_q.returncode}): {(ket_q.stderr or '').strip()[:160]}"
    )
    assert ket_q.returncode == 1, (
        f"{duong} NAY ĐÃ bị ignore — luật vừa được mở rộng. Đọc docstring của ca "
        "này trước khi sửa: kiểm chiều ngược rồi mới cập nhật danh sách."
    )


@pytest.mark.parametrize("duong", DUONG_LANH)
def test_duong_lanh_khong_bi_ignore(repo_tam, duong):
    # `-q`, không `-v`: xem chú thích ở ca trên. Với `-v`, một pattern PHỦ ĐỊNH
    # khớp cũng cho rc=0, nên chiều ngược sẽ đỏ NHẦM cho một cấu hình lành.
    ket_q = _git("check-ignore", "-q", "--no-index", duong, cwd=repo_tam)
    assert ket_q.returncode in (0, 1), (
        f"git lỗi (mã {ket_q.returncode}): {(ket_q.stderr or '').strip()[:160]}"
    )
    if ket_q.returncode == 0:
        chi_tiet = _git(
            "check-ignore", "-v", "--no-index", duong, cwd=repo_tam
        ).stdout.strip()
        pytest.fail(
            f"{duong} BỊ ignore bởi `{chi_tiet}` — luật quá rộng. Một pattern "
            "kiểu `scripts/export*` đóng lỗ PII bằng cách mở một lỗ khác: mã "
            "vận hành lặng lẽ rơi khỏi git."
        )


# ---------------------------------------------------------------------------
# Tầng 3 — `git add -A --dry-run` với tệp CÓ THẬT (mồi vô hại)
# ---------------------------------------------------------------------------

def test_git_add_khong_chon_duong_nhay_cam(repo_tam, tmp_path):
    """Tệp mồi VÔ HẠI, dựng trong repo tạm. Không tệp PII nào bị chạm."""
    goc = tmp_path / "addcheck"
    goc.mkdir()
    (goc / ".gitignore").write_text(_doc_gitignore(), encoding="utf-8")
    ket = _git("init", "-q", cwd=goc)
    if ket.returncode != 0:
        pytest.skip(f"git init hỏng: {(ket.stderr or '').strip()[:160]}")

    for duong in DUONG_NHAY_CAM + DUONG_DI_DOI:
        tep = goc / duong
        tep.parent.mkdir(parents=True, exist_ok=True)
        tep.write_text("MOI-VO-HAI-KHONG-PHAI-PII\n", encoding="utf-8")

    # Neo chống rỗng: nếu `git add -An` không chọn gì cả (repo hỏng, git đổi
    # hành vi), phép kiểm dưới sẽ xanh một cách vô nghĩa. Tệp mồi LÀNH này phải
    # được chọn, nếu không ca test tự khai là không đo được gì.
    lanh = goc / "scripts" / "deploy-moi.sh"
    lanh.parent.mkdir(parents=True, exist_ok=True)
    lanh.write_text("#!/bin/sh\necho moi\n", encoding="utf-8")

    ket = _git("add", "-A", "--dry-run", cwd=goc)
    assert ket.returncode == 0, (
        f"`git add -A --dry-run` hỏng (mã {ket.returncode}): "
        f"{(ket.stderr or '').strip()[:200]}"
    )
    ra = ket.stdout

    assert "scripts/deploy-moi.sh" in ra, (
        "tệp mồi LÀNH không được `git add -An` chọn ⇒ phép kiểm này không đo "
        f"được gì. Output: {ra.strip()[:300]!r}"
    )

    dinh = [d for d in ra.splitlines() if "export-hoso-excel" in d]
    assert not dinh, (
        f"`git add -A --dry-run` CHỌN {len(dinh)} đường nhạy cảm: {dinh!r}. "
        "Trên kho PUBLIC, đó là PII của 969 hồ sơ cách một `git commit`."
    )


# ---------------------------------------------------------------------------
# CI phải NHÌN THẤY tệp này
# ---------------------------------------------------------------------------

TEP_NAY = "tests/unit/test_gitignore_export_pii.py"


def test_tep_nay_nam_trong_dung_MOT_leg_cua_pr_gate():
    """Tệp test không có tên trong tier nào thì KHÔNG shard nào chạy nó mà
    required check VẪN XANH — nguyên văn bài học `ci-allowlist`."""
    yaml = pytest.importorskip("yaml")
    wf_duong = GOC / ".github" / "workflows" / "backend-test.yml"
    if not wf_duong.is_file():
        pytest.skip(f"không thấy {wf_duong}")

    wf = yaml.safe_load(wf_duong.read_text(encoding="utf-8"))
    legs = wf["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]
    chua = [
        str(leg.get("tier", ""))
        for leg in legs
        if TEP_NAY in str(leg.get("tests", "")).split()
    ]
    assert len(chua) == 1, (
        f"{TEP_NAY} nằm trong {len(chua)} leg: {chua!r}. 0 leg nghĩa là guard "
        "này không bao giờ chạy mà cổng vẫn xanh."
    )


def test_bo_loc_paths_phu_ca_hai_duong_guard_nay_doc():
    """Guard đọc `.gitignore` và `scripts/**`; `paths:` thiếu chúng ⇒ một PR
    CHỈ gỡ luật ignore sẽ không kích hoạt lượt chạy nào."""
    yaml = pytest.importorskip("yaml")
    wf_duong = GOC / ".github" / "workflows" / "backend-test.yml"
    if not wf_duong.is_file():
        pytest.skip(f"không thấy {wf_duong}")

    wf = yaml.safe_load(wf_duong.read_text(encoding="utf-8"))
    kich_hoat = wf.get("on", wf.get(True, {}))
    mau = kich_hoat.get("pull_request", {}).get("paths") or []
    assert mau, "backend-test.yml không có bộ lọc `paths:`"

    def _khop(duong: str, pat: str) -> bool:
        if pat.endswith("/**"):
            return duong.startswith(pat[:-2])
        return duong == pat

    can_phu = [".gitignore", "scripts/deploy.sh"]
    thieu = [d for d in can_phu if not any(_khop(d, p) for p in mau)]
    assert not thieu, (
        f"gate `pytest` KHÔNG chạy khi các đường sau đổi: {thieu}. "
        f"Bộ lọc hiện có: {mau}"
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
