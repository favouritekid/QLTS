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

import React, { useState, useCallback, useTransition } from "react";
import {
  Search,
  X,
  RotateCcw,
  Download,
  Plus,
  ChevronDown,
  Calendar,
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
import { cn } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import type { LeadStatus } from "@/types/lead.types";
import { LEAD_STATUS_OPTIONS, LEAD_SOURCE_OPTIONS } from "@/constants";
import { usePipelineStages } from "@/hooks/usePipeline";
import { useAllProgramOfferings } from "@/hooks/useOrganization";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { useAuth } from "@/hooks/useAuth";
import { isAdmin as checkIsAdmin, canFilterByOfficer as checkCanFilterByOfficer } from "@/lib/utils/permissions";
import { MultiOfferingSelector } from "@/components/common/selectors";
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
  offeringFilters: string[];
  onOfferingChange: (offerings: string[]) => void;
  stageFilters: string[];
  onStageChange: (stages: string[]) => void;
  officerFilters: string[];
  onOfficerChange: (officers: string[]) => void;
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
  onExport: () => void;
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
            "h-8 gap-1 transition-all duration-200",
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
      className="animate-in fade-in-0 zoom-in-95 h-6 gap-1 pr-1 text-xs transition-all duration-200"
    >
      {label}
      <button
        onClick={onRemove}
        className="hover:bg-muted ml-0.5 rounded-full p-0.5 transition-colors"
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
  offeringFilters,
  onOfferingChange,
  stageFilters,
  onStageChange,
  officerFilters,
  onOfficerChange,
  scoreRange,
  onScoreRangeChange,
  dateFrom,
  dateTo,
  dateField,
  onDateFromChange,
  onDateToChange,
  onDateFieldChange,
  onReset,
  onExport,
  onAddLead,
  totalCount,
}: LeadFilterBarProps) {
  const [isPending, startTransition] = useTransition();
  const { user } = useAuth();
  const { data: pipelineStages = [] } = usePipelineStages();
  const { data: offeringsList = [] } = useAllProgramOfferings();
  const { data: usersData } = useAdminUsersList({ page: 1, page_size: 100, status: "active" });
  const officers = usersData?.users?.filter((u) => u.role === "officer" || u.role === "manager") || [];

  const [isMounted, setIsMounted] = React.useState(false);
  React.useEffect(() => { setIsMounted(true); }, []);

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
    offeringFilters.length > 0 ||
    stageFilters.length > 0 ||
    officerFilters.length > 0 ||
    hasScoreFilter ||
    dateFrom ||
    dateTo;

  // Get display labels
  const getStatusLabel = (value: LeadStatus) =>
    LEAD_STATUS_OPTIONS.find((o) => o.value === value)?.label || value;
  const getSourceLabel = (value: string) =>
    LEAD_SOURCE_OPTIONS.find((o) => o.value === value)?.label || value;
  const getStageLabel = (id: string) =>
    pipelineStages.find((s) => s.id === id)?.name || id;
  const getOfficerLabel = (id: string) =>
    officers.find((o) => o.id.toString() === id)?.full_name || id;
  const getOfferingLabel = (id: string) => {
    const offering = offeringsList.find((o) => o.id.toString() === id);
    if (!offering) return id;
    const programName = offering.program?.name || "";
    const type = offering.offering_type || "";
    return `${programName} - ${type}`;
  };

  return (
    <div className="bg-background/95 supports-[backdrop-filter]:bg-background/60 border-b backdrop-blur">
      {/* Main Filter Row */}
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Search */}
        <div className="relative w-64">
          <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
          <Input
            placeholder="Tìm kiếm tên, SĐT, email..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="h-8 pl-9 pr-8 text-sm"
          />
          {search && (
            <button
              onClick={() => onSearchChange("")}
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Divider */}
        <div className="bg-border h-6 w-px" />

        {/* Filter Dropdowns */}
        <div className="flex items-center gap-2">
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
                    <ColorDot color={STAGE_COLORS[stage.id]} size="sm" />
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

        {/* Spacer */}
        <div className="flex-1" />

        {/* Actions */}
        <div className="flex items-center gap-2">
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
          <Button variant="outline" size="sm" onClick={onExport} className="h-8">
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Xuất
          </Button>
          <Button size="sm" onClick={onAddLead} className="h-8">
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Thêm Lead
          </Button>
        </div>
      </div>

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
        stageFilters.forEach((stage) => {
          allPills.push({ key: `stage-${stage}`, label: getStageLabel(stage), onRemove: () => handleStageToggle(stage) });
        });
        officerFilters.forEach((officer) => {
          allPills.push({ key: `officer-${officer}`, label: getOfficerLabel(officer), onRemove: () => handleOfficerToggle(officer) });
        });
        offeringFilters.forEach((id) => {
          allPills.push({ key: `offering-${id}`, label: getOfferingLabel(id), onRemove: () => handleOfferingToggle(id) });
        });
        if (hasScoreFilter) {
          allPills.push({ key: "score", label: `Điểm: ${scoreRange[0]}-${scoreRange[1]}`, onRemove: () => onScoreRangeChange([0, 100]) });
        }
        if (dateFrom || dateTo) {
          allPills.push({
            key: "date",
            label: `${dateField === "created_at" ? "Tạo" : "TĐ"}: ${dateFrom || "..."} → ${dateTo || "..."}`,
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
