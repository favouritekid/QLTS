// src/components/layouts/dashboard/Header.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Menu, Search, Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/ui/theme-toggle";

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
        {/* Search Bar */}
        <div className="relative hidden md:block">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 h-4 w-4" />
          <Input
            type="search"
            placeholder="Search..."
            className="bg-muted w-[200px] rounded-lg pl-8 lg:w-[250px]"
          />
        </div>

        {/* Theme Toggle */}
        <ThemeToggle />

        {/* Notification Button */}
        <Button variant="ghost" size="icon" className="relative h-9 w-9 rounded-full">
          <Bell className="h-5 w-5" />
          <span className="bg-destructive text-destructive-foreground absolute top-0 right-0 flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold">
            3
          </span>
          <span className="sr-only">Notifications</span>
        </Button>
      </div>
    </header>
  );
}
