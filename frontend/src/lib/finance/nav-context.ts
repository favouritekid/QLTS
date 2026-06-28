// src/lib/finance/nav-context.ts
/**
 * Finance navigation context.
 *
 * The "Thu học phí" workspace (/finance/invoices) is the hub; fee & invoice
 * detail pages are spokes. When the workspace links into a detail page it stamps
 * a `?from=` context so the detail page's "Quay lại" returns to EXACTLY where the
 * user came from (reopening the right profile drawer) instead of a blind
 * browser-back. If no context is present we fall back to the workspace, never a
 * dead-end.
 *
 * Only internal finance targets are ever produced (no open-redirect surface):
 * `from` is parsed, validated, and mapped to a fixed route shape here.
 */

/** Workspace hub — the safe finance landing when there's no return context. */
const FINANCE_WORKSPACE = "/finance/invoices"

/** `?from` value the workspace stamps on a link into a profile's detail page. */
export function profileFrom(profileId: number): string {
  return `profile:${profileId}`
}

/**
 * Resolve the controlled return target for a finance detail page from its
 * `?from` param. Returns the href to navigate to and a human label naming the
 * destination (so the back control says where it goes, not a generic "back").
 */
export function resolveFinanceReturn(from: string | null | undefined): {
  href: string
  label: string
} {
  if (from) {
    const [kind, raw] = from.split(":")
    if (kind === "profile" && raw && /^\d+$/.test(raw)) {
      return {
        href: `${FINANCE_WORKSPACE}?profile=${raw}`,
        label: "Quay lại hồ sơ",
      }
    }
  }
  return { href: FINANCE_WORKSPACE, label: "Quay lại Thu học phí" }
}

/**
 * Append the current `?from` to a same-page replace target so closing an action
 * dialog (which strips the `?action=` param) does NOT lose the return context.
 */
export function withFrom(path: string, from: string | null | undefined): string {
  return from ? `${path}?from=${encodeURIComponent(from)}` : path
}
