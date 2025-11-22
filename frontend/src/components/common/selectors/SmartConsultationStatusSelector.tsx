// src/components/common/selectors/SmartConsultationStatusSelector.tsx
/**
 * SmartConsultationStatusSelector - Reusable Consultation Status Selector
 *
 * Features:
 * - Automatic data fetching via useConsultationStatuses hook
 * - Grouped by pipeline stage
 * - Color-coded status display
 * - Outcome type indicators
 * - Transition filtering (only show valid next statuses)
 * - Searchable with Command component
 *
 * Usage:
 * - ConsultationDialog (status selection)
 * - EditConsultationDialog (status update)
 * - QuickDisposition (quick status change)
 */

"use client";

import { useState, useMemo } from "react";
import { Check, ChevronsUpDown, Circle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  useConsultationStatuses,
  usePipelineStages,
} from "@/hooks/usePipeline";
import type { ConsultationStatus, PipelineStage, OutcomeType } from "@/types/pipeline.types";
import { OUTCOME_TYPE_OPTIONS, getOutcomeTypeColor } from "@/constants/consultation.constants";

// =============================================================================
// TYPES
// =============================================================================

export interface SmartConsultationStatusSelectorProps {
  /** Current selected status ID */
  value?: string;
  /** Callback when selection changes */
  onChange: (value: string) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Filter to only show statuses from specific stage */
  filterStageId?: string;
  /** Filter to only show statuses with specific outcome type */
  filterOutcomeType?: OutcomeType;
  /** Exclude specific status IDs */
  excludeStatusIds?: string[];
  /** Only show these specific status IDs (for status transitions) */
  allowedStatusIds?: string[];
  /** Filter to only show final statuses */
  finalOnly?: boolean;
  /** Filter to only show non-final statuses */
  nonFinalOnly?: boolean;
  /** Disable the selector */
  disabled?: boolean;
  /** Variant: 'select' for grouped dropdown, 'combobox' for searchable */
  variant?: "select" | "combobox";
  /** Show outcome type badge */
  showOutcomeType?: boolean;
  /** Additional CSS classes */
  className?: string;
}

interface StatusWithStage extends ConsultationStatus {
  stageName: string;
  stageOrder: number;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Process statuses with stage info and filtering
 */
function processStatuses(
  statuses: ConsultationStatus[],
  stages: PipelineStage[],
  options: {
    filterStageId?: string;
    filterOutcomeType?: OutcomeType;
    excludeStatusIds?: string[];
    allowedStatusIds?: string[];
    finalOnly?: boolean;
    nonFinalOnly?: boolean;
  }
): StatusWithStage[] {
  const { filterStageId, filterOutcomeType, excludeStatusIds, allowedStatusIds, finalOnly, nonFinalOnly } = options;

  // Create stage lookup
  const stageMap = new Map(stages.map((s) => [s.id, s]));

  return statuses
    .map((status) => {
      const stage = stageMap.get(status.stage_id);
      return {
        ...status,
        stageName: stage?.name ?? "Unknown",
        stageOrder: stage?.order ?? 999,
      };
    })
    .filter((status) => {
      // Filter by allowed IDs (for status transitions)
      if (allowedStatusIds && allowedStatusIds.length > 0 && !allowedStatusIds.includes(status.id)) return false;

      // Filter by stage
      if (filterStageId && status.stage_id !== filterStageId) return false;

      // Filter by outcome type
      if (filterOutcomeType && status.outcome_type !== filterOutcomeType) return false;

      // Exclude specific IDs
      if (excludeStatusIds && excludeStatusIds.includes(status.id)) return false;

      // Filter by final status
      if (finalOnly && !status.is_final_status) return false;
      if (nonFinalOnly && status.is_final_status) return false;

      return true;
    })
    .sort((a, b) => a.stageOrder - b.stageOrder);
}

/**
 * Group statuses by stage
 */
function groupByStage(statuses: StatusWithStage[]): Map<string, StatusWithStage[]> {
  const groups = new Map<string, StatusWithStage[]>();

  for (const status of statuses) {
    const key = status.stageName;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(status);
  }

  return groups;
}

// =============================================================================
// STATUS ITEM DISPLAY
// =============================================================================

function StatusItem({
  status,
  showOutcomeType,
  isSelected,
}: {
  status: StatusWithStage;
  showOutcomeType: boolean;
  isSelected: boolean;
}) {
  return (
    <div className="flex items-center gap-2 w-full">
      {isSelected && <Check className="h-4 w-4 shrink-0" />}
      {!isSelected && <div className="w-4" />}
      <Circle
        className="h-3 w-3 shrink-0"
        fill={status.color_code || status.color}
        stroke={status.color_code || status.color}
      />
      <span className="flex-1 truncate">{status.name}</span>
      {showOutcomeType && (
        <Badge
          variant="outline"
          className={cn("text-xs shrink-0", getOutcomeTypeColor(status.outcome_type))}
        >
          {OUTCOME_TYPE_OPTIONS.find((o) => o.value === status.outcome_type)?.label}
        </Badge>
      )}
      {status.is_final_status && (
        <Badge variant="secondary" className="text-xs shrink-0">
          Final
        </Badge>
      )}
    </div>
  );
}

// =============================================================================
// SELECT VARIANT COMPONENT
// =============================================================================

function SelectVariant({
  value,
  onChange,
  placeholder,
  disabled,
  statuses,
  isLoading,
  showOutcomeType,
  className,
}: {
  value?: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled: boolean;
  statuses: StatusWithStage[];
  isLoading: boolean;
  showOutcomeType: boolean;
  className?: string;
}) {
  const groupedStatuses = useMemo(() => groupByStage(statuses), [statuses]);
  const selectedStatus = statuses.find((s) => s.id === value);

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled || isLoading}>
      <SelectTrigger className={className}>
        <SelectValue placeholder={isLoading ? "Dang tai..." : placeholder}>
          {selectedStatus && (
            <div className="flex items-center gap-2">
              <Circle
                className="h-3 w-3 shrink-0"
                fill={selectedStatus.color_code || selectedStatus.color}
                stroke={selectedStatus.color_code || selectedStatus.color}
              />
              <span>{selectedStatus.name}</span>
            </div>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-[300px]">
        {isLoading ? (
          <SelectItem value="loading" disabled>
            Dang tai trang thai...
          </SelectItem>
        ) : statuses.length === 0 ? (
          <SelectItem value="empty" disabled>
            Khong co trang thai kha dung
          </SelectItem>
        ) : (
          Array.from(groupedStatuses.entries()).map(([stageName, stageStatuses]) => (
            <SelectGroup key={stageName}>
              <SelectLabel className="text-xs font-semibold text-muted-foreground">
                {stageName}
              </SelectLabel>
              {stageStatuses.map((status) => (
                <SelectItem key={status.id} value={status.id}>
                  <div className="flex items-center gap-2">
                    <Circle
                      className="h-3 w-3 shrink-0"
                      fill={status.color_code || status.color}
                      stroke={status.color_code || status.color}
                    />
                    <span>{status.name}</span>
                    {showOutcomeType && (
                      <span
                        className={cn("text-xs ml-1", getOutcomeTypeColor(status.outcome_type))}
                      >
                        ({OUTCOME_TYPE_OPTIONS.find((o) => o.value === status.outcome_type)?.label})
                      </span>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectGroup>
          ))
        )}
      </SelectContent>
    </Select>
  );
}

// =============================================================================
// COMBOBOX VARIANT COMPONENT
// =============================================================================

function ComboboxVariant({
  value,
  onChange,
  placeholder,
  disabled,
  statuses,
  isLoading,
  showOutcomeType,
  className,
}: {
  value?: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled: boolean;
  statuses: StatusWithStage[];
  isLoading: boolean;
  showOutcomeType: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const groupedStatuses = useMemo(() => groupByStage(statuses), [statuses]);
  const selectedStatus = statuses.find((s) => s.id === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || isLoading}
          className={cn("w-full justify-between", className)}
        >
          {isLoading ? (
            "Dang tai..."
          ) : selectedStatus ? (
            <div className="flex items-center gap-2">
              <Circle
                className="h-3 w-3 shrink-0"
                fill={selectedStatus.color_code || selectedStatus.color}
                stroke={selectedStatus.color_code || selectedStatus.color}
              />
              <span className="truncate">{selectedStatus.name}</span>
            </div>
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[350px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Tim kiem trang thai..." />
          <CommandEmpty>Khong tim thay trang thai nao.</CommandEmpty>
          {Array.from(groupedStatuses.entries()).map(([stageName, stageStatuses]) => (
            <CommandGroup key={stageName} heading={stageName}>
              {stageStatuses.map((status) => (
                <CommandItem
                  key={status.id}
                  value={`${status.name} ${status.stageName}`}
                  onSelect={() => {
                    onChange(status.id);
                    setOpen(false);
                  }}
                >
                  <StatusItem
                    status={status}
                    showOutcomeType={showOutcomeType}
                    isSelected={value === status.id}
                  />
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function SmartConsultationStatusSelector({
  value,
  onChange,
  placeholder = "Chon trang thai",
  filterStageId,
  filterOutcomeType,
  excludeStatusIds,
  allowedStatusIds,
  finalOnly = false,
  nonFinalOnly = false,
  disabled = false,
  variant = "select",
  showOutcomeType = false,
  className,
}: SmartConsultationStatusSelectorProps) {
  // Fetch data
  const { data: statuses = [], isLoading: statusesLoading } = useConsultationStatuses();
  const { data: stages = [], isLoading: stagesLoading } = usePipelineStages();

  const isLoading = statusesLoading || stagesLoading;

  // Process statuses with filtering
  const processedStatuses = useMemo(
    () =>
      processStatuses(statuses, stages, {
        filterStageId,
        filterOutcomeType,
        excludeStatusIds,
        allowedStatusIds,
        finalOnly,
        nonFinalOnly,
      }),
    [statuses, stages, filterStageId, filterOutcomeType, excludeStatusIds, allowedStatusIds, finalOnly, nonFinalOnly]
  );

  // Render based on variant
  const commonProps = {
    value,
    onChange,
    placeholder,
    disabled,
    statuses: processedStatuses,
    isLoading,
    showOutcomeType,
    className,
  };

  if (variant === "combobox") {
    return <ComboboxVariant {...commonProps} />;
  }

  return <SelectVariant {...commonProps} />;
}

export default SmartConsultationStatusSelector;
