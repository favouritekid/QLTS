// src/components/leads/command-center/LeadFilters.tsx
"use client";

import React from "react";
import { Search, X, RotateCcw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LeadStatus } from "@/types/lead.types";
import { SmartOfferingSelector } from "@/components/common/selectors";
import { LEAD_STATUS_OPTIONS, LEAD_SOURCE_OPTIONS } from "@/constants";
import { usePipelineStages } from "@/hooks/usePipeline";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { useAuth } from "@/hooks/useAuth";

interface LeadFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilters: LeadStatus[];
  onStatusChange: (statuses: LeadStatus[]) => void;
  // Multi-select arrays
  sourceFilters: string[];
  onSourceChange: (sources: string[]) => void;
  scoreRange: [number, number];
  onScoreRangeChange: (range: [number, number]) => void;
  offeringFilters: string[];
  onOfferingChange: (offeringIds: string[]) => void;
  stageFilters: string[];
  onStageChange: (stageIds: string[]) => void;
  // === OFFICER FILTER (admin/manager only) ===
  officerFilters: string[];
  onOfficerChange: (officerIds: string[]) => void;
  // === DATE RANGE FILTER ===
  dateFrom: string;
  dateTo: string;
  dateField: "created_at" | "updated_at";
  onDateFromChange: (date: string) => void;
  onDateToChange: (date: string) => void;
  onDateFieldChange: (field: "created_at" | "updated_at") => void;
  onReset: () => void;
}

// Using centralized constants from @/constants
// STATUS_OPTIONS and SOURCE_OPTIONS are now imported as LEAD_STATUS_OPTIONS and LEAD_SOURCE_OPTIONS

export const LeadFilters = React.memo(function LeadFilters({
  search,
  onSearchChange,
  statusFilters,
  onStatusChange,
  // Multi-select
  sourceFilters,
  onSourceChange,
  scoreRange,
  onScoreRangeChange,
  offeringFilters,
  onOfferingChange,
  stageFilters,
  onStageChange,
  // === OFFICER FILTER ===
  officerFilters,
  onOfficerChange,
  // === DATE RANGE FILTER ===
  dateFrom,
  dateTo,
  dateField,
  onDateFromChange,
  onDateToChange,
  onDateFieldChange,
  onReset,
}: LeadFiltersProps) {
  // Fetch pipeline stages
  const { data: pipelineStages = [] } = usePipelineStages();
  const { user } = useAuth();

  // Hydration-safe role checks - only render role-dependent UI after mount
  const [isMounted, setIsMounted] = React.useState(false);
  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  // Role checks only work after hydration to prevent server/client mismatch
  const isAdmin = isMounted && user?.role === "admin";
  const isManager = isMounted && user?.role === "manager";
  const canFilterByOfficer = isAdmin || isManager;

  // Fetch officers list (always fetch, conditionally render UI)
  // We fetch all active users and filter by role on the client
  const { data: usersData } = useAdminUsersList({ page: 1, page_size: 100, status: "active" });
  const officers = usersData?.users?.filter((u) => u.role === "officer" || u.role === "manager") || [];

  const handleStatusToggle = (status: LeadStatus) => {
    if (statusFilters.includes(status)) {
      onStatusChange(statusFilters.filter((s) => s !== status));
    } else {
      onStatusChange([...statusFilters, status]);
    }
  };

  // Multi-select toggle helpers
  const handleSourceToggle = (source: string) => {
    if (sourceFilters.includes(source)) {
      onSourceChange(sourceFilters.filter((s) => s !== source));
    } else {
      onSourceChange([...sourceFilters, source]);
    }
  };

  const handleStageToggle = (stageId: string) => {
    if (stageFilters.includes(stageId)) {
      onStageChange(stageFilters.filter((s) => s !== stageId));
    } else {
      onStageChange([...stageFilters, stageId]);
    }
  };

  const handleOfficerToggle = (officerId: string) => {
    if (officerFilters.includes(officerId)) {
      onOfficerChange(officerFilters.filter((o) => o !== officerId));
    } else {
      onOfficerChange([...officerFilters, officerId]);
    }
  };

  const hasActiveFilters =
    search ||
    statusFilters.length > 0 ||
    sourceFilters.length > 0 ||
    scoreRange[0] > 0 ||
    scoreRange[1] < 100 ||
    offeringFilters.length > 0 ||
    stageFilters.length > 0 ||
    officerFilters.length > 0 ||
    dateFrom ||
    dateTo;

  return (
    <div className="bg-card h-full">
      <div className="h-full space-y-4 overflow-y-auto p-4">
        {/* Tiêu đề */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Bộ lọc</h3>
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={onReset} className="h-7 px-2 text-xs">
              <RotateCcw className="mr-1 h-3 w-3" />
              Đặt lại
            </Button>
          )}
        </div>

        {/* Tìm kiếm */}
        <div className="relative">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 h-4 w-4" />
          <Input
            placeholder="Tìm kiếm tên, số điện thoại, email..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pr-8 pl-8"
          />
          {search && (
            <button
              onClick={() => onSearchChange("")}
              className="text-muted-foreground hover:text-foreground absolute top-2.5 right-2.5"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Bộ lọc */}
        <Accordion type="multiple" defaultValue={["pipeline_stage"]} className="space-y-2">
          {/* Bộ lọc trạng thái - Chỉ hiển thị cho Admin */}
          {isAdmin && (
            <AccordionItem value="status" className="rounded-lg border px-3">
              <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                Vòng đời Lead
                {statusFilters.length > 0 && (
                  <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                    {statusFilters.length}
                  </span>
                )}
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <div className="space-y-2">
                  {LEAD_STATUS_OPTIONS.map((option) => (
                    <div key={option.value} className="flex items-center space-x-2">
                      <Checkbox
                        id={`status-${option.value}`}
                        checked={statusFilters.includes(option.value)}
                        onCheckedChange={() => handleStatusToggle(option.value)}
                      />
                      <Label
                        htmlFor={`status-${option.value}`}
                        className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                      >
                        <span className={`h-2 w-2 rounded-full ${option.color}`} />
                        {option.label}
                      </Label>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {/* Bộ lọc Pipeline Stage - Multi-select */}
          <AccordionItem value="pipeline_stage" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              Giai đoạn Pipeline
              {stageFilters.length > 0 && (
                <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                  {stageFilters.length}
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <div className="space-y-2">
                {pipelineStages.map((stage) => (
                  <div key={stage.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`stage-${stage.id}`}
                      checked={stageFilters.includes(stage.id)}
                      onCheckedChange={() => handleStageToggle(stage.id)}
                    />
                    <Label
                      htmlFor={`stage-${stage.id}`}
                      className="flex cursor-pointer items-center gap-2 text-sm font-normal"
                    >
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: STAGE_COLORS[stage.id] || "#6B7280" }}
                      />
                      {stage.name}
                    </Label>
                  </div>
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc nguồn - Multi-select */}
          <AccordionItem value="source" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              Nguồn
              {sourceFilters.length > 0 && (
                <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                  {sourceFilters.length}
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <div className="space-y-2">
                {LEAD_SOURCE_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center space-x-2">
                    <Checkbox
                      id={`source-${option.value}`}
                      checked={sourceFilters.includes(option.value)}
                      onCheckedChange={() => handleSourceToggle(option.value)}
                    />
                    <Label
                      htmlFor={`source-${option.value}`}
                      className="cursor-pointer text-sm font-normal"
                    >
                      {option.label}
                    </Label>
                  </div>
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc điểm Lead */}
          <AccordionItem value="score" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              Điểm Lead
            </AccordionTrigger>
            <AccordionContent className="pt-2 pb-3">
              <div className="space-y-4">
                <Slider
                  value={scoreRange}
                  onValueChange={(value) => onScoreRangeChange(value as [number, number])}
                  max={100}
                  min={0}
                  step={5}
                  className="w-full"
                />
                <div className="text-muted-foreground flex justify-between text-xs">
                  <span>{scoreRange[0]}</span>
                  <span>{scoreRange[1]}</span>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc chương trình - Multi-select (still uses SmartOfferingSelector for now, will need separate update) */}
          <AccordionItem value="offering" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              Chương trình
              {offeringFilters.length > 0 && (
                <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                  {offeringFilters.length}
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <SmartOfferingSelector
                value={offeringFilters.length === 1 ? offeringFilters[0] : undefined}
                onChange={(val) => onOfferingChange(val ? [val] : [])}
                placeholder="Chọn chương trình..."
                allowAll
                allLabel="Tất cả chương trình"
                variant="combobox"
              />
              {/* TODO: Implement proper multi-select for offerings */}
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc cán bộ phụ trách - Multi-select, chỉ cho Admin/Manager */}
          {(isAdmin || isManager) && (
            <AccordionItem value="officer" className="rounded-lg border px-3">
              <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                Cán bộ phụ trách
                {officerFilters.length > 0 && (
                  <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                    {officerFilters.length}
                  </span>
                )}
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {officers.map((officer) => (
                    <div key={officer.id} className="flex items-center space-x-2">
                      <Checkbox
                        id={`officer-${officer.id}`}
                        checked={officerFilters.includes(officer.id.toString())}
                        onCheckedChange={() => handleOfficerToggle(officer.id.toString())}
                      />
                      <Label
                        htmlFor={`officer-${officer.id}`}
                        className="cursor-pointer text-sm font-normal"
                      >
                        {officer.full_name}
                      </Label>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {/* Bộ lọc ngày tạo/cập nhật */}
          <AccordionItem value="date" className="rounded-lg border px-3">
            <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
              <div className="flex items-center gap-2">Khoảng thời gian</div>
              {(dateFrom || dateTo) && (
                <span className="bg-primary text-primary-foreground mr-2 ml-auto rounded-full px-1.5 py-0.5 text-xs">
                  1
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="space-y-3 pb-3">
              {/* Date field selector */}
              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs">Lọc theo</Label>
                <Select
                  value={dateField}
                  onValueChange={(val) => onDateFieldChange(val as "created_at" | "updated_at")}
                >
                  <SelectTrigger className="h-8 w-full text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="created_at">Ngày tạo</SelectItem>
                    <SelectItem value="updated_at">Ngày cập nhật</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Date from */}
              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs">Từ ngày</Label>
                <Input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => onDateFromChange(e.target.value)}
                  className="h-8 text-sm"
                />
              </div>

              {/* Date to */}
              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs">Đến ngày</Label>
                <Input
                  type="date"
                  value={dateTo}
                  onChange={(e) => onDateToChange(e.target.value)}
                  className="h-8 text-sm"
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  );
});
