// src/components/officer/TodaySchedule.tsx
/**
 * Today's Schedule Widget
 * Shows mini calendar and list of scheduled activities
 */
"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { 
  ChevronLeft, 
  ChevronRight, 
  MoreHorizontal,
  Phone,
  Video,
  UserCheck,
  Clock
} from "lucide-react";

// =============================================================================
// TYPES
// =============================================================================

interface ScheduleItem {
  id: number;
  time: string;
  title: string;
  type: "meeting" | "call" | "follow_up" | "review";
  leadId?: number;
}

interface TodayScheduleProps {
  activities?: ScheduleItem[];
  className?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

const ACTIVITY_ICONS: Record<string, React.ElementType> = {
  meeting: UserCheck,
  call: Phone,
  follow_up: Clock,
  review: Video,
};

const ACTIVITY_COLORS: Record<string, string> = {
  meeting: "bg-blue-500",
  call: "bg-green-500",
  follow_up: "bg-amber-500",
  review: "bg-purple-500",
};

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
  activeDates = []
}: { 
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
  activeDates?: number[]; // Days that have activities
}) {
  const [viewDate, setViewDate] = useState(new Date());
  
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const today = new Date();
  
  const daysInMonth = getDaysInMonth(year, month);
  const firstDayOfMonth = getFirstDayOfMonth(year, month);
  
  // Previous month navigation
  const goToPrevMonth = () => {
    setViewDate(new Date(year, month - 1, 1));
  };
  
  // Next month navigation
  const goToNextMonth = () => {
    setViewDate(new Date(year, month + 1, 1));
  };
  
  // Generate calendar days
  const calendarDays = useMemo(() => {
    const days: (number | null)[] = [];
    
    // Add empty cells for days before the first day of month
    for (let i = 0; i < firstDayOfMonth; i++) {
      days.push(null);
    }
    
    // Add days of the month
    for (let day = 1; day <= daysInMonth; day++) {
      days.push(day);
    }
    
    return days;
  }, [firstDayOfMonth, daysInMonth]);
  
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
  
  return (
    <div className="space-y-2">
      {/* Month Navigation */}
      <div className="flex items-center justify-between">
        <Button 
          variant="ghost" 
          size="icon" 
          className="h-6 w-6"
          onClick={goToPrevMonth}
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
            onClick={() => day && onDateSelect(new Date(year, month, day))}
            className={cn(
              "relative h-7 w-7 text-xs rounded-full transition-colors disabled:invisible",
              "hover:bg-muted focus:outline-none focus:ring-2 focus:ring-primary/20",
              isToday(day!) && !isSelected(day!) && "bg-primary/10 text-primary font-semibold",
              isSelected(day!) && "bg-primary text-primary-foreground font-semibold",
              activeDates.includes(day!) && !isSelected(day!) && "font-semibold"
            )}
          >
            {day}
            {/* Activity indicator dot */}
            {day && activeDates.includes(day) && !isSelected(day) && (
              <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 bg-primary rounded-full" />
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

export function TodaySchedule({ activities = [], className }: TodayScheduleProps) {
  const router = useRouter();
  const [selectedDate, setSelectedDate] = useState(new Date());
  
  // Mock data for demo - replace with real data
  const mockActivities: ScheduleItem[] = activities.length > 0 ? activities : [
    { id: 1, time: "09:00 AM", title: "Team Meeting", type: "meeting" },
    { id: 2, time: "11:00 AM", title: "Client Call (Online)", type: "call", leadId: 123 },
    { id: 3, time: "02:00 PM", title: "Follow-up", type: "follow_up", leadId: 456 },
    { id: 4, time: "04:30 PM", title: "Internal Review", type: "review" },
  ];
  
  // Get days with activities (for calendar highlight)
  const activeDates = useMemo(() => {
    const today = new Date();
    // Demo: mark today and a few other days
    return [today.getDate(), today.getDate() + 2, today.getDate() + 5];
  }, []);
  
  const handleActivityClick = (activity: ScheduleItem) => {
    if (activity.leadId) {
      router.push(`/leads/${activity.leadId}`);
    }
  };
  
  return (
    <Card className={cn("border bg-card", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">
            Today's Schedule
          </CardTitle>
          <Button variant="ghost" size="icon" className="h-6 w-6">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Mini Calendar */}
        <MiniCalendar 
          selectedDate={selectedDate}
          onDateSelect={setSelectedDate}
          activeDates={activeDates}
        />
        
        {/* Divider */}
        <div className="border-t" />
        
        {/* Activities List */}
        <div className="space-y-2">
          {mockActivities.map((activity) => {
            const Icon = ACTIVITY_ICONS[activity.type] || Clock;
            const bgColor = ACTIVITY_COLORS[activity.type] || "bg-gray-500";
            
            return (
              <button
                key={activity.id}
                onClick={() => handleActivityClick(activity)}
                className={cn(
                  "w-full flex items-center gap-3 p-2 rounded-lg text-left",
                  "hover:bg-muted/50 transition-colors",
                  activity.leadId && "cursor-pointer"
                )}
              >
                {/* Color indicator */}
                <div className={cn("w-1 h-8 rounded-full", bgColor)} />
                
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground font-medium">
                      {activity.time}
                    </span>
                    <span className="text-sm truncate">
                      {activity.title}
                    </span>
                  </div>
                </div>
                
                {/* Icon */}
                <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              </button>
            );
          })}
          
          {mockActivities.length === 0 && (
            <div className="text-center py-4 text-sm text-muted-foreground">
              Không có lịch hẹn hôm nay
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default TodaySchedule;
