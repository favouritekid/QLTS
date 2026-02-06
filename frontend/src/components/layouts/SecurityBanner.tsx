// src/components/layouts/SecurityBanner.tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Shield, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/stores/auth.store";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

const DISMISS_KEY = "security_banner_dismissed_until";
const DISMISS_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours
export const SECURITY_BANNER_HEIGHT = 44; // px - height of the banner

/**
 * Store to track security banner visibility state globally
 * This ensures Header and Main content are in sync with banner visibility
 * 
 * PERSISTED to sessionStorage to survive client-side navigation between pages.
 * This fixes the race condition where triggerBannerCheck() sets isVisible=true
 * but the value is lost during Next.js navigation.
 */
interface SecurityBannerStore {
  isVisible: boolean;
  setVisible: (visible: boolean) => void;
}

export const useSecurityBannerStore = create<SecurityBannerStore>()(
  persist(
    (set) => ({
      isVisible: false,
      setVisible: (visible: boolean) => set({ isVisible: visible }),
    }),
    {
      name: "security-banner-storage",
      storage: createJSONStorage(() => sessionStorage),
    }
  )
);

/**
 * Hook to check if security banner should be visible
 * Used by other components (e.g., Header) to adjust their positioning
 * Returns the global visibility state that accounts for both:
 * - password_reset_required flag
 * - Local dismiss state (24h localStorage)
 */
export function useShouldShowSecurityBanner(): boolean {
  const { isVisible } = useSecurityBannerStore();
  return isVisible;
}

/**
 * Trigger function to check and update banner visibility
 * Call this after login to ensure banner appears immediately
 * @param password_reset_required - The user's password_reset_required flag from login response
 */
export function triggerBannerCheck(password_reset_required: boolean | undefined): void {
  const shouldShow = checkShouldShowBanner(password_reset_required);
  useSecurityBannerStore.getState().setVisible(shouldShow);
}

/**
 * Check if banner should be visible based on user state and localStorage
 */
function checkShouldShowBanner(password_reset_required: boolean | undefined): boolean {
  // Only show if password_reset_required is true
  if (!password_reset_required) {
    return false;
  }

  // Check if user has dismissed and if dismiss period has expired
  if (typeof window !== "undefined") {
    const dismissedUntil = localStorage.getItem(DISMISS_KEY);
    if (dismissedUntil) {
      const dismissedUntilTime = parseInt(dismissedUntil, 10);
      if (Date.now() < dismissedUntilTime) {
        return false; // Still within dismiss period
      }
      // Dismiss period expired, remove key
      localStorage.removeItem(DISMISS_KEY);
    }
  }

  return true;
}

/**
 * Security Banner - Shows when user.password_reset_required is true
 * 
 * Displays a persistent banner reminding the user to change their password
 * after a "Secure Account" action. User can:
 * - Click "Đổi ngay" to navigate to settings
 * - Click "Nhắc sau" to dismiss for 24 hours
 * 
 * STATE PERSISTENCE FIX:
 * - useSecurityBannerStore is now persisted to sessionStorage
 * - triggerBannerCheck() sets isVisible=true in login callback
 * - The sessionStorage persistence ensures the value survives navigation
 * - Fallback effect re-syncs if user.password_reset_required is somehow out of sync
 */
export function SecurityBanner() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { isVisible, setVisible } = useSecurityBannerStore();

  // Sync visibility state when user changes (e.g., after password change clears flag)
  // This effect runs on login (user: null → user object) and on user profile updates
  useEffect(() => {
    // If user logs out or password_reset_required becomes false, hide the banner
    if (!user?.password_reset_required) {
      // Only set to false if currently visible, to avoid unnecessary state updates
      if (isVisible) {
        setVisible(false);
      }
      // Clean up dismiss key when password_reset_required is cleared (after password change)
      // This ensures next time password_reset_required=true, banner shows immediately
      if (typeof window !== "undefined") {
        localStorage.removeItem(DISMISS_KEY);
      }
      return;
    }
    
    // Check dismiss state for non-persisted users
    const dismissedUntil = localStorage.getItem(DISMISS_KEY);
    if (dismissedUntil) {
      const dismissedUntilTime = parseInt(dismissedUntil, 10);
      if (Date.now() < dismissedUntilTime) {
        if (isVisible) {
          setVisible(false);
        }
        return;
      }
      localStorage.removeItem(DISMISS_KEY);
    }
    
    // User has password_reset_required=true and not dismissed - show banner
    if (!isVisible) {
      setVisible(true);
    }
  }, [user?.password_reset_required, isVisible, setVisible]);

  // Handle "Đổi ngay" click
  const handleChangeNow = () => {
    router.push("/settings");
  };

  // Handle "Nhắc sau" click - dismiss for 24 hours
  const handleRemindLater = () => {
    const dismissUntil = Date.now() + DISMISS_DURATION_MS;
    if (typeof window !== "undefined") {
      localStorage.setItem(DISMISS_KEY, dismissUntil.toString());
    }
    setVisible(false); // Update global state immediately
  };

  // Don't render if not visible
  if (!isVisible) {
    return null;
  }

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-warning-500 text-warning-950 px-4 py-2.5 flex items-center justify-between gap-4 shadow-md">
      <div className="flex items-center gap-3">
        <Shield aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
        <span className="text-sm font-medium">
          Vì lý do bảo mật, bạn nên đổi mật khẩu ngay bây giờ.
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          className="bg-warning-600 hover:bg-warning-700 text-white border-0 h-7 text-xs"
          onClick={handleChangeNow}
        >
          Đổi ngay
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-warning-950 hover:bg-warning-400/50 h-7 text-xs"
          onClick={handleRemindLater}
        >
          Nhắc sau
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="text-warning-950 hover:bg-warning-400/50 h-7 w-7"
          onClick={handleRemindLater}
          aria-label="Đóng"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
