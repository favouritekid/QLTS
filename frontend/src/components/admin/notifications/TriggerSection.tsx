// src/components/admin/notifications/TriggerSection.tsx
/**
 * Step 1 wrapper: Combines EventSelectorSection + Separator + ConditionSection.
 * Extracted from NotificationRuleWizard for modularity.
 *
 * The wizard passes all state/callbacks; this component owns no state.
 */
"use client";

import { Bell, Filter, HelpCircle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";

import { EventSelectorSection } from "./EventSelectorSection";
import { ConditionSection } from "./ConditionSection";

import type { EventSelectorSectionProps } from "./EventSelectorSection";
import type { ConditionSectionProps } from "./ConditionSection";

// ============================================
// TYPES
// ============================================

export interface TriggerSectionProps extends EventSelectorSectionProps, ConditionSectionProps {}

// ============================================
// HELPERS
// ============================================

function HelpTooltip({ content }: { content: string }) {
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <HelpCircle className="h-4 w-4 text-muted-foreground cursor-help inline-block ml-1" />
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-xs">
          <p className="text-sm">{content}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ============================================
// COMPONENT
// ============================================

export function TriggerSection(props: TriggerSectionProps) {
  // Split props for sub-components
  const {
    // EventSelectorSection props
    value,
    onChange,
    groupedEvents,
    sortedCategoryKeys,
    // ConditionSection props
    conditionEnabled,
    onConditionEnabledChange,
    conditionField,
    onConditionFieldChange,
    conditionOperator,
    onConditionOperatorChange,
    conditionValue,
    onConditionValueChange,
    isCompoundCondition,
    onIsCompoundConditionChange,
    conditionData,
    updateCondition,
    selectedEventMetadata,
  } = props;

  return (
    <>
      {/* Header: Event selection */}
      <div>
        <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
          <Bell className="h-5 w-5 text-primary" />
          Bước 1: Khi nào gửi thông báo?
          <HelpTooltip content="Chọn sự kiện hệ thống sẽ kích hoạt thông báo này. Ví dụ: khi có lead mới, khi phân công lead, v.v." />
        </h3>
        <p className="text-sm text-muted-foreground">
          Chọn sự kiện hệ thống sẽ kích hoạt thông báo này
        </p>
      </div>

      {/* Event Selector */}
      <EventSelectorSection
        value={value}
        onChange={onChange}
        groupedEvents={groupedEvents}
        sortedCategoryKeys={sortedCategoryKeys}
      />

      {/* Separator between event and condition */}
      <Separator />

      {/* Header: Condition */}
      <div>
        <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
          <Filter className="h-5 w-5 text-primary" />
          Điều kiện (Tùy chọn)
          <HelpTooltip content="Thêm điều kiện để chỉ gửi thông báo khi thỏa mãn tiêu chí. Ví dụ: chỉ gửi khi người thực hiện là Manager. Bạn có thể bỏ qua." />
        </h3>
        <p className="text-sm text-muted-foreground">
          Chỉ gửi thông báo khi đáp ứng điều kiện (có thể bỏ qua)
        </p>
      </div>

      {/* Condition Builder */}
      <ConditionSection
        conditionEnabled={conditionEnabled}
        onConditionEnabledChange={onConditionEnabledChange}
        conditionField={conditionField}
        onConditionFieldChange={onConditionFieldChange}
        conditionOperator={conditionOperator}
        onConditionOperatorChange={onConditionOperatorChange}
        conditionValue={conditionValue}
        onConditionValueChange={onConditionValueChange}
        isCompoundCondition={isCompoundCondition}
        onIsCompoundConditionChange={onIsCompoundConditionChange}
        conditionData={conditionData}
        updateCondition={updateCondition}
        selectedEventMetadata={selectedEventMetadata}
      />
    </>
  );
}

export default TriggerSection;
