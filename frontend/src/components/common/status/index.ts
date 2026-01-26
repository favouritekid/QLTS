// src/components/common/status/index.ts
/**
 * Status Components
 *
 * Reusable status display components with color-coding
 * and predefined status mappings.
 *
 * @example
 * // Using semantic badges (recommended for QLTS)
 * import { AdmissionBadge, LeadBadge, ScoreLevelBadge } from "@/components/common/status"
 * <AdmissionBadge status="approved" />
 * <LeadBadge status="qualified" />
 * <ScoreLevelBadge level="excellent" />
 *
 * // Using generic StatusBadge
 * import { StatusBadge, StatusFromMap, LEAD_STATUS_MAP } from "@/components/common/status"
 * <StatusBadge variant="success">Hoàn thành</StatusBadge>
 * <StatusFromMap status="new" statusMap={LEAD_STATUS_MAP} />
 */

// Main components
export {
  StatusBadge,
  StatusFromMap,
  AdmissionBadge,
  LeadBadge,
  ScoreLevelBadge,
  getStatusConfig,
} from "./StatusBadge";

// Types
export type {
  StatusBadgeProps,
  StatusFromMapProps,
  StatusConfig,
  StatusVariant,
} from "./StatusBadge";

// Pre-defined status maps
export {
  LEAD_STATUS_MAP,
  ADMISSION_STATUS_MAP,
  SCORE_LEVEL_MAP,
  PAYMENT_STATUS_MAP,
  CONSULTATION_STATUS_MAP,
  ACTIVE_STATUS_MAP,
} from "./StatusBadge";
