// src/components/common/status/index.ts
/**
 * Status Components
 *
 * Reusable status display components with color-coding
 * and predefined status mappings.
 */

export { StatusBadge, StatusFromMap, getStatusConfig } from "./StatusBadge";
export type { StatusBadgeProps, StatusFromMapProps, StatusConfig, StatusVariant } from "./StatusBadge";

// Pre-defined status maps
export {
  LEAD_STATUS_MAP,
  PAYMENT_STATUS_MAP,
  CONSULTATION_STATUS_MAP,
  ACTIVE_STATUS_MAP,
} from "./StatusBadge";
