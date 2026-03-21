// src/components/leads/command-center/LeadFilterBar.tsx
/**
 * LeadFilterBar - Horizontal filter bar for leads page
 * 
 * Features:
 * - Search input with debounce
 * - Filter dropdowns with multi-select
 * - Active filter pills with remove
 * - Smooth animations
 */

"use client";

import React, { useState, useCallback, useTransition, useEffect, useRef } from "react";
import {
  Search,
  X,
  RotateCcw,
  Plus,
  ChevronDown,
  Calendar,
  Building2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import type { LeadStatus } from "@/types/lead.types";
import { LEAD_STATUS_OPTIONS, LEAD_SOURCE_OPTIONS } from "@/constants";
import { LEAD_VALIDITY_OPTIONS } from "@/constants/lead.constants";
import { usePipelineStages } from "@/hooks/usePipeline";
import { useAllProgramOfferings } from "@/hooks/useOrganization";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { useAuth } from "@/hooks/useAuth";
import { isAdmin as checkIsAdmin, canFilterByOfficer as checkCanFilterByOfficer } from "@/lib/utils/permissions";
import { MultiOfferingSelector } from "@/components/common/selectors";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// =============================================================================
// TYPES
// =============================================================================

interface LeadFilterBarProps {
  // Search
  search: string;
  onSearchChange: (value: string) => void;
  // Status filter
  statusFilters: LeadStatus[];
  onStatusChange: (statuses: LeadStatus[]) => void;
  // Multi-select filters
  sourceFilters: string[];
  onSourceChange: (sources: string[]) => void;
  validityFilters: string[];
  onValidityChange: (validity: string[]) => void;
  offeringFilters: string[];
  onOfferingChange: (offerings: string[]) => void;
  stageFilters: string[];
  onStageChange: (stages: string[]) => void;
  officerFilters: string[];
  onOfficerChange: (officers: string[]) => void;
  // Unit filter (admin only)
  unitId: string;
  onUnitIdChange: (unitId: string) => void;
  // Score range
  scoreRange: [number, number];
  onScoreRangeChange: (range: [number, number]) => void;
  // Date range
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "last_consultation_at";
  onDateFromChange: (date: string) => void;
  onDateToChange: (date: string) => void;
  onDateFieldChange: (field: "created_at" | "last_consultation_at") => void;
  // Actions
  onReset: () => void;
  onAddLead: () => void;
  // Total count
  totalCount: number;
}

// =============================================================================
// FILTER DROPDOWN COMPONENT
// =============================================================================

interface FilterDropdownProps {
  label: string;
  count: number;
  children: React.ReactNode;
}

function FilterDropdown({ label, count, children }: FilterDropdownProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "h-9 md:h-8 gap-1 transition-colors duration-200",
            count > 0 && "border-primary bg-primary/5"
          )}
        >
          {label}
          {count > 0 && (
            <Badge
              variant="secondary"
              className="bg-primary text-primary-foreground ml-1 h-5 min-w-[20px] px-1.5 text-xs"
            >
              {count}
            </Badge>
          )}
          <ChevronDown className="h-3.5 w-3.5 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-3" align="start">
        {children}
      </PopoverContent>
    </Popover>
  );
}

// =============================================================================
// FILTER PILL COMPONENT
// =============================================================================

interface FilterPillProps {
  label: string;
  onRemove: () => void;
}

function FilterPill({ label, onRemove }: FilterPillProps) {
  return (
    <Badge
      variant="secondary"
      className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 h-6 gap-1 pr-1 text-xs transition-colors duration-200"
    >
      {label}
      <button
        onClick={onRemove}
        className="hover:bg-muted ml-0.5 rounded-full p-0.5 transition-colors"
        aria-label={`Xóa bộ lọc ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </Badge>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function LeadFilterBar({
  search,
  onSearchChange,
  statusFilters,
  onStatusChange,
  sourceFilters,
  onSourceChange,
  validityFilters,
  onValidityChange,
  offeringFilters,
  onOfferingChange,
  stageFilters,
  onStageChange,
  officerFilters,
  onOfficerChange,
  unitId,
  onUnitIdChange,
  scoreRange,
  onScoreRangeChange,
  dateFrom,
  dateTo,
  dateField,
  onDateFromChange,
  onDateToChange,
  onDateFieldChange,
  onReset,
  onAddLead,
  totalCount,
}: LeadFilterBarProps) {
  const [isPending, startTransition] = useTransition();
  const { user } = useAuth();
  const { data: pipelineStages = [] } = usePipelineStages();
  const { data: offeringsList = [] } = useAllProgramOfferings();
  const { data: organizationUnits = [] } = useOrganizationUnits();
  const [officerSearch, setOfficerSearch] = useState("");
  const [debouncedOfficerSearch, setDebouncedOfficerSearch] = useState("");
  const officerSearchDebounceRef = useRef<NodeJS.Timeout | null>(null);

  const handleOfficerSearchChange = useCallback((value: string) => {
    setOfficerSearch(value);
    if (officerSearchDebounceRef.current) clearTimeout(officerSearchDebounceRef.current);
    officerSearchDebounceRef.current = setTimeout(() => {
      setDebouncedOfficerSearch(value);
    }, 300);
  }, []);

  const { data: usersData } = useAdminUsersList({
    page: 1,
    page_size: 50,
    status: "active",
    role: "officer",
    ...(debouncedOfficerSearch && { search: debouncedOfficerSearch }),
  });
  const officers = usersData?.users || [];
  const officersTotalCount = usersData?.total_count ?? 0;
  const officersTruncated = officersTotalCount > officers.length;

  const [isMounted, setIsMounted] = React.useState(false);
  React.useEffect(() => { setIsMounted(true); }, []);

  // ✅ FIX Critical: Debounced search to prevent excessive API calls
  const [localSearch, setLocalSearch] = useState(search);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const DEBOUNCE_DELAY = 300; // 300ms debounce

  // Sync local search with external search prop (e.g., when reset is clicked)
  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  // Debounce the search callback
  const handleSearchInputChange = useCallback((value: string) => {
    setLocalSearch(value);

    // Clear previous timeout
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    // Set new timeout
    debounceRef.current = setTimeout(() => {
      onSearchChange(value);
    }, DEBOUNCE_DELAY);
  }, [onSearchChange]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      if (officerSearchDebounceRef.current) {
        clearTimeout(officerSearchDebounceRef.current);
      }
    };
  }, []);

  // ✅ SECURITY: Use centralized permission utility (UX only - backend enforces)
  const isAdminFlag = isMounted && checkIsAdmin(user);
  const canFilterByOfficerFlag = isMounted && checkCanFilterByOfficer(user);

  // Collapsible filter pills state
  const [isFiltersExpanded, setIsFiltersExpanded] = React.useState(false);
  const MAX_VISIBLE_PILLS = 5;

  // Toggle handlers
  const handleStatusToggle = useCallback((status: LeadStatus) => {
    startTransition(() => {
      if (statusFilters.includes(status)) {
        onStatusChange(statusFilters.filter((s) => s !== status));
      } else {
        onStatusChange([...statusFilters, status]);
      }
    });
  }, [statusFilters, onStatusChange]);

  const handleSourceToggle = useCallback((source: string) => {
    startTransition(() => {
      if (sourceFilters.includes(source)) {
        onSourceChange(sourceFilters.filter((s) => s !== source));
      } else {
        onSourceChange([...sourceFilters, source]);
      }
    });
  }, [sourceFilters, onSourceChange]);

  const handleValidityToggle = useCallback((validity: string) => {
    startTransition(() => {
      if (validityFilters.includes(validity)) {
        onValidityChange(validityFilters.filter((v) => v !== validity));
      } else {
        onValidityChange([...validityFilters, validity]);
      }
    });
  }, [validityFilters, onValidityChange]);

  const handleStageToggle = useCallback((stageId: string) => {
    startTransition(() => {
      if (stageFilters.includes(stageId)) {
        onStageChange(stageFilters.filter((s) => s !== stageId));
      } else {
        onStageChange([...stageFilters, stageId]);
      }
    });
  }, [stageFilters, onStageChange]);

  const handleOfficerToggle = useCallback((officerId: string) => {
    startTransition(() => {
      if (officerFilters.includes(officerId)) {
        onOfficerChange(officerFilters.filter((o) => o !== officerId));
      } else {
        onOfficerChange([...officerFilters, officerId]);
      }
    });
  }, [officerFilters, onOfficerChange]);

  const handleOfferingToggle = useCallback((offeringId: string) => {
    startTransition(() => {
      if (offeringFilters.includes(offeringId)) {
        onOfferingChange(offeringFilters.filter((o) => o !== offeringId));
      } else {
        onOfferingChange([...offeringFilters, offeringId]);
      }
    });
  }, [offeringFilters, onOfferingChange]);

  // Check if any filters are active
  const hasScoreFilter = scoreRange[0] > 0 || scoreRange[1] < 100;
  const hasActiveFilters =
    search ||
    statusFilters.length > 0 ||
    sourceFilters.length > 0 ||
    validityFilters.length > 0 ||
    offeringFilters.length > 0 ||
    stageFilters.length > 0 ||
    officerFilters.length > 0 ||
    !!unitId ||
    hasScoreFilter ||
    dateFrom ||
    dateTo;

  // Get display labels
  const getStatusLabel = (value: LeadStatus) =>
    LEAD_STATUS_OPTIONS.find((o) => o.value === value)?.label || value;
  const getSourceLabel = (value: string) =>
    LEAD_SOURCE_OPTIONS.find((o) => o.value === value)?.label || value;
  const getValidityLabel = (value: string) =>
    LEAD_VALIDITY_OPTIONS.find((o) => o.value === value)?.label || value;
  const getStageLabel = (id: string) =>
    pipelineStages.find((s) => s.id === id)?.name || id;
  const getOfficerLabel = (id: string) =>
    officers.find((o) => o.id.toString() === id)?.full_name || id;
  const getUnitLabel = (id: string) =>
    organizationUnits.find((u) => u.id.toString() === id)?.name || id;
  const getOfferingLabel = (id: string) => {
    const offering = offeringsList.find((o) => o.id.toString() === id);
    if (!offering) return id;
    const programName = offering.program?.name || "";
    const type = offering.offering_type || "";
    return `${programName} - ${type}`;
  };

  // Mobile filter sheet state
  const [mobileFiltersOpen, setMobileFiltersOpen] = React.useState(false);

  // Count active filters for badge
  const activeFilterCount =
    statusFilters.length +
    sourceFilters.length +
    validityFilters.length +
    stageFilters.length +
    offeringFilters.length +
    officerFilters.length +
    (unitId ? 1 : 0) +
    (hasScoreFilter ? 1 : 0) +
    (dateFrom || dateTo ? 1 : 0) +
    (search ? 1 : 0);

  return (
    <div className="bg-background/95 supports-[backdrop-filter]:bg-background/60 border-b backdrop-blur">
      {/* Main Filter Row */}
      <div className="flex items-center gap-2 px-3 py-2 md:gap-3 md:px-4 md:py-3">
        {/* Search - Responsive width with debounce */}
        <div className="relative min-w-0 flex-1 md:w-64 md:flex-none">
          <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
          <Input
            placeholder="Tìm kiếm..."
            value={localSearch}
            onChange={(e) => handleSearchInputChange(e.target.value)}
            className="h-9 pl-9 pr-8 text-sm md:h-8"
          />
          {localSearch && (
            <button
              onClick={() => {
                setLocalSearch("");
                if (debounceRef.current) clearTimeout(debounceRef.current);
                onSearchChange("");
              }}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
              aria-label="Xóa tìm kiếm"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Mobile: Filter toggle button */}
        <Button
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 md:hidden"
          onClick={() => setMobileFiltersOpen(!mobileFiltersOpen)}
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", mobileFiltersOpen && "rotate-180")} />
          Lọc
          {activeFilterCount > 0 && (
            <Badge variant="secondary" className="bg-primary text-primary-foreground ml-1 h-5 min-w-[20px] px-1.5 text-xs">
              {activeFilterCount}
            </Badge>
          )}
        </Button>

        {/* Mobile: Add Lead button */}
        <Button size="sm" onClick={onAddLead} className="h-9 gap-1.5 md:hidden">
          <Plus className="h-4 w-4" />
          <span className="sr-only sm:not-sr-only">Thêm</span>
        </Button>

        {/* Desktop: Divider */}
        <div className="bg-border hidden h-6 w-px md:block" />

        {/* Desktop: Filter Dropdowns */}
        <div className="hidden items-center gap-2 md:flex">
          {/* Status Filter - Admin only */}
          {isAdminFlag && (
            <FilterDropdown label="Trạng thái" count={statusFilters.length}>
              <div className="space-y-2">
                {LEAD_STATUS_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`bar-status-${option.value}`}
                      checked={statusFilters.includes(option.value)}
                      onCheckedChange={() => handleStatusToggle(option.value)}
                    />
                    <Label
                      htmlFor={`bar-status-${option.value}`}
                      className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                    >
                      <span className={`h-2 w-2 rounded-full ${option.color}`} />
                      {option.label}
                    </Label>
                  </div>
                ))}
              </div>
            </FilterDropdown>
          )}

          {/* Unit Filter - Admin only */}
          {isAdminFlag && (
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-8 gap-1",
                    unitId && "border-primary bg-primary/5"
                  )}
                >
                  <Building2 className="h-3.5 w-3.5" />
                  {unitId ? getUnitLabel(unitId) : "Đơn vị"}
                  {unitId && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onUnitIdChange(""); }}
                      className="hover:bg-muted ml-0.5 rounded-full p-0.5"
                      aria-label="Xóa lọc đơn vị"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                  <ChevronDown className="h-3.5 w-3.5 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-56 p-3" align="start">
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {organizationUnits.map((unit) => (
                    <div
                      key={unit.id}
                      className={cn(
                        "cursor-pointer rounded px-2 py-1.5 text-sm transition-colors hover:bg-accent",
                        unitId === unit.id.toString() && "bg-accent font-medium"
                      )}
                      onClick={() => onUnitIdChange(
                        unitId === unit.id.toString() ? "" : unit.id.toString()
                      )}
                    >
                      {unit.name}
                    </div>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          )}

          {/* Source Filter */}
          <FilterDropdown label="Nguồn" count={sourceFilters.length}>
            <div className="space-y-2">
              {LEAD_SOURCE_OPTIONS.map((option) => (
                <div key={option.value} className="flex items-center space-x-2">
                  <Checkbox
                    id={`bar-source-${option.value}`}
                    checked={sourceFilters.includes(option.value)}
                    onCheckedChange={() => handleSourceToggle(option.value)}
                  />
                  <Label
                    htmlFor={`bar-source-${option.value}`}
                    className="cursor-pointer text-sm font-normal"
                  >
                    {option.label}
                  </Label>
                </div>
              ))}
            </div>
          </FilterDropdown>

          {/* Validity Filter */}
          <FilterDropdown label="Hợp lệ" count={validityFilters.length}>
            <div className="space-y-2">
              {LEAD_VALIDITY_OPTIONS.map((option) => (
                <div key={option.value} className="flex items-center space-x-2">
                  <Checkbox
                    id={`bar-validity-${option.value}`}
                    checked={validityFilters.includes(option.value)}
                    onCheckedChange={() => handleValidityToggle(option.value)}
                  />
                  <Label
                    htmlFor={`bar-validity-${option.value}`}
                    className="cursor-pointer text-sm font-normal flex items-center gap-1.5"
                  >
                    <span className={`inline-block h-2 w-2 rounded-full ${option.color}`} />
                    {option.label}
                  </Label>
                </div>
              ))}
            </div>
          </FilterDropdown>

          {/* Stage Filter */}
          <FilterDropdown label="Giai đoạn" count={stageFilters.length}>
            <div className="space-y-2">
              {pipelineStages.map((stage) => (
                <div key={stage.id} className="flex items-center space-x-2">
                  <Checkbox
                    id={`bar-stage-${stage.id}`}
                    checked={stageFilters.includes(stage.id)}
                    onCheckedChange={() => handleStageToggle(stage.id)}
                  />
                  <Label
                    htmlFor={`bar-stage-${stage.id}`}
                    className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                  >
                    <ColorDot color={sanitizeColorCode(stage.color_code) || STAGE_COLORS[stage.id]} size="sm" />
                    {stage.name}
                  </Label>
                </div>
              ))}
            </div>
          </FilterDropdown>

          {/* Offering Filter */}
          <FilterDropdown label="Chương trình" count={offeringFilters.length}>
            <MultiOfferingSelector
              values={offeringFilters}
              onChange={onOfferingChange}
            />
          </FilterDropdown>

          {/* Officer Filter - Admin/Manager only */}
          {canFilterByOfficerFlag && (
            <FilterDropdown label="Cán bộ" count={officerFilters.length}>
              <div className="space-y-2">
                <Input
                  placeholder="Tìm cán bộ…"
                  value={officerSearch}
                  onChange={(e) => handleOfficerSearchChange(e.target.value)}
                  className="h-7 text-xs"
                />
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {officers.map((officer) => (
                    <div key={officer.id} className="flex items-center space-x-2">
                      <Checkbox
                        id={`bar-officer-${officer.id}`}
                        checked={officerFilters.includes(officer.id.toString())}
                        onCheckedChange={() => handleOfficerToggle(officer.id.toString())}
                      />
                      <Label
                        htmlFor={`bar-officer-${officer.id}`}
                        className="cursor-pointer text-sm font-normal"
                      >
                        {officer.full_name}
                      </Label>
                    </div>
                  ))}
                </div>
                {officersTruncated && (
                  <p className="text-xs text-muted-foreground pt-1">
                    Hiển thị {officers.length}/{officersTotalCount} — nhập tên để tìm thêm
                  </p>
                )}
              </div>
            </FilterDropdown>
          )}

          {/* Score Filter */}
          <FilterDropdown
            label="Điểm"
            count={hasScoreFilter ? 1 : 0}
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between text-sm">
                <span>Điểm lead</span>
                <span className="text-muted-foreground">
                  {scoreRange[0]} - {scoreRange[1]}
                </span>
              </div>
              <Slider
                value={scoreRange}
                onValueChange={(value) => onScoreRangeChange(value as [number, number])}
                min={0}
                max={100}
                step={5}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>0</span>
                <span>50</span>
                <span>100</span>
              </div>
            </div>
          </FilterDropdown>

          {/* Date Range */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={cn(
                  "h-8 gap-1",
                  (dateFrom || dateTo) && "border-primary bg-primary/5"
                )}
              >
                <Calendar className="h-3.5 w-3.5" />
                {dateField === "created_at" ? "Ngày tạo" : "Ngày TĐ"}
                {(dateFrom || dateTo) && (
                  <Badge variant="secondary" className="bg-primary text-primary-foreground ml-1 h-5 px-1.5 text-xs">
                    1
                  </Badge>
                )}
                <ChevronDown className="h-3.5 w-3.5 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-72 p-3" align="start">
              <div className="space-y-3">
                {/* Date Field Selector */}
                <div>
                  <Label className="text-xs">Lọc theo</Label>
                  <Select value={dateField} onValueChange={(v) => onDateFieldChange(v as "created_at" | "last_consultation_at")}>
                    <SelectTrigger className="mt-1 h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="created_at">Ngày tạo</SelectItem>
                      <SelectItem value="last_consultation_at">Ngày tư vấn cuối</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Từ ngày</Label>
                  <Input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => onDateFromChange(e.target.value)}
                    className="mt-1 h-8"
                  />
                </div>
                <div>
                  <Label className="text-xs">Đến ngày</Label>
                  <Input
                    type="date"
                    value={dateTo}
                    onChange={(e) => onDateToChange(e.target.value)}
                    className="mt-1 h-8"
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>

        {/* Desktop: Spacer */}
        <div className="hidden flex-1 md:block" />

        {/* Desktop: Actions */}
        <div className="hidden items-center gap-2 md:flex">
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onReset}
              className="h-8 text-xs"
            >
              <RotateCcw className="mr-1 h-3.5 w-3.5" />
              Đặt lại
            </Button>
          )}
          <Button size="sm" onClick={onAddLead} className="h-8">
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Thêm Lead
          </Button>
        </div>
      </div>

      {/* Mobile: Collapsible Filters */}
      {mobileFiltersOpen && (
        <div className="motion-safe:animate-in motion-safe:slide-in-from-top-2 border-t px-3 py-3 md:hidden">
          <div className="flex flex-wrap gap-2">
            {/* Status Filter - Admin only */}
            {isAdminFlag && (
              <FilterDropdown label="Trạng thái" count={statusFilters.length}>
                <div className="space-y-2">
                  {LEAD_STATUS_OPTIONS.map((option) => (
                    <div key={option.value} className="flex items-center space-x-2">
                      <Checkbox
                        id={`mobile-status-${option.value}`}
                        checked={statusFilters.includes(option.value)}
                        onCheckedChange={() => handleStatusToggle(option.value)}
                      />
                      <Label
                        htmlFor={`mobile-status-${option.value}`}
                        className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                      >
                        <span className={`h-2 w-2 rounded-full ${option.color}`} />
                        {option.label}
                      </Label>
                    </div>
                  ))}
                </div>
              </FilterDropdown>
            )}

            {/* Unit Filter - Admin only (mobile) */}
            {isAdminFlag && (
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(
                      "h-9 gap-1",
                      unitId && "border-primary bg-primary/5"
                    )}
                  >
                    <Building2 className="h-3.5 w-3.5" />
                    {unitId ? getUnitLabel(unitId) : "Đơn vị"}
                    <ChevronDown className="h-3.5 w-3.5 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-56 p-3" align="start">
                  <div className="max-h-48 space-y-2 overflow-y-auto">
                    {organizationUnits.map((unit) => (
                      <div
                        key={unit.id}
                        className={cn(
                          "cursor-pointer rounded px-2 py-1.5 text-sm transition-colors hover:bg-accent",
                          unitId === unit.id.toString() && "bg-accent font-medium"
                        )}
                        onClick={() => onUnitIdChange(
                          unitId === unit.id.toString() ? "" : unit.id.toString()
                        )}
                      >
                        {unit.name}
                      </div>
                    ))}
                  </div>
                </PopoverContent>
              </Popover>
            )}

            {/* Source Filter */}
            <FilterDropdown label="Nguồn" count={sourceFilters.length}>
              <div className="space-y-2">
                {LEAD_SOURCE_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`mobile-source-${option.value}`}
                      checked={sourceFilters.includes(option.value)}
                      onCheckedChange={() => handleSourceToggle(option.value)}
                    />
                    <Label
                      htmlFor={`mobile-source-${option.value}`}
                      className="cursor-pointer text-sm font-normal"
                    >
                      {option.label}
                    </Label>
                  </div>
                ))}
              </div>
            </FilterDropdown>

            {/* Validity Filter */}
            <FilterDropdown label="Hợp lệ" count={validityFilters.length}>
              <div className="space-y-2">
                {LEAD_VALIDITY_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`mobile-validity-${option.value}`}
                      checked={validityFilters.includes(option.value)}
                      onCheckedChange={() => handleValidityToggle(option.value)}
                    />
                    <Label
                      htmlFor={`mobile-validity-${option.value}`}
                      className="cursor-pointer text-sm font-normal flex items-center gap-1.5"
                    >
                      <span className={`inline-block h-2 w-2 rounded-full ${option.color}`} />
                      {option.label}
                    </Label>
                  </div>
                ))}
              </div>
            </FilterDropdown>

            {/* Stage Filter */}
            <FilterDropdown label="Giai đoạn" count={stageFilters.length}>
              <div className="space-y-2">
                {pipelineStages.map((stage) => (
                  <div key={stage.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`mobile-stage-${stage.id}`}
                      checked={stageFilters.includes(stage.id)}
                      onCheckedChange={() => handleStageToggle(stage.id)}
                    />
                    <Label
                      htmlFor={`mobile-stage-${stage.id}`}
                      className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                    >
                      <ColorDot color={sanitizeColorCode(stage.color_code) || STAGE_COLORS[stage.id]} size="sm" />
                      {stage.name}
                    </Label>
                  </div>
                ))}
              </div>
            </FilterDropdown>

            {/* Offering Filter */}
            <FilterDropdown label="Chương trình" count={offeringFilters.length}>
              <MultiOfferingSelector
                values={offeringFilters}
                onChange={onOfferingChange}
              />
            </FilterDropdown>

            {/* Officer Filter - Admin/Manager only */}
            {canFilterByOfficerFlag && (
              <FilterDropdown label="Cán bộ" count={officerFilters.length}>
                <div className="space-y-2">
                  <Input
                    placeholder="Tìm cán bộ…"
                    value={officerSearch}
                    onChange={(e) => handleOfficerSearchChange(e.target.value)}
                    className="h-7 text-xs"
                  />
                  <div className="max-h-48 space-y-2 overflow-y-auto">
                    {officers.map((officer) => (
                      <div key={officer.id} className="flex items-center space-x-2">
                        <Checkbox
                          id={`mobile-officer-${officer.id}`}
                          checked={officerFilters.includes(officer.id.toString())}
                          onCheckedChange={() => handleOfficerToggle(officer.id.toString())}
                        />
                        <Label
                          htmlFor={`mobile-officer-${officer.id}`}
                          className="cursor-pointer text-sm font-normal"
                        >
                          {officer.full_name}
                        </Label>
                      </div>
                    ))}
                  </div>
                  {officersTruncated && (
                    <p className="text-xs text-muted-foreground pt-1">
                      Hiển thị {officers.length}/{officersTotalCount} — nhập tên để tìm thêm
                    </p>
                  )}
                </div>
              </FilterDropdown>
            )}
          </div>

          {/* Mobile: Action buttons */}
          <div className="mt-3 flex items-center gap-2 border-t pt-3">
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { onReset(); setMobileFiltersOpen(false); }}
                className="h-9 text-xs"
              >
                <RotateCcw className="mr-1 h-3.5 w-3.5" />
                Đặt lại
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Active Filter Pills - Collapsible */}
      {hasActiveFilters && (() => {
        // Build all pills as an array
        const allPills: { key: string; label: string; onRemove: () => void }[] = [];
        
        if (search) {
          allPills.push({ key: "search", label: `"${search}"`, onRemove: () => onSearchChange("") });
        }
        statusFilters.forEach((status) => {
          allPills.push({ key: `status-${status}`, label: getStatusLabel(status), onRemove: () => handleStatusToggle(status) });
        });
        sourceFilters.forEach((source) => {
          allPills.push({ key: `source-${source}`, label: getSourceLabel(source), onRemove: () => handleSourceToggle(source) });
        });
        validityFilters.forEach((validity) => {
          allPills.push({ key: `validity-${validity}`, label: getValidityLabel(validity), onRemove: () => handleValidityToggle(validity) });
        });
        stageFilters.forEach((stage) => {
          allPills.push({ key: `stage-${stage}`, label: getStageLabel(stage), onRemove: () => handleStageToggle(stage) });
        });
        officerFilters.forEach((officer) => {
          allPills.push({ key: `officer-${officer}`, label: getOfficerLabel(officer), onRemove: () => handleOfficerToggle(officer) });
        });
        offeringFilters.forEach((id) => {
          allPills.push({ key: `offering-${id}`, label: getOfferingLabel(id), onRemove: () => handleOfferingToggle(id) });
        });
        if (unitId) {
          allPills.push({ key: "unit", label: `Đơn vị: ${getUnitLabel(unitId)}`, onRemove: () => onUnitIdChange("") });
        }
        if (hasScoreFilter) {
          allPills.push({ key: "score", label: `Điểm: ${scoreRange[0]}-${scoreRange[1]}`, onRemove: () => onScoreRangeChange([0, 100]) });
        }
        if (dateFrom || dateTo) {
          allPills.push({
            key: "date",
            label: `${dateField === "created_at" ? "Tạo" : "TĐ"}: ${dateFrom && dateTo ? `${dateFrom} → ${dateTo}` : dateFrom ? `từ ${dateFrom}` : `đến ${dateTo}`}`,
            onRemove: () => { onDateFromChange(""); onDateToChange(""); },
          });
        }

        const visiblePills = isFiltersExpanded ? allPills : allPills.slice(0, MAX_VISIBLE_PILLS);
        const hiddenCount = allPills.length - MAX_VISIBLE_PILLS;

        return (
          <div className="flex flex-wrap items-center gap-2 border-t px-4 py-2">
            <span className="text-muted-foreground text-xs">Đang lọc:</span>
            
            {visiblePills.map((pill) => (
              <FilterPill key={pill.key} label={pill.label} onRemove={pill.onRemove} />
            ))}
            
            {/* Show "+X more" button when collapsed and has hidden pills */}
            {!isFiltersExpanded && hiddenCount > 0 && (
              <Badge
                variant="outline"
                className="h-6 cursor-pointer gap-1 px-2 text-xs transition-colors hover:bg-primary/10"
                onClick={() => setIsFiltersExpanded(true)}
              >
                +{hiddenCount} more
                <ChevronDown className="h-3 w-3" />
              </Badge>
            )}
            
            {/* Show "Thu gọn" button when expanded */}
            {isFiltersExpanded && allPills.length > MAX_VISIBLE_PILLS && (
              <Badge
                variant="outline"
                className="h-6 cursor-pointer gap-1 px-2 text-xs transition-colors hover:bg-primary/10"
                onClick={() => setIsFiltersExpanded(false)}
              >
                Thu gọn
                <ChevronDown className="h-3 w-3 rotate-180" />
              </Badge>
            )}

            <span className="text-muted-foreground ml-2 text-xs">
              • {totalCount.toLocaleString()} kết quả
            </span>
          </div>
        );
      })()}
    </div>
  );
}

export default LeadFilterBar;
