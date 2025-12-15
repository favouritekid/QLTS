// src/components/officer/dashboard/SmartHeader.tsx
/**
 * Smart Header - Clean shadcn design
 * Greeting, goal progress, quick actions
 * Note: Availability toggle moved to WorkloadCard
 */

"use client";

import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Target,
  Plus,
  Phone,
  Calendar,
  ChevronDown,
  Sparkles,
  Bell,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface SmartHeaderProps {
  consultationsToday: number;
  dailyTarget: number;
  isAvailable: boolean;
  onToggleAvailability: (available: boolean) => void;
  onQuickAction?: (action: "new_lead" | "log_call" | "schedule") => void;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Chào buổi sáng";
  if (hour < 18) return "Chào buổi chiều";
  return "Chào buổi tối";
}

export function SmartHeader({
  consultationsToday,
  dailyTarget,
  isAvailable,
  onToggleAvailability,
  onQuickAction,
}: SmartHeaderProps) {
  const { user } = useAuth();
  // Fix: Handle division by zero when dailyTarget is 0
  const progressPercent = dailyTarget > 0
    ? Math.min((consultationsToday / dailyTarget) * 100, 100)
    : 0;
  const isGoalMet = dailyTarget > 0 && consultationsToday >= dailyTarget;
  // Fix: Ensure remaining is not negative
  const remaining = Math.max(0, dailyTarget - consultationsToday);

  return (
    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      {/* Left: Greeting + Date */}
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          {/* Fix: Add fallback for empty user name */}
          {getGreeting()}, {user?.full_name || user?.username || "Officer"}!
          {isGoalMet && <Sparkles className="h-5 w-5 text-amber-500" />}
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          {new Date().toLocaleDateString("vi-VN", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      {/* Right: Goal Progress + Actions */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Goal Progress - Compact */}
        <div className="flex items-center gap-3 bg-muted/50 rounded-lg px-4 py-2 border">
          <Target className={cn(
            "h-4 w-4",
            isGoalMet ? "text-green-500" : "text-primary"
          )} />
          <div className="min-w-[100px]">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-muted-foreground">Hôm nay</span>
              <span className={cn(
                "font-semibold",
                isGoalMet ? "text-green-600" : "text-foreground"
              )}>
                {consultationsToday}/{dailyTarget}
              </span>
            </div>
            <Progress 
              value={progressPercent} 
              className={cn(
                "h-1.5",
                isGoalMet && "[&>div]:bg-green-500"
              )}
            />
          </div>
          {isGoalMet ? (
            <Badge className="bg-green-500 text-xs">Done!</Badge>
          ) : remaining <= 3 ? (
            <Badge variant="outline" className="text-xs">
              còn {remaining}
            </Badge>
          ) : null}
        </div>

        {/* Notifications */}
        <Button variant="outline" size="icon" className="h-9 w-9 relative">
          <Bell className="h-4 w-4" />
          <span className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-red-500 text-[10px] font-medium text-white flex items-center justify-center">
            3
          </span>
        </Button>

        {/* Quick Actions */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-4 w-4" />
              Thao tác
              <ChevronDown className="h-3 w-3 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onClick={() => onQuickAction?.("new_lead")}>
              <Plus className="h-4 w-4 mr-2" />
              Thêm Lead
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onQuickAction?.("log_call")}>
              <Phone className="h-4 w-4 mr-2" />
              Ghi cuộc gọi
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onQuickAction?.("schedule")}>
              <Calendar className="h-4 w-4 mr-2" />
              Đặt lịch hẹn
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
