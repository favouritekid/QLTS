// src/components/officer/WorkloadCard.tsx
/**
 * Consolidated Workload Widget
 * Shows capacity donut, workload stats, and availability toggle in one card
 * Following shadcn/ui design standards
 */
"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Briefcase, Users, CircleDot } from "lucide-react";
import { api } from "@/lib/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface StatusOverview {
  current_workload: number;
  max_capacity: number;
  utilization: number;
  availability_status: "available" | "busy" | "offline";
}

interface WorkloadCardProps {
  statusOverview: StatusOverview;
}

async function updateAvailability(status: string) {
  const response = await api.post("/api/officer/availability", {
    availability_status: status,
  });
  return response.data;
}

export function WorkloadCard({ statusOverview }: WorkloadCardProps) {
  const queryClient = useQueryClient();
  // Derive isAvailable directly from props - avoids unnecessary sync with useEffect
  // Local state only tracks optimistic update during mutation
  const [optimisticAvailable, setOptimisticAvailable] = useState<boolean | null>(null);
  
  // Use optimistic state during mutation, otherwise derive from props
  const isAvailable = optimisticAvailable ?? (statusOverview.availability_status === "available");

  const mutation = useMutation({
    mutationFn: updateAvailability,
    onSuccess: (data) => {
      // Clear optimistic state - let props drive the UI
      setOptimisticAvailable(null);
      queryClient.invalidateQueries({ queryKey: ["officer", "dashboard"] });
      toast.success(`Đã cập nhật: ${data.availability_status === "available" ? "Sẵn sàng" : "Bận"}`);
    },
    onError: () => {
      toast.error("Không thể cập nhật trạng thái");
      // Revert optimistic state
      setOptimisticAvailable(null);
    },
  });

  const handleAvailabilityToggle = (checked: boolean) => {
    // Set optimistic state for immediate UI feedback
    setOptimisticAvailable(checked);
    mutation.mutate(checked ? "available" : "busy");
  };

  const utilizationPercentage = statusOverview.utilization ?? 0;
  // Fix: Clamp remaining capacity to 0 to avoid showing negative values
  const remainingCapacity = Math.max(0, (statusOverview.max_capacity ?? 0) - (statusOverview.current_workload ?? 0));

  // Donut chart values
  const circumference = 2 * Math.PI * 40;
  const strokeDashoffset = circumference - (utilizationPercentage / 100) * circumference;

  const utilizationColor = 
    utilizationPercentage >= 90 ? "text-red-500" : 
    utilizationPercentage >= 70 ? "text-amber-500" : 
    "text-green-500";

  const strokeColor = 
    utilizationPercentage >= 90 ? "stroke-red-500" : 
    utilizationPercentage >= 70 ? "stroke-amber-500" : 
    "stroke-primary";

  return (
    <Card className="border bg-card">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <Briefcase className="h-4 w-4" />
            Khối lượng công việc
          </CardTitle>
          <Badge 
            variant={isAvailable ? "default" : "secondary"}
            className={cn(
              "text-xs",
              isAvailable && "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
            )}
          >
            <CircleDot className="h-3 w-3 mr-1" />
            {isAvailable ? "Sẵn sàng" : "Bận"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Donut Chart + Stats */}
        <div className="flex items-center gap-6">
          {/* Donut Chart */}
          <div className="relative">
            <svg width="100" height="100" className="-rotate-90">
              {/* Background circle */}
              <circle
                cx="50"
                cy="50"
                r="40"
                fill="none"
                strokeWidth="10"
                className="stroke-muted"
              />
              {/* Progress circle */}
              <circle
                cx="50"
                cy="50"
                r="40"
                fill="none"
                strokeWidth="10"
                strokeLinecap="round"
                className={cn("transition-all duration-500", strokeColor)}
                style={{
                  strokeDasharray: circumference,
                  strokeDashoffset: strokeDashoffset,
                }}
              />
            </svg>
            {/* Center text */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className={cn("text-2xl font-bold", utilizationColor)}>
                {utilizationPercentage.toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Stats */}
          <div className="flex-1 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Đang xử lý</span>
              <span className="text-lg font-semibold">
                {statusOverview.current_workload}/{statusOverview.max_capacity}
              </span>
            </div>
            <Progress value={utilizationPercentage} className="h-2" />
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground flex items-center gap-1">
                <Users className="h-3.5 w-3.5" />
                Còn trống
              </span>
              <span className={cn(
                "font-medium",
                remainingCapacity <= 5 ? "text-amber-600" : "text-green-600"
              )}>
                {remainingCapacity} leads
              </span>
            </div>
          </div>
        </div>

        {/* Availability Toggle */}
        <div className="pt-3 border-t flex items-center justify-between">
          <div className="text-sm">
            <p className="font-medium">Nhận lead mới</p>
            <p className="text-xs text-muted-foreground">
              {isAvailable ? "Đang nhận leads tự động" : "Tạm dừng nhận leads"}
            </p>
          </div>
          <Switch
            checked={isAvailable}
            onCheckedChange={handleAvailabilityToggle}
            disabled={mutation.isPending}
          />
        </div>
      </CardContent>
    </Card>
  );
}
