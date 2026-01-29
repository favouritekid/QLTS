// src/app/(dashboard)/admissions/page.tsx
/**
 * Admissions List Page
 *
 * Features:
 * - TanStack Table with sorting and selection
 * - Search, filter, date range
 * - Mobile card view
 * - Bulk actions (approve, reject, assign, export)
 */

import { AdmissionsClient } from "./_components/AdmissionsClient"

export default function AdmissionsPage() {
  return <AdmissionsClient />
}
