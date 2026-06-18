"""Unit tests for the post-delete cleanup + lead-status revert policy wired
into ``delete_profile``.

Two pure/low-level pieces are pinned here so the riskiest logic is covered
without a DB:

1. ``_remove_profile_upload_dir`` — best-effort removal of a deleted profile's
   ``uploads/admissions/{id}/`` directory (docs + staging + the dir). It runs
   AFTER the delete commits, so it must NEVER raise — otherwise a successful
   delete becomes a 500 and the router's realtime dispatch is skipped.

2. ``_resolve_lead_revert_status`` — the pure policy deciding whether (and to
   what) a lead's consultation status reverts when its last draft is deleted.
"""
from app.services.admission_service import (
    _CREATE_MILESTONE_STATUS,
    _remove_profile_upload_dir,
    _resolve_lead_revert_status,
)


class TestRemoveProfileUploadDir:
    def test_removes_dir_with_docs_and_staging(self, tmp_path, monkeypatch):
        prof_id = 4242
        target = tmp_path / "uploads" / "admissions" / str(prof_id)
        (target / "docs").mkdir(parents=True)
        (target / "docs" / "hocba.pdf").write_text("x")
        (target / ".staging.abc.pdf").write_text("y")  # staging temp file
        monkeypatch.chdir(tmp_path)

        _remove_profile_upload_dir(prof_id)

        assert not target.exists()  # docs + staging + dir all gone

    def test_missing_dir_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # No uploads/ tree at all → must not raise.
        _remove_profile_upload_dir(999999)

    def test_never_raises_even_if_rmtree_throws(self, monkeypatch):
        # Pins the regression flagged in review: the helper must swallow ANY
        # error (not just OSError) — e.g. a ValueError("embedded null byte").
        def _boom(*args, **kwargs):
            raise ValueError("embedded null byte")

        monkeypatch.setattr("shutil.rmtree", _boom)
        # Must not propagate.
        _remove_profile_upload_dir(123)


class TestResolveLeadRevertStatus:
    """Exhaustive policy tests for the lead-status revert decision when a draft
    profile is deleted (the business edge case: deleting a profile must not
    leave the lead stranded at sts06 with no profile — nor mis-attribute an
    independent sts06, nor re-close a lead).

    Revert fires ONLY when all conditions hold; any single failing condition
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
        assert (
            _resolve_lead_revert_status(
                has_other_profile=True,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id=self.PREV,
            )
            is None
        )

    def test_no_revert_when_lead_advanced_past_milestone(self):
        # Lead moved beyond sts06 (submit/approve/fee/manual) → don't regress.
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
        # No recoverable pre-creation status (e.g. lead was already at sts06
        # before creation, so the create milestone wrote no history row).
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

    def test_no_revert_when_prev_is_terminal_or_negative(self):
        # A lost lead (sts20 "Đã ngừng tư vấn", terminal/negative) reopened to
        # sts06 then create+delete must NOT be re-closed by the delete.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id="sts20",
                prev_is_terminal_or_negative=True,
            )
            is None
        )

    def test_reverts_to_non_terminal_prev(self):
        # Sanity: the terminal flag defaulting False still allows normal revert.
        assert (
            _resolve_lead_revert_status(
                has_other_profile=False,
                current_consultation_status_id=_CREATE_MILESTONE_STATUS,
                prev_consultation_status_id="sts03",
                prev_is_terminal_or_negative=False,
            )
            == "sts03"
        )
