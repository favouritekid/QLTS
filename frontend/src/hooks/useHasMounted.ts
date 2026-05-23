"use client";

import { useEffect, useState } from "react";

/**
 * Returns `false` on SSR + first client render, `true` after the mount
 * effect fires. Use to gate role-aware / persisted-store-aware branches
 * that would otherwise render different element trees on SSR vs first
 * client render → "Hydration failed" mismatch.
 *
 * Anchor: `auth.store.ts:79-87` Zustand `persist` middleware rehydrates
 * SYNCHRONOUSLY from localStorage BEFORE the first React render. Reading
 * `useAuth().user` during render therefore returns:
 *   - SSR: null (no localStorage)
 *   - Client first render: persisted user
 *
 * If a render branch depends on `user.role` (e.g., "show unsupported-role
 * Alert"), the two trees diverge. Wrap that branch with `hasMounted &&`
 * to keep first client render aligned to SSR (both render the false
 * branch), then let the next render — post-effect — show the role-aware
 * UI.
 *
 * Used in: `OfficerDashboardClient.tsx` to gate the `isUnsupportedRole`
 * Alert (PR #325 follow-up to PR #324 Commit 1).
 */
export function useHasMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true); // eslint-disable-line react-hooks/set-state-in-effect
  }, []);
  return mounted;
}
