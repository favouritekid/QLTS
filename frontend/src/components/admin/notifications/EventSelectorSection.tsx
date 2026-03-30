// src/components/admin/notifications/EventSelectorSection.tsx
/**
 * Step 1 sub-component: Event picker with category cards and radio groups.
 * Extracted from NotificationRuleEditor for modularity.
 *
 * Receives value + onChange props (no react-hook-form dependency).
 */
"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
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
  return (
    <div className="space-y-4">
      {sortedCategoryKeys.map((categoryKey) => {
        const categoryEvents = groupedEvents[categoryKey];
        if (!categoryEvents || categoryEvents.length === 0) return null;

        return (
          <Card key={categoryKey}>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className="text-lg">{getCategoryIcon(categoryKey)}</span>
                {getCategoryLabel(categoryKey)}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <RadioGroup
                value={value}
                onValueChange={onChange}
              >
                <div className="space-y-2">
                  {categoryEvents.map((event) => (
                    <div
                      key={event.value}
                      className={`
                        flex items-start space-x-3 rounded-lg border p-3 cursor-pointer transition-colors
                        ${value === event.value ? "border-primary bg-primary/5" : "hover:bg-muted/50"}
                      `}
                      onClick={() => onChange(event.value)}
                    >
                      <RadioGroupItem value={event.value} id={event.value} />
                      <div className="flex-1">
                        <label
                          htmlFor={event.value}
                          className="text-sm font-medium cursor-pointer"
                        >
                          {event.icon} {event.label}
                        </label>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {event.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </RadioGroup>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

export default EventSelectorSection;
