// src/components/officer/WorkloadCard.tsx
"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { api } from "@/lib/api/client";
import { useToast } from "@/components/ui/use-toast";

interface StatusOverview {
  workload: number;
  max_capacity: number;
  utilization: number;
  availability_status: "available" | "busy" | "offline";
  last_assigned_at: string | null;
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
  const { toast } = useToast();
  const [isAvailable, setIsAvailable] = useState(
    statusOverview.availability_status === "available"
  );

  const mutation = useMutation({
    mutationFn: updateAvailability,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["officer", "stats"] });
      toast({
        title: "Availability Updated",
        description: `You are now ${data.availability_status}`,
      });
    },
    onError: (error: unknown) => {
      const errorMessage =
        error &&
        typeof error === "object" &&
        "response" in error &&
        error.response &&
        typeof error.response === "object" &&
        "data" in error.response &&
        error.response.data &&
        typeof error.response.data === "object" &&
        "detail" in error.response.data
          ? String(error.response.data.detail)
          : "Failed to update availability";

      toast({
        title: "Error",
        description: errorMessage,
        variant: "destructive",
      });
      // Revert toggle on error
      setIsAvailable(!isAvailable);
    },
  });

  const handleAvailabilityToggle = (checked: boolean) => {
    setIsAvailable(checked);
    const newStatus = checked ? "available" : "busy";
    mutation.mutate(newStatus);
  };

  const utilizationPercentage = statusOverview.utilization;
  const utilizationColor =
    utilizationPercentage >= 90
      ? "text-red-600"
      : utilizationPercentage >= 70
      ? "text-yellow-600"
      : "text-green-600";

  const statusBadge = {
    available: { variant: "default" as const, icon: CheckCircle2, color: "text-green-600" },
    busy: { variant: "secondary" as const, icon: Clock, color: "text-yellow-600" },
    offline: { variant: "destructive" as const, icon: AlertCircle, color: "text-red-600" },
  };

  const currentBadge = statusBadge[statusOverview.availability_status];
  const StatusIcon = currentBadge.icon;

  // Format relative time for last assignment
  const getRelativeTime = (timestamp: string | null) => {
    if (!timestamp) return "No assignments yet";

    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? "s" : ""} ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? "s" : ""} ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays !== 1 ? "s" : ""} ago`;
  };

  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
      {/* Workload Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Current Workload</CardDescription>
          <CardTitle className="text-4xl">
            {statusOverview.workload}
            <span className="text-lg text-muted-foreground ml-2">
              / {statusOverview.max_capacity}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Progress value={utilizationPercentage} className="h-2" />
          <p className={`text-xs mt-2 ${utilizationColor} font-medium`}>
            {utilizationPercentage.toFixed(1)}% utilized
          </p>
        </CardContent>
      </Card>

      {/* Availability Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Availability Status</CardDescription>
          <CardTitle className="flex items-center gap-2">
            <StatusIcon className={`h-5 w-5 ${currentBadge.color}`} />
            <Badge variant={currentBadge.variant}>
              {statusOverview.availability_status.toUpperCase()}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center space-x-2 mt-2">
            <Switch
              id="availability"
              checked={isAvailable}
              onCheckedChange={handleAvailabilityToggle}
              disabled={mutation.isPending}
            />
            <Label htmlFor="availability" className="cursor-pointer">
              {isAvailable ? "Accepting new leads" : "Not accepting leads"}
            </Label>
          </div>
        </CardContent>
      </Card>

      {/* Capacity Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Remaining Capacity</CardDescription>
          <CardTitle className="text-4xl">
            {statusOverview.max_capacity - statusOverview.workload}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            leads before reaching max capacity
          </p>
        </CardContent>
      </Card>

      {/* Last Assigned Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Last Assignment</CardDescription>
          <CardTitle className="text-lg">
            {statusOverview.last_assigned_at
              ? new Date(statusOverview.last_assigned_at).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "Never"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            {getRelativeTime(statusOverview.last_assigned_at)}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
