// src/constants/index.ts
/**
 * Centralized Constants
 *
 * Single source of truth for all enum options and configuration constants.
 *
 * Usage:
 *   import { LEAD_STATUS_OPTIONS, PRESET_COLORS } from '@/constants';
 */

// Lead Constants
export {
  LEAD_STATUS_OPTIONS,
  LEAD_SOURCE_OPTIONS,
  COMPLEX_STATUS_IDS,
  SCHEDULABLE_STATUS_IDS,
  getLeadStatusOption,
  getLeadStatusColor,
  getLeadStatusLabel,
  getLeadSourceOption,
  getLeadSourceLabel,
  isComplexStatus,
  isSchedulableStatus,
} from "./lead.constants";
export type { LeadStatusOption, LeadSourceOption } from "./lead.constants";

// Consultation Constants
export {
  LEGACY_STATUS_OPTIONS,
  OUTCOME_TYPE_OPTIONS,
  PRESET_COLORS,
  DEFAULT_STATUS_COLOR,
  DEFAULT_OUTCOME_TYPE,
  getOutcomeTypeOption,
  getOutcomeTypeColor,
  getOutcomeTypeBgColor,
  getPresetColorName,
  isPresetColor,
} from "./consultation.constants";
export type { LegacyStatusOption, OutcomeTypeOption, PresetColor } from "./consultation.constants";
