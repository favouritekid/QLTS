// src/components/leads/command-center/LeadFilterBar.tsx
/**
 * LeadFilterBar — slim navigation bar (LEAD_FILTER_UX_PLAN §5.0-A).
 *
 * Only search + quick presets + a "Bộ lọc (N)" button (opens the drawer) +
 * active filter chips + Add Lead live here. The full filter surface moved into
 * LeadFilterPanel rendered inside a <Sheet> owned by LeadsClient. The 9 inline
 * dropdowns and the mobile collapse panel were removed.
 */

"use client";

import React, { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Search, X, RotateCcw, Plus, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { LEAD_STATUS_OPTIONS, LEAD_SOURCE_OPTIONS } from "@/constants";
import { LEAD_VALIDITY_OPTIONS } from "@/constants/lead.constants";
import { usePipelineStages, useConsultationStatuses } from "@/hooks/usePipeline";
import { useAllProgramOfferings, useOrganizationUnits } from "@/hooks/useOrganization";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import type { LeadStatus } from "@/types/lead.types";
import type { LeadsFilterState, LeadsFilterHandlers } from "@/hooks/useLeadsFilter";
import { LeadQuickPresets } from "./LeadQuickPresets";

interface LeadFilterBarProps {
  state: LeadsFilterState;
  handlers: LeadsFilterHandlers;
  hasActiveFilters: boolean;
  /** Number of filters active inside the drawer (excludes search + sort). */
  drawerFilterCount: number;
  onOpenFilters: () => void;
  onAddLead: () => void;
  totalCount: number;
}

function FilterPill({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <Badge
      variant="secondary"
      className="motion-safe:animate-in motion-safe:fade-in-0 h-6 gap-1 pr-1 text-xs"
    >
      {label}
      <button
        onClick={onRemove}
        className="hover:bg-muted ml-0.5 rounded-full p-1 transition-colors"
        aria-label={`Xóa bộ lọc ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </Badge>
  );
}

const MAX_VISIBLE_PILLS = 6;

export function LeadFilterBar({
  state,
  handlers,
  hasActiveFilters,
  drawerFilterCount,
  onOpenFilters,
  onAddLead,
  totalCount,
}: LeadFilterBarProps) {
  // Label sources (chips need names for dynamic ids). React Query shares the
  // cache with LeadFilterPanel, so this is not a double-fetch.
  const { data: pipelineStages = [] } = usePipelineStages();
  const { data: consultationStatuses = [] } = useConsultationStatuses();
  const { data: offeringsList = [] } = useAllProgramOfferings();
  const { data: organizationUnits = [] } = useOrganizationUnits();
  const { data: usersData } = useAdminUsersList({ page: 1, page_size: 100, status: "active", role: "officer" });
  const officers = usersData?.users || [];

  const flatUnits = useMemo(() => {
    const result: { id: number; name: string }[] = [];
    function walk(units: typeof organizationUnits) {
      for (const unit of units) {
        result.push({ id: unit.id, name: unit.name });
        if (unit.children?.length) walk(unit.children);
      }
    }
    walk(organizationUnits);
    return result;
  }, [organizationUnits]);

  // Debounced search (local input → debounced handler)
  const [localSearch, setLocalSearch] = useState(state.search);
  const [syncedSearch, setSyncedSearch] = useState(state.search);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  // Sync external search → local input WITHOUT an effect (React's official
  // "adjust state during render" pattern) — avoids the set-state-in-effect
  // cascading-render lint error. Fires only when state.search actually changes
  // (e.g. reset / preset / deep-link), not on every keystroke.
  if (syncedSearch !== state.search) {
    setSyncedSearch(state.search);
    setLocalSearch(state.search);
  }
  const handleSearchInputChange = useCallback(
    (value: string) => {
      setLocalSearch(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => handlers.handleSearchChange(value), 300);
    },
    [handlers],
  );
  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const [isFiltersExpanded, setIsFiltersExpanded] = useState(false);

  // Label helpers
  const statusLabel = (v: LeadStatus) => LEAD_STATUS_OPTIONS.find((o) => o.value === v)?.label || v;
  const sourceLabel = (v: string) => LEAD_SOURCE_OPTIONS.find((o) => o.value === v)?.label || v;
  const validityLabel = (v: string) => LEAD_VALIDITY_OPTIONS.find((o) => o.value === v)?.label || v;
  const stageLabel = (id: string) => pipelineStages.find((s) => s.id === id)?.name || id;
  const cstatusLabel = (id: string) => consultationStatuses.find((s) => s.id === id)?.name || id;
  const officerLabel = (id: string) => officers.find((o) => o.id.toString() === id)?.full_name || `#${id}`;
  const unitLabel = (id: string) => flatUnits.find((u) => u.id.toString() === id)?.name || id;
  const offeringLabel = (id: string) => {
    const o = offeringsList.find((x) => x.id.toString() === id);
    if (!o) return id;
    return `${o.program?.name || ""} - ${o.offering_type || ""}`;
  };

  const removeFromArray = (arr: string[], value: string, onChange: (next: string[]) => void) =>
    onChange(arr.filter((v) => v !== value));

  const hasScoreFilter = state.scoreRange[0] > 0 || state.scoreRange[1] < 100;

  // Build chips (search included here on the bar, even though it's not part of
  // drawerFilterCount).
  const pills: { key: string; label: string; onRemove: () => void }[] = [];
  if (state.search) pills.push({ key: "q", label: `"${state.search}"`, onRemove: () => handlers.handleSearchChange("") });
  if (state.overdue) pills.push({ key: "overdue", label: "Quá hạn", onRemove: () => handlers.handleOverdueChange(false) });
  if (state.unassigned) pills.push({ key: "unassigned", label: "Chưa gán", onRemove: () => handlers.handleUnassignedChange(false) });
  if (state.isHot) pills.push({ key: "hot", label: "Hot", onRemove: () => handlers.handleIsHotChange(false) });
  if (state.noConsultation) pills.push({ key: "nocontact", label: "Chưa có lần tư vấn", onRemove: () => handlers.handleNoConsultationChange(false) });
  if (state.nextActivityFrom || state.nextActivityTo) {
    const f = state.nextActivityFrom, t = state.nextActivityTo;
    pills.push({
      key: "na",
      label: `Follow-up: ${f && t ? `${f} → ${t}` : f ? `từ ${f}` : `đến ${t}`}`,
      onRemove: () => { handlers.handleNextActivityFromChange(""); handlers.handleNextActivityToChange(""); },
    });
  }
  state.consultationStatusFilters.forEach((id) =>
    pills.push({ key: `cs-${id}`, label: cstatusLabel(id), onRemove: () => removeFromArray(state.consultationStatusFilters, id, handlers.handleConsultationStatusChange) }),
  );
  state.stageFilters.forEach((id) =>
    pills.push({ key: `stage-${id}`, label: stageLabel(id), onRemove: () => removeFromArray(state.stageFilters, id, handlers.handleStageChange) }),
  );
  state.statusFilters.forEach((v) =>
    pills.push({ key: `status-${v}`, label: `Vòng đời: ${statusLabel(v)}`, onRemove: () => handlers.handleStatusChange(state.statusFilters.filter((s) => s !== v)) }),
  );
  state.validityFilters.forEach((v) =>
    pills.push({ key: `validity-${v}`, label: validityLabel(v), onRemove: () => removeFromArray(state.validityFilters, v, handlers.handleValidityChange) }),
  );
  state.sourceFilters.forEach((v) =>
    pills.push({ key: `source-${v}`, label: sourceLabel(v), onRemove: () => removeFromArray(state.sourceFilters, v, handlers.handleSourceChange) }),
  );
  state.offeringFilters.forEach((id) =>
    pills.push({ key: `offering-${id}`, label: offeringLabel(id), onRemove: () => removeFromArray(state.offeringFilters, id, handlers.handleOfferingChange) }),
  );
  state.officerFilters.forEach((id) =>
    pills.push({ key: `officer-${id}`, label: officerLabel(id), onRemove: () => removeFromArray(state.officerFilters, id, handlers.handleOfficerChange) }),
  );
  if (state.unitId) pills.push({ key: "unit", label: `Đơn vị: ${unitLabel(state.unitId)}`, onRemove: () => handlers.handleUnitIdChange("") });
  if (hasScoreFilter) pills.push({ key: "score", label: `Điểm: ${state.scoreRange[0]}-${state.scoreRange[1]}`, onRemove: () => handlers.handleScoreRangeChange([0, 100]) });
  if (state.dateFrom || state.dateTo) {
    const f = state.dateFrom, t = state.dateTo;
    pills.push({
      key: "date",
      label: `${state.dateField === "created_at" ? "Tạo" : "TV"}: ${f && t ? `${f} → ${t}` : f ? `từ ${f}` : `đến ${t}`}`,
      onRemove: () => { handlers.handleDateFromChange(""); handlers.handleDateToChange(""); },
    });
  }

  const visiblePills = isFiltersExpanded ? pills : pills.slice(0, MAX_VISIBLE_PILLS);
  const hiddenCount = pills.length - MAX_VISIBLE_PILLS;

  return (
    <div className="bg-background/95 supports-[backdrop-filter]:bg-background/60 border-b backdrop-blur">
      {/* Row 1: search + quick presets + open-filters + add — all on one line
          to save vertical space. Search shrinks; presets take the remaining
          width and horizontal-scroll when tight. */}
      <div className="flex items-center gap-2 px-3 py-2 md:gap-3 md:px-4">
        <div className="relative w-40 shrink-0 sm:w-56 md:w-72">
          <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
          <Input
            placeholder="Tìm kiếm tên / SĐT / email…"
            value={localSearch}
            onChange={(e) => handleSearchInputChange(e.target.value)}
            className="h-11 pl-9 pr-8 text-base sm:text-sm md:h-9"
          />
          {localSearch && (
            <button
              onClick={() => { setLocalSearch(""); if (debounceRef.current) clearTimeout(debounceRef.current); handlers.handleSearchChange(""); }}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
              aria-label="Xóa tìm kiếm"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Quick presets — fill the middle, horizontal-scroll when space is tight */}
        <div className="min-w-0 flex-1">
          <LeadQuickPresets state={state} handlers={handlers} hasActiveFilters={hasActiveFilters} />
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={onOpenFilters}
          aria-label="Bộ lọc"
          className="h-11 shrink-0 gap-1.5 md:h-9 touch-manipulation"
        >
          <SlidersHorizontal className="h-4 w-4" />
          <span className="hidden sm:inline">Bộ lọc</span>
          {drawerFilterCount > 0 && (
            <Badge variant="secondary" className="bg-primary text-primary-foreground ml-0.5 h-5 min-w-[20px] px-1.5 text-xs">
              {drawerFilterCount}
            </Badge>
          )}
        </Button>

        <Button size="sm" onClick={onAddLead} aria-label="Thêm Lead" className="h-11 shrink-0 gap-1.5 md:h-9 touch-manipulation">
          <Plus className="h-4 w-4" />
          <span className="hidden sm:inline">Thêm Lead</span>
        </Button>
      </div>

      {/* Row 3: active chips */}
      {pills.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2 md:px-4">
          <span className="text-muted-foreground text-xs">Đang lọc:</span>
          {visiblePills.map((pill) => (
            <FilterPill key={pill.key} label={pill.label} onRemove={pill.onRemove} />
          ))}
          {!isFiltersExpanded && hiddenCount > 0 && (
            <Badge
              variant="outline"
              className="h-6 cursor-pointer gap-1 px-2 text-xs hover:bg-primary/10"
              onClick={() => setIsFiltersExpanded(true)}
            >
              +{hiddenCount}
            </Badge>
          )}
          {isFiltersExpanded && pills.length > MAX_VISIBLE_PILLS && (
            <Badge
              variant="outline"
              className="h-6 cursor-pointer gap-1 px-2 text-xs hover:bg-primary/10"
              onClick={() => setIsFiltersExpanded(false)}
            >
              Thu gọn
            </Badge>
          )}
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={handlers.resetFilters} className="h-7 text-xs">
              <RotateCcw className="mr-1 h-3.5 w-3.5" />
              Đặt lại
            </Button>
          )}
          <span className="text-muted-foreground ml-auto text-xs">
            {totalCount.toLocaleString("vi-VN")} kết quả
          </span>
        </div>
      )}
    </div>
  );
}

export default LeadFilterBar;
