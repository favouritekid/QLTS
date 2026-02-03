// src/app/(dashboard)/finance/layout.tsx
/**
 * Finance Module Layout
 *
 * Wraps all finance pages with common layout elements.
 * This is a simple passthrough layout - we use the main dashboard layout.
 */

import type { ReactNode } from "react"

export default function FinanceLayout({ children }: { children: ReactNode }) {
  return <>{children}</>
}
