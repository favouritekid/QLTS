import type { NotificationAction, NotificationRule } from "@/types/api.types"

/**
 * Derive the channel list for a rule from its actions (the runtime truth
 * since Phase C0), preserving step order and de-duplicating.
 *
 * Wave 4a (2026-04-21) fallback: if `actions` is empty/missing the helper
 * falls back to the deprecated top-level `rule.channels` compat column
 * so the FE keeps working while Wave 4b is still pending. Wave 4b will
 * drop the column and the fallback becomes dead code.
 */
export function deriveRuleChannels(
  rule: Pick<NotificationRule, "actions" | "channels">,
): string[] {
  const actions: NotificationAction[] = rule.actions ?? []
  if (actions.length > 0) {
    const seen = new Set<string>()
    const ordered: string[] = []
    for (const action of [...actions].sort((a, b) => a.step - b.step)) {
      if (!action.channel) continue
      if (seen.has(action.channel)) continue
      seen.add(action.channel)
      ordered.push(action.channel)
    }
    if (ordered.length > 0) return ordered
  }
  return rule.channels ?? []
}
