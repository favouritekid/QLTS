// src/components/officer/dashboard/SmartHeader.tsx
/**
 * Smart Header - Clean shadcn design
 * Greeting, date range filter, scope filter (for manager/admin), quick actions
 */

"use client";

import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import {
  Plus,
  Phone,
  Calendar,
  ChevronDown,
  Sparkles,
  Users,
  Building2,
  User,
} from "lucide-react";
import { DateRangeFilter } from "./DateRangeFilter";
import type { DashboardScope } from "@/hooks/useDashboardStats";

interface SmartHeaderProps {
  /** Whether officer reached daily goal (optional, for sparkle icon) */
  isGoalMet?: boolean;
  onQuickAction?: (action: "new_lead" | "log_call" | "schedule") => void;
  /** Current dashboard scope */
  scope?: DashboardScope;
  /** Callback when scope changes */
  onScopeChange?: (scope: DashboardScope) => void;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Chào buổi sáng";
  if (hour < 18) return "Chào buổi chiều";
  return "Chào buổi tối";
}

const SCOPE_LABELS: Record<DashboardScope, { label: string; icon: typeof User }> = {
  personal: { label: "Cá nhân", icon: User },
  team: { label: "Đội nhóm", icon: Users },
  organization: { label: "Tổ chức", icon: Building2 },
};

export function SmartHeader({
  isGoalMet = false,
  onQuickAction,
  scope = "personal",
  onScopeChange,
}: SmartHeaderProps) {
  const { user } = useAuth();
  
  // Determine if user can change scope
  const canChangeScope = user?.role === "manager" || user?.role === "admin";
  const availableScopes: DashboardScope[] = 
    user?.role === "admin" 
      ? ["personal", "team", "organization"]
      : user?.role === "manager"
        ? ["personal", "team"]
        : ["personal"];

  const currentScopeInfo = SCOPE_LABELS[scope];
  const ScopeIcon = currentScopeInfo.icon;

  return (
    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      {/* Left: Greeting + Date */}
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          {getGreeting()}, {user?.full_name || user?.username || "Officer"}!
          {isGoalMet && <Sparkles className="h-5 w-5 text-amber-500" />}
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          {new Date().toLocaleDateString("vi-VN", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      {/* Right: Scope Filter + Date Range Filter + Quick Actions */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Scope Filter (only for manager/admin) */}
        {canChangeScope && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <ScopeIcon className="h-4 w-4" />
                {currentScopeInfo.label}
                <ChevronDown className="h-3 w-3 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuLabel>Phạm vi xem</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuRadioGroup 
                value={scope} 
                onValueChange={(value) => onScopeChange?.(value as DashboardScope)}
              >
                {availableScopes.map((s) => {
                  const info = SCOPE_LABELS[s];
                  const Icon = info.icon;
                  return (
                    <DropdownMenuRadioItem key={s} value={s} className="gap-2">
                      <Icon className="h-4 w-4" />
                      {info.label}
                    </DropdownMenuRadioItem>
                  );
                })}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Date Range Filter */}
        <DateRangeFilter />

        {/* Quick Actions */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-4 w-4" />
              Thao tác
              <ChevronDown className="h-3 w-3 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onClick={() => onQuickAction?.("new_lead")}>
              <Plus className="h-4 w-4 mr-2" />
              Thêm Lead
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onQuickAction?.("log_call")}>
              <Phone className="h-4 w-4 mr-2" />
              Ghi cuộc gọi
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onQuickAction?.("schedule")}>
              <Calendar className="h-4 w-4 mr-2" />
              Đặt lịch hẹn
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
