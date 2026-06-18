// src/components/leads/command-center/LeadQuickPresets.tsx
"use client";

/**
 * LeadQuickPresets — 1-click filter combos on the bar (LEAD_FILTER_UX_PLAN §5.3).
 *
 * Each preset just writes into the same filter state via the hook handlers, so
 * they deep-link / share like any other filter (not a separate mode). The
 * unassigned XOR officer conflict policy is enforced inside the handlers
 * (handleUnassignedChange / handleOfficerChange), so presets don't re-implement
 * it. A preset highlights when ITS predicate is active, even if other additive
 * filters are also on; "Tất cả" highlights only when nothing is active.
 *
 * Mobile: horizontal-scroll (no wrap).
 */

import React from "react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { canFilterByOfficer as checkCanFilterByOfficer } from "@/lib/utils/permissions";
import type { LeadStatus } from "@/types/lead.types";
import type { LeadsFilterState, LeadsFilterHandlers } from "@/hooks/useLeadsFilter";

interface LeadQuickPresetsProps {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  hasActiveFilters: boolean;
}

export const LeadQuickPresets = React.memo(function LeadQuickPresets({
  state,
  handlers,
  hasActiveFilters,
}: LeadQuickPresetsProps) {
  const { user } = useAuth();
  const [isMounted, setIsMounted] = React.useState(false);
  React.useEffect(() => setIsMounted(true), []);

  const canFilterByOfficerFlag = isMounted && checkCanFilterByOfficer(user);
  const myId = user?.id != null ? String(user.id) : null;

  const presets: { key: string; label: string; active: boolean; onClick: () => void; show: boolean }[] = [
    {
      key: "all",
      label: "Tất cả",
      active: !hasActiveFilters,
      onClick: () => handlers.resetFilters(),
      show: true,
    },
    {
      key: "mine",
      // Active only when EXACTLY "me" is selected (not merely included among
      // several officers) so it doesn't claim to own a multi-officer selection.
      label: "Của tôi",
      active: !!myId && state.officerFilters.length === 1 && state.officerFilters[0] === myId,
      onClick: () => {
        if (!myId) return;
        // Toggle: clear when exactly-mine, else set to [me] (which also clears
        // unassigned via the handler's conflict policy). Avoids silently
        // dropping a manager's other selected officers on a second click.
        const exactlyMine = state.officerFilters.length === 1 && state.officerFilters[0] === myId;
        handlers.handleOfficerChange(exactlyMine ? [] : [myId]);
      },
      show: true,
    },
    {
      key: "overdue",
      label: "Quá hạn",
      active: state.overdue,
      onClick: () => handlers.handleOverdueChange(!state.overdue),
      show: true,
    },
    {
      key: "hot",
      label: "Hot",
      active: state.isHot,
      onClick: () => handlers.handleIsHotChange(!state.isHot),
      show: true,
    },
    {
      key: "unassigned",
      label: "Chưa gán",
      active: state.unassigned,
      onClick: () => handlers.handleUnassignedChange(!state.unassigned), // clears officer
      show: canFilterByOfficerFlag,
    },
    {
      key: "new",
      label: "Mới",
      active: state.statusFilters.includes("new" as LeadStatus),
      onClick: () => {
        const has = state.statusFilters.includes("new" as LeadStatus);
        handlers.handleStatusChange(
          (has
            ? state.statusFilters.filter((s) => s !== "new")
            : [...state.statusFilters, "new" as LeadStatus]) as LeadStatus[],
        );
      },
      show: true,
    },
  ];

  return (
    <div className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {presets
        .filter((p) => p.show)
        .map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={p.onClick}
            aria-pressed={p.active}
            className={cn(
              "h-11 shrink-0 touch-manipulation rounded-full border px-3 text-sm font-medium transition-colors md:h-8",
              p.active
                ? "border-primary bg-primary text-primary-foreground"
                : "bg-background hover:bg-accent text-foreground",
            )}
          >
            {p.label}
          </button>
        ))}
    </div>
  );
});

export default LeadQuickPresets;
