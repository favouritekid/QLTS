"""Image production KHÔNG được chứa công cụ smoke và hiện vật do smoke sinh ra.

Vì sao cần phép kiểm chạy thật thay vì đọc `.dockerignore` bằng mắt: mẫu trong
`.dockerignore` có ngữ nghĩa riêng, và đọc nhầm ngữ nghĩa đó chính là gốc của lỗ
hổng này.

Đo được ngày 14-08-2026 trên chính build context:

* `scripts/smoke/` được loại đúng, nhưng **12 mục cùng họ vẫn lọt** — gồm
  `smoke_e4_phase6_reset_passwords.py`, đúng thứ mà comment trong `.dockerignore`
  viện dẫn làm lý do phải loại;
* `*.md` ở đầu tệp **không** loại được `scripts/SMOKE_SEED_GUIDE.md`, vì mẫu
  không có `**/` chỉ khớp ở GỐC context. Cùng cái bẫy ấy áp cho `*.dump`.

`Dockerfile` dùng `COPY . .`, nên "thứ nằm trong build context" **là** "thứ nằm
trong image". Probe ở đây dựng một image tối giản từ CHÍNH context ấy
(`FROM postgres:16-alpine` + `COPY . /ctx`) — không chạy `pip install` của
Dockerfile thật nên nhanh, mà vẫn đo đúng thứ cần đo, vì `.dockerignore` áp cho
MỌI lượt build trong context.

Ba tầng chống xanh-giả, thiếu một tầng là phép kiểm mất nghĩa:

1. tệp CHỨNG (`app/main.py`) phải CÓ — context rỗng thì mọi khẳng định "không
   thấy" đều đúng một cách vô nghĩa;
2. tệp ĐỐI CHỨNG do chính ca test sinh ra, mang token ngẫu nhiên, phải CÓ **và
   đúng nội dung** — chứng minh probe đọc context của LƯỢT NÀY, không phải một
   lớp cache cũ;
3. hiện vật sentinel do ca test sinh ra ở cả gốc lẫn thư mục con phải VẮNG —
   chứng minh mẫu thật sự chặn, chứ không phải "vô tình chẳng có tệp nào".
"""

from __future__ import annotations

import shutil
import subprocess as _sp
import uuid
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
_DOCKERIGNORE = _GOC / ".dockerignore"
_CO_DOCKER = shutil.which("docker") is not None

# Mẫu bắt buộc phải có mặt trong .dockerignore. Ca kiểm tĩnh dưới đây chạy được
# cả khi không có Docker; nó KHÔNG thay thế probe, chỉ bắt sớm lỗi xoá nhầm dòng.
_MAU_BAT_BUOC = (
    "scripts/smoke*",
    "scripts/seed_smoke_dev.py",
    ".smoke/",
    ".smoke_*",
    "**/smoke_ids.json",
    "**/smoke_ids.json.tmp",
    "**/smoke-*.png",
    "**/*.dump",
    "**/*.md",
)


def test_dockerignore_con_du_bay_nhom_mau():
    """Kiểm tĩnh — rẻ, luôn chạy, bắt trường hợp có người xoá mất một dòng."""
    dong = {
        d.strip()
        for d in _DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if d.strip() and not d.lstrip().startswith("#")
    }
    thieu = [m for m in _MAU_BAT_BUOC if m not in dong]
    assert not thieu, f"thiếu mẫu trong .dockerignore: {thieu}"


# ---------------------------------------------------------------------------
# Probe build thật
# ---------------------------------------------------------------------------

# Dùng ảnh mà runner CI đã kéo sẵn cho service container của shard này, nên
# probe không cần mạng. Cùng lý do với sentinel ở test_smoke_cli.py.
_ANH_NEN = "postgres:16-alpine"

# Hiện vật sentinel do ca test tự sinh: đặt ở CẢ gốc context lẫn thư mục con,
# vì đó chính là chỗ mẫu trần (không `**/`) trượt.
_SENTINEL_VANG = (
    "smoke_ids.json",
    "smoke_ids.json.tmp",
    "scripts/probe_sentinel.dump",
    "app/smoke-probe.png",
    ".smoke_probe/x.txt",
    # Markdown LỒNG: `*.md` ở đầu .dockerignore chỉ khớp gốc context, nên tài
    # liệu trong thư mục con vẫn vào image cho tới khi có `**/*.md`.
    "scripts/probe_sentinel_doc.md",
)
_DOI_CHUNG = "scripts/probe_sentinel_control.txt"


@pytest.fixture
def context_probe(tmp_path):
    """Dựng probe image từ build context thật; dọn image + hiện vật trong finally."""
    token = uuid.uuid4().hex
    nhan = "qlts-probe-ctx:" + token[:12]
    tep_docker = tmp_path / "probe.Dockerfile"
    tep_docker.write_text(f"FROM {_ANH_NEN}\nCOPY . /ctx\n", encoding="utf-8")

    da_tao: list[Path] = []
    da_build = False
    try:
        for tuong_doi in _SENTINEL_VANG + (_DOI_CHUNG,):
            p = _GOC / tuong_doi
            assert not p.exists(), f"{tuong_doi} đã tồn tại sẵn — không ghi đè"
            p.parent.mkdir(parents=True, exist_ok=True)
            # Token vào tệp đối chứng: nội dung đổi mỗi lượt ⇒ khoá cache lớp
            # COPY chắc chắn đổi ⇒ không thể đọc nhầm lớp cũ.
            p.write_text(token, encoding="utf-8")
            da_tao.append(p)

        ket = _sp.run(
            ["docker", "build", "-q", "-f", str(tep_docker), "-t", nhan, str(_GOC)],
            shell=False, capture_output=True, text=True, timeout=600,
        )
        assert ket.returncode == 0, (
            f"probe build hỏng (rc={ket.returncode}); cần ảnh {_ANH_NEN} có sẵn:\n"
            f"{((ket.stderr or '') + (ket.stdout or ''))[:600]}"
        )
        da_build = True
        yield nhan, token
    finally:
        for p in da_tao:
            p.unlink(missing_ok=True)
        thu_muc = _GOC / ".smoke_probe"
        if thu_muc.is_dir():
            shutil.rmtree(thu_muc, ignore_errors=True)
        con_sot = [str(p.relative_to(_GOC)) for p in da_tao if p.exists()]
        assert not con_sot, f"chưa dọn hết hiện vật sentinel: {con_sot}"

        # `da_build` chứ không gọi `rmi` vô điều kiện: build hỏng thì chẳng có
        # image nào để gỡ, mà `rmi` vẫn trả khác 0 và sinh teardown error ĐÈ LÊN
        # chính lỗi build — người đọc log sẽ đi sửa nhầm chỗ.
        if da_build:
            go = _sp.run(
                ["docker", "rmi", "-f", nhan],
                shell=False, capture_output=True, text=True, timeout=180,
            )
            # Bỏ qua mã thoát ở đây thì một lượt dọn hỏng vẫn để ca test XANH mà
            # bỏ lại image trong daemon của lượt sau.
            assert go.returncode == 0, (
                f"gỡ image probe {nhan} HỎNG (rc={go.returncode}): "
                f"{((go.stderr or '') + (go.stdout or ''))[:300]!r}"
            )


def _trong_probe(nhan: str, lenh: str) -> str:
    ket = _sp.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", nhan, "-c", lenh],
        shell=False, capture_output=True, text=True, timeout=180,
    )
    assert ket.returncode == 0, (
        f"chạy probe hỏng (rc={ket.returncode}): {(ket.stderr or '')[:300]}"
    )
    return ket.stdout or ""


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để dựng probe build context")
def test_probe_doc_dung_context_cua_luot_nay(context_probe):
    """Tầng 1+2: context không rỗng, và probe đọc đúng lượt này chứ không phải cache."""
    nhan, token = context_probe

    chung = _trong_probe(nhan, "cat /ctx/app/main.py 2>/dev/null | head -c 1; echo")
    assert chung.strip(), "không thấy /ctx/app/main.py — context rỗng thì mọi khẳng định vô nghĩa"

    doi_chung = _trong_probe(nhan, f"cat /ctx/{_DOI_CHUNG} 2>/dev/null; echo")
    assert doi_chung.strip() == token, (
        f"tệp đối chứng phải mang token {token} của lượt này, nhận {doi_chung.strip()!r} "
        "⇒ probe đang đọc một lớp cache cũ, mọi kết luận bên dưới không dùng được"
    )

    dem = _trong_probe(nhan, "ls /ctx/scripts | wc -l").strip()
    assert int(dem) >= 30, f"/ctx/scripts chỉ có {dem} mục — context bị cắt bất thường"


@pytest.mark.skipif(not _CO_DOCKER, reason="cần docker CLI để dựng probe build context")
def test_image_khong_chua_cong_cu_va_hien_vat_smoke(context_probe):
    """Tầng 3: không mã smoke, không hiện vật smoke — kể cả ở thư mục con."""
    nhan, _ = context_probe

    ra = _trong_probe(nhan, r"""
        for p in /ctx/scripts/smoke* /ctx/scripts/seed_smoke_dev.py \
                 /ctx/.smoke /ctx/.smoke_* /ctx/smoke_ids.json /ctx/smoke_ids.json.tmp \
                 /ctx/scripts/SMOKE_SEED_GUIDE.md; do
          # SMOKE_SEED_GUIDE.md là tệp THẬT trong repo, không phải sentinel do
          # test sinh: bằng chứng sống của bẫy "mẫu trần chỉ khớp gốc context".
          [ -e "$p" ] && echo "LOT:$p"
        done
        find /ctx \( -name '*.dump' -o -name 'smoke-*.png' -o -name '*.md' \) \
          2>/dev/null | sed 's|^|LOT:|'
        true
    """)
    lot = sorted({d.strip()[4:] for d in ra.splitlines() if d.strip().startswith("LOT:")})
    assert not lot, (
        "công cụ/hiện vật smoke lọt vào build context ⇒ vào thẳng image production "
        f"(Dockerfile dùng `COPY . .`): {lot}"
    )
