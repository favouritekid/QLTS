// src/components/officer/dashboard/WeeklyLeaderboard.tsx
/**
 * Weekly Leaderboard Component
 * Shows top officers by consultations for gamification
 *
 * Now supports date range and scope filtering to align with dashboard filters.
 */

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Crown,
  Medal,
  TrendingUp,
  TrendingDown,
  Minus,
  Trophy
} from "lucide-react";
import { cn } from "@/lib/utils";
import { format, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { useDashboardDate } from "@/contexts/DashboardDateContext";
import { useWeeklyLeaderboard } from "@/hooks/officer/useWeeklyLeaderboard";

interface WeeklyLeaderboardProps {
  /** Dashboard scope (affects unit filtering) */
  scope?: "personal" | "team" | "organization";
  /** Selected unit ID (for organization scope) */
  unitId?: number | null;
  /** Drill-down target officer (highlights this officer in leaderboard) */
  officerId?: number | null;
}

const getRankIcon = (rank: number) => {
  switch (rank) {
    case 1:
      return <Crown className="h-4 w-4 text-yellow-500" />;
    case 2:
      return <Medal className="h-4 w-4 text-border" />;
    case 3:
      return <Medal className="h-4 w-4 text-amber-600" />;
    default:
      return <span className="text-xs font-medium text-muted-foreground w-4 text-center">{rank}</span>;
  }
};

// ✅ PHASE 6: Rank trend indicator
const getRankTrendIndicator = (rankChange: number | null | undefined) => {
  if (rankChange === null || rankChange === undefined) {
    return (
      <span className="text-[10px] text-info-500 font-medium">MỚI</span>
    );
  }
  if (rankChange > 0) {
    return (
      <div className="flex items-center text-success-600 dark:text-success-500">
        <TrendingUp className="h-3 w-3" />
        <span className="text-[10px] font-medium ml-0.5">+{rankChange}</span>
      </div>
    );
  }
  if (rankChange < 0) {
    return (
      <div className="flex items-center text-error-500 dark:text-error-500">
        <TrendingDown className="h-3 w-3" />
        <span className="text-[10px] font-medium ml-0.5">{rankChange}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center text-muted-foreground">
      <Minus className="h-3 w-3" />
    </div>
  );
};

const getRankBg = (rank: number, isHighlighted: boolean) => {
  if (isHighlighted) return "bg-primary/10 border-primary/30";
  switch (rank) {
    case 1:
      return "bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800";
    case 2:
      return "bg-border/40 dark:bg-border/20 border-border dark:border-border";
    case 3:
      return "bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800";
    default:
      return "bg-muted/50 border-transparent";
  }
};

export function WeeklyLeaderboard({ scope, unitId, officerId }: WeeklyLeaderboardProps) {
  const { startDate, endDate } = useDashboardDate();
  const { data, isLoading, error } = useWeeklyLeaderboard({
    startDate,
    endDate,
    scope,
    unitId,
    officerId,
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  // Fix: Show error state instead of silent fail
  if (error) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <Trophy className="h-5 w-5 text-amber-500" />
            Bảng xếp hạng tuần
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-6 text-muted-foreground text-sm">
            Không thể tải bảng xếp hạng
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return null;
  }

  // Format date range for display (YYYY-MM-DD → dd/MM/yyyy vi-VN)
  const formatDateRange = () => {
    try {
      const startFormatted = format(parseISO(data.week_start), "dd/MM/yyyy", { locale: vi });
      if (data.week_end && data.week_start !== data.week_end) {
        const endFormatted = format(parseISO(data.week_end), "dd/MM/yyyy", { locale: vi });
        return `${startFormatted} → ${endFormatted}`;
      }
      return startFormatted;
    } catch {
      // Graceful fallback if parse fails
      return data.week_end ? `${data.week_start} → ${data.week_end}` : data.week_start;
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <Trophy className="h-5 w-5 text-amber-500" />
              Bảng xếp hạng
            </CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              {formatDateRange()}
            </p>
          </div>
          <Badge variant="outline" className="text-xs">
            {data.current_user_rank != null
              ? `#${data.current_user_rank}/${data.total_officers}`
              : `${data.total_officers} officers`}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.leaderboard.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground text-sm">
            Chưa có dữ liệu trong kỳ
          </div>
        ) : (
          data.leaderboard.map((entry, index) => {
            const showSeparator = entry.rank > 5 && index === data.leaderboard.length - 1;
            
            return (
              <div key={entry.user_id}>
                {showSeparator && (
                  <div className="border-t border-dashed my-2" />
                )}
                <div
                  className={cn(
                    "flex items-center gap-3 p-2.5 rounded-lg border transition-colors",
                    getRankBg(entry.rank, entry.is_current_user || !!entry.is_focus_officer)
                  )}
                >
                  {/* Rank */}
                  <div className="w-6 flex items-center justify-center">
                    {getRankIcon(entry.rank)}
                  </div>

                  {/* Avatar placeholder - Fix: Handle empty full_name */}
                  <div className={cn(
                    "h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium",
                    (entry.is_current_user || entry.is_focus_officer)
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  )}>
                    {(entry.full_name || entry.username || "??").slice(0, 2).toUpperCase()}
                  </div>

                  {/* Name */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-sm font-medium truncate",
                        (entry.is_current_user || entry.is_focus_officer) && "text-primary"
                      )}>
                        {entry.full_name}
                      </span>
                      {entry.is_current_user && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1">
                          Bạn
                        </Badge>
                      )}
                      {entry.is_focus_officer && !entry.is_current_user && (
                        <Badge variant="outline" className="text-[10px] h-4 px-1">
                          Đang xem
                        </Badge>
                      )}
                    </div>
                  </div>
                  
                  {/* ✅ PHASE 6: Rank Trend Indicator */}
                  <div className="flex items-center">
                    {getRankTrendIndicator(entry.rank_change)}
                  </div>
                  
                  {/* Stats */}
                  <div className="text-right">
                    <div className="text-sm font-semibold">
                      {entry.consultations}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      tư vấn
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
