// src/components/layouts/SecurityBanner.tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Shield, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/stores/auth.store";

const DISMISS_KEY = "security_banner_dismissed_until";
const DISMISS_DURATION_MS = 24 * 60 * 60 * 1000; // 24 hours

/**
 * Security Banner - Shows when user.password_reset_required is true
 * 
 * Displays a persistent banner reminding the user to change their password
 * after a "Secure Account" action. User can:
 * - Click "Đổi ngay" to navigate to settings
 * - Click "Nhắc sau" to dismiss for 24 hours
 */
export function SecurityBanner() {
  const router = useRouter();
  const { user } = useAuthStore();
  const [isDismissed, setIsDismissed] = useState(true); // Start hidden to avoid flash

  // Check if banner should be shown
  const shouldShowBanner = useCallback(() => {
    // Only show if password_reset_required is true
    if (!user?.password_reset_required) {
      return false;
    }

    // Check if user has dismissed and if dismiss period has expired
    const dismissedUntil = localStorage.getItem(DISMISS_KEY);
    if (dismissedUntil) {
      const dismissedUntilTime = parseInt(dismissedUntil, 10);
      if (Date.now() < dismissedUntilTime) {
        return false; // Still within dismiss period
      }
      // Dismiss period expired, remove key
      localStorage.removeItem(DISMISS_KEY);
    }

    return true;
  }, [user?.password_reset_required]);

  // Check on mount and when user changes
  useEffect(() => {
    setIsDismissed(!shouldShowBanner());
  }, [shouldShowBanner]);

  // Handle "Đổi ngay" click
  const handleChangeNow = () => {
    router.push("/settings");
  };

  // Handle "Nhắc sau" click - dismiss for 24 hours
  const handleRemindLater = () => {
    const dismissUntil = Date.now() + DISMISS_DURATION_MS;
    localStorage.setItem(DISMISS_KEY, dismissUntil.toString());
    setIsDismissed(true);
  };

  // Don't render if dismissed or no need to show
  if (isDismissed) {
    return null;
  }

  return (
    <div className="bg-amber-500 text-amber-950 px-4 py-2.5 flex items-center justify-between gap-4 shadow-md">
      <div className="flex items-center gap-3">
        <Shield className="h-5 w-5 flex-shrink-0" />
        <span className="text-sm font-medium">
          Vì lý do bảo mật, bạn nên đổi mật khẩu ngay bây giờ.
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          className="bg-amber-600 hover:bg-amber-700 text-white border-0 h-7 text-xs"
          onClick={handleChangeNow}
        >
          Đổi ngay
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-amber-950 hover:bg-amber-400/50 h-7 text-xs"
          onClick={handleRemindLater}
        >
          Nhắc sau
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="text-amber-950 hover:bg-amber-400/50 h-7 w-7"
          onClick={handleRemindLater}
          aria-label="Đóng"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
