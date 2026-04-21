import type { NotificationAction, NotificationRule } from "@/types/api.types"

/**
 * Derive the channel list for a rule from its actions (the runtime truth
 * since Phase C0), preserving step order and de-duplicating.
 *
 * Wave 4b (2026-04-21) removed the deprecated top-level `rule.channels`
 * compat column, so the helper now only inspects `actions`. An empty
 * `actions` list yields an empty channel list — that is a misconfigured
 * rule (Phase C0 contract requires at least one action).
 */
export function deriveRuleChannels(
  rule: Pick<NotificationRule, "actions">,
): string[] {
  const actions: NotificationAction[] = rule.actions ?? []
  const seen = new Set<string>()
  const ordered: string[] = []
  for (const action of [...actions].sort((a, b) => a.step - b.step)) {
    if (!action.channel) continue
    if (seen.has(action.channel)) continue
    seen.add(action.channel)
    ordered.push(action.channel)
  }
  return ordered
}
