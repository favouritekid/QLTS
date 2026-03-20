// src/hooks/useClientNow.ts
"use client";

import { useEffect, useState } from "react";

/**
 * Returns a stable Date.now() timestamp that is only set on the client
 * after hydration. Returns null during SSR and initial hydration render.
 *
 * This avoids both:
 * - Hydration mismatch (server/client Date.now() differ)
 * - react-hooks/set-state-in-effect on derived values (use the returned
 *   `now` to compute derived values as plain const expressions)
 *
 * Usage:
 *   const now = useClientNow();
 *   const daysAgo = now && date ? Math.floor((now - date) / MS_PER_DAY) : null;
 */
export function useClientNow(): number | null {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now()); // eslint-disable-line react-hooks/set-state-in-effect
  }, []);

  return now;
}
