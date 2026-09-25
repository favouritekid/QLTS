"""Deploy workflow phải deploy ĐÚNG commit sinh ra nó, không phải tip mới nhất.

Job `deploy` dừng ở `environment: production` chờ người duyệt. Giữa lúc run được
sinh và lúc có người bấm approve, `main` có thể đã nhận thêm commit. Bản trước
chạy `git pull --ff-only origin main` rồi chỉ `echo` ra SHA — nên một run mang
metadata của commit A vẫn lặng lẽ deploy commit B, và log không hề mâu thuẫn với
chính nó.

Phép kiểm ở đây không dừng ở việc grep vài chữ: nó **trích đúng khối `if` đã
ship** trong `deploy.yml` rồi thi hành bằng `sh`. Một khối được chép tay vào test
chỉ chứng minh giả định của người viết test, không chứng minh thứ chạy trên VPS.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess as _sp
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import re
import yaml


def _goc_repo() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / ".github" / "workflows").is_dir():
            return goc
    pytest.fail("không tìm thấy gốc repo (thiếu .github/workflows)")


_DEPLOY = _goc_repo() / ".github" / "workflows" / "deploy.yml"
_NOI_DUNG = _DEPLOY.read_text(encoding="utf-8")
_CO_SH = shutil.which("sh") is not None

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def test_workflow_truyen_github_sha_sang_vps():
    """Thiếu `envs:` thì biến không sang tới VPS và cổng thành no-op câm lặng."""
    assert "SHA_MONG_DOI: ${{ github.sha }}" in _NOI_DUNG, "chưa khai github.sha ở env:"
    assert re.search(r"^\s*envs:\s*SHA_MONG_DOI\s*$", _NOI_DUNG, re.M), (
        "thiếu `envs: SHA_MONG_DOI` — appleboy/ssh-action chỉ chuyển biến được "
        "liệt kê ở đây; không có nó thì `$SHA_MONG_DOI` rỗng trên VPS"
    )


def _dong_lenh() -> list[str]:
    """Chỉ các dòng LỆNH, bỏ hết chú thích.

    Phép kiểm đầu tiên viết ra ở đây đã đỏ oan vì khớp trúng chữ
    `git pull --ff-only origin main` nằm trong một dòng `#` giải thích tại sao
    nhánh ấy bị bỏ. Một biểu thức khớp cả chú thích thì vừa báo động giả, vừa có
    thể im lặng khi lệnh thật được viết khác đi.
    """
    return [
        d for d in _NOI_DUNG.splitlines()
        if d.strip() and not d.lstrip().startswith("#")
    ]


def test_khong_con_pull_tron_theo_nhanh():
    """`git pull --ff-only origin main` là chính cái nhánh fail-open đã bỏ."""
    con_sot = [d for d in _dong_lenh() if "git pull --ff-only origin main" in d]
    assert not con_sot, (
        "vẫn còn `pull` trống theo nhánh — nó kéo tip mới nhất bất kể run này "
        f"được sinh cho commit nào: {con_sot}"
    )
    assert any('git merge --ff-only "$SHA_MONG_DOI"' in d for d in _dong_lenh()), (
        "phải ghim tường minh tới SHA của run"
    )


def _trich_khoi_cong() -> str:
    """Lấy nguyên văn khối `if` so SHA trong script đã ship."""
    m = re.search(
        r'^(\s*)if \[ "\$SHA_TIP" != "\$SHA_MONG_DOI" \]; then\n(.*?)^\1fi$',
        _NOI_DUNG,
        re.S | re.M,
    )
    assert m, "không tìm thấy khối `if` so SHA trong deploy.yml"
    khoi = m.group(0)
    # Bỏ thụt lề của YAML block scalar để `sh` đọc được.
    thut = len(m.group(1))
    return "\n".join(d[thut:] if d[:thut].strip() == "" else d for d in khoi.splitlines())


def _chay(khoi: str, tip: str, mong_doi: str):
    kich_ban = f'SHA_TIP={tip}\nSHA_MONG_DOI={mong_doi}\n{khoi}\nexit 0\n'
    return _sp.run(["sh", "-c", kich_ban], capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not _CO_SH, reason="cần `sh` để thi hành khối cổng đã ship")
def test_cong_sha_chan_that_khi_tip_lech():
    """Lệch ⇒ mã thoát khác 0, và nêu đích danh cả hai SHA."""
    ket = _chay(_trich_khoi_cong(), _SHA_B, _SHA_A)
    ra = (ket.stdout or "") + (ket.stderr or "")
    assert ket.returncode != 0, f"cổng KHÔNG chặn khi tip lệch (rc={ket.returncode}): {ra[:300]}"
    assert _SHA_A in ra and _SHA_B in ra, (
        f"thông báo phải nêu cả SHA thật lẫn SHA mong đợi, nhận: {ra[:300]}"
    )


@pytest.mark.skipif(not _CO_SH, reason="cần `sh` để thi hành khối cổng đã ship")
def test_cong_sha_cho_di_tiep_khi_trung_khop():
    """Kiểm chiều ngược: trùng khớp thì KHÔNG được chặn.

    Thiếu ca này thì một khối `exit 1` vô điều kiện vẫn làm ca trên xanh.
    """
    ket = _chay(_trich_khoi_cong(), _SHA_A, _SHA_A)
    assert ket.returncode == 0, (
        f"cổng chặn nhầm khi SHA trùng khớp (rc={ket.returncode}): "
        f"{((ket.stdout or '') + (ket.stderr or ''))[:300]}"
    )


# ---------------------------------------------------------------------------
# Deploy change classifier: workflow luôn sinh, environment chỉ sinh khi cần
# ---------------------------------------------------------------------------

_CLASSIFIER_PATH = _goc_repo() / ".github" / "scripts" / "deploy_change_classifier.py"
_BACKEND_GATE = _goc_repo() / ".github" / "workflows" / "backend-test.yml"


def _load_classifier():
    spec = importlib.util.spec_from_file_location("deploy_change_classifier_test", _CLASSIFIER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def classifier():
    return _load_classifier()


def _on_block(doc: dict) -> dict:
    if "on" in doc:
        return doc["on"]
    if True in doc:  # YAML 1.1: ``on`` may become boolean True
        return doc[True]
    raise AssertionError("workflow không có khối on")


class _StrictYamlLoader(yaml.SafeLoader):
    pass


def _strict_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise AssertionError("workflow có khoá YAML trùng: %r" % (key,))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_mapping
)


def _workflow(path: Path) -> dict:
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictYamlLoader)
    assert isinstance(doc, dict)
    return doc


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("frontend/src/components/Foo.test.tsx", "runtime"),
        ("frontend/docs/guide.md", "runtime"),
        ("scripts/rollback-preflight.sh", "runtime"),
        ("Backend_FastAPI/app/main.py", "runtime"),
        ("Backend_FastAPI/alembic/versions/001.py", "runtime"),
        ("Backend_FastAPI/scripts/preflight_config.py", "runtime"),
        ("Backend_FastAPI/requirements-dev.txt", "runtime"),
        ("docker-compose.smoke.yml", "runtime"),
        (".github/workflows/deploy.yml", "runtime"),
        (".github/scripts/deploy_change_classifier.py", "runtime"),
        (".github/scripts/deploy_future_helper.py", "runtime"),
        (".github/actions/future-deploy/action.yml", "runtime"),
        ("Backend_FastAPI/tests/fixtures/constants.py", "safe"),
        (".github/scripts/tests/test_pr_classifier.py", "safe"),
        (".github/workflows/backend-test.yml", "safe"),
        ("Documents/reports/a.csv", "safe"),
        ("tests-e2e/session-survival/kiem-phien.py", "safe"),
        (".agent/rules/backend-architecture.md", "safe"),
        (".smoke-evidence/.gitkeep", "safe"),
        ("README.md", "safe"),
        ("new_worker/consumer.py", "unknown"),
    ],
)
def test_phan_loai_theo_tien_to_khong_theo_ten_tep(classifier, path, expected):
    assert classifier.classify_path(path) == expected


def test_frontend_la_runtime_nguyen_khoi_ke_ca_test(classifier):
    paths = (
        "frontend/src/a.test.ts",
        "frontend/src/a.test.tsx",
        "frontend/src/a.spec.tsx",
        "frontend/tests/screenshot.png",
    )
    assert {classifier.classify_path(path) for path in paths} == {"runtime"}


def test_chi_tap_duong_an_toan_moi_khong_deploy(classifier):
    records = [
        classifier.ChangeRecord("M", None, "Backend_FastAPI/tests/unit/test_x.py"),
        classifier.ChangeRecord("A", None, "Documents/report.csv"),
        classifier.ChangeRecord("M", None, ".github/workflows/backend-test.yml"),
    ]
    plan = classifier.classify_records(records)
    assert plan["classification"] == classifier.SAFE_NO_DEPLOY
    assert plan["deploy"] is False
    assert plan["reasons"] == ["only_explicit_safe_paths"]


def test_runtime_tron_safe_van_deploy(classifier):
    records = [
        classifier.ChangeRecord("M", None, "Documents/report.csv"),
        classifier.ChangeRecord("M", None, "Backend_FastAPI/app/main.py"),
    ]
    plan = classifier.classify_records(records)
    assert plan["classification"] == classifier.DEPLOY
    assert plan["deploy"] is True
    assert plan["runtime_paths"] == ["Backend_FastAPI/app/main.py"]


def test_unknown_khong_bao_gio_roi_xuong_safe(classifier):
    plan = classifier.classify_records(
        [classifier.ChangeRecord("A", None, "new_worker/consumer.py")]
    )
    assert plan["classification"] == classifier.DEPLOY
    assert plan["unknown_paths"] == ["new_worker/consumer.py"]


def test_rename_xet_ca_duong_cu_lan_moi(classifier):
    record = classifier.ChangeRecord(
        "R100", "Backend_FastAPI/app/worker.py", "Documents/worker-old.py"
    )
    plan = classifier.classify_records([record])
    assert plan["deploy"] is True
    assert plan["runtime_paths"] == ["Backend_FastAPI/app/worker.py"]
    assert plan["safe_paths"] == ["Documents/worker-old.py"]


def test_xoa_tep_runtime_van_deploy(classifier):
    plan = classifier.classify_records(
        [classifier.ChangeRecord("D", "scripts/deploy.sh", None)]
    )
    assert plan["deploy"] is True
    assert plan["runtime_paths"] == ["scripts/deploy.sh"]


def test_diff_rong_la_block_khong_phai_safe(classifier):
    with pytest.raises(classifier.ClassificationError, match="zero change records"):
        classifier.classify_records([])


def test_parser_nul_giu_rename_va_khoang_trang(classifier):
    raw = b"R083\0Documents/old name.md\0scripts/new name.sh\0M\0README.md\0"
    records = classifier.parse_name_status_z(raw)
    assert records == [
        classifier.ChangeRecord("R083", "Documents/old name.md", "scripts/new name.sh"),
        classifier.ChangeRecord("M", None, "README.md"),
    ]


def test_parser_khong_co_tran_300_tep(classifier):
    raw = b"".join(
        b"M\0Documents/item-%04d.md\0" % index for index in range(822)
    )
    records = classifier.parse_name_status_z(raw)
    assert len(records) == 822
    assert classifier.classify_records(records)["deploy"] is False


def test_read_diff_dung_git_nul_khong_qua_compare_api(classifier, monkeypatch):
    calls = []

    def fake_git(*args, text=False):
        calls.append((args, text))
        return b"M\0Documents/report.md\0"

    monkeypatch.setattr(classifier, "_git", fake_git)
    records = classifier.read_diff("a" * 40, "b" * 40)
    assert records == [classifier.ChangeRecord("M", None, "Documents/report.md")]
    assert calls == [( (
        "-c", "diff.renames=true", "diff", "--name-status", "-z", "-M",
        "a" * 40, "b" * 40, "--",
    ), False)]
    source = _CLASSIFIER_PATH.read_text(encoding="utf-8").lower()
    assert "api.github" not in source
    assert "gh api" not in source


@pytest.mark.parametrize(
    "raw",
    [
        b"M\0Documents/a.md",       # thiếu NUL cuối
        b"R100\0Documents/a.md\0",  # thiếu new_path
        b"?\0Documents/a.md\0",     # status không hợp lệ
    ],
)
def test_parser_diff_hong_phai_block(classifier, raw):
    with pytest.raises(classifier.ClassificationError):
        classifier.parse_name_status_z(raw)


@pytest.mark.parametrize(
    "directive",
    [
        "[skip ci]",
        "[ci skip]",
        "[no ci]",
        "[skip actions]",
        "[actions skip]",
        "skip-checks: true",
        "SKIP-CHECKS:true",
    ],
)
def test_phat_hien_chi_thi_lam_workflow_bien_mat(classifier, directive):
    found = classifier.find_skip_directives([("commit[1]", f"subject\n\n{directive}")])
    assert found and found[0]["source"] == "commit[1]"


def test_khong_bat_nham_cum_tu_gan_giong_skip_directive(classifier):
    assert classifier.find_skip_directives([
        ("title", "document skip ci behavior without brackets"),
        ("body", "skip-checks: false"),
    ]) == []


def test_guard_skip_quet_tieu_de_body_va_moi_commit(classifier, monkeypatch):
    monkeypatch.setattr(
        classifier,
        "_commit_messages",
        lambda _base, _head: ["commit sạch", "legacy\n\n[ci skip]"],
    )
    found = classifier.check_skip_directives(
        "a" * 40,
        "b" * 40,
        "tiêu đề sạch",
        "body sạch",
    )
    assert found == [{"source": "commit[2]", "directive": "[ci skip]"}]


def test_workflow_dispatch_luon_ep_deploy(classifier, monkeypatch):
    sha = "a" * 40
    monkeypatch.setattr(
        classifier,
        "_git",
        lambda *args, text=False: (sha + "\n") if text else b"",
    )
    plan = classifier.make_plan("workflow_dispatch", "", sha)
    assert plan["classification"] == classifier.DEPLOY
    assert plan["deploy"] is True
    assert plan["reasons"] == ["manual_workflow_dispatch"]
    assert plan["change_record_count"] == 0


def test_push_zero_before_fail_closed_thanh_deploy(classifier, monkeypatch):
    sha = "b" * 40
    monkeypatch.setattr(
        classifier,
        "_git",
        lambda *args, text=False: (sha + "\n") if text else b"",
    )
    plan = classifier.make_plan("push", classifier.ZERO_SHA, sha)
    assert plan["deploy"] is True
    assert plan["reasons"] == ["zero_before_sha"]


def test_cli_block_van_ghi_artifact_va_output_fail_closed(classifier, tmp_path, monkeypatch):
    artifact = tmp_path / "plan.json"
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        classifier,
        "make_plan",
        lambda *_: (_ for _ in ()).throw(classifier.ClassificationError("diff truncated")),
    )
    args = type("Args", (), {
        "artifact": str(artifact),
        "event": "push",
        "before": "a" * 40,
        "after": "b" * 40,
    })()
    assert classifier._classify_command(args) == 1
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["classification"] == classifier.BLOCK
    assert payload["deploy"] is False
    assert "deploy=false" in output.read_text(encoding="utf-8")


def test_workflow_luon_sinh_tren_push_main_va_co_manual_dispatch():
    doc = _workflow(_DEPLOY)
    on = _on_block(doc)
    assert on["push"]["branches"] == ["main"]
    assert "paths" not in on["push"]
    assert "paths-ignore" not in on["push"]
    assert "workflow_dispatch" in on


def test_chi_job_deploy_so_huu_environment_va_concurrency():
    """Duyệt TOÀN BỘ jobs, không chỉ hai tên cố định.

    Bản trước chỉ assert trên `classify-changes` và `deploy`. Tên hàm hứa "chỉ
    job deploy sở hữu", nhưng thân hàm không kiểm điều đó: thêm một job thứ ba
    mang `environment: production` thì phép kiểm VẪN XANH. Đúng loại guard
    canh hụt mà CLAUDE.md §3 nói tới.
    """
    jobs = _workflow(_DEPLOY)["jobs"]
    co_env = sorted(ten for ten, job in jobs.items() if "environment" in job)
    co_conc = sorted(ten for ten, job in jobs.items() if "concurrency" in job)
    assert co_env == ["deploy"], f"chỉ `deploy` được mang environment, thấy {co_env}"
    assert co_conc == ["deploy"], f"chỉ `deploy` được mang concurrency, thấy {co_conc}"
    assert jobs["deploy"]["environment"] == "production"
    assert jobs["deploy"]["concurrency"] == {
        "group": "deploy-production",
        "cancel-in-progress": True,
    }


def test_deploy_chi_chay_sau_ket_luan_deploy_tuong_minh():
    jobs = _workflow(_DEPLOY)["jobs"]
    deploy_job = jobs["deploy"]
    assert deploy_job["needs"] == ["classify-changes", "reap-stale-production-runs"]
    assert deploy_job["if"] == (
        "needs.classify-changes.result == 'success' && "
        "needs.classify-changes.outputs.deploy == 'true' && "
        "needs.reap-stale-production-runs.result == 'success'"
    )
    assert jobs["classify-changes"]["outputs"]["deploy"] == (
        "${{ steps.plan.outputs.deploy }}"
    )


def test_workflow_doc_toan_bo_git_diff_va_luu_artifact_khi_block():
    job = _workflow(_DEPLOY)["jobs"]["classify-changes"]
    checkout = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkout) == 1
    assert checkout[0]["with"]["fetch-depth"] == 0

    plans = [s for s in job["steps"] if s.get("id") == "plan"]
    assert len(plans) == 1
    assert ".github/scripts/deploy_change_classifier.py classify" in plans[0]["run"]

    uploads = [s for s in job["steps"]
               if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(uploads) == 1
    assert uploads[0]["if"] == "always()"
    assert uploads[0]["with"]["if-no-files-found"] == "error"
    assert uploads[0]["with"]["retention-days"] == 90
    assert "github.run_attempt" in uploads[0]["with"]["name"]


def test_required_classifier_contract_canh_skip_directive():
    jobs = _workflow(_BACKEND_GATE)["jobs"]
    contract = jobs["classifier-contract"]
    checkout = [s for s in contract["steps"]
                if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkout) == 1 and checkout[0]["with"]["fetch-depth"] == 0
    guards = [s for s in contract["steps"]
              if "check-skip-directives" in str(s.get("run", ""))]
    assert len(guards) == 1
    assert set(guards[0]["env"]) == {"BASE_SHA", "HEAD_SHA", "PR_TITLE", "PR_BODY"}
    assert "if" not in guards[0]
    assert not guards[0].get("continue-on-error")


def test_moi_duong_github_cuc_bo_ma_deploy_dung_deu_la_runtime(classifier):
    doc = _workflow(_DEPLOY)
    paths = set()
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            uses = str(step.get("uses", ""))
            if uses.startswith("./.github/"):
                paths.add(uses[2:])
            run = str(step.get("run", ""))
            paths.update(re.findall(r"(?<![\w.-])(\.github/[\w./-]+)", run))
    assert ".github/scripts/deploy_change_classifier.py" in paths
    assert all(classifier.classify_path(path) == "runtime" for path in paths), paths


# --------------------------------------------------------------- HM2-A: SINK THẬT
#
# Bộ ca cũ chứng minh guard bắt được directive trong COMMIT, và chứng minh bốn
# biến `PR_TITLE`/`PR_BODY`/`BASE_SHA`/`HEAD_SHA` TỒN TẠI trong `env:` của bước.
# Không ca nào chứng minh title và body thật sự ĐƯỢC QUÉT.
#
# Đo được: xoá cả hai phần tử ``("pull_request.title", title)`` và
# ``("pull_request.body", body)`` khỏi ``parts`` trong ``check_skip_directives``
# thì TOÀN BỘ bộ cũ vẫn XANH — kể cả ca mang tên
# ``test_guard_skip_quet_tieu_de_body_va_moi_commit``, vì nó truyền title/body
# SẠCH rồi chỉ khẳng định finding ở ``commit[2]``.
#
# Bốn ca dưới đây mỗi ca vi phạm ĐÚNG MỘT bất biến, để khi đỏ thì biết đỏ vì gì.


def _khong_commit(classifier, monkeypatch):
    """Cắt đường git: ``parts`` chỉ còn title + body."""
    monkeypatch.setattr(classifier, "_commit_messages", lambda _b, _h: [])


def test_directive_trong_TIEU_DE_pr_bi_bat(classifier, monkeypatch):
    """Tiêu đề PR là message squash mặc định — đường ngắn nhất vào `main`."""
    _khong_commit(classifier, monkeypatch)
    found = classifier.check_skip_directives(
        _SHA_A, _SHA_B, "fix(ci): dọn nhanh [skip ci]", "body sạch")
    assert found == [{"source": "pull_request.title", "directive": "[skip ci]"}], (
        "directive trong TIÊU ĐỀ không bị bắt — thấy %r" % (found,))


def test_directive_trong_BODY_pr_bi_bat(classifier, monkeypatch):
    """Body cũng đi vào message của merge commit ở chế độ merge/squash."""
    _khong_commit(classifier, monkeypatch)
    found = classifier.check_skip_directives(
        _SHA_A, _SHA_B, "tiêu đề sạch", "mô tả bình thường\n\nskip-checks: true\n")
    # `SKIP_TRAILER_RE` neo `\s*$` nên `group(0)` nuốt luôn ký tự xuống dòng —
    # so nguyên văn ở đây là so nhầm thứ. Cái cần khoá là NGUỒN và nội dung
    # directive sau khi bỏ khoảng trắng.
    assert len(found) == 1, "directive trong BODY không bị bắt — thấy %r" % (found,)
    assert found[0]["source"] == "pull_request.body", (
        "bắt được nhưng gán sai nguồn: %r" % (found,))
    assert found[0]["directive"].strip() == "skip-checks: true"


def test_directive_trong_COMMIT_van_bi_bat(classifier, monkeypatch):
    """Nhánh cũ không được hỏng khi thêm hai nhánh mới."""
    monkeypatch.setattr(
        classifier, "_commit_messages",
        lambda _b, _h: ["commit sạch", "legacy\n\n[actions skip]"])
    found = classifier.check_skip_directives(
        _SHA_A, _SHA_B, "tiêu đề sạch", "body sạch")
    assert found == [{"source": "commit[2]", "directive": "[actions skip]"}], (
        "directive trong COMMIT không còn bị bắt — thấy %r" % (found,))


def test_tieu_de_body_commit_sach_thi_khong_bao_gi(classifier, monkeypatch):
    """Guard fail-closed không được là guard báo bừa."""
    monkeypatch.setattr(classifier, "_commit_messages", lambda _b, _h: ["commit sạch"])
    assert classifier.check_skip_directives(
        _SHA_A, _SHA_B,
        "docs: mô tả hành vi skip ci không có ngoặc",
        "skip-checks: false\n") == []


# --- tầng CLI: mã thoát + nguồn được nêu tên -------------------------------
#
# `check_skip_directives` đúng vẫn chưa đủ: bước CI gọi qua `_check_skip_command`,
# nơi title/body được đọc từ BIẾN MÔI TRƯỜNG. Nối dây sai tên biến ở tầng này
# làm guard mù trong khi mọi ca thuần vẫn xanh.


def _args_gia():
    return type("Args", (), {"base": _SHA_A, "head": _SHA_B})()


def test_cli_bao_do_va_NEU_TEN_nguon_khi_directive_o_tieu_de(
        classifier, monkeypatch, capsys):
    _khong_commit(classifier, monkeypatch)
    monkeypatch.setenv("PR_TITLE", "chore: gấp [ci skip]")
    monkeypatch.setenv("PR_BODY", "")
    rc = classifier._check_skip_command(_args_gia())
    ra = capsys.readouterr().out
    assert rc == 1, "CLI phải trả 1 khi có directive, trả %r" % rc
    assert "::error::" in ra and "pull_request.title" in ra, (
        "CLI không nêu đúng nguồn `pull_request.title` — người đọc log không "
        "biết phải sửa ở đâu. Thấy: %r" % ra)


def test_cli_bao_do_khi_directive_o_body(classifier, monkeypatch, capsys):
    _khong_commit(classifier, monkeypatch)
    monkeypatch.setenv("PR_TITLE", "tiêu đề sạch")
    monkeypatch.setenv("PR_BODY", "chi tiết\n\n[no ci]\n")
    rc = classifier._check_skip_command(_args_gia())
    assert rc == 1
    assert "pull_request.body" in capsys.readouterr().out


def test_cli_tra_0_khi_moi_nguon_deu_sach(classifier, monkeypatch, capsys):
    _khong_commit(classifier, monkeypatch)
    monkeypatch.setenv("PR_TITLE", "feat: thêm cổng")
    monkeypatch.setenv("PR_BODY", "không có gì đặc biệt")
    assert classifier._check_skip_command(_args_gia()) == 0
    assert "No Actions skip directive" in capsys.readouterr().out


def test_cli_doc_dung_TEN_bien_PR_TITLE_va_PR_BODY(classifier, monkeypatch, capsys):
    """Đổi tên biến ở workflow là đường làm guard mù mà không ai thấy.

    Ca này ghim đúng hai tên `PR_TITLE`/`PR_BODY`: đặt directive vào một tên
    KHÁC thì guard phải KHÔNG thấy gì (chứng minh nó chỉ đọc đúng hai tên ấy),
    còn đặt vào đúng tên thì phải đỏ.
    """
    _khong_commit(classifier, monkeypatch)
    monkeypatch.delenv("PR_TITLE", raising=False)
    monkeypatch.delenv("PR_BODY", raising=False)
    monkeypatch.setenv("PR_SUBJECT", "chore: gấp [ci skip]")
    assert classifier._check_skip_command(_args_gia()) == 0, (
        "guard đọc một biến ngoài PR_TITLE/PR_BODY — hợp đồng tên biến không "
        "còn là hợp đồng.")
    capsys.readouterr()
    monkeypatch.setenv("PR_TITLE", "chore: gấp [ci skip]")
    assert classifier._check_skip_command(_args_gia()) == 1


# --- cấu trúc workflow: guard nằm trên đường RẺ ---------------------------

_DEP_AUDIT = _goc_repo() / ".github" / "workflows" / "dependency-audit.yml"


def test_guard_tieu_de_nam_trong_required_python_dependencies():
    """`edited` phải ở workflow RẺ, và guard phải ở cùng workflow ấy.

    Đặt `edited` ở `backend-test.yml` cũng bịt được lỗ nhưng bắt tám shard chạy
    lại (~37 phút) cho mỗi lần sửa tiêu đề.
    """
    wf = _workflow(_DEP_AUDIT)
    types = _on_block(wf)["pull_request"]["types"]
    assert "edited" in types, "dependency-audit thiếu `edited`; thấy %r" % (types,)

    job = wf["jobs"]["python-audit"]
    assert job["name"] == "Python Dependencies"
    guards = [s for s in job["steps"] if "check-skip-directives" in str(s.get("run", ""))]
    assert len(guards) == 1, "cần đúng một guard trong python-audit, thấy %d" % len(guards)
    g = guards[0]
    assert set(g["env"]) == {"BASE_SHA", "HEAD_SHA", "PR_TITLE", "PR_BODY"}
    assert str(g.get("if", "")).strip() == "github.event_name == 'pull_request'"
    assert "github.workspace" in str(g.get("working-directory", ""))
    assert not g.get("continue-on-error")

    co = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(co) == 1 and co[0]["with"]["fetch-depth"] == 0


# ===========================================================================
# scripts/deploy.sh — cổng ghim SHA + cổng health (vá 09-09-2026)
# ===========================================================================
# Hai lỗ được đóng ở đây, và cả hai chỉ chứng minh được bằng cách THI HÀNH
# THẬT `scripts/deploy.sh`, không phải bằng cách grep nội dung nó:
#
#   * TOCTOU ghim SHA: `deploy.yml` đưa VPS tới đúng `$SHA_MONG_DOI` rồi mới gọi
#     script, nhưng Step 2 của script `git pull origin main` — kéo TIP nhánh, đẩy
#     cây vượt qua commit vừa xác minh. Job dừng ở `environment: production` chờ
#     duyệt nên khoảng hở dài bằng thời gian chờ approve.
#   * Cổng health đọc bằng `grep -q "healthy"` — khớp SUBSTRING nên `unhealthy`
#     cũng lọt; và frontend hết timeout thì KHÔNG có nhánh nào chặn.
#
# Bộ ca dưới đây tự dựng sân khấu riêng (stub `docker`/`git`) thay vì dùng lại
# harness của `test_deploy_startup_gates.py`, để hai tệp không ràng buộc nhau.

_DEPLOY_SH = _goc_repo() / "scripts" / "deploy.sh"

_SHA_HEAD = "c" * 40          # HEAD mà stub `git rev-parse` trả về
_SHA_KHAC = "d" * 40          # một SHA hợp lệ nhưng KHÁC HEAD

_MOC_THANH_CONG = "Deployment completed successfully!"
_MOC_NGINX = "nginx-apply"
_MOC_GHIM = "Cây đã ghim tại"

_STUB_DOCKER_DH = r"""#!/usr/bin/env bash
_tat_ca="$*"
echo "docker $_tat_ca" >> "$QLTS_STUB_LOG"

# CID giả phải theo ĐÚNG hợp đồng production: `docker compose ps -q` và
# `docker inspect` trả ID ĐẦY ĐỦ 64 hex thường (đã đo: `ps -q` của compose ra
# 64, `docker ps -q` ra 12). Một fixture trả "cid-backend" làm cổng schema của
# marker không thể đòi 64 hex — tức fixture giả đang định nghĩa hợp đồng thay
# cho production. Mỗi service một chữ số hex riêng nên vẫn phân biệt bằng `case`.
_cid_gia() {
    case "$1" in
        backend)       _cc=1 ;;
        celery-worker) _cc=2 ;;
        celery-beat)   _cc=3 ;;
        frontend)      _cc=4 ;;
        mot)           _cc=6 ;;
        hai)           _cc=7 ;;
        *)             _cc=5 ;;
    esac
    _c8=$_cc$_cc$_cc$_cc$_cc$_cc$_cc$_cc
    printf '%s\n' "$_c8$_c8$_c8$_c8$_c8$_c8$_c8$_c8"
}

case "$_tat_ca" in
    *compose*" config "*)
        # `_ra_dan_xuat_dich_vu` hỏi MODEL Compose để dẫn xuất danh sách service
        # phải ghim, thay cho một hằng chép tay. Sân khấu này khai BỐN service
        # ứng dụng — đó là thế giới mà bộ test này mô phỏng.
        #
        # ⚠️ Bất biến "bản ghim phủ HẾT tập bị build" KHÔNG thuộc về đây: nó đọc
        # `docker-compose.yml` THẬT và có một tầng chủ sở hữu duy nhất là
        # `tests/unit/test_rollback_asset_contract.py`. Khai lại 5 ảnh ở đây là
        # đẻ ra một nguồn chuẩn thứ hai, rồi hai bản sẽ trôi khỏi nhau.
        #
        # `STUB_COMPOSE_CONFIG` lái các ca HỎNG (xem kiểm ngược bên dưới) — nó là
        # biến của SÂN KHẤU, không phải bypass trong script production.
        case "${STUB_COMPOSE_CONFIG:-ok}" in
            rong)  exit 0 ;;
            hong)  printf 'khong phai json\n'; exit 0 ;;
            rc)    exit 77 ;;
            thieu) printf '{"services": {"postgres": {"image": "postgres:16"}}}\n'; exit 0 ;;
        esac
        cat <<'__QLTS_JSON__'
{"services": {
  "backend":       {"build": {"context": "./Backend_FastAPI", "dockerfile": "Dockerfile"}},
  "celery-worker": {"build": {"context": "./Backend_FastAPI", "dockerfile": "Dockerfile"}},
  "celery-beat":   {"build": {"context": "./Backend_FastAPI", "dockerfile": "Dockerfile"}},
  "frontend":      {"build": {"context": "./frontend", "dockerfile": "Dockerfile"}},
  "postgres":      {"image": "postgres:16-alpine"},
  "redis":         {"image": "redis:7-alpine"}
}}
__QLTS_JSON__
        exit 0
        ;;
    *" ps -q "*)
        # Step 3b/8c hỏi ID container theo TỪNG service. Khác hẳn `ps -aq` của
        # vòng chờ health bên dưới, và KHÔNG chịu ảnh hưởng `STUB_PSQ_*` —
        # những biến ấy dựng ca cho cổng health, không phải cho tài sản rollback.
        for _sv in backend celery-worker celery-beat frontend; do
            case "$_tat_ca" in
                *" $_sv"*) _cid_gia "$_sv"; exit 0 ;;
            esac
        done
        echo "STUB: 'ps -q' service lạ: $_tat_ca" >&2
        exit 92
        ;;
    "tag "*)
        exit 0
        ;;
    "image inspect"*)
        # Cổng chống va chạm tag của Step 3b hỏi "tag này CÓ chưa?".
        # Mặc định CHƯA (exit 1) ⇒ deploy được phép tạo tag mới.
        exit 1
        ;;
    *" ps -aq "*)
        [ "${STUB_PSQ_RC:-0}" != "0" ] && exit "${STUB_PSQ_RC}"
        [ "${STUB_PSQ_EMPTY:-0}" = "1" ] && exit 0
        [ "${STUB_PSQ_NHIEU:-0}" = "1" ] && { _cid_gia mot; _cid_gia hai; exit 0; }
        case "$_tat_ca" in
            *frontend*) _cid_gia frontend ;;
            *)          _cid_gia backend  ;;
        esac
        exit 0
        ;;
    inspect*)
        # `{{.Image}}` phục vụ Step 3b/8c (tài sản rollback), KHÔNG phải cổng
        # health. Nó phải trả lời TRƯỚC `STUB_INSPECT_RC` — biến ấy được viết ra
        # để dựng ca "inspect hỏng" cho vòng chờ healthy; nếu nó cũng làm hỏng
        # `.Image` thì deploy dừng ở Step 3b và ca kia xanh vì lý do sai.
        case "$_tat_ca" in
            *".Image"*)
                for _sv in backend celery-worker celery-beat frontend; do
                    case "$_tat_ca" in
                        *"$(_cid_gia "$_sv")"*)
                            case "$_sv" in
                                backend)       _k=b ;;
                                celery-worker) _k=c ;;
                                celery-beat)   _k=d ;;
                                frontend)      _k=f ;;
                            esac
                            _r=$_k$_k$_k$_k$_k$_k$_k$_k
                            echo "sha256:$_r$_r$_r$_r$_r$_r$_r$_r"
                            exit 0 ;;
                    esac
                done
                echo "STUB: '{{.Image}}' container lạ: $_tat_ca" >&2
                exit 93
                ;;
        esac
        [ "${STUB_INSPECT_RC:-0}" != "0" ] && exit "${STUB_INSPECT_RC}"
        case "$_tat_ca" in
            *State.Status*)
                case "$_tat_ca" in
                    *"$(_cid_gia frontend)"*) echo "${STUB_STATUS_FRONTEND:-running}" ;;
                    *)              echo "${STUB_STATUS_BACKEND:-running}"  ;;
                esac
                ;;
            *ExitCode*)
                echo "1"
                ;;
            *)
                case "$_tat_ca" in
                    *"$(_cid_gia frontend)"*) echo "${STUB_HEALTH_FRONTEND:-healthy}" ;;
                    *)              echo "${STUB_HEALTH_BACKEND:-healthy}"  ;;
                esac
                ;;
        esac
        exit 0
        ;;
    *pg_isready*)  exit 0 ;;
    *pg_dump*)     printf -- '-- ban sao gia\nSELECT 1;\n'; exit 0 ;;
    *)             exit 0 ;;
esac
"""

_STUB_GIT_DH = r"""#!/usr/bin/env bash
echo "git $*" >> "$QLTS_STUB_LOG"
case "$1" in
    rev-parse)
        [ "${STUB_GIT_REVPARSE_RC:-0}" != "0" ] && exit "${STUB_GIT_REVPARSE_RC}"
        echo "${STUB_GIT_HEAD:-cccccccccccccccccccccccccccccccccccccccc}"
        ;;
    pull) echo "[git gia] pull" ;;
    log)  : ;;
    *)    : ;;
esac
exit 0
"""

_STUB_NGINX_APPLY_DH = r"""#!/usr/bin/env bash
echo "nginx-apply $*" >> "$QLTS_STUB_LOG"
exit 0
"""

_STUB_ROLLBACK_PREFLIGHT_DH = r"""#!/usr/bin/env bash
# Ghi lại HỢP ĐỒNG, không chỉ "đã được gọi": thiếu `LOCAL_ONLY=1` là preflight
# đi nhánh GHCR và dừng ở cổng đăng nhập — ca nào cần thấy điều đó phải thấy.
_L="$QLTS_STUB_LOG"
echo "rollback-preflight tag=${QLTS_ROLLBACK_TAG:-KHONG_DAT}" >> "$_L"
echo "rollback-preflight local_only=${QLTS_ROLLBACK_LOCAL_ONLY:-KHONG_DAT}" >> "$_L"
exit "${STUB_ROLLBACK_PREFLIGHT_RC:-0}"
"""

# Bản đồ image ID phải TRÙNG KHÍT `docker` giả ở trên. Lệch một ký tự là mọi ca
# marker-khớp biến thành ca marker-lệch mà không ai nhận ra.
_ANH_DH = {
    "backend": "sha256:" + "b" * 64,
    "celery-worker": "sha256:" + "c" * 64,
    "celery-beat": "sha256:" + "d" * 64,
    "frontend": "sha256:" + "f" * 64,
}
_DICH_VU_DH = ("backend", "celery-worker", "celery-beat", "frontend")
_SHA_MARKER_DH = "a" * 40  # SHA của lượt deploy TRƯỚC — khác `_SHA_HEAD`


def _cid_gia(sv: str) -> str:
    """CID giả — ID ĐẦY ĐỦ 64 hex thường, đúng hợp đồng production.

    Phải khớp từng byte với hàm `_cid_gia` trong stub `docker`: marker do
    script ghi lấy CID từ stub, còn các ca kiểm ở đây so chuỗi trên tệp.
    """
    ky = {"backend": "1", "celery-worker": "2", "celery-beat": "3",
          "frontend": "4", "mot": "6", "hai": "7"}.get(sv, "5")
    return ky * 64


def _marker_dh(sha: str = _SHA_MARKER_DH) -> str:
    """Marker hợp lệ: SHA đã deploy + image ID của bốn container đang chạy."""
    dong = [
        "# marker-version\t1",
        f"# deployed-sha\t{sha}",
        "# deployed-at\t2026-09-18T00:00:00Z",
    ]
    dong += [f"{s}\t{_ANH_DH[s]}\t{_cid_gia(s)}" for s in _DICH_VU_DH]
    return "\n".join(dong) + "\n"


_ENV_PROD_DH = (
    "DOMAIN=vidu.test\n"
    "POSTGRES_USER=qlts\n"
    "POSTGRES_DB=qlts_production\n"
    "POSTGRES_PASSWORD=matkhau-gia\n"
)

_bo_qua_neu_khong_posix_dh = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None,
    reason="cần bash và PATH kiểu POSIX để thi hành thật scripts/deploy.sh",
)


# Shim ngữ cảnh (root + root:root) dùng CHUNG với `test_deploy_startup_gates`.
# Đây là lớp mô phỏng môi trường, không phải stub nghiệp vụ: khai bản thứ hai ở
# đây là mời hai bản trôi khỏi nhau, rồi một bộ xanh còn bộ kia đỏ vì ngữ cảnh.
from tests.unit.test_deploy_startup_gates import (  # noqa: E402
    _sandbox_cua,
    _viet_shim_ngu_canh,
)


def _san_khau_dh(
    tmp_path: Path, deploy_sh: str | None = None, marker: str | None = "MAC_DINH"
) -> Path:
    """``marker``: ``"MAC_DINH"`` ⇒ marker hợp lệ khớp 4/4 image ID giả lập;
    ``None`` ⇒ KHÔNG tạo marker; chuỗi khác ⇒ ghi nguyên văn chuỗi đó."""
    goc = tmp_path / "qlts"
    (goc / "scripts").mkdir(parents=True)
    (goc / "nginx" / "templates").mkdir(parents=True)
    (goc / "bin").mkdir()
    _viet_shim_ngu_canh(goc)

    # Hop dong MOI: $OPS phai san 700 root:root; deploy.sh khong tu sua.
    (goc / "ops").mkdir(mode=0o700)
    os.chmod(goc / "ops", 0o700)
    if marker is not None:
        _mk = goc / "ops" / "last-deploy.marker"
        _mk.write_text(
            _marker_dh() if marker == "MAC_DINH" else marker,
            encoding="utf-8", newline="\n",
        )
        os.chmod(_mk, 0o600)

    than = deploy_sh if deploy_sh is not None else _DEPLOY_SH.read_text(encoding="utf-8")
    (goc / "scripts" / "deploy.sh").write_text(than, encoding="utf-8", newline="\n")
    for ten, noi_dung in (
        ("scripts/nginx-apply.sh", _STUB_NGINX_APPLY_DH),
        ("scripts/rollback-preflight.sh", _STUB_ROLLBACK_PREFLIGHT_DH),
        ("bin/docker", _STUB_DOCKER_DH),
        ("bin/git", _STUB_GIT_DH),
    ):
        duong = goc / ten
        duong.write_text(noi_dung, encoding="utf-8", newline="\n")
        duong.chmod(0o755)

    (goc / ".env.production").write_text(_ENV_PROD_DH, encoding="utf-8", newline="\n")
    (goc / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8", newline="\n")
    (goc / "nginx" / "templates" / "default.conf.template").write_text(
        "server { server_name ${DOMAIN}; }\n", encoding="utf-8", newline="\n"
    )
    return goc


def _chay_dh(goc: Path, **kich_ban: str):
    nhat_ky = goc / "lenh.log"
    nhat_ky.write_text("", encoding="utf-8")
    moi_truong = {
        **os.environ,
        "PATH": f"{goc / 'bin'}:{os.environ.get('PATH', '')}",
        "QLTS_STUB_LOG": str(nhat_ky),
        # Mặc định của deploy.sh là /opt/qlts-ops/rollback — tuyệt đối không để
        # test ghi ra đó. Mỗi ca có thư mục ops riêng trong tmp_path.
        "QLTS_ROLLBACK_OPS_DIR": str(goc / "ops"),
        # Ngữ cảnh production mà shim `stat`/`id` mô phỏng.
        "QLTS_TEST_SANDBOX": _sandbox_cua(goc),
    }
    # Các biến điều khiển PHẢI đến từ kịch bản của ca, không từ môi trường
    # người chạy — nếu không, một ca có thể xanh mà chẳng chứng minh gì.
    for bien in (
        # Hai cổng thoát hiểm của Step 3b: nếu môi trường người chạy đang đặt
        # chúng thì MỌI ca dưới đây bỏ qua khối tài sản và xanh giả.
        "QLTS_SKIP_ROLLBACK_ASSET", "QLTS_SKIP_ROLLBACK_ASSET_REASON",
        # Lái shim ngữ cảnh — sót lại trong shell người chạy là xanh giả.
        "QLTS_TEST_UID", "QLTS_TEST_CHU_SO_HUU",
        "STUB_ROLLBACK_PREFLIGHT_RC",
        "SHA_MONG_DOI", "QLTS_HEALTH_TIMEOUT", "STUB_GIT_HEAD", "STUB_GIT_REVPARSE_RC",
        "STUB_HEALTH_BACKEND", "STUB_HEALTH_FRONTEND", "STUB_STATUS_BACKEND",
        "STUB_STATUS_FRONTEND", "STUB_INSPECT_RC", "STUB_PSQ_RC", "STUB_PSQ_EMPTY",
        "STUB_PSQ_NHIEU", "RUN_MIGRATIONS_ON_STARTUP",
        "RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP", "RUN_CASBIN_LOAD_ON_STARTUP",
    ):
        moi_truong.pop(bien, None)
    # Hạn chờ ngắn cho MỌI ca: cùng ngữ nghĩa, nhưng một bộ 19 ca không phải đốt
    # 60 giây mỗi lần chạm nhánh quá hạn. Ca nào cần con số khác thì tự đặt lại.
    moi_truong["QLTS_HEALTH_TIMEOUT"] = "4"
    moi_truong.update(kich_ban)
    ket = _sp.run(
        ["bash", "scripts/deploy.sh"],
        cwd=str(goc), env=moi_truong, capture_output=True, text=True, timeout=300,
    )
    return ket, nhat_ky.read_text(encoding="utf-8"), (ket.stdout or "") + (ket.stderr or "")


# --- I. Cổng ghim SHA -------------------------------------------------------


@_bo_qua_neu_khong_posix_dh
def test_dh_sha_khop_thi_di_tiep_va_khong_pull(tmp_path: Path) -> None:
    """ĐỐI CHỨNG cho cổng SHA: khớp thì đi tiếp, và TUYỆT ĐỐI không `git pull`."""
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode == 0, f"đường thuận lợi mà chặn (rc={ket.returncode}):\n{ra[-2000:]}"
    assert _MOC_GHIM in ra, f"không thấy log xác nhận đã ghim:\n{ra[-1500:]}"
    assert "git pull" not in nhat_ky, (
        f"có SHA_MONG_DOI mà VẪN `git pull` — đúng lỗ TOCTOU đang vá:\n{nhat_ky}"
    )


@_bo_qua_neu_khong_posix_dh
def test_dh_sha_lech_thi_chan_truoc_moi_mutation(tmp_path: Path) -> None:
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_KHAC, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode != 0, "HEAD lệch mà deploy vẫn thoát 0"
    assert _SHA_HEAD in ra and _SHA_KHAC in ra, f"phải nêu cả hai SHA:\n{ra[-800:]}"
    for cam in ("pg_dump", "build --parallel", "upgrade head"):
        assert cam not in nhat_ky, f"đã chạy `{cam}` dù cổng SHA lệch:\n{nhat_ky}"
    assert "git pull" not in nhat_ky, "đã `git pull` dù cổng SHA lệch"


@_bo_qua_neu_khong_posix_dh
@pytest.mark.parametrize(
    "ten_ca,gia_tri",
    [
        ("quá ngắn", "abc123"),
        ("chữ HOA", "C" * 40),
        ("39 ký tự", "c" * 39),
        ("41 ký tự", "c" * 41),
        ("có ký tự lạ", "g" * 40),
        ("khoảng trắng hai đầu", " " + "c" * 40 + " "),
        ("khoảng trắng ở giữa", "c" * 20 + " " + "c" * 19),
        ("chỉ khoảng trắng", "   "),
    ],
)
def test_dh_sha_sai_dinh_dang_thi_chan(tmp_path: Path, ten_ca: str, gia_tri: str) -> None:
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, _ = _chay_dh(goc, SHA_MONG_DOI=gia_tri, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode != 0, f"{ten_ca}: SHA sai định dạng mà vẫn thoát 0"
    assert "git pull" not in nhat_ky, f"{ten_ca}: đã `git pull` dù SHA sai định dạng"


@_bo_qua_neu_khong_posix_dh
def test_dh_rev_parse_loi_thi_chan(tmp_path: Path) -> None:
    """Không đọc được HEAD ⇒ KHÔNG đoán bừa là đang đứng đúng chỗ."""
    goc = _san_khau_dh(tmp_path)
    ket, _, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_REVPARSE_RC="1")

    assert ket.returncode != 0, "git rev-parse hỏng mà deploy vẫn đi tiếp"
    assert "không đọc được HEAD" in ra, f"thông điệp không nêu nguyên nhân:\n{ra[-800:]}"


@_bo_qua_neu_khong_posix_dh
def test_dh_sha_khong_hien_dien_thi_di_duong_manual(tmp_path: Path) -> None:
    """UNSET THẬT ⇒ giữ hành vi manual (VẪN `git pull`, VẪN unpinned)."""
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc)

    assert ket.returncode == 0, f"đường manual bị chặn nhầm:\n{ra[-1500:]}"
    assert "git pull" in nhat_ky, "đường manual phải giữ nguyên `git pull origin main`"
    assert "KHÔNG HIỆN DIỆN" in ra, (
        f"cảnh báo phải nói đúng trạng thái 'không hiện diện':\n{ra[-800:]}"
    )
    assert "KHÔNG có bảo đảm ghim SHA" in ra, (
        "đường manual phải nói rõ nó KHÔNG được ghim — im lặng ở đây là overclaim"
    )


@_bo_qua_neu_khong_posix_dh
def test_dh_sha_co_mat_nhung_rong_thi_chan(tmp_path: Path) -> None:
    """CÓ MẶT + RỖNG là LỖI, không phải 'chạy tay'.

    `[ -n "${SHA_MONG_DOI:-}" ]` gộp unset với set-empty, nên một workflow đã
    forward biến mà giá trị không tới nơi (`envs:` thiếu tên, secret rỗng,
    expression sai) sẽ rơi xuống nhánh manual, `git pull` tip mới và thoát 0 —
    cổng tự tắt đúng lúc cần canh nhất, không một dòng log nào nói ra.
    """
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI="")

    assert ket.returncode != 0, f"set-empty mà deploy vẫn thoát 0:\n{ra[-1500:]}"
    assert "CÓ MẶT nhưng RỖNG" in ra, f"thông điệp phải phân biệt với unset:\n{ra[-800:]}"
    assert "KHÔNG HIỆN DIỆN" not in ra, (
        "set-empty KHÔNG được báo là 'không hiện diện' — hai trạng thái khác nhau"
    )
    assert "git pull" not in nhat_ky, f"set-empty mà VẪN `git pull`:\n{nhat_ky}"
    for cam in ("pg_dump", "build --parallel", "upgrade head", "nginx-apply"):
        assert cam not in nhat_ky, f"set-empty mà đã chạy `{cam}`:\n{nhat_ky}"


# --- II. Cổng health --------------------------------------------------------


@_bo_qua_neu_khong_posix_dh
def test_dh_duong_thuan_loi_healthy_thi_exit_0(tmp_path: Path) -> None:
    """ĐỐI CHỨNG BẮT BUỘC: thiếu ca này thì `error "chặn hết"` cũng xanh."""
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode == 0, f"cả hai healthy mà vẫn chặn:\n{ra[-2000:]}"
    assert _MOC_NGINX in nhat_ky, f"không tới được nginx-apply:\n{nhat_ky[-1500:]}"
    assert _MOC_THANH_CONG in ra, "không in dòng hoàn tất"


@_bo_qua_neu_khong_posix_dh
@pytest.mark.parametrize(
    "ten_ca,kich_ban,manh_mong_doi",
    [
        ("backend unhealthy",  {"STUB_HEALTH_BACKEND": "unhealthy"},  "'backend' UNHEALTHY"),
        ("frontend unhealthy", {"STUB_HEALTH_FRONTEND": "unhealthy"}, "'frontend' UNHEALTHY"),
        ("backend starting → quá hạn",
         {"STUB_HEALTH_BACKEND": "starting", "QLTS_HEALTH_TIMEOUT": "4"},
         "'backend' quá hạn 4s"),
        ("frontend starting → quá hạn",
         {"STUB_HEALTH_FRONTEND": "starting", "QLTS_HEALTH_TIMEOUT": "4"},
         "'frontend' quá hạn 4s"),
        ("không khai healthcheck",
         {"STUB_HEALTH_BACKEND": "khong-co-healthcheck"},
         "KHÔNG khai healthcheck"),
        ("inspect lỗi",   {"STUB_INSPECT_RC": "1"},  "docker inspect THẤT BẠI"),
        ("ps -aq lỗi",    {"STUB_PSQ_RC": "1"},      "không liệt kê được container"),
        ("0 container",   {"STUB_PSQ_EMPTY": "1"},   "không thấy container nào"),
        ("nhiều container", {"STUB_PSQ_NHIEU": "1"}, "đang có 2 container"),
        ("backend exited", {"STUB_STATUS_BACKEND": "exited"}, "đã DỪNG"),
    ],
)
def test_dh_moi_trang_thai_khong_healthy_deu_chan(
    tmp_path: Path, ten_ca: str, kich_ban: dict, manh_mong_doi: str
) -> None:
    """Mỗi ca vi phạm ĐÚNG MỘT bất biến, và đòi ĐÚNG thông điệp của bất biến ấy.

    Chỉ khẳng định `returncode != 0` là không đủ: một đột biến làm mất nhánh
    riêng vẫn có thể rơi vào nhánh quá hạn và giữ rc≠0, che mất hồi quy.
    """
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(
        goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD=_SHA_HEAD, **kich_ban
    )

    assert ket.returncode != 0, f"{ten_ca}: KHÔNG healthy mà deploy vẫn thoát 0:\n{ra[-1500:]}"
    assert manh_mong_doi in ra, f"{ten_ca}: thiếu thông điệp {manh_mong_doi!r}:\n{ra[-1500:]}"
    assert _MOC_NGINX not in nhat_ky, f"{ten_ca}: đã tới nginx-apply dù cổng health đỏ"
    assert _MOC_THANH_CONG not in ra, f"{ten_ca}: đã in dòng hoàn tất dù cổng health đỏ"


# =============================================================================
# Step 3b không được nuốt các cổng ĐỨNG TRƯỚC nó
# =============================================================================
# Khối tài sản rollback nằm sau Step 3. Thứ tự ấy PHẢI giữ: một cấu hình hỏng
# ở Step 1 hay một cây lệch SHA ở Step 2 phải dừng deploy với ĐÚNG lý do của
# nó, chứ không phải với "THIẾU marker". Nếu Step 3b bị kéo lên trước, mọi ca
# dưới đây vẫn "đỏ" — nhưng đỏ vì lý do sai, và cổng SHA coi như mất phép kiểm.
#
# Cả ba ca chạy với `marker=None` (KHÔNG có marker) để phép kiểm có nghĩa:
# nếu deploy chạm tới Step 3b thì nó chắc chắn báo thiếu marker.


@_bo_qua_neu_khong_posix_dh
def test_dh_cong_sha_do_thi_dung_TRUOC_khi_can_marker(tmp_path: Path) -> None:
    goc = _san_khau_dh(tmp_path, marker=None)
    ket, nhat_ky, ra = _chay_dh(
        goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD="d" * 40
    )

    assert ket.returncode != 0, "cây lệch SHA mà deploy vẫn thoát 0"
    assert "SHA_MONG_DOI" in ra or "được sinh cho" in ra, (
        f"phải dừng vì cổng SHA:\n{ra[-1500:]}"
    )
    assert "marker" not in ra.lower(), (
        "dừng vì THIẾU MARKER thay vì vì cổng SHA — Step 3b đã bị kéo lên trước "
        f"Step 2:\n{ra[-1500:]}"
    )


@_bo_qua_neu_khong_posix_dh
def test_dh_sha_rong_thi_dung_TRUOC_khi_can_marker(tmp_path: Path) -> None:
    """Biến CÓ MẶT nhưng RỖNG là ca riêng — không được rơi vào đường manual."""
    goc = _san_khau_dh(tmp_path, marker=None)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI="")

    assert ket.returncode != 0
    assert "RỖNG" in ra or "RONG" in ra, f"phải dừng vì SHA rỗng:\n{ra[-1500:]}"
    assert "marker" not in ra.lower(), (
        f"dừng vì thiếu marker thay vì vì SHA rỗng:\n{ra[-1500:]}"
    )


@_bo_qua_neu_khong_posix_dh
def test_dh_thieu_env_production_thi_dung_TRUOC_khi_can_marker(tmp_path: Path) -> None:
    """Step 1 (thiếu `.env.production`) phải chặn sớm hơn Step 3b."""
    goc = _san_khau_dh(tmp_path, marker=None)
    (goc / ".env.production").unlink()
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode != 0
    assert ".env.production" in ra, f"phải dừng vì thiếu .env.production:\n{ra[-1500:]}"
    assert "marker" not in ra.lower(), (
        f"dừng vì thiếu marker thay vì vì thiếu .env.production:\n{ra[-1500:]}"
    )


@_bo_qua_neu_khong_posix_dh
def test_dh_duong_thuan_loi_DI_QUA_step_3b_va_tao_tai_san(tmp_path: Path) -> None:
    """Đối chứng dương tính: đường thuận lợi phải THẬT SỰ đi qua Step 3b.

    Không có ca này thì ba ca trên có thể xanh chỉ vì deploy chưa bao giờ chạm
    tới khối tài sản — tức phép kiểm "không nhắc marker" trở nên vô nghĩa.
    """
    goc = _san_khau_dh(tmp_path)
    ket, nhat_ky, ra = _chay_dh(goc, SHA_MONG_DOI=_SHA_HEAD, STUB_GIT_HEAD=_SHA_HEAD)

    assert ket.returncode == 0, f"đường thuận lợi mà chặn:\n{ra[-2500:]}"
    for dv in _DICH_VU_DH:
        assert f"docker tag {_ANH_DH[dv]} qlts-{dv}:pre-" in nhat_ky, (
            f"Step 3b không ghim ảnh của '{dv}':\n{nhat_ky}"
        )
    assert "rollback-preflight local_only=1" in nhat_ky, (
        f"preflight phải chạy ở chế độ local-only:\n{nhat_ky}"
    )
    ban_ke = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert len(ban_ke) == 1, f"phải xuất bản đúng một bản kê, thấy {ban_ke}"
    assert f"# git-rev\t{_SHA_MARKER_DH}" in ban_ke[0].read_text(encoding="utf-8"), (
        "bản kê phải ghim SHA từ MARKER (phiên bản cũ), không phải HEAD hiện tại"
    )


# ---------------------------------------------------------------------------
# Reaper: run production chờ duyệt cho SHA đã bị `main` vượt qua phải bị huỷ
# ---------------------------------------------------------------------------
#
# Vì sao mục này tồn tại — đo 24-09-2026, deployment 6637504446:
# `deploy` là job DUY NHẤT mang `environment` + `concurrency: deploy-production`.
# Một push SAFE_NO_DEPLOY làm job ấy bị `if:` loại ⇒ nó không bao giờ vào nhóm
# concurrency ⇒ `cancel-in-progress` không chạy ⇒ run cũ nằm `waiting` với một
# SHA mà cổng SHA chắc chắn sẽ từ chối.
#
# Số đo: ba push DEPLOY liên tiếp dọn được run cũ trong 11-16 giây; push safe
# `0b2dd8a7` (xong sau 14 giây) KHÔNG dọn gì, để 6637504446 treo thêm 83 phút
# rồi đỏ ngay sau khi được approve. Production không hại, nhưng một lượt phê
# duyệt bị đốt và deployment đỏ vĩnh viễn.
#
# Các ca dưới đây **thi hành đúng đoạn Python đã ship** trong `deploy.yml`.
# Một bản chép tay vào test chỉ chứng minh giả định của người viết test.

_TEN_REAPER = "reap-stale-production-runs"
_TIP = "c" * 40
_SHA_CU = "a" * 40


def _job_reaper() -> dict:
    jobs = _workflow(_DEPLOY)["jobs"]
    assert _TEN_REAPER in jobs, f"thiếu job {_TEN_REAPER} trong deploy.yml"
    return jobs[_TEN_REAPER]


def _ma_reaper() -> str:
    """Nguyên văn đoạn Python đã ship trong bước huỷ run."""
    buoc = _job_reaper()["steps"]
    assert len(buoc) == 1, f"reaper phải có đúng một bước, thấy {len(buoc)}"
    m = re.search(r"<<'PY'\n(.*?)\nPY\s*$", buoc[0]["run"], re.S)
    assert m, "không trích được đoạn Python của reaper"
    return m.group(1)


def _kiem_reaper_luon_chay(doc: dict) -> None:
    """Tách riêng để ca đột biến chứng minh được phép kiểm này ĐỎ được."""
    job = doc["jobs"][_TEN_REAPER]
    assert job.get("if") == "always()", (
        "reaper phải `always()`: ca cần dọn nhất CHÍNH LÀ push SAFE_NO_DEPLOY, "
        f"nhận {job.get('if')!r}"
    )


# --- cấu trúc ---------------------------------------------------------------


def test_reaper_ton_tai_va_luon_chay():
    _kiem_reaper_luon_chay(_workflow(_DEPLOY))
    assert _job_reaper()["needs"] == "classify-changes"


def test_dot_bien_gate_reaper_theo_deploy_thi_DO():
    """Gate reaper theo `deploy == 'true'` là tái tạo ĐÚNG lỗi 6637504446."""
    doc = _workflow(_DEPLOY)
    doc["jobs"][_TEN_REAPER]["if"] = "needs.classify-changes.outputs.deploy == 'true'"
    with pytest.raises(AssertionError):
        _kiem_reaper_luon_chay(doc)


def test_reaper_khong_environment_khong_concurrency():
    """Job dọn thứ đang chờ duyệt thì không được tự đi chờ duyệt.

    Và không được mượn nhóm `deploy-production`: hành vi "job không có
    environment vào nhóm có huỷ nổi job đang chờ duyệt hay không" CHƯA AI ĐO.
    """
    job = _job_reaper()
    assert "environment" not in job
    assert "concurrency" not in job


def test_reaper_chi_xin_dung_quyen_actions_write():
    """Không `contents`, không `deployments`, không `packages`.

    `deployments: write` không cần: deployment tự chuyển `error` khi run bị
    huỷ (đo 24-09: 6630723643 → error đúng giây run 35958984186 bị huỷ).
    """
    assert _job_reaper()["permissions"] == {"actions": "write"}


def test_deploy_phu_thuoc_reaper_o_CA_needs_LAN_if():
    """Chỉ thêm vào `needs` là CHƯA ĐỦ.

    Một job khai `if:` tuỳ biến thì GitHub BỎ yêu cầu `success()` ngầm của
    `needs`. Thiếu vế `result == 'success'` thì reaper đỏ — ví dụ HTTP 403 vì
    không được cấp `actions: write` — mà `deploy` vẫn chạy: cơ chế dọn stale
    tự biến thành fail-open, đúng thứ nó sinh ra để loại bỏ.
    """
    job = _workflow(_DEPLOY)["jobs"]["deploy"]
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert _TEN_REAPER in needs, f"`deploy` phải `needs` reaper, thấy {needs}"
    assert f"needs.{_TEN_REAPER}.result == 'success'" in job["if"], (
        f"`if` của deploy phải đòi reaper thành công, nhận: {job['if']!r}"
    )


# --- hành vi: thi hành đoạn đã ship ------------------------------------------


_KHONG_DAT = object()


class _PhanHoiGia:
    def __init__(self, status, payload, tho=None):
        self.status = status
        if tho is not None:
            self._raw = tho          # byte thô, để giả lập thân KHÔNG phải JSON
        else:
            self._raw = b"" if payload is None else json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _ban_ghi_run(rid, sha, *, status="waiting", so=1):
    return {"id": rid, "head_sha": sha, "status": status, "run_number": so}


def _thi_hanh_reaper(
    monkeypatch,
    *,
    danh_sach,
    tip=_TIP,
    run_id=900,
    so_hieu=9,
    ma_liet_ke=200,
    ma_cancel=None,
    doc_lai=None,
    doc_lai_ma=200,
    than_liet_ke=_KHONG_DAT,
    tho_liet_ke=None,
    loi_mang=None,
    ma_nguon=None,
):
    ma_cancel = ma_cancel or {}
    doc_lai = doc_lai or {}
    da_huy = []
    da_goi = []

    def urlopen(req, timeout=None):
        url = req.full_url
        cach = req.get_method()
        da_goi.append(f"{cach} {url}")
        if cach == "GET" and "/runs?" in url:
            if loi_mang is not None:
                raise loi_mang           # KHÔNG phải HTTPError: mạng/DNS/timeout
            if ma_liet_ke != 200:
                raise urllib.error.HTTPError(url, ma_liet_ke, "loi", None, None)
            if tho_liet_ke is not None:
                return _PhanHoiGia(200, None, tho=tho_liet_ke)
            than = (
                {"workflow_runs": danh_sach}
                if than_liet_ke is _KHONG_DAT
                else than_liet_ke
            )
            return _PhanHoiGia(200, than)
        if cach == "POST" and url.endswith("/cancel"):
            rid = int(url.rsplit("/", 2)[-2])
            da_huy.append(rid)
            ma = ma_cancel.get(rid, 202)
            if ma != 202:
                raise urllib.error.HTTPError(url, ma, "loi", None, None)
            return _PhanHoiGia(202, None)
        if cach == "GET":
            rid = int(url.rsplit("/", 1)[-1])
            if doc_lai_ma != 200:
                raise urllib.error.HTTPError(url, doc_lai_ma, "loi", None, None)
            return _PhanHoiGia(200, doc_lai.get(rid, {"status": "completed"}))
        raise AssertionError(f"gọi API ngoài dự kiến: {cach} {url}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    for ten, gia_tri in {
        "GH_API_URL": "https://api.github.test",
        "GH_REPO": "chu/kho",
        "GH_TOKEN": "khong-phai-bi-mat",
        "GH_RUN_ID": str(run_id),
        "GH_RUN_NUMBER": str(so_hieu),
        "GH_TIP_SHA": tip,
        "GH_WORKFLOW_REF": "chu/kho/.github/workflows/deploy.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(ten, gia_tri)

    khong_gian = {"__name__": "__reaper__"}
    rc = 0
    try:
        exec(compile(ma_nguon or _ma_reaper(), "<reaper>", "exec"), khong_gian)
    except SystemExit as loi:
        rc = loi.code if isinstance(loi.code, int) else 1
    return rc, da_huy, da_goi


def test_reaper_huy_dung_run_CU_dang_cho_duyet(monkeypatch):
    rc, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)]
    )
    assert rc == 0, "đường thuận lợi không được đỏ"
    assert huy == [111]


@pytest.mark.parametrize(
    ("ly_do", "ban_ghi"),
    [
        ("chính run hiện tại", _ban_ghi_run(900, _SHA_CU, so=5)),
        ("mang đúng SHA tip", _ban_ghi_run(112, _TIP, so=5)),
        ("đang chạy", _ban_ghi_run(113, _SHA_CU, status="in_progress", so=5)),
        ("đã xong", _ban_ghi_run(114, _SHA_CU, status="completed", so=5)),
        ("đang xếp hàng", _ban_ghi_run(115, _SHA_CU, status="queued", so=5)),
        ("MỚI hơn run này", _ban_ghi_run(116, _SHA_CU, so=12)),
    ],
)
def test_reaper_khong_duoc_dung_toi(monkeypatch, ly_do, ban_ghi):
    rc, huy, _ = _thi_hanh_reaper(monkeypatch, danh_sach=[ban_ghi])
    assert rc == 0
    assert huy == [], f"KHÔNG được huỷ run {ly_do}"


def test_reaper_chi_hoi_run_cua_CHINH_workflow_nay(monkeypatch):
    """Không được quét toàn repo: chỉ `workflows/deploy.yml/runs`."""
    _, _, goi = _thi_hanh_reaper(monkeypatch, danh_sach=[])
    liet_ke = [g for g in goi if "/runs?" in g]
    assert len(liet_ke) == 1, f"phải liệt kê đúng một lần, thấy {liet_ke}"
    assert "/actions/workflows/deploy.yml/runs?" in liet_ke[0], (
        f"phải hỏi theo workflow của chính nó, nhận: {liet_ke[0]}"
    )
    assert "status=waiting" in liet_ke[0]


def test_reaper_liet_ke_hong_thi_DO_va_khong_huy_gi(monkeypatch):
    """Không đọc được danh sách ⇒ không kết luận được ⇒ chặn deploy."""
    rc, huy, _ = _thi_hanh_reaper(monkeypatch, danh_sach=[], ma_liet_ke=500)
    assert rc != 0
    assert huy == []


def test_reaper_403_thi_DO_va_neu_dich_danh_quyen_thieu(monkeypatch, capsys):
    """Không được cấp `actions: write` ⇒ dừng an toàn, không im lặng bỏ qua."""
    rc, _, _ = _thi_hanh_reaper(
        monkeypatch,
        danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)],
        ma_cancel={111: 403},
    )
    assert rc != 0
    ra = capsys.readouterr().out
    assert "actions: write" in ra and "403" in ra


def test_reaper_409_vo_hai_CHI_KHI_run_da_roi_waiting(monkeypatch):
    rc, _, _ = _thi_hanh_reaper(
        monkeypatch,
        danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)],
        ma_cancel={111: 409},
        doc_lai={111: {"status": "completed"}},
    )
    assert rc == 0


def test_reaper_409_ma_van_waiting_thi_DO(monkeypatch):
    """Chiều ngược: thiếu ca này thì một `except 409: pass` vẫn làm ca trên xanh."""
    rc, _, _ = _thi_hanh_reaper(
        monkeypatch,
        danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)],
        ma_cancel={111: 409},
        doc_lai={111: {"status": "waiting"}},
    )
    assert rc != 0


# --- kiểm ngược: mỗi guard MỘT đột biến riêng (CLAUDE.md §3) -----------------


def _dot_bien(mau: str) -> str:
    nguon = _ma_reaper()
    assert nguon.count(mau) == 1, f"mẫu đột biến khớp {nguon.count(mau)} lần, cần đúng 1"
    return nguon.replace(mau, "if False:  # DOT BIEN", 1)


def test_dot_bien_bo_kiem_TIP_thi_huy_nham_run_con_deploy_duoc(monkeypatch):
    """Gỡ vế `head_sha != tip` ⇒ một run VẪN deploy được bị huỷ."""
    mut = _dot_bien('if (run.get("head_sha") or "").strip().lower() == TIP_SHA:')
    _, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[_ban_ghi_run(112, _TIP, so=5)], ma_nguon=mut
    )
    assert huy == [112], "đột biến KHÔNG lọt ⇒ phép kiểm gốc đang canh hụt"


def test_dot_bien_bo_kiem_SO_HIEU_thi_huy_nham_run_MOI_hon(monkeypatch):
    """Hai push liên tiếp: run cũ không được phép huỷ run mới hơn nó."""
    mut = _dot_bien('if int(run.get("run_number") or 0) >= RUN_NUMBER:')
    _, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[_ban_ghi_run(116, _SHA_CU, so=12)], ma_nguon=mut
    )
    assert huy == [116], "đột biến KHÔNG lọt ⇒ phép kiểm gốc đang canh hụt"


def test_dot_bien_bo_TU_LOAI_TRU_thi_reaper_tu_huy_chinh_minh(monkeypatch):
    """Bản ghi ở đây là TỔNG HỢP, và phải nói rõ vì sao.

    Run hiện tại ngoài đời luôn mang đúng SHA tip và đúng số hiệu của chính
    nó, nên ba vế (`id`, `tip`, `run_number`) cùng che nó — gỡ một vế thôi thì
    không ca thật nào đỏ được. Ca này cố ý dựng một bản ghi mang `id` của run
    hiện tại nhưng SHA khác và số hiệu nhỏ hơn, để chứng minh vế `id` là mã
    SỐNG chứ không phải một dòng thừa ăn theo hai vế kia.
    """
    mut = _dot_bien('if int(run.get("id") or 0) == RUN_ID:')
    _, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[_ban_ghi_run(900, _SHA_CU, so=5)], ma_nguon=mut
    )
    assert huy == [900], "đột biến KHÔNG lọt ⇒ vế tự-loại-trừ là mã chết"


# --- fail-closed: MỌI nhánh "không kết luận được" phải CHẶN deploy -----------
#
# Bản đầu của reaper đọc `payload.get("workflow_runs") or []`, nên một phản hồi
# HTTP 200 SAI HÌNH DẠNG bị hoá thành "không có run nào chờ duyệt": reaper lặng
# lẽ không dọn gì rồi thoát 0, và `deploy` đi tiếp. Đó đúng là lỗi
# `return-value-conflates-two-cases` — gộp "API nói không có" với "phản hồi
# hỏng" — nằm ngay trong bản vá sinh ra để diệt fail-open.
#
# Bốn nhánh `stop()` còn lại cũng chưa ca kiểm nào chứng minh bắn được. Một
# guard chưa ai thấy nó đỏ là một guard chưa được chứng minh (CLAUDE.md §3).


@pytest.mark.parametrize(
    ("ly_do", "than"),
    [
        ("thiếu hẳn khoá `workflow_runs`", {"total_count": 0}),
        ("`workflow_runs` là null", {"workflow_runs": None}),
        ("`workflow_runs` không phải danh sách", {"workflow_runs": {"id": 1}}),
        ("thân rỗng hoàn toàn", {}),
    ],
)
def test_reaper_than_200_SAI_HINH_DANG_thi_DO(monkeypatch, capsys, ly_do, than):
    """200 mà thân hỏng KHÔNG được hoá thành "không có run nào"."""
    rc, huy, _ = _thi_hanh_reaper(monkeypatch, danh_sach=[], than_liet_ke=than)
    assert rc != 0, f"phải CHẶN deploy khi {ly_do}"
    assert huy == [], "không được huỷ gì khi chưa đọc nổi danh sách"
    assert "SAI HINH DANG" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("ly_do", "dung_loi", "than_tho"),
    [
        ("mạng/DNS đứt", OSError("gia lap dut mang"), None),
        ("thân KHÔNG phải JSON", None, b"<html>502 Bad Gateway</html>"),
    ],
)
def test_reaper_loi_MANG_hoac_JSON_thi_DO(monkeypatch, ly_do, dung_loi, than_tho):
    """Cả hai rơi vào cùng nhánh `except Exception` — và nhánh ấy phải CHẶN."""
    rc, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[], loi_mang=dung_loi, tho_liet_ke=than_tho
    )
    assert rc != 0, f"phải CHẶN deploy khi {ly_do}"
    assert huy == []


def test_reaper_409_roi_DOC_LAI_CUNG_HONG_thi_DO(monkeypatch):
    """409 chỉ vô hại khi đọc lại XÁC NHẬN được. Đọc lại hỏng ⇒ không biết gì."""
    rc, _, _ = _thi_hanh_reaper(
        monkeypatch,
        danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)],
        ma_cancel={111: 409},
        doc_lai_ma=500,
    )
    assert rc != 0


@pytest.mark.parametrize("ma", [400, 401, 422, 500, 502])
def test_reaper_ma_HTTP_LA_khi_huy_thi_DO(monkeypatch, ma):
    """Mọi mã ngoài 202/403/409 đều là "không biết" ⇒ chặn, không đoán."""
    rc, huy, _ = _thi_hanh_reaper(
        monkeypatch,
        danh_sach=[_ban_ghi_run(111, _SHA_CU, so=5)],
        ma_cancel={111: ma},
    )
    assert rc != 0, f"HTTP {ma} khi huỷ mà vẫn cho deploy đi tiếp"
    assert huy == [111], "đã thử huỷ rồi mới hỏng — không phải bỏ qua"


def test_dot_bien_bo_kiem_HINH_DANG_thi_lai_fail_open(monkeypatch):
    """Kiểm ngược cho chính F1: gỡ vế hình dạng ⇒ quay lại fail-open cũ.

    Bản đột biến biến `isinstance(run_list, list)` thành luôn đúng, rồi nuốt
    `TypeError` của vòng lặp — tức tái tạo đúng hành vi cũ: thoát 0, không dọn
    gì, `deploy` đi tiếp.
    """
    nguon = _ma_reaper()
    mau = "if not isinstance(run_list, list):"
    assert nguon.count(mau) == 1
    mut = nguon.replace(mau, "if False:  # DOT BIEN", 1).replace(
        "for run in run_list:", "for run in (run_list or []):", 1
    )
    rc, huy, _ = _thi_hanh_reaper(
        monkeypatch, danh_sach=[], than_liet_ke={"total_count": 0}, ma_nguon=mut
    )
    assert rc == 0 and huy == [], (
        "đột biến KHÔNG lọt ⇒ phép kiểm hình dạng đang canh hụt"
    )
