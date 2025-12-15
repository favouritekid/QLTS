// src/components/officer/dashboard/SmartHeader.tsx
/**
 * Smart Header for Officer Dashboard
 * Shows personalized greeting, goal progress, availability toggle, and quick actions
 */

"use client";

import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
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
  FileText,
  ChevronDown,
  Sparkles,
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
  const progressPercent = Math.min((consultationsToday / dailyTarget) * 100, 100);
  const isGoalMet = consultationsToday >= dailyTarget;

  return (
    <div className="bg-gradient-to-r from-primary/10 via-primary/5 to-transparent rounded-xl p-5 border">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Left: Greeting */}
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              {getGreeting()}, {user?.full_name || user?.username}!
              {isGoalMet && <Sparkles className="h-5 w-5 text-yellow-500" />}
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {new Date().toLocaleDateString("vi-VN", {
                weekday: "long",
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </p>
          </div>
        </div>

        {/* Right: Goal + Actions */}
        <div className="flex items-center gap-4 flex-wrap">
          {/* Goal Progress */}
          <div className="flex items-center gap-3 bg-background/80 rounded-lg px-4 py-2.5 border">
            <Target className={cn(
              "h-5 w-5",
              isGoalMet ? "text-green-500" : "text-orange-500"
            )} />
            <div className="min-w-[120px]">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground">Mục tiêu hôm nay</span>
                <span className={cn(
                  "font-medium",
                  isGoalMet && "text-green-600"
                )}>
                  {consultationsToday}/{dailyTarget}
                </span>
              </div>
              <Progress 
                value={progressPercent} 
                className={cn(
                  "h-2",
                  isGoalMet && "[&>div]:bg-green-500"
                )}
              />
            </div>
            {isGoalMet && (
              <Badge variant="default" className="bg-green-500 text-xs">
                Hoàn thành!
              </Badge>
            )}
          </div>

          {/* Availability Toggle */}
          <div className="flex items-center gap-2 bg-background/80 rounded-lg px-4 py-2.5 border">
            <span className="text-sm text-muted-foreground">Trạng thái:</span>
            <Switch
              checked={isAvailable}
              onCheckedChange={onToggleAvailability}
              className="data-[state=checked]:bg-green-500"
            />
            <Badge 
              variant={isAvailable ? "default" : "secondary"}
              className={cn(
                "text-xs",
                isAvailable ? "bg-green-500" : ""
              )}
            >
              {isAvailable ? "Sẵn sàng" : "Bận"}
            </Badge>
          </div>

          {/* Quick Actions */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="default" size="sm" className="gap-2">
                <Plus className="h-4 w-4" />
                Thao tác nhanh
                <ChevronDown className="h-3 w-3 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem onClick={() => onQuickAction?.("new_lead")}>
                <Plus className="h-4 w-4 mr-2" />
                Thêm Lead mới
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => onQuickAction?.("log_call")}>
                <Phone className="h-4 w-4 mr-2" />
                Ghi nhận cuộc gọi
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onQuickAction?.("schedule")}>
                <Calendar className="h-4 w-4 mr-2" />
                Đặt lịch hẹn
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
}
