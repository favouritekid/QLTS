/**
 * Phase 3 PR-3D-A — Profile permissions helper.
 *
 * `hasAction(profile, actionName)` centralizes available_actions check across
 * `available_actions_v2` (typed shape, PREFERRED) + legacy `available_actions`
 * (string list, fallback for Wave B+90 soft cutoff per Plan v0.7 P-UI-08).
 *
 * Migration path:
 * - Wave B+0 (2026-08-13): BE populates BOTH v2 + legacy — FE uses hasAction(),
 *   transparent to consumers.
 * - Wave B+30 (2026-09-13): BE deprecation header live; FE still uses hasAction().
 * - Wave B+90 (2026-12-15 SHIFTED): BE drops legacy; hasAction() v2 path only.
 *
 * Consumers should NEVER read `available_actions` or `available_actions_v2`
 * directly — use `hasAction()` instead. This decouples FE from backend field
 * lifecycle.
 *
 * Memory `react-query-mutation-cache-parity` — when mutation changes
 * available_actions, invalidate detail key so UI re-renders.
 */

interface ActionItemV2 {
  action: string
  target?: number
  endpoint?: string
}

interface ProfileWithActions {
  available_actions?: string[]
  available_actions_v2?: ActionItemV2[]
}

/**
 * Check if a profile grants the given workflow action.
 *
 * Priority order:
 * 1. `available_actions_v2` typed shape (Phase 3 multi-NV preferred)
 * 2. `available_actions` legacy string list (backward compat)
 *
 * Returns `false` if neither field present (no permission).
 *
 * @example
 * if (hasAction(profile, "calculate_fee")) { ... }
 * if (hasAction(profile, "claim")) { ... }
 */
export function hasAction(
  profile: ProfileWithActions | null | undefined,
  actionName: string,
): boolean {
  if (!profile) {
    return false
  }
  // Preferred: typed v2 shape (Phase 3+)
  if (Array.isArray(profile.available_actions_v2)) {
    return profile.available_actions_v2.some((item) => item.action === actionName)
  }
  // Fallback: legacy string list
  if (Array.isArray(profile.available_actions)) {
    return profile.available_actions.includes(actionName)
  }
  return false
}

/**
 * Extract typed action item details (target id, endpoint) — useful for FE
 * routing/navigation. Returns `null` if action not found OR only in legacy
 * (legacy doesn't carry target/endpoint metadata).
 *
 * @example
 * const item = getActionItem(profile, "promote_choice")
 * if (item?.target) router.push(`/choices/${item.target}`)
 */
export function getActionItem(
  profile: ProfileWithActions | null | undefined,
  actionName: string,
): ActionItemV2 | null {
  if (!profile || !Array.isArray(profile.available_actions_v2)) {
    return null
  }
  return profile.available_actions_v2.find((item) => item.action === actionName) ?? null
}
