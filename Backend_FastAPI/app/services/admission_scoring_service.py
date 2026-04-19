# app/services/admission_scoring_service.py
"""
Admission Scoring Service v2.0

STATELESS, DETERMINISTIC, REPRODUCIBLE, POLICY-VERSIONED.

Core responsibilities:
1. Resolve allowed subjects from criteria + subject_group
2. Calculate admission scores based on Rule Engine config
3. Generate immutable snapshots with policy versioning
4. Validate scoring against criteria rules

CRITICAL RULES (from Admission Rulebook):
- Invalid profile → final_score = None (NOT 0)
- Selection must be 100% deterministic
- any_n mode DEPRECATED (use group_ordered)
- Policy version must be in snapshot

NO DB calls inside scoring logic - pure math + rules.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Literal

from app.models.admission_config import (
    AdmissionCriteria,
    SubjectGroup,
    Subject,
)


# =============================================================================
# ENUMS (Match DB CHECK constraints + Rulebook)
# =============================================================================

class SubjectSelectionMode(str, Enum):
    """How to select subjects from pool (DEFINITIVE per Rulebook)."""
    FIXED = "fixed"            # Lấy đúng N môn đầu tiên theo thứ tự group
    BEST_N = "best_n"          # Sắp xếp điểm DESC, lấy N cao nhất
    GROUP_ORDERED = "any_n"    # Legacy name, same as fixed (DEPRECATED alias)
    # Note: any_n is kept for backward compatibility but treated as fixed


class ScoringMethod(str, Enum):
    """How to calculate final score."""
    SUM = "sum"          # Σ(scores)
    AVERAGE = "average"  # Σ(scores) / N
    WEIGHTED = "weighted"  # Σ(score × weight) - Future


class ProfileStatus(str, Enum):
    """Status of admission profile after scoring."""
    VALID = "valid"          # All rules passed
    INVALID = "invalid"      # Failed validation (no score)
    PENDING = "pending"      # Awaiting more data


class DisqualificationReason(str, Enum):
    """Standardized failure codes (from Rulebook)."""
    MISSING_REQUIRED_SUBJECTS = "MISSING_REQUIRED_SUBJECTS"
    BELOW_MIN_SCORE = "BELOW_MIN_SCORE"
    BELOW_MIN_GPA = "BELOW_MIN_GPA"
    SUBJECT_BELOW_THRESHOLD = "SUBJECT_BELOW_THRESHOLD"
    NO_VALID_SCORES = "NO_VALID_SCORES"
    INVALID_SUBJECT_GROUP = "INVALID_SUBJECT_GROUP"


# =============================================================================
# RESULT DATACLASSES
# =============================================================================

@dataclass
class AdmissionScoreResult:
    """
    Result of admission score calculation.
    
    CRITICAL: If status == INVALID, final_score MUST be None.
    """
    
    # Profile status (VALID / INVALID)
    status: ProfileStatus
    passed: bool
    
    # Core result - None if INVALID
    final_score: Optional[Decimal]
    
    # Subject details
    selected_subjects: list[str]
    subject_scores: dict[str, Decimal]
    
    # Transparency metadata
    input_subject_count: int = 0
    used_subject_count: int = 0
    ignored_subjects: list[str] = field(default_factory=list)
    
    # Rule info
    criteria_code: str = ""
    selection_mode: str = "fixed"
    scoring_method: str = "sum"
    required_count: Optional[int] = None
    
    # Thresholds
    min_score_threshold: Optional[Decimal] = None
    min_subject_score_threshold: Optional[Decimal] = None
    
    # Failure reasons with codes
    failure_reasons: list[str] = field(default_factory=list)
    disqualification_codes: list[str] = field(default_factory=list)
    
    # Metadata
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SubjectResolutionResult:
    """
    Result of subject resolution.
    
    Enhanced with priority metadata for deterministic selection.
    """
    allowed_subjects: list[str]  # Subject codes allowed (ordered by priority)
    subject_group_code: Optional[str] = None
    source: str = "explicit"  # "explicit" | "criteria_default" | "all_groups"
    
    # Priority metadata (for audit)
    subject_priorities: dict[str, int] = field(default_factory=dict)  # code -> priority
    

# =============================================================================
# SCORING SERVICE
# =============================================================================

class AdmissionScoringService:
    """
    Stateless service for admission score calculation.
    
    All methods are pure functions - no DB calls, no side effects.
    Results are 100% deterministic and reproducible for audit.
    """
    
    SCHEMA_VERSION = "2.0"
    
    # =========================================================================
    # SUBJECT RESOLUTION
    # =========================================================================
    
    @staticmethod
    def resolve_allowed_subjects(
        criteria: AdmissionCriteria,
        subject_group: Optional[SubjectGroup] = None,
    ) -> SubjectResolutionResult:
        """
        Resolve which subjects are allowed for scoring.
        
        DETERMINISTIC: Same input always gives same output.
        
        Priority:
        1. If subject_group is provided -> use subjects from that group (ordered)
        2. If not -> collect from ALL groups linked to criteria (by group priority)
        """
        allowed_subjects = []
        priorities = {}
        source = "explicit"
        group_code = None
        
        if subject_group:
            # Case 1: Explicit subject group provided
            for mapping in sorted(subject_group.subject_mappings, key=lambda m: m.position):
                if mapping.subject.is_active:
                    code = mapping.subject.code
                    allowed_subjects.append(code)
                    priorities[code] = mapping.position
            group_code = subject_group.code
            source = "explicit"
        
        elif criteria.subject_group_mappings:
            # Case 2: Use all groups linked to criteria (ordered by group, then position)
            seen = set()
            priority_counter = 0
            
            for csg in sorted(criteria.subject_group_mappings, key=lambda x: x.id):  # Deterministic order
                group = csg.subject_group
                if group and group.is_active:
                    for sm in sorted(group.subject_mappings, key=lambda m: m.position):
                        if sm.subject.code not in seen and sm.subject.is_active:
                            code = sm.subject.code
                            allowed_subjects.append(code)
                            priorities[code] = priority_counter
                            seen.add(code)
                            priority_counter += 1
            source = "criteria_default"
        
        else:
            source = "none"
        
        return SubjectResolutionResult(
            allowed_subjects=allowed_subjects,
            subject_group_code=group_code,
            source=source,
            subject_priorities=priorities,
        )
    
    # =========================================================================
    # CORE SCORING
    # =========================================================================
    
    @staticmethod
    def calculate_score(
        criteria: AdmissionCriteria,
        subject_scores: dict[str, Decimal],
        allowed_subjects: list[str],
        subject_weights: Optional[dict[str, Decimal | float]] = None,
    ) -> AdmissionScoreResult:
        """
        Calculate admission score based on criteria rules.

        CRITICAL RULES:
        - If validation fails → status = INVALID, final_score = None
        - Selection is 100% deterministic
        - any_n treated as fixed (DEPRECATED)

        **Weights (PR6 Step 2, 2026-04-19)**:
        - ``subject_weights`` is the map frozen into the snapshot at
          application time (see ``generate_snapshot``).
        - ``None`` or empty dict → plain behavior (legacy). This is how
          pre-migration snapshots keep working without retroactive backfill.
        - Missing key for a selected subject → treated as 1.0. Matches the
          no-op default at the DB layer (NUMERIC DEFAULT 1.0).
        - Actively consumed only when ``scoring_method == "weighted"``; sum
          and average ignore weights so switching methods on a snapshot
          doesn't silently change results.
        """
        failure_reasons = []
        disqualification_codes = []
        input_count = len(subject_scores)
        
        # Extract rule params
        selection_mode = criteria.subject_selection_mode or "fixed"
        scoring_method = criteria.scoring_method or "sum"
        required_count = criteria.required_subject_count
        min_score = Decimal(str(criteria.min_score)) if criteria.min_score else None
        min_subject = Decimal(str(criteria.min_subject_score)) if criteria.min_subject_score else None
        
        # DEPRECATION: any_n → treat as fixed
        if selection_mode == "any_n":
            selection_mode = "fixed"
        
        # Step 1: Resolve candidate subjects (deterministic)
        selected_codes, selected_scores = AdmissionScoringService._select_subjects(
            selection_mode=selection_mode,
            subject_scores=subject_scores,
            allowed_subjects=allowed_subjects,
            required_count=required_count,
        )
        
        # Calculate ignored subjects
        submitted_codes = set(subject_scores.keys())
        used_codes = set(selected_codes)
        ignored = sorted(list(submitted_codes - used_codes))  # Sorted for determinism
        
        actual_count = len(selected_codes)
        
        # =======================================================================
        # VALIDATION (CRITICAL: Invalid → no score)
        # =======================================================================
        
        is_invalid = False
        
        # Check 1: Required subject count
        if required_count is not None and actual_count < required_count:
            failure_reasons.append(
                f"Thiếu môn: cần {required_count}, có {actual_count}"
            )
            disqualification_codes.append(DisqualificationReason.MISSING_REQUIRED_SUBJECTS.value)
            is_invalid = True
        
        # Check 2: No valid scores at all
        if actual_count == 0:
            failure_reasons.append("Không có môn nào hợp lệ để tính điểm")
            disqualification_codes.append(DisqualificationReason.NO_VALID_SCORES.value)
            is_invalid = True
        
        # Check 3: Min subject score (điểm liệt)
        if min_subject is not None and not is_invalid:
            for code, score in selected_scores.items():
                if score < min_subject:
                    failure_reasons.append(
                        f"Môn {code} = {score} < điểm liệt {min_subject}"
                    )
                    disqualification_codes.append(DisqualificationReason.SUBJECT_BELOW_THRESHOLD.value)
                    is_invalid = True
                    break  # One is enough
        
        # =======================================================================
        # CRITICAL RULE: Invalid profile → final_score = None
        # =======================================================================
        
        if is_invalid:
            return AdmissionScoreResult(
                status=ProfileStatus.INVALID,
                passed=False,
                final_score=None,  # ← CRITICAL: None, not 0
                selected_subjects=selected_codes,
                subject_scores=selected_scores,
                input_subject_count=input_count,
                used_subject_count=actual_count,
                ignored_subjects=ignored,
                criteria_code=criteria.code,
                selection_mode=selection_mode,
                scoring_method=scoring_method,
                required_count=required_count,
                min_score_threshold=min_score,
                min_subject_score_threshold=min_subject,
                failure_reasons=failure_reasons,
                disqualification_codes=disqualification_codes,
            )
        
        # =======================================================================
        # SCORING (only for valid profiles)
        # =======================================================================
        
        final_score = AdmissionScoringService._calculate_final_score(
            scores=list(selected_scores.values()),
            method=scoring_method,
            selected_codes=selected_codes,
            subject_weights=subject_weights,
        )
        
        # Check min_score threshold
        passed = True
        if min_score is not None and final_score < min_score:
            failure_reasons.append(
                f"Điểm {final_score} < điểm chuẩn {min_score}"
            )
            disqualification_codes.append(DisqualificationReason.BELOW_MIN_SCORE.value)
            passed = False
        
        return AdmissionScoreResult(
            status=ProfileStatus.VALID,
            passed=passed,
            final_score=final_score,
            selected_subjects=selected_codes,
            subject_scores=selected_scores,
            input_subject_count=input_count,
            used_subject_count=actual_count,
            ignored_subjects=ignored,
            criteria_code=criteria.code,
            selection_mode=selection_mode,
            scoring_method=scoring_method,
            required_count=required_count,
            min_score_threshold=min_score,
            min_subject_score_threshold=min_subject,
            failure_reasons=failure_reasons,
            disqualification_codes=disqualification_codes,
        )
    
    @staticmethod
    def _select_subjects(
        selection_mode: str,
        subject_scores: dict[str, Decimal],
        allowed_subjects: list[str],
        required_count: Optional[int],
    ) -> tuple[list[str], dict[str, Decimal]]:
        """
        Select subjects based on mode (DETERMINISTIC).
        
        ┌────────────────┬────────────────────────────────────────────┐
        │ Mode           │ Behavior                                   │
        ├────────────────┼────────────────────────────────────────────┤
        │ fixed          │ Take N in order from allowed_subjects      │
        │ best_n         │ Sort by score DESC (then by code ASC)      │
        └────────────────┴────────────────────────────────────────────┘
        """
        # Filter to only allowed subjects
        valid_scores = {
            code: score 
            for code, score in subject_scores.items() 
            if code in allowed_subjects
        }
        
        count = required_count or len(valid_scores)
        
        if selection_mode == SubjectSelectionMode.FIXED.value:
            # Fixed: take first N from allowed (order from SubjectGroup)
            selected = []
            for code in allowed_subjects:
                if code in valid_scores and len(selected) < count:
                    selected.append(code)
        
        elif selection_mode == SubjectSelectionMode.BEST_N.value:
            # Best N: sort by score DESC, then by code ASC (for determinism)
            sorted_codes = sorted(
                valid_scores.keys(),
                key=lambda c: (-valid_scores[c], c)  # Score DESC, code ASC
            )
            selected = sorted_codes[:count]
        
        else:
            # Default to fixed (handles deprecated any_n)
            selected = []
            for code in allowed_subjects:
                if code in valid_scores and len(selected) < count:
                    selected.append(code)
        
        selected_scores = {code: valid_scores[code] for code in selected if code in valid_scores}
        return selected, selected_scores
    
    @staticmethod
    def _calculate_final_score(
        scores: list[Decimal],
        method: str,
        selected_codes: Optional[list[str]] = None,
        subject_weights: Optional[dict[str, Decimal | float]] = None,
    ) -> Decimal:
        """Calculate final score based on method.

        ``selected_codes`` and ``subject_weights`` are only meaningful for
        the ``weighted`` method. For ``sum`` / ``average`` they are
        intentionally ignored so that switching scoring_method on an
        existing snapshot doesn't silently re-weight historical scores.
        """
        if not scores:
            return Decimal("0")

        if method == ScoringMethod.SUM.value:
            return sum(scores)

        elif method == ScoringMethod.AVERAGE.value:
            return sum(scores) / len(scores)

        elif method == ScoringMethod.WEIGHTED.value:
            # Missing weights or missing selected_codes → safe fallback to
            # plain sum. This mirrors the "no-retroactive" guarantee: a
            # pre-migration snapshot with scoring_method="weighted" but no
            # frozen weights must not suddenly start applying coefficients.
            if not subject_weights or not selected_codes:
                return sum(scores)
            # Align scores with codes by position (callers build the two
            # lists from the same ordered dict).
            if len(selected_codes) != len(scores):
                # Defensive: caller contract violation → fall back.
                return sum(scores)
            total = Decimal("0")
            for code, score in zip(selected_codes, scores):
                raw = subject_weights.get(code, 1.0)
                # Accept both float (from JSONB snapshot) and Decimal.
                weight = raw if isinstance(raw, Decimal) else Decimal(str(raw))
                total += score * weight
            return total

        else:
            return sum(scores)
    
    # =========================================================================
    # SNAPSHOT GENERATION (with Policy Versioning)
    # =========================================================================
    
    @classmethod
    def generate_snapshot(
        cls,
        criteria: AdmissionCriteria,
        subject_group: Optional[SubjectGroup],
        allowed_subjects: list[str],
        input_scores: dict[str, Decimal],
        score_result: Optional[AdmissionScoreResult] = None,
        policy_version: str = "2025.1",
    ) -> dict:
        """
        Generate immutable snapshot of applied rules.
        
        Includes policy versioning per Rulebook requirements.
        """
        now = datetime.now(timezone.utc)
        
        # Precompute weights up front so they feed BOTH the rule hash
        # (change-detection: a weight edit must bump the hash) and the
        # snapshot body below.
        subject_weights: dict[str, float] = (
            {
                m.subject.code: float(m.weight)
                for m in subject_group.subject_mappings
                if m.subject
            }
            if subject_group
            else {}
        )

        # Build rule params for hashing
        rule_params = {
            "required_subject_count": criteria.required_subject_count,
            "subject_selection_mode": criteria.subject_selection_mode,
            "scoring_method": criteria.scoring_method,
            "min_score": float(criteria.min_score) if criteria.min_score else None,
            "min_gpa": float(criteria.min_gpa) if criteria.min_gpa else None,
            "min_subject_score": float(criteria.min_subject_score) if criteria.min_subject_score else None,
            # PR6 Step 1: weights participate in the hash so editing a
            # coefficient is treated as a rule change, not a cosmetic one.
            "subject_weights": subject_weights,
        }
        rule_hash = cls._generate_checksum(rule_params)
        
        snapshot = {
            # Versioning (ENHANCED)
            "__schema_version__": cls.SCHEMA_VERSION,
            "__policy_version__": policy_version,  # ← NEW: Required by Rulebook
            "__rule_hash__": rule_hash,            # ← NEW: For rule change detection
            "__snapshot_at__": now.isoformat(),
            
            # Criteria
            "criteria_code": criteria.code,
            "criteria_name": criteria.name,
            "method_code": criteria.method.code if criteria.method else None,
            
            # Rule params
            **rule_params,
            "max_possible_score": float(criteria.max_possible_score) if criteria.max_possible_score else None,
            
            # Subject group
            "subject_group_code": subject_group.code if subject_group else None,
            "allowed_subjects": allowed_subjects,
            # PR6 Step 1 (2026-04-19): per-subject weights from join table.
            # Frozen into the snapshot at application time so future weight
            # edits on SubjectGroupSubject never retroactively affect this
            # profile's already-committed score. Default {} when no group
            # resolved — scoring logic treats absent keys as weight=1.0.
            "subject_weights": subject_weights,
            
            # Input (for audit)
            "input_scores": {k: float(v) for k, v in input_scores.items()},
        }
        
        # Add result if provided
        if score_result:
            snapshot["status"] = score_result.status.value
            snapshot["passed"] = score_result.passed
            snapshot["final_score"] = float(score_result.final_score) if score_result.final_score else None
            snapshot["selected_subjects"] = score_result.selected_subjects
            snapshot["failure_reasons"] = score_result.failure_reasons
            snapshot["disqualification_codes"] = score_result.disqualification_codes
            snapshot["input_subject_count"] = score_result.input_subject_count
            snapshot["used_subject_count"] = score_result.used_subject_count
            snapshot["ignored_subjects"] = score_result.ignored_subjects
        
        # Generate checksum
        snapshot["__checksum__"] = cls._generate_checksum(snapshot)
        
        return snapshot
    
    @staticmethod
    def _generate_checksum(data: dict) -> str:
        """Generate SHA256 checksum of snapshot data."""
        payload = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()
    
    @staticmethod
    def verify_checksum(snapshot: dict) -> bool:
        """Verify snapshot checksum is valid."""
        stored_checksum = snapshot.get("__checksum__", "")
        data = {k: v for k, v in snapshot.items() if k != "__checksum__"}
        payload = json.dumps(data, sort_keys=True, default=str)
        calculated = hashlib.sha256(payload.encode()).hexdigest()
        return stored_checksum == calculated
