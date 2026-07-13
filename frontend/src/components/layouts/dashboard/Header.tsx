// src/components/layouts/dashboard/Header.tsx
"use client";

import { useState } from "react";
import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Menu, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { NotificationDropdown } from "@/components/notifications/NotificationDropdown";
import { AppointmentReminder } from "@/components/leads/AppointmentReminder";
import { useCommandPalette } from "@/hooks/useCommandPalette";
import { useShouldShowSecurityBanner, SECURITY_BANNER_HEIGHT } from "@/components/layouts/SecurityBanner";
import { useAuth } from "@/hooks/useAuth";

const ADMIN_NAV_ROLES = ["admin", "manager"];

const TopNav = () => {
  const { user } = useAuth();
  const canAccessAdmin = user?.role ? ADMIN_NAV_ROLES.includes(user.role) : false;

  return (
    <nav className="hidden items-center gap-4 text-sm font-medium lg:flex">
      <Link
        href="/dashboard"
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        Bảng điều khiển
      </Link>
      <Link href="/leads" className="text-muted-foreground hover:text-foreground transition-colors">
        Lead
      </Link>
      {canAccessAdmin && (
        <Link
          href="/admin/users"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          Người dùng
        </Link>
      )}
    </nav>
  );
};

export function Header() {
  const { isSidebarCollapsed, toggleSidebar } = useUIStore();
  const { open } = useCommandPalette();
  const showSecurityBanner = useShouldShowSecurityBanner();
  const [isMac, setIsMac] = useState(() =>
    typeof navigator !== "undefined"
      ? /Mac|iPod|iPhone|iPad/.test(navigator.platform)
      : false
  );

  return (
    <header
      className={cn(
        // Base styles - z-index cao để luôn ở trên main content
        "bg-background/95 fixed right-0 z-40 flex h-14 items-center gap-4 border-b px-4 backdrop-blur-sm md:px-6",
        // Smooth transition
        "transition-colors duration-300 ease-in-out",
        // Left position based on sidebar state
        "left-0",
        "lg:left-[72px]",
        !isSidebarCollapsed && "lg:left-64"
      )}
      style={{
        // Adjust top position when security banner is visible
        top: showSecurityBanner ? `${SECURITY_BANNER_HEIGHT}px` : 0,
      }}
    >
      {/* Toggle Button */}
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0"
        onClick={toggleSidebar}
        aria-label="Bật/tắt thanh bên"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Top Navigation */}
      <TopNav />

      {/* Right Section */}
      <div className="ml-auto flex items-center gap-2 md:gap-3">
        {/* Command Palette Trigger */}
        <Button
          variant="outline"
          onClick={open}
          aria-label="Tìm kiếm trang và thao tác"
          className={cn(
            "relative h-9 w-9 p-0 md:w-auto md:px-3 md:justify-start md:gap-2 text-sm text-muted-foreground",
            "transition-colors duration-200 ease-in-out",
            "hover:shadow-md",
            "group"
          )}
        >
          <Search className="h-4 w-4 md:h-4 md:w-4" />
          <span className="hidden md:inline-flex transition-colors duration-200 group-hover:text-foreground">
            Tìm kiếm…
          </span>
          <kbd className={cn(
            "pointer-events-none ml-auto hidden h-5 select-none items-center gap-1",
            "rounded border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 md:inline-flex",
            "transition-colors duration-200 group-hover:bg-accent"
          )}>
            <span className="text-xs" suppressHydrationWarning>{isMac ? "⌘" : "Ctrl+"}</span>K
          </kbd>
        </Button>

        {/* Theme Toggle */}
        <ThemeToggle />

        {/* Nhắc lịch hẹn ("Nhịp hẹn") */}
        <AppointmentReminder />

        {/* Notification Dropdown */}
        <NotificationDropdown />
      </div>
    </header>
  );
}
