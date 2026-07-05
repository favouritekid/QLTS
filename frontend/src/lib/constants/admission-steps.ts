/**
 * Admission pipeline step metadata — single source of truth.
 *
 * Extracted from `PipelineSidebar.tsx` (was a local `STEPS` array) so BOTH the
 * layout sidebar AND the Step 8 readiness surface (`tabs/finalize/*`) import the
 * same 8 labels/icons without coupling a tab to the layout folder. Placed under
 * `lib/constants/` (next to `admission-audience.ts`) per STEP8 plan P1-b.
 *
 * Thin Client: pure presentation metadata, no business logic.
 */

import {
  User,
  Users,
  GraduationCap,
  Award,
  Calculator,
  FileText,
  Wallet,
  CheckSquare,
  type LucideIcon,
} from "lucide-react"

export interface AdmissionStep {
  id: number
  label: string
  icon: LucideIcon
}

export const ADMISSION_STEPS: AdmissionStep[] = [
  { id: 1, label: "Thông tin cá nhân", icon: User },
  { id: 2, label: "Gia đình / Giám hộ", icon: Users },
  { id: 3, label: "Học tập", icon: GraduationCap },
  { id: 4, label: "Trình độ & Ưu tiên", icon: Award },
  { id: 5, label: "Điểm & Điều kiện", icon: Calculator },
  { id: 6, label: "Tài liệu pháp lý", icon: FileText },
  { id: 7, label: "Học phí", icon: Wallet },
  { id: 8, label: "Hoàn tất & Nộp", icon: CheckSquare },
]

/**
 * Semantic step ids — name the pipeline positions so consumers (e.g. the CTA
 * router in `priorityIssues.ts`) reference `STEP.FAMILY` instead of a bare `2`.
 * If the 8-step model is ever reordered, update THIS map alongside
 * `ADMISSION_STEPS` in one place rather than hunting magic numbers.
 */
export const STEP = {
  PERSONAL: 1,
  FAMILY: 2,
  ACADEMIC: 3,
  PRIORITY: 4,
  SCORES: 5,
  DOCUMENTS: 6,
  TUITION: 7,
  FINALIZE: 8,
} as const

/**
 * Map a `grouped_validation_errors` section key (backend `_compute_frontend_fields`,
 * admission_service.py:1878) → its pipeline step. Drives message-level ActionItems
 * in `useSubmissionReadiness` (STEP8 plan B2). Step 4 (priority) is derived
 * separately via `derivePriorityIssues`; step 2/3 are section-level (step_status).
 */
export const GROUPED_SECTION_TO_STEP = {
  personal_info: 1,
  scores: 5,
  documents: 6,
} as const

export type GroupedSectionKey = keyof typeof GROUPED_SECTION_TO_STEP

/** Lookup a step's Vietnamese label; falls back to a generic "Bước N". */
export function getAdmissionStepLabel(id: number): string {
  return ADMISSION_STEPS.find((s) => s.id === id)?.label ?? `Bước ${id}`
}
