/**
 * Pure wire-payload builders for the AdmissionPath governance fields
 * (phase1_02 / phase1_03).
 *
 * Extracted from the legacy ``PathBasicInfo`` wizard
 * (``PathBasicInfo.tsx:148-199``) so the new "Nâng cao" tab in
 * ``PathDetailDrawer`` reuses the exact same clear→null semantics instead of
 * re-implementing them. Unlike the wizard versions these take their inputs as
 * arguments (no component-state closure), which keeps them pure and directly
 * unit-testable.
 */

import type {
  AdmissionAudience,
  BonusRuleOverride,
} from "@/lib/zod/admission-path";

/**
 * Build the wire payload for ``applicable_to``.
 *
 * Empty Set → ``null`` (NULL on the wire = applicable to every audience).
 * A non-empty set serialises to the explicit audience array so the
 * "clear filter" semantic stays unambiguous under
 * ``model_dump(exclude_unset=True)`` on the BE.
 */
export function buildApplicableToPayload(
  applicableTo: Set<AdmissionAudience>,
): AdmissionAudience[] | null {
  return applicableTo.size > 0 ? Array.from(applicableTo) : null;
}

/**
 * Build the wire payload for ``method_quota``.
 *
 * BE column is ``Integer`` with Pydantic ``ge=0``. Floor decimal input
 * (e.g. ``"1.5"`` → ``1``) so the BE doesn't reject with a 400. Empty,
 * negative, or non-numeric input → ``null`` (admin intent = "clear the cap").
 * ``"0"`` is a real cap, not a clear.
 */
export function buildMethodQuotaPayload(
  methodQuotaInput: string,
): number | null {
  if (methodQuotaInput.trim() === "") return null;
  const parsed = Number(methodQuotaInput);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.floor(parsed);
}

/**
 * Build the wire payload for ``bonus_rule_override``.
 *
 * Toggle OFF → ``null`` (= inherit the method default). Toggle ON → the full
 * 3-field shape; an empty ``max_total_bonus`` → ``null`` (no cap). A provided
 * cap is clamped into ``[0, 10]`` (the BE Pydantic range) rather than rejected
 * — admin intent at the form boundary is "cap me", not "drop the cap".
 * Non-numeric cap → ``null``.
 */
export function buildBonusOverridePayload(
  enabled: boolean,
  applyAreaBonus: boolean,
  applyObjectBonus: boolean,
  maxTotalBonusInput: string,
): BonusRuleOverride | null {
  if (!enabled) return null;
  const trimmed = maxTotalBonusInput.trim();
  let maxTotal: number | null;
  if (trimmed === "") {
    maxTotal = null;
  } else {
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      maxTotal = null;
    } else {
      // Clamp into [0, 10] — BE Pydantic enforces the same range.
      maxTotal = Math.min(10, Math.max(0, parsed));
    }
  }
  return {
    apply_area_bonus: applyAreaBonus,
    apply_object_bonus: applyObjectBonus,
    max_total_bonus: maxTotal,
  };
}
