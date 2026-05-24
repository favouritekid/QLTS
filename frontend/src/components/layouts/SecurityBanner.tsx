// src/components/layouts/SecurityBanner.tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Shield, ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/stores/auth.store";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

const DISMISS_KEY = "security_banner_dismissed_until";
const DISMISS_SUSPICIOUS_KEY = "security_banner_suspicious_dismissed_until";
const DISMISS_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours
export const SECURITY_BANNER_HEIGHT = 44; // px - height of the banner

/**
 * Banner type determines which alert is shown.
 * Priority: password_reset > suspicious_login
 */
type BannerType = "password_reset" | "suspicious_login" | null;

/**
 * Store to track security banner visibility state globally.
 * Persisted to sessionStorage to survive client-side navigation.
 */
interface SecurityBannerStore {
  isVisible: boolean;
  bannerType: BannerType;
  suspiciousCount: number;
  setVisible: (visible: boolean) => void;
  setBannerType: (type: BannerType) => void;
  setSuspiciousCount: (count: number) => void;
}

export const useSecurityBannerStore = create<SecurityBannerStore>()(
  persist(
    (set) => ({
      isVisible: false,
      bannerType: null,
      suspiciousCount: 0,
      setVisible: (visible: boolean) => set({ isVisible: visible }),
      setBannerType: (bannerType: BannerType) => set({ bannerType }),
      setSuspiciousCount: (suspiciousCount: number) => set({ suspiciousCount }),
    }),
    {
      name: "security-banner-storage",
      storage: createJSONStorage(() => sessionStorage),
    }
  )
);

/**
 * Hook to check if security banner should be visible.
 * Used by Header and DashboardLayout for positioning.
 */
export function useShouldShowSecurityBanner(): boolean {
  const { isVisible } = useSecurityBannerStore();
  return isVisible;
}

/**
 * Trigger banner check for password_reset_required.
 * Called after login in useAuth.ts.
 */
export function triggerBannerCheck(
  password_reset_required: boolean | undefined
): void {
  const store = useSecurityBannerStore.getState();

  if (password_reset_required && !isDismissed(DISMISS_KEY)) {
    store.setBannerType("password_reset");
    store.setVisible(true);
    return;
  }

  // If no password reset needed, check if suspicious logins banner should show
  if (!password_reset_required && store.bannerType === "password_reset") {
    // Password reset resolved — check if suspicious banner should take over
    if (store.suspiciousCount > 0 && !isDismissed(DISMISS_SUSPICIOUS_KEY)) {
      store.setBannerType("suspicious_login");
      store.setVisible(true);
    } else {
      store.setBannerType(null);
      store.setVisible(false);
    }
  }
}

/**
 * Trigger banner for suspicious logins.
 * Called after login when login_notification is present, or after fetching suspicious count.
 */
export function triggerSuspiciousLoginBanner(count: number): void {
  const store = useSecurityBannerStore.getState();
  store.setSuspiciousCount(count);

  // Don't override password_reset banner (higher priority)
  if (store.bannerType === "password_reset" && store.isVisible) {
    return;
  }

  if (count > 0 && !isDismissed(DISMISS_SUSPICIOUS_KEY)) {
    store.setBannerType("suspicious_login");
    store.setVisible(true);
  } else if (count === 0 && store.bannerType === "suspicious_login") {
    store.setBannerType(null);
    store.setVisible(false);
  }
}

/**
 * Option-B Commit 8: increment the banner count by one in response to a
 * real-time ``suspicious_login`` socket event (a NEW suspicious login
 * landed in another session while this tab is open).
 *
 * Unlike ``triggerSuspiciousLoginBanner`` which SETS an absolute count
 * (from the login response or the /settings/security fetch), this
 * helper ADDS to the current count — the socket payload represents one
 * incremental event, and we don't want a re-fetch round-trip just to
 * learn "+1". The SocketHandler also debounce-invalidates the
 * ``loginHistory`` query so the authoritative count reconciles on the
 * next /settings/security visit.
 *
 * Respects the same priority + dismiss rules as the SET path: the
 * password_reset banner still wins, and a dismissed banner stays
 * dismissed (the user explicitly snoozed for 24h).
 */
export function bumpSuspiciousLoginBanner(): void {
  const store = useSecurityBannerStore.getState();
  const nextCount = store.suspiciousCount + 1;
  store.setSuspiciousCount(nextCount);

  // password_reset banner has higher priority — keep it showing.
  if (store.bannerType === "password_reset" && store.isVisible) {
    return;
  }

  // Honour an active 24h dismissal — don't re-surface a snoozed banner.
  if (isDismissed(DISMISS_SUSPICIOUS_KEY)) {
    return;
  }

  store.setBannerType("suspicious_login");
  store.setVisible(true);
}

function isDismissed(key: string): boolean {
  if (typeof window === "undefined") return false;
  const dismissedUntil = localStorage.getItem(key);
  if (!dismissedUntil) return false;
  const until = parseInt(dismissedUntil, 10);
  if (Date.now() < until) return true;
  localStorage.removeItem(key);
  return false;
}

function dismiss(key: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem(key, (Date.now() + DISMISS_DURATION_MS).toString());
  }
}

/**
 * Security Banner Component
 *
 * Shows persistent alerts for:
 * 1. password_reset_required — "Đổi mật khẩu ngay" (priority)
 * 2. Pending suspicious logins — "Phát hiện N đăng nhập đáng ngờ"
 */
export function SecurityBanner() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { isVisible, bannerType, suspiciousCount, setVisible, setBannerType } =
    useSecurityBannerStore();

  // Sync visibility when user state changes
  useEffect(() => {
    // Password reset resolved
    if (!user?.password_reset_required && bannerType === "password_reset") {
      localStorage.removeItem(DISMISS_KEY);
      // Fall through to suspicious login check
      if (suspiciousCount > 0 && !isDismissed(DISMISS_SUSPICIOUS_KEY)) {
        setBannerType("suspicious_login");
      } else {
        setBannerType(null);
        setVisible(false);
      }
      return;
    }

    // Password reset required — show if not dismissed
    if (user?.password_reset_required && bannerType !== "password_reset") {
      if (!isDismissed(DISMISS_KEY)) {
        setBannerType("password_reset");
        setVisible(true);
      }
    }
  }, [user?.password_reset_required, bannerType, suspiciousCount, setVisible, setBannerType]);

  if (!isVisible || !bannerType) return null;

  // ---- Password Reset Banner ----
  if (bannerType === "password_reset") {
    return (
      <div className="bg-warning-500 text-warning-950 fixed top-0 right-0 left-0 z-50 flex items-center justify-between gap-4 px-4 py-2.5 shadow-md">
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
            className="bg-warning-600 hover:bg-warning-700 h-7 border-0 text-xs text-white"
            onClick={() => router.push("/settings")}
          >
            Đổi ngay
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-warning-950 hover:bg-warning-400/50 h-7 text-xs"
            onClick={() => {
              dismiss(DISMISS_KEY);
              // Check if suspicious banner should take over
              if (suspiciousCount > 0 && !isDismissed(DISMISS_SUSPICIOUS_KEY)) {
                setBannerType("suspicious_login");
              } else {
                setVisible(false);
              }
            }}
          >
            Nhắc sau
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="text-warning-950 hover:bg-warning-400/50 h-7 w-7"
            onClick={() => {
              dismiss(DISMISS_KEY);
              if (suspiciousCount > 0 && !isDismissed(DISMISS_SUSPICIOUS_KEY)) {
                setBannerType("suspicious_login");
              } else {
                setVisible(false);
              }
            }}
            aria-label="Đóng"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  // ---- Suspicious Login Banner ----
  return (
    <div className="fixed top-0 right-0 left-0 z-50 flex items-center justify-between gap-4 bg-orange-500 px-4 py-2.5 text-white shadow-md">
      <div className="flex items-center gap-3">
        <ShieldAlert aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
        <span className="text-sm font-medium">
          Phát hiện {suspiciousCount} đăng nhập đáng ngờ cần xác nhận.
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          className="h-7 border-0 bg-orange-600 text-xs text-white hover:bg-orange-700"
          onClick={() => router.push("/settings/security")}
        >
          Xem ngay
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 text-white hover:bg-orange-400/50"
          onClick={() => {
            dismiss(DISMISS_SUSPICIOUS_KEY);
            setVisible(false);
          }}
          aria-label="Đóng"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
