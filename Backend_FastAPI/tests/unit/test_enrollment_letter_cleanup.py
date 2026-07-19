"""Unit tests for enrollment-letter file lifecycle cleanup.

Covers the code-review findings:
- Commit-failure orphan cleanup helper deletes the file (and is idempotent).
- The retention task's orphan sweep deletes old, unreferenced PDFs while
  keeping referenced ones and recently-written ones (race guard).
"""
import os
import time

from app.services.enrollment_letter_service import _best_effort_delete
from app.tasks.enrollment_letter_tasks import (
    _ORPHAN_MAX_AGE_SECONDS,
    _scrub_snapshot,
    _sweep_orphan_pdfs,
)
from app.utils.sms_export import STAGING_PREFIX


def test_best_effort_delete_removes_and_is_idempotent(tmp_path):
    f = tmp_path / "letter.pdf"
    f.write_bytes(b"%PDF-1.4 pii")
    _best_effort_delete(str(f))
    assert not f.exists()
    # Second call on a missing file must not raise.
    _best_effort_delete(str(f))


def test_sweep_orphan_pdfs_deletes_only_old_unknown(tmp_path):
    old_orphan = tmp_path / "a.pdf"
    known = tmp_path / "b.pdf"
    recent_orphan = tmp_path / "c.pdf"
    for f in (old_orphan, known, recent_orphan):
        f.write_bytes(b"x")

    # Age the two candidates past the grace period; leave recent_orphan fresh.
    old = time.time() - _ORPHAN_MAX_AGE_SECONDS - 60
    os.utime(old_orphan, (old, old))
    os.utime(known, (old, old))

    removed = _sweep_orphan_pdfs(str(tmp_path), known_paths={str(known)})

    assert removed == 1
    assert not old_orphan.exists()   # old + unreferenced → deleted
    assert known.exists()            # referenced by a row → kept
    assert recent_orphan.exists()    # younger than grace → kept (race guard)


def test_sweep_orphan_pdfs_missing_dir_is_noop():
    assert _sweep_orphan_pdfs("/nonexistent/dir/xyz", known_paths=set()) == 0


def test_sweep_orphan_pdfs_bails_when_nothing_matches_the_db(tmp_path):
    """CHỐT AN TOÀN: quét ra file nhưng KHÔNG khớp lấy một đường dẫn nào trong
    DB ⇒ nghi lệch cấu hình (ops đổi ENROLLMENT_LETTER_STORAGE_DIR rồi copy
    file sang, mọi row vẫn trỏ chỗ cũ), KHÔNG phải cả thư mục đều mồ côi.
    Không có chốt này thì lượt beat kế tiếp xoá sạch giấy báo chính thức."""
    live = tmp_path / "letter-1.pdf"
    live.write_bytes(b"%PDF-1.4 that")
    old = time.time() - _ORPHAN_MAX_AGE_SECONDS - 60
    os.utime(live, (old, old))

    # DB trỏ một mount HOÀN TOÀN khác → 0 path khớp.
    removed = _sweep_orphan_pdfs(
        str(tmp_path), known_paths={"/mnt/cu/letters/1/abc.pdf"}
    )

    assert removed == 0
    assert live.exists(), "file đang sống bị xoá vì lệch cấu hình"


def test_sweep_orphan_pdfs_matches_across_path_spellings(tmp_path):
    """Path trong DB và path quét được có thể khác cách viết (thành phần './',
    dấu '/' thừa) cho cùng một file — so chuỗi thô sẽ coi nhầm là mồ côi."""
    known = tmp_path / "keep.pdf"
    known.write_bytes(b"x")
    old = time.time() - _ORPHAN_MAX_AGE_SECONDS - 60
    os.utime(known, (old, old))

    odd_spelling = os.path.join(str(tmp_path), ".", "keep.pdf")
    removed = _sweep_orphan_pdfs(str(tmp_path), known_paths={odd_spelling})

    assert removed == 0
    assert known.exists()


def test_sweep_orphan_pdfs_skips_staging_crumbs(tmp_path):
    """A '.staging.*.pdf' crumb belongs to the staging sweep, not the orphan
    sweep — it must NOT be counted/removed here (metric accuracy)."""
    staging = tmp_path / f"{STAGING_PREFIX}abc123.pdf"
    staging.write_bytes(b"x")
    old = time.time() - _ORPHAN_MAX_AGE_SECONDS - 60
    os.utime(staging, (old, old))

    removed = _sweep_orphan_pdfs(str(tmp_path), known_paths=set())

    assert removed == 0
    assert staging.exists()


def test_scrub_snapshot_removes_pii_keeps_nonpii():
    """Retention scrub drops candidate PII, keeps non-PII, marks _purged."""
    snap = {
        "full_name": "Nguyễn Văn A",
        "dob": "2008-01-01",
        "permanent_address": "Số 1, Đắk Lắk",
        "phone": "0900000000",
        "major_name": "Cao đẳng Dược",
        "hk1_fee_amount": 9200000,
        "fee_id": 5,
    }
    out = _scrub_snapshot(snap)

    assert out["_purged"] is True
    for pii in ("full_name", "dob", "permanent_address", "phone"):
        assert pii not in out
    assert out["major_name"] == "Cao đẳng Dược"
    assert out["hk1_fee_amount"] == 9200000
    assert out["fee_id"] == 5
    # Idempotent: re-scrubbing an already-purged snapshot stays purged.
    assert _scrub_snapshot(out)["_purged"] is True
