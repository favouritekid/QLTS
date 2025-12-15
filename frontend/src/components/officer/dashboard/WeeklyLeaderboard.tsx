// src/components/officer/dashboard/WeeklyLeaderboard.tsx
/**
 * Weekly Leaderboard Component
 * Shows top officers by consultations for gamification
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Trophy, Medal, Crown, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";

interface LeaderboardEntry {
  rank: number;
  user_id: number;
  username: string;
  full_name: string;
  consultations: number;
  is_current_user: boolean;
  rank_change?: number | null; // +2 = up 2 spots, -1 = down 1, null = new
}

interface WeeklyLeaderboardData {
  week_start: string;
  total_officers: number;
  current_user_rank: number;
  leaderboard: LeaderboardEntry[];
}

async function fetchLeaderboard(): Promise<WeeklyLeaderboardData> {
  const response = await api.get("/api/officer/leaderboard");
  return response.data;
}

const getRankIcon = (rank: number) => {
  switch (rank) {
    case 1:
      return <Crown className="h-4 w-4 text-yellow-500" />;
    case 2:
      return <Medal className="h-4 w-4 text-gray-400" />;
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
      <span className="text-[10px] text-blue-500 font-medium">MỚI</span>
    );
  }
  if (rankChange > 0) {
    return (
      <div className="flex items-center text-green-600 dark:text-green-400">
        <TrendingUp className="h-3 w-3" />
        <span className="text-[10px] font-medium ml-0.5">+{rankChange}</span>
      </div>
    );
  }
  if (rankChange < 0) {
    return (
      <div className="flex items-center text-red-500 dark:text-red-400">
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

const getRankBg = (rank: number, isCurrentUser: boolean) => {
  if (isCurrentUser) return "bg-primary/10 border-primary/30";
  switch (rank) {
    case 1:
      return "bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800";
    case 2:
      return "bg-gray-50 dark:bg-gray-950/30 border-gray-200 dark:border-gray-700";
    case 3:
      return "bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800";
    default:
      return "bg-muted/50 border-transparent";
  }
};

export function WeeklyLeaderboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["officer", "leaderboard"],
    queryFn: fetchLeaderboard,
    staleTime: 60000, // 1 minute
    refetchInterval: 300000, // 5 minutes
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

  if (error || !data) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <Trophy className="h-5 w-5 text-amber-500" />
            Bảng xếp hạng tuần
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            #{data.current_user_rank}/{data.total_officers}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.leaderboard.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground text-sm">
            Chưa có dữ liệu tuần này
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
                    "flex items-center gap-3 p-2.5 rounded-lg border transition-all",
                    getRankBg(entry.rank, entry.is_current_user)
                  )}
                >
                  {/* Rank */}
                  <div className="w-6 flex items-center justify-center">
                    {getRankIcon(entry.rank)}
                  </div>
                  
                  {/* Avatar placeholder */}
                  <div className={cn(
                    "h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium",
                    entry.is_current_user 
                      ? "bg-primary text-primary-foreground" 
                      : "bg-muted text-muted-foreground"
                  )}>
                    {entry.full_name.slice(0, 2).toUpperCase()}
                  </div>
                  
                  {/* Name */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-sm font-medium truncate",
                        entry.is_current_user && "text-primary"
                      )}>
                        {entry.full_name}
                      </span>
                      {entry.is_current_user && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1">
                          Bạn
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
