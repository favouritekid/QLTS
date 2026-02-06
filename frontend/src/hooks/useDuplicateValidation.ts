/**
 * Real-time duplicate validation hook for Lead forms
 *
 * Features:
 * - Debounced API calls (500ms) to avoid excessive requests
 * - Separate validation for phone and email
 * - Visual state management (idle, checking, valid, invalid)
 * - Conflict info display
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { leadsApi } from "@/lib/api/leads";

// Validation states
export type ValidationState = "idle" | "checking" | "valid" | "invalid";

export interface DuplicateValidation {
  state: ValidationState;
  message: string | null;
}

export interface UseDuplicateValidationOptions {
  /** Debounce delay in milliseconds (default: 500) */
  debounceMs?: number;
  /** Lead ID to exclude from check (for edit mode) */
  excludeId?: number;
  /** Unit ID for email scope check */
  unitId?: number;
}

export interface UseDuplicateValidationResult {
  /** Phone validation state */
  phone: DuplicateValidation;
  /** Email validation state */
  email: DuplicateValidation;
  /** Validate phone number */
  validatePhone: (phone: string) => void;
  /** Validate email */
  validateEmail: (email: string) => void;
  /** Reset all validations */
  reset: () => void;
  /** Check if any validation is in progress */
  isChecking: boolean;
  /** Check if all validations passed */
  isValid: boolean;
}

// Vietnam phone regex - matches backend validation
const VIETNAM_PHONE_REGEX = /^(0|\+?84)(3|5|7|8|9|2)\d{8,9}$/;

// Normalize phone number (remove spaces, dashes, dots)
const normalizePhone = (phone: string): string => {
  return phone.replace(/[\s\-.()/]/g, "");
};

// Email regex for basic validation
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function useDuplicateValidation(
  options: UseDuplicateValidationOptions = {}
): UseDuplicateValidationResult {
  const { debounceMs = 500, excludeId, unitId } = options;

  // State
  const [phoneValidation, setPhoneValidation] = useState<DuplicateValidation>({
    state: "idle",
    message: null,
  });
  const [emailValidation, setEmailValidation] = useState<DuplicateValidation>({
    state: "idle",
    message: null,
  });

  // Refs for debounce timers
  const phoneTimerRef = useRef<NodeJS.Timeout | null>(null);
  const emailTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (phoneTimerRef.current) clearTimeout(phoneTimerRef.current);
      if (emailTimerRef.current) clearTimeout(emailTimerRef.current);
    };
  }, []);

  // Validate phone with debounce
  const validatePhone = useCallback(
    (phone: string) => {
      // Clear previous timer
      if (phoneTimerRef.current) {
        clearTimeout(phoneTimerRef.current);
      }

      // Empty check
      if (!phone || phone.trim() === "") {
        setPhoneValidation({ state: "idle", message: null });
        return;
      }

      // Normalize phone
      const normalized = normalizePhone(phone);

      // Format validation first
      if (!VIETNAM_PHONE_REGEX.test(normalized)) {
        setPhoneValidation({
          state: "invalid",
          message: "Số điện thoại không hợp lệ (VD: 0901234567)",
        });
        return;
      }

      // Set checking state
      setPhoneValidation({ state: "checking", message: null });

      // Debounced API call
      phoneTimerRef.current = setTimeout(async () => {
        try {
          const result = await leadsApi.checkDuplicate({
            phone: normalized,
            exclude_id: excludeId,
          });

          if (result.phone_available) {
            setPhoneValidation({ state: "valid", message: null });
          } else {
            setPhoneValidation({
              state: "invalid",
              message: result.phone_conflict || "Số điện thoại đã tồn tại",
            });
          }
        } catch {
          // API error - don't block form, just reset to idle
          setPhoneValidation({ state: "idle", message: null });
        }
      }, debounceMs);
    },
    [debounceMs, excludeId]
  );

  // Validate email with debounce
  const validateEmail = useCallback(
    (email: string) => {
      // Clear previous timer
      if (emailTimerRef.current) {
        clearTimeout(emailTimerRef.current);
      }

      // Empty check - email is optional
      if (!email || email.trim() === "") {
        setEmailValidation({ state: "idle", message: null });
        return;
      }

      // Format validation first
      if (!EMAIL_REGEX.test(email)) {
        setEmailValidation({
          state: "invalid",
          message: "Email không hợp lệ",
        });
        return;
      }

      // Need unitId for email check
      if (!unitId) {
        setEmailValidation({ state: "idle", message: null });
        return;
      }

      // Set checking state
      setEmailValidation({ state: "checking", message: null });

      // Debounced API call
      emailTimerRef.current = setTimeout(async () => {
        try {
          const result = await leadsApi.checkDuplicate({
            email,
            unit_id: unitId,
            exclude_id: excludeId,
          });

          if (result.email_available) {
            setEmailValidation({ state: "valid", message: null });
          } else {
            setEmailValidation({
              state: "invalid",
              message: result.email_conflict || "Email đã tồn tại trong đơn vị",
            });
          }
        } catch {
          // API error - don't block form, just reset to idle
          setEmailValidation({ state: "idle", message: null });
        }
      }, debounceMs);
    },
    [debounceMs, excludeId, unitId]
  );

  // Reset all validations
  const reset = useCallback(() => {
    if (phoneTimerRef.current) clearTimeout(phoneTimerRef.current);
    if (emailTimerRef.current) clearTimeout(emailTimerRef.current);
    setPhoneValidation({ state: "idle", message: null });
    setEmailValidation({ state: "idle", message: null });
  }, []);

  // Derived states
  const isChecking =
    phoneValidation.state === "checking" || emailValidation.state === "checking";

  const isValid =
    phoneValidation.state !== "invalid" && emailValidation.state !== "invalid";

  return {
    phone: phoneValidation,
    email: emailValidation,
    validatePhone,
    validateEmail,
    reset,
    isChecking,
    isValid,
  };
}

export default useDuplicateValidation;
