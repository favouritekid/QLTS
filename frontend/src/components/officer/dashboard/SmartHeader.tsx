// src/components/officer/dashboard/SmartHeader.tsx
/**
 * Smart Header - Clean shadcn design
 * Greeting, date range filter, scope filter (for manager/admin), quick actions
 *
 * Enhanced: Secondary filters for unit and officer selection
 */

"use client";

import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Plus,
  ChevronDown,
  Sparkles,
  Users,
  Building2,
  User,
} from "lucide-react";
import { DateRangeFilter } from "./DateRangeFilter";
import type { DashboardScope } from "@/hooks/useDashboardStats";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { SmartUnitSelector } from "@/components/common/selectors/SmartUnitSelector";
import type { User as UserType } from "@/types/api.types";

interface SmartHeaderProps {
  /** Whether officer reached daily goal (optional, for sparkle icon) */
  isGoalMet?: boolean;
  onQuickAction?: (action: "new_lead") => void;
  /** Current dashboard scope */
  scope?: DashboardScope;
  /** Callback when scope changes */
  onScopeChange?: (scope: DashboardScope) => void;
  /** Selected officer ID for personal/team drill-down */
  selectedOfficerId?: number | null;
  /** Callback when officer selection changes */
  onOfficerChange?: (officerId: number | null) => void;
  /** Selected unit ID for organization scope (any level in hierarchy) */
  selectedUnitId?: number | null;
  /** Callback when unit selection changes */
  onUnitChange?: (unitId: number | null) => void;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Chào buổi sáng";
  if (hour < 18) return "Chào buổi chiều";
  return "Chào buổi tối";
}

const SCOPE_LABELS: Record<DashboardScope, { label: string; icon: typeof User }> = {
  personal: { label: "Cá nhân", icon: User },
  unit: { label: "Đơn vị", icon: Users },
  organization: { label: "Tổ chức", icon: Building2 },
};

export function SmartHeader({
  isGoalMet = false,
  onQuickAction,
  scope = "personal",
  onScopeChange,
  selectedOfficerId,
  onOfficerChange,
  selectedUnitId,
  onUnitChange,
}: SmartHeaderProps) {
  const { user } = useAuth();

  // Determine if user can change scope
  const canChangeScope = user?.role === "manager" || user?.role === "admin";
  const isAdmin = user?.role === "admin";
  const isManager = user?.role === "manager";

  const availableScopes: DashboardScope[] =
    isAdmin
      ? ["personal", "organization"]
      : isManager
        ? ["unit"]
        : ["personal"];

  // Show officer selector when:
  // - Admin: always (can drill down to any officer)
  // - Manager: when scope is "unit" (can drill down to unit members)
  // Computed BEFORE the fetch hook so we can gate the API call. Officer
  // role never sees this selector → never needs the /api/admin/users
  // call → eliminates one spurious Casbin 403 in CI/prod logs.
  // (Audit 2026-05-26 task #51: officer role nightly smoke logged
  // ``GET /api/admin/users 403`` because hook fired unconditionally
  // regardless of `showOfficerSelector` gate.)
  const showOfficerSelector =
    (isAdmin && (scope === "personal" || scope === "unit" || scope === "organization")) ||
    (isManager && scope === "unit");

  // Fetch officers for officer selector based on scope:
  // - "unit" scope: ALWAYS filter by user's own unit (unit = user's unit)
  // - "organization" scope (admin): filter by selectedUnitId (any level in hierarchy)
  // - "personal" scope: no filter (admin can see all to drill down)
  const filterUnitId =
    scope === "unit"
      ? (user?.unit_id ?? undefined) // Unit = user's own unit
      : scope === "organization"
        ? (selectedUnitId ?? undefined) // Organization = selected unit or all
        : undefined; // Personal = no filter (admin can pick any officer)

  const { data: usersData } = useAdminUsersList(
    {
      role: "officer",
      unit_id: filterUnitId,
      include_children: true,
      page_size: 500,
    },
    { enabled: showOfficerSelector },
  );
  const officers: UserType[] = usersData?.users ?? [];

  const currentScopeInfo = SCOPE_LABELS[scope];
  const ScopeIcon = currentScopeInfo.icon;

  // Helper to get officer name
  const getOfficerName = (id: number | null | undefined) => {
    if (!id) return "Tất cả";
    const officer = officers.find((o) => o.id === id);
    return officer?.full_name || officer?.username || `ID: ${id}`;
  };

  // ``showOfficerSelector`` is computed earlier (above the
  // ``useAdminUsersList`` call) so it can gate the API request.

  // Show unit selector when:
  // - Admin and scope is "organization"
  const showUnitSelector = isAdmin && scope === "organization";

  return (
    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      {/* Left: Greeting + Date */}
      <div>
        <h1 suppressHydrationWarning className="text-2xl font-semibold font-display flex items-center gap-2">
          {getGreeting()}, {user?.full_name || user?.username || "Officer"}!
          {isGoalMet && <Sparkles className="h-5 w-5 text-amber-500" />}
        </h1>
        <p suppressHydrationWarning className="text-sm text-muted-foreground mt-0.5">
          {new Date().toLocaleDateString("vi-VN", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      {/* Right: Scope Filter + Secondary Filters + Date Range Filter + Quick Actions */}
      <div className="flex items-center gap-2 flex-wrap">
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
                onValueChange={(value) => {
                  onScopeChange?.(value as DashboardScope);
                  // Reset all selections when scope changes
                  onUnitChange?.(null);
                  onOfficerChange?.(null);
                }}
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

        {/* Unit Selector with hierarchical tree (Admin + Organization scope) */}
        {showUnitSelector && (
          <SmartUnitSelector
            value={selectedUnitId?.toString()}
            onChange={(value) => {
              onUnitChange?.(value ? parseInt(value) : null);
              // Reset officer when unit changes
              onOfficerChange?.(null);
            }}
            placeholder="Chọn đơn vị"
            allowNone={true}
            noneLabel="Tất cả đơn vị"
            variant="combobox"
            className="w-[220px] h-9"
          />
        )}

        {/* Officer Selector (Admin can see all, Manager sees team) */}
        {showOfficerSelector && (
          <Select
            value={selectedOfficerId?.toString() ?? "all"}
            onValueChange={(value) => onOfficerChange?.(value === "all" ? null : parseInt(value))}
          >
            <SelectTrigger className="w-[180px] h-9">
              <User className="h-4 w-4 mr-2 opacity-50" />
              <SelectValue placeholder="Chọn nhân viên">
                {getOfficerName(selectedOfficerId)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                {scope === "organization" ? "Tổng hợp" : scope === "unit" ? "Cả đơn vị" : "Tất cả"}
              </SelectItem>
              {officers.map((officer) => (
                <SelectItem key={officer.id} value={officer.id.toString()}>
                  {officer.full_name || officer.username}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Date Range Filter */}
        <DateRangeFilter />

        {/* Quick Action */}
        <Button size="sm" className="gap-1.5" onClick={() => onQuickAction?.("new_lead")}>
          <Plus className="h-4 w-4" />
          Thêm Lead
        </Button>
      </div>
    </div>
  );
}
