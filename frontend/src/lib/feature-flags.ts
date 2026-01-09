/**
 * ARCHITECTURE STANDARD: Feature Flags
 * 
 * This module provides feature flags for gradual rollout of new features.
 * Flags can be controlled via environment variables or backend config.
 * 
 * Rules:
 * - Use flags for breaking changes during migration
 * - Remove flags once migration is complete
 * - Default to false for new features (opt-in)
 * 
 * @see ADR-FE-001 Migration Strategy
 */

/**
 * Feature flag definitions.
 * 
 * Environment variables should be prefixed with NEXT_PUBLIC_FF_
 */
export const FEATURE_FLAGS = {
  /**
   * Enable new permission-based rendering via usePermissions hook.
   * When false, falls back to permission-adapter inference.
   */
  USE_PERMISSION_HOOK: process.env.NEXT_PUBLIC_FF_PERMISSION_HOOK === 'true',
  
  /**
   * Enable centralized error handler.
   * When false, uses legacy toast.error calls.
   */
  USE_CENTRALIZED_ERROR_HANDLER: process.env.NEXT_PUBLIC_FF_ERROR_HANDLER === 'true',
  
  /**
   * Enable status-config based rendering.
   * When false, uses hardcoded status labels.
   */
  USE_STATUS_CONFIG: process.env.NEXT_PUBLIC_FF_STATUS_CONFIG === 'true',
  
  /**
   * Enable strict permission checking (no fallback).
   * When false, uses permission-adapter for backward compatibility.
   */
  STRICT_PERMISSIONS: process.env.NEXT_PUBLIC_FF_STRICT_PERMISSIONS === 'true',
} as const

export type FeatureFlagKey = keyof typeof FEATURE_FLAGS

/**
 * Check if a feature flag is enabled.
 * 
 * @param flag - Feature flag key
 * @returns true if flag is enabled
 * 
 * @example
 * if (isFeatureEnabled('USE_PERMISSION_HOOK')) {
 *   // Use new permission system
 * }
 */
export function isFeatureEnabled(flag: FeatureFlagKey): boolean {
  return FEATURE_FLAGS[flag]
}

/**
 * Get all enabled feature flags (for debugging).
 */
export function getEnabledFlags(): FeatureFlagKey[] {
  return (Object.keys(FEATURE_FLAGS) as FeatureFlagKey[])
    .filter(key => FEATURE_FLAGS[key])
}
