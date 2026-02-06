// src/app/(dashboard)/finance/layout.tsx
/**
 * Finance Module Layout
 *
 * Authorization is enforced by server-side middleware (proxy.ts) BEFORE page render.
 * Only users with finance access (accountant, manager, admin) can reach these pages.
 * Backend Casbin performs the FINAL authorization check on all API calls.
 *
 * This layout serves as a container for finance pages.
 */

import type { ReactNode } from "react"

export default function FinanceLayout({ children }: { children: ReactNode }) {
  return <>{children}</>
}
