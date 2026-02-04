// src/components/common/index.ts
/**
 * Common Components
 *
 * Central export for all reusable UI components.
 * Import from this file for cleaner imports:
 *
 *   import { FormInput, DataTable, StatusBadge } from '@/components/common';
 *
 * ✅ PERFORMANCE: Uses explicit named exports to enable tree-shaking.
 * Avoid `export *` which defeats bundler dead-code elimination.
 */

// Form components
export { FormInput } from "./form";
export type { FormInputProps, InputType } from "./form";
export { FormTextarea } from "./form";
export type { FormTextareaProps } from "./form";
export { FormNumber } from "./form";
export type { FormNumberProps } from "./form";
export { DatePicker } from "./form";
export type { DatePickerProps } from "./form";
export { DateTimePicker } from "./form";
export type { DateTimePickerProps } from "./form";
export { SearchInput } from "./form";
export type { SearchInputProps } from "./form";

// Table components
export { Pagination } from "./table";
export type { PaginationProps } from "./table";
export { DataTable } from "./table";
export type { DataTableProps } from "./table";
export { DataTableToolbar } from "./table";
export type { DataTableToolbarProps } from "./table";

// Modal components
export { ConfirmDialog } from "./modals";
export type { ConfirmDialogProps, ConfirmDialogVariant } from "./modals";
export { FormModal } from "./modals";
export type { FormModalProps } from "./modals";

// Upload components
export { FileUpload } from "./upload";
export type { FileUploadProps, FileItem } from "./upload";
export { ImageUpload } from "./upload";
export type { ImageUploadProps } from "./upload";

// Status components
export {
  StatusBadge,
  StatusFromMap,
  AdmissionBadge,
  LeadBadge,
  ScoreLevelBadge,
  getStatusConfig,
} from "./status";
export type {
  StatusBadgeProps,
  StatusFromMapProps,
  StatusConfig,
  StatusVariant,
} from "./status";
export {
  LEAD_STATUS_MAP,
  ADMISSION_STATUS_MAP,
  SCORE_LEVEL_MAP,
  PAYMENT_STATUS_MAP,
  CONSULTATION_STATUS_MAP,
  ACTIVE_STATUS_MAP,
} from "./status";

// Selector components
export { SmartUnitSelector } from "./selectors";
export type { SmartUnitSelectorProps } from "./selectors";
export { SmartConsultationStatusSelector } from "./selectors";
export type { SmartConsultationStatusSelectorProps } from "./selectors";
export { SmartOfferingSelector } from "./selectors";
export type { SmartOfferingSelectorProps } from "./selectors";
export { MultiOfferingSelector } from "./selectors";
export type { MultiOfferingSelectorProps } from "./selectors";

// Navigation components
export { BackButton } from "./BackButton";
export { Breadcrumbs } from "./Breadcrumbs";

// Workflow components
export { WorkflowBreadcrumb, MiniBreadcrumb } from "./WorkflowBreadcrumb";
export type { WorkflowBreadcrumbProps, MiniBreadcrumbProps } from "./WorkflowBreadcrumb";
