// src/components/admin/notifications/EventSelectorSection.tsx
/**
 * Step 1 sub-component: Event picker with collapsible category groups.
 * Extracted from NotificationRuleEditor for modularity.
 *
 * Uses Accordion to keep the long event list compact — only the category
 * containing the selected event (or clicked by user) is expanded.
 */
"use client";

import { useMemo } from "react";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { CATEGORY_DISPLAY, getCategoryIcon } from "./wizard-constants";

// ============================================
// TYPES
// ============================================

export interface EventOption {
  value: string;
  label: string;
  category: string;
  description: string;
  icon: string;
}

export interface EventSelectorSectionProps {
  value: string;
  onChange: (value: string) => void;
  groupedEvents: Record<string, EventOption[]>;
  sortedCategoryKeys: string[];
}

// ============================================
// HELPERS
// ============================================

function getCategoryLabel(category: string): string {
  return CATEGORY_DISPLAY[category]?.label || `Sự kiện ${category.charAt(0).toUpperCase() + category.slice(1)}`;
}

// ============================================
// COMPONENT
// ============================================

export function EventSelectorSection({
  value,
  onChange,
  groupedEvents,
  sortedCategoryKeys,
}: EventSelectorSectionProps) {
  // Find which category the currently selected event belongs to
  const selectedCategory = useMemo(() => {
    if (!value) return undefined;
    for (const [cat, events] of Object.entries(groupedEvents)) {
      if (events.some((e) => e.value === value)) return cat;
    }
    return undefined;
  }, [value, groupedEvents]);

  // Default open: category of selected event, or first category
  const defaultOpen = selectedCategory || sortedCategoryKeys[0] || "";

  return (
    <RadioGroup value={value} onValueChange={onChange}>
      <Accordion
        type="single"
        collapsible
        defaultValue={defaultOpen}
        className="space-y-2"
      >
        {sortedCategoryKeys.map((categoryKey) => {
          const categoryEvents = groupedEvents[categoryKey];
          if (!categoryEvents || categoryEvents.length === 0) return null;

          const isSelectedCategory = categoryKey === selectedCategory;

          return (
            <AccordionItem
              key={categoryKey}
              value={categoryKey}
              className="border rounded-lg px-4"
            >
              <AccordionTrigger className="py-3 hover:no-underline">
                <div className="flex items-center gap-2">
                  <span className="text-lg">{getCategoryIcon(categoryKey)}</span>
                  <span className="text-sm font-medium">{getCategoryLabel(categoryKey)}</span>
                  <Badge variant="secondary" className="text-xs ml-1">
                    {categoryEvents.length}
                  </Badge>
                  {isSelectedCategory && (
                    <Badge variant="default" className="text-xs">
                      Đã chọn
                    </Badge>
                  )}
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                  {categoryEvents.map((event) => (
                    <div
                      key={event.value}
                      className={`
                        flex items-start gap-2 rounded-lg border px-3 py-2 cursor-pointer transition-colors
                        ${value === event.value ? "border-primary bg-primary/5" : "hover:bg-muted/50"}
                      `}
                      onClick={() => onChange(event.value)}
                    >
                      <RadioGroupItem value={event.value} id={event.value} className="mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <label
                          htmlFor={event.value}
                          className="text-sm font-medium cursor-pointer leading-tight"
                        >
                          {event.label}
                        </label>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {event.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </RadioGroup>
  );
}

export default EventSelectorSection;
