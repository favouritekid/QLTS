// src/components/officer/TodaySchedule.tsx
/**
 * Today's Schedule Widget
 * Shows mini calendar and list of scheduled activities
 * Data from next_activity_at field in Lead model
 */
"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
// useQuery removed

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { 
  ChevronLeft, 
  ChevronRight, 
  MoreHorizontal,
  User,
  Calendar
} from "lucide-react";
import { useOfficerSchedule, type ScheduleActivity } from "@/hooks/officer/useOfficerSchedule";

// =============================================================================
// TYPES
// =============================================================================

// Types are now imported from officer.ts

interface TodayScheduleProps {
  className?: string;
  scope?: "personal" | "team" | "organization" | null;
  unitId?: number | null;
  officerId?: number | null;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const WEEKDAYS = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

// =============================================================================
// MINI CALENDAR COMPONENT
// =============================================================================

function MiniCalendar({ 
  selectedDate, 
  onDateSelect,
  viewDate,
  onViewDateChange,
  datesWithActivities = []
}: { 
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
  viewDate: Date;
  onViewDateChange: (date: Date) => void;
  datesWithActivities?: number[];
}) {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const today = new Date();
  
  // Previous month navigation
  const goToPrevMonth = () => {
    onViewDateChange(new Date(year, month - 1, 1));
  };
  
  // Next month navigation
  const goToNextMonth = () => {
    onViewDateChange(new Date(year, month + 1, 1));
  };
  
  // Generate calendar days - use year/month as stable dependencies
  // Calculate derived values inside useMemo to ensure React Compiler can optimize
  const calendarDays = useMemo(() => {
    const totalDays = getDaysInMonth(year, month);
    const firstDay = getFirstDayOfMonth(year, month);
    const days: (number | null)[] = [];
    
    // Add empty cells for days before the first day of month
    for (let i = 0; i < firstDay; i++) {
      days.push(null);
    }
    
    // Add days of the month
    for (let day = 1; day <= totalDays; day++) {
      days.push(day);
    }
    
    return days;
  }, [year, month]);
  
  const isToday = (day: number) => {
    return (
      day === today.getDate() &&
      month === today.getMonth() &&
      year === today.getFullYear()
    );
  };
  
  const isSelected = (day: number) => {
    return (
      day === selectedDate.getDate() &&
      month === selectedDate.getMonth() &&
      year === selectedDate.getFullYear()
    );
  };
  
  const hasActivity = (day: number) => {
    return datesWithActivities.includes(day);
  };
  
  return (
    <div className="space-y-2">
      {/* Month Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={goToPrevMonth}
          aria-label="Tháng trước"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm font-medium">
          {viewDate.toLocaleDateString("vi-VN", { month: "long", year: "numeric" })}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={goToNextMonth}
          aria-label="Tháng sau"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      
      {/* Weekday Headers */}
      <div className="grid grid-cols-7 gap-1 text-center">
        {WEEKDAYS.map((day) => (
          <div key={day} className="text-xs text-muted-foreground font-medium py-1">
            {day}
          </div>
        ))}
      </div>
      
      {/* Calendar Grid */}
      <div className="grid grid-cols-7 gap-1">
        {calendarDays.map((day, index) => (
          <button
            key={index}
            disabled={day === null}
            onClick={() => day !== null && onDateSelect(new Date(year, month, day))}
            aria-label={day !== null ? `Ngày ${day} tháng ${month + 1}${hasActivity(day) ? ' - Có lịch hẹn' : ''}` : undefined}
            className={cn(
              "relative h-7 w-7 text-xs rounded-full transition-colors disabled:invisible",
              "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20",
              // Fix: Safe null checks instead of non-null assertions
              day !== null && isToday(day) && !isSelected(day) && "bg-primary/10 text-primary font-semibold",
              day !== null && isSelected(day) && "bg-primary text-primary-foreground font-semibold",
              day !== null && hasActivity(day) && !isSelected(day) && "font-semibold"
            )}
          >
            {day}
            {/* Red dot indicator for days with activities */}
            {day !== null && hasActivity(day) && (
              <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1.5 h-1.5 bg-error-500 rounded-full" aria-hidden="true" />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function TodaySchedule({ className, scope, unitId, officerId }: TodayScheduleProps) {
  const router = useRouter();
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [viewDate, setViewDate] = useState(new Date());

  // Fetch upcoming activities for current view month (scope-aware + officer drill-down)
  const { data, isLoading } = useOfficerSchedule(
    viewDate.getMonth() + 1,
    viewDate.getFullYear(),
    scope ?? undefined,
    unitId,
    officerId,
  );
  
  // Filter activities for selected date
  // Fix: Compare date strings directly to avoid timezone shift issues
  // When new Date("2024-12-15") is created, it's interpreted as UTC midnight,
  // which shifts to a different day in local timezone (e.g., UTC+7)
  const activities = data?.activities;
  const selectedDateActivities = useMemo(() => {
    if (!activities) return [];
    
    // Format selected date as YYYY-MM-DD string for comparison
    const selectedDateStr = `${selectedDate.getFullYear()}-${String(selectedDate.getMonth() + 1).padStart(2, '0')}-${String(selectedDate.getDate()).padStart(2, '0')}`;
    
    return activities.filter(activity => {
      // activity.date is already a YYYY-MM-DD string from the API
      return activity.date === selectedDateStr;
    });
  }, [activities, selectedDate]);
  
  // Get dates with activities for calendar highlighting
  const datesWithActivities = data?.dates_with_activities || [];
  
  const handleActivityClick = (activity: ScheduleActivity) => {
    router.push(`/leads/${activity.lead_id}`);
  };
  
  // Format selected date for header
  const formattedSelectedDate = selectedDate.toLocaleDateString("vi-VN", {
    weekday: "long",
    day: "numeric",
    month: "long"
  });
  
  return (
    <Card className={cn("border bg-card", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">
            Lịch hẹn
          </CardTitle>
          <Button variant="ghost" size="icon" className="h-6 w-6" aria-label="Tùy chọn">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Mini Calendar */}
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <MiniCalendar 
            selectedDate={selectedDate}
            onDateSelect={setSelectedDate}
            viewDate={viewDate}
            onViewDateChange={setViewDate}
            datesWithActivities={datesWithActivities}
          />
        )}
        
        {/* Divider with selected date */}
        <div className="border-t pt-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
            <Calendar className="h-4 w-4" />
            <span className="capitalize">{formattedSelectedDate}</span>
          </div>
        </div>
        
        {/* Activities List for Selected Date */}
        <div className="space-y-2">
          {isLoading ? (
            <>
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </>
          ) : selectedDateActivities.length > 0 ? (
            selectedDateActivities.map((activity) => (
              <button
                key={activity.id}
                onClick={() => handleActivityClick(activity)}
                aria-label={`Lịch hẹn lúc ${activity.time} với ${activity.lead_name}`}
                className={cn(
                  "w-full flex items-center gap-3 p-2 rounded-lg text-left",
                  "hover:bg-muted/50 transition-colors cursor-pointer"
                )}
              >
                {/* Time */}
                <span className="text-sm font-medium text-primary min-w-[50px]">
                  {activity.time}
                </span>
                
                {/* Lead name */}
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <User className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                  <span className="text-sm truncate">
                    {activity.lead_name}
                  </span>
                </div>
              </button>
            ))
          ) : (
            <div className="text-center py-4 text-sm text-muted-foreground">
              Không có lịch hẹn
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default TodaySchedule;
