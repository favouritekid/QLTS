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
import { STAGE_COLORS } from "@/types/pipeline.types";
import { useAuth } from "@/hooks/useAuth";

interface LeadFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilters: LeadStatus[];
  onStatusChange: (statuses: LeadStatus[]) => void;
  sourceFilter: string;
  onSourceChange: (source: string) => void;
  scoreRange: [number, number];
  onScoreRangeChange: (range: [number, number]) => void;
  offeringFilter: string;
  onOfferingChange: (offeringId: string) => void;
  // === PIPELINE STAGE FILTER ===
  pipelineStageFilter: string;
  onPipelineStageChange: (stageId: string) => void;
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
  sourceFilter,
  onSourceChange,
  scoreRange,
  onScoreRangeChange,
  offeringFilter,
  onOfferingChange,
  // === PIPELINE STAGE FILTER ===
  pipelineStageFilter,
  onPipelineStageChange,
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
  const isAdmin = user?.role === "admin";

  const handleStatusToggle = (status: LeadStatus) => {
    if (statusFilters.includes(status)) {
      onStatusChange(statusFilters.filter((s) => s !== status));
    } else {
      onStatusChange([...statusFilters, status]);
    }
  };

  const hasActiveFilters =
    search ||
    statusFilters.length > 0 ||
    sourceFilter !== "all" ||
    scoreRange[0] > 0 ||
    scoreRange[1] < 100 ||
    offeringFilter !== "all" ||
    pipelineStageFilter !== "all" ||
    dateFrom ||
    dateTo;

  return (
    <div className="h-full bg-card">
      <div className="h-full overflow-y-auto p-4 space-y-4">
        {/* Tiêu đề */}
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Bộ lọc</h3>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onReset}
              className="h-7 px-2 text-xs"
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Đặt lại
            </Button>
          )}
        </div>

        {/* Tìm kiếm */}
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm kiếm tên, số điện thoại, email..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-8 pr-8"
          />
          {search && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Bộ lọc */}
        <Accordion type="multiple" defaultValue={["pipeline_stage"]} className="space-y-2">
          {/* Bộ lọc trạng thái - Chỉ hiển thị cho Admin */}
          {isAdmin && (
            <AccordionItem value="status" className="border rounded-lg px-3">
              <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
                Vòng đời Lead
                {statusFilters.length > 0 && (
                  <span className="ml-auto mr-2 text-xs bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">
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
                        className="text-sm font-normal cursor-pointer flex items-center gap-2"
                      >
                        <span className={`w-2 h-2 rounded-full ${option.color}`} />
                        {option.label}
                      </Label>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {/* Bộ lọc Pipeline Stage */}
          <AccordionItem value="pipeline_stage" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Giai đoạn Pipeline
              {pipelineStageFilter !== "all" && (
                <span className="ml-auto mr-2 text-xs bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">
                  1
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <Select value={pipelineStageFilter} onValueChange={onPipelineStageChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Tất cả giai đoạn" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả giai đoạn</SelectItem>
                  {pipelineStages.map((stage) => (
                    <SelectItem key={stage.id} value={stage.id}>
                      <div className="flex items-center gap-2">
                        <span 
                          className="w-2.5 h-2.5 rounded-full" 
                          style={{ backgroundColor: STAGE_COLORS[stage.id] || '#6B7280' }}
                        />
                        {stage.name}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc nguồn */}
          <AccordionItem value="source" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Nguồn
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <Select value={sourceFilter} onValueChange={onSourceChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Tất cả nguồn" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả nguồn</SelectItem>
                  {LEAD_SOURCE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc điểm Lead */}
          <AccordionItem value="score" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Điểm Lead
            </AccordionTrigger>
            <AccordionContent className="pb-3 pt-2">
              <div className="space-y-4">
                <Slider
                  value={scoreRange}
                  onValueChange={(value) => onScoreRangeChange(value as [number, number])}
                  max={100}
                  min={0}
                  step={5}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{scoreRange[0]}</span>
                  <span>{scoreRange[1]}</span>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc chương trình */}
          <AccordionItem value="offering" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              Chương trình
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <SmartOfferingSelector
                value={offeringFilter === "all" ? undefined : offeringFilter}
                onChange={(val) => onOfferingChange(val || "all")}
                placeholder="Chọn chương trình..."
                allowAll
                allLabel="Tất cả chương trình"
                variant="combobox"
              />
            </AccordionContent>
          </AccordionItem>

          {/* Bộ lọc ngày tạo/cập nhật */}
          <AccordionItem value="date" className="border rounded-lg px-3">
            <AccordionTrigger className="text-sm font-medium py-3 hover:no-underline">
              <div className="flex items-center gap-2">
                Khoảng thời gian
              </div>
              {(dateFrom || dateTo) && (
                <span className="ml-auto mr-2 text-xs bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">
                  1
                </span>
              )}
            </AccordionTrigger>
            <AccordionContent className="pb-3 space-y-3">
              {/* Date field selector */}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Lọc theo</Label>
                <Select value={dateField} onValueChange={(val) => onDateFieldChange(val as "created_at" | "updated_at")}>
                  <SelectTrigger className="w-full h-8 text-sm">
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
                <Label className="text-xs text-muted-foreground">Từ ngày</Label>
                <Input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => onDateFromChange(e.target.value)}
                  className="h-8 text-sm"
                />
              </div>

              {/* Date to */}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Đến ngày</Label>
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
