"""Unit tests for the orphaned-file cleanup wired into ``delete_profile``.

``profile_document.profile_id`` is ``ondelete=CASCADE`` so deleting a draft
profile removes the rows, but the physical uploads were previously left on
disk. ``delete_profile`` now returns a post-commit callback that drops those
files via ``_remove_orphaned_document_files``.

These tests pin the helper's best-effort contract — it must NEVER raise, even
on a missing/None/undeletable path — so a future change can't silently turn
file cleanup into a request-failing exception after the profile is already
gone from the DB.
"""
from app.services.admission_service import (
    _CREATE_MILESTONE_STATUS,
    _remove_orphaned_document_files,
    _resolve_lead_revert_status,
)


class TestRemoveOrphanedDocumentFiles:
    def test_removes_existing_files(self, tmp_path):
        f1 = tmp_path / "doc1.pdf"
        f2 = tmp_path / "doc2.pdf"
        f1.write_text("x")
        f2.write_text("y")

        _remove_orphaned_document_files([str(f1), str(f2)])

        assert not f1.exists()
        assert not f2.exists()

    def test_missing_path_is_ignored(self, tmp_path):
        missing = str(tmp_path / "nope.pdf")
        # Must not raise even though the file does not exist.
        _remove_orphaned_document_files([missing])

    def test_none_and_empty_paths_ignored(self):
        # None / "" entries (file_path is nullable) must be skipped silently.
        _remove_orphaned_document_files([None, "", None])

    def test_partial_failure_does_not_stop_others(self, tmp_path):
        good = tmp_path / "good.pdf"
        good.write_text("z")
        # A directory cannot be removed by os.remove → OSError; it must be
        # swallowed and the good file must still be deleted.
        a_dir = tmp_path / "subdir"
        a_dir.mkdir()

        _remove_orphaned_document_files([str(a_dir), str(good)])

        assert not good.exists()
        assert a_dir.exists()  # directory left intact, error swallowed

    def test_empty_list_noop(self):
        # No paths → no-op, no raise.
        _remove_orphaned_document_files([])


class TestResolveLeadRevertStatus:
    """Exhaustive policy tests for the lead-status revert decision when a
    draft profile is deleted (the business edge case: deleting a profile must
    not leave the lead stranded at sts06 'Đồng ý tư vấn' with no profile).

    Pure function → every branch is covered cheaply without a DB. The revert
    fires ONLY when all three conditions hold; any single failing condition
    must preserve the lead (return None).
    """

    PREV = "sts04"  # a plausible pre-creation consultation status

    def test_reverts_when_all_conditions_met(self):
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id=self.PREV,
            )
            == self.PREV
        )

    def test_no_revert_when_other_profile_exists(self):
        # Another profile justifies the lead's status → keep it.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=True,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id=self.PREV,
            )
            is None
        )

    def test_no_revert_when_lead_advanced_past_milestone(self):
        # Lead moved beyond sts06 (e.g. sts07 submitted, sts09 approved, or an
        # officer manual change) → do not regress it.
        for advanced in ("sts07", "sts09", "sts13", "sts05"):
            assert (
                _resolve_lead_revert_status(
                    has_other_profile=False,
                    current_consultation_status_id=advanced,
                    prev_consultation_status_id=self.PREV,
                )
                is None
            ), f"Should not revert when lead is at {advanced}"

    def test_no_revert_when_prev_status_unknown(self):
        # No history of the pre-creation status → cannot safely revert.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id=None,
            )
            is None
        )

    def test_no_revert_when_prev_equals_milestone(self):
        # A self-revert (sts06 → sts06) is a no-op; treat as no revert.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id=_CREATE_MILESTONE_STATUS,
            )
            is None
        )

    def test_no_revert_when_current_status_none(self):
        # Defensive: a lead with no consultation status set is not at sts06.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=None,
                prev_consultation_status_id=self.PREV,
            )
            is None
        )
