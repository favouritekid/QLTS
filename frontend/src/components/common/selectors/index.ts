// src/components/common/selectors/index.ts
/**
 * Smart Selector Components
 *
 * Reusable selector components with built-in data fetching,
 * filtering, and formatting. Based on the Smart Component architecture.
 *
 * Usage:
 *   import { SmartUnitSelector, SmartConsultationStatusSelector, SmartOfferingSelector } from '@/components/common/selectors';
 */

// Organization Unit Selector
export { SmartUnitSelector } from "./SmartUnitSelector";
export type { SmartUnitSelectorProps } from "./SmartUnitSelector";

// Consultation Status Selector
export { SmartConsultationStatusSelector } from "./SmartConsultationStatusSelector";
export type { SmartConsultationStatusSelectorProps } from "./SmartConsultationStatusSelector";

// Program Offering Selector
export { SmartOfferingSelector } from "./SmartOfferingSelector";
export type { SmartOfferingSelectorProps } from "./SmartOfferingSelector";
