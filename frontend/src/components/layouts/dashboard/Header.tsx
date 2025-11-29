// src/components/layouts/dashboard/Header.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Menu, Search, Command as CommandIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { NotificationDropdown } from "@/components/notifications/NotificationDropdown";
import { useCommandPalette } from "@/hooks/useCommandPalette";

const TopNav = () => (
  <nav className="hidden items-center gap-4 text-sm font-medium lg:flex">
    <Link
      href="/dashboard"
      className="text-muted-foreground hover:text-foreground transition-colors"
    >
      Dashboard
    </Link>
    <Link href="/leads" className="text-muted-foreground hover:text-foreground transition-colors">
      Leads
    </Link>
    <Link
      href="/admin/users"
      className="text-muted-foreground hover:text-foreground transition-colors"
    >
      Users
    </Link>
  </nav>
);

export function Header() {
  const { isSidebarCollapsed, toggleSidebar } = useUIStore();
  const { open } = useCommandPalette();

  return (
    <header
      className={cn(
        // Base styles - z-index cao để luôn ở trên main content
        "bg-background/95 fixed top-0 right-0 z-40 flex h-14 items-center gap-4 border-b px-4 backdrop-blur-sm md:px-6",
        // Smooth transition
        "transition-all duration-300 ease-in-out",
        // Left position based on sidebar state
        "left-0",
        "lg:left-[72px]",
        !isSidebarCollapsed && "lg:left-64"
      )}
    >
      {/* Toggle Button */}
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 shrink-0"
        onClick={toggleSidebar}
        aria-label="Toggle sidebar"
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
          className="relative h-9 w-9 p-0 md:w-auto md:px-3 md:justify-start md:gap-2 text-sm text-muted-foreground"
        >
          <Search className="h-4 w-4 md:h-4 md:w-4" />
          <span className="hidden md:inline-flex">Search...</span>
          <kbd className="pointer-events-none ml-auto hidden h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 md:inline-flex">
            <span className="text-xs">⌘</span>K
          </kbd>
        </Button>

        {/* Theme Toggle */}
        <ThemeToggle />

        {/* Notification Dropdown */}
        <NotificationDropdown />
      </div>
    </header>
  );
}
