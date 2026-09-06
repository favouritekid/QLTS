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
    jobs = _workflow(_DEPLOY)["jobs"]
    classifier_job = jobs["classify-changes"]
    deploy_job = jobs["deploy"]
    assert "environment" not in classifier_job
    assert "concurrency" not in classifier_job
    assert deploy_job["environment"] == "production"
    assert deploy_job["concurrency"] == {
        "group": "deploy-production",
        "cancel-in-progress": True,
    }


def test_deploy_chi_chay_sau_ket_luan_deploy_tuong_minh():
    jobs = _workflow(_DEPLOY)["jobs"]
    deploy_job = jobs["deploy"]
    assert deploy_job["needs"] == "classify-changes"
    assert deploy_job["if"] == (
        "needs.classify-changes.result == 'success' && "
        "needs.classify-changes.outputs.deploy == 'true'"
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
