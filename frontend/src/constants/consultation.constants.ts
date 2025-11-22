// src/constants/consultation.constants.ts
/**
 * Centralized Consultation Constants
 *
 * Single source of truth for consultation/pipeline-related enums and options.
 * Used across ConsultationStatusDialog, ConsultationDialog, TransitionMatrix, etc.
 */

import { OutcomeType } from "@/types/pipeline.types";

// =============================================================================
// LEGACY STATUS OPTIONS
// =============================================================================

export interface LegacyStatusOption {
  value: string;
  label: string;
}

/**
 * Valid legacy status values for lead.status backward compatibility
 * Maps consultation statuses to the original lead status enum
 */
export const LEGACY_STATUS_OPTIONS: LegacyStatusOption[] = [
  { value: "new", label: "New" },
  { value: "assigned", label: "Assigned" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "unqualified", label: "Unqualified" },
  { value: "converted", label: "Converted" },
  { value: "rejected", label: "Rejected" },
];

// =============================================================================
// OUTCOME TYPE OPTIONS
// =============================================================================

export interface OutcomeTypeOption {
  value: OutcomeType;
  label: string;
  color: string;
  bgColor: string;
  description: string;
}

export const OUTCOME_TYPE_OPTIONS: OutcomeTypeOption[] = [
  {
    value: OutcomeType.POSITIVE,
    label: "Positive",
    color: "text-green-700",
    bgColor: "bg-green-100",
    description: "Ket qua tich cuc, lead tien den chuyen doi",
  },
  {
    value: OutcomeType.NEUTRAL,
    label: "Neutral",
    color: "text-gray-700",
    bgColor: "bg-gray-100",
    description: "Trang thai trung gian, can theo doi them",
  },
  {
    value: OutcomeType.NEGATIVE,
    label: "Negative",
    color: "text-red-700",
    bgColor: "bg-red-100",
    description: "Ket qua tieu cuc, lead khong phu hop",
  },
];

// Helpers
export const getOutcomeTypeOption = (value: OutcomeType): OutcomeTypeOption | undefined =>
  OUTCOME_TYPE_OPTIONS.find((option) => option.value === value);

export const getOutcomeTypeColor = (value: OutcomeType): string =>
  getOutcomeTypeOption(value)?.color ?? "text-gray-500";

export const getOutcomeTypeBgColor = (value: OutcomeType): string =>
  getOutcomeTypeOption(value)?.bgColor ?? "bg-gray-100";

// =============================================================================
// PRESET COLORS
// =============================================================================

export interface PresetColor {
  name: string;
  value: string;
}

/**
 * Preset color palette for status configuration
 */
export const PRESET_COLORS: PresetColor[] = [
  { name: "Blue", value: "#3B82F6" },
  { name: "Green", value: "#10B981" },
  { name: "Yellow", value: "#F59E0B" },
  { name: "Red", value: "#EF4444" },
  { name: "Purple", value: "#8B5CF6" },
  { name: "Pink", value: "#EC4899" },
  { name: "Indigo", value: "#6366F1" },
  { name: "Gray", value: "#6B7280" },
  { name: "Teal", value: "#14B8A6" },
  { name: "Orange", value: "#F97316" },
  { name: "Cyan", value: "#06B6D4" },
  { name: "Lime", value: "#84CC16" },
];

// Helper to get color by value
export const getPresetColorName = (value: string): string | undefined =>
  PRESET_COLORS.find((c) => c.value.toLowerCase() === value.toLowerCase())?.name;

// Helper to check if a color is from preset
export const isPresetColor = (value: string): boolean =>
  PRESET_COLORS.some((c) => c.value.toLowerCase() === value.toLowerCase());

// =============================================================================
// DEFAULT VALUES
// =============================================================================

export const DEFAULT_STATUS_COLOR = "#3B82F6"; // Blue
export const DEFAULT_OUTCOME_TYPE: OutcomeType = OutcomeType.NEUTRAL;
