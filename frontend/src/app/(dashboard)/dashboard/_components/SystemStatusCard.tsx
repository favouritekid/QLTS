// src/app/(dashboard)/dashboard/_components/SystemStatusCard.tsx
/**
 * System Status Card - Shows real-time system health
 *
 * ✅ FIX: Replaces static "Hoạt động" badges with real monitoring data
 * Uses the same API as /admin/monitoring but in a compact card format
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Server,
  Database,
  Activity,
  Workflow,
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  XCircle,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api/client";

interface SystemOverview {
  timestamp: string;
  overall_status: "healthy" | "degraded";
  api: { status: string };
  database: { status: string; error?: string };
  redis: { status: string; connected_clients?: number; used_memory?: string; error?: string };
  celery: { status: string; workers?: number; active_tasks?: number; error?: string };
}

const SERVICE_CONFIG = [
  { key: "api", label: "Máy chủ API", icon: Server },
  { key: "database", label: "Cơ sở dữ liệu", icon: Database },
  { key: "redis", label: "Bộ nhớ đệm", icon: Activity },
  { key: "celery", label: "Background Jobs", icon: Workflow },
] as const;

function getStatusBadge(status: string) {
  switch (status) {
    case "ok":
    case "healthy":
    case "connected":
    case "online":
      return (
        <Badge variant="default" className="bg-success-500 hover:bg-success-600 text-white gap-1">
          <CheckCircle className="h-3 w-3" />
          OK
        </Badge>
      );
    case "degraded":
    case "no_workers":
      return (
        <Badge variant="secondary" className="bg-warning-500 hover:bg-warning-600 text-white gap-1">
          <AlertTriangle className="h-3 w-3" />
          Cảnh báo
        </Badge>
      );
    case "error":
    case "unknown":
      return (
        <Badge variant="destructive" className="gap-1">
          <XCircle className="h-3 w-3" />
          Lỗi
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" className="gap-1">
          <Activity className="h-3 w-3" />
          {status}
        </Badge>
      );
  }
}

export function SystemStatusCard() {
  const {
    data: overview,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery<SystemOverview>({
    queryKey: ["system-overview-dashboard"],
    queryFn: async () => {
      const response = await api.get("/api/monitoring/system/overview");
      return response.data;
    },
    staleTime: 30000, // 30 seconds
    refetchInterval: 60000, // Auto-refresh every minute
    retry: 1,
  });

  // Derive overall status description
  const overallDescription = overview
    ? overview.overall_status === "healthy"
      ? "Tất cả hệ thống hoạt động bình thường"
      : "Một số dịch vụ đang gặp sự cố"
    : "Đang kiểm tra trạng thái...";

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Trạng Thái Hệ Thống</CardTitle>
            <CardDescription>{overallDescription}</CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => refetch()}
            disabled={isFetching}
            className="h-8 w-8"
            aria-label="Làm mới trạng thái"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {isLoading ? (
          <>
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center justify-between">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-5 w-16" />
              </div>
            ))}
          </>
        ) : error ? (
          <div className="text-center py-4">
            <XCircle className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              Không thể kết nối với hệ thống giám sát
            </p>
            <Button
              variant="link"
              size="sm"
              onClick={() => refetch()}
              className="mt-2"
            >
              Thử lại
            </Button>
          </div>
        ) : (
          <>
            {SERVICE_CONFIG.map(({ key, label, icon: Icon }) => {
              const service = overview?.[key as keyof SystemOverview];
              const status =
                typeof service === "object" && service !== null && "status" in service
                  ? (service as { status: string }).status
                  : "unknown";

              return (
                <div
                  key={key}
                  className="flex items-center justify-between text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">{label}</span>
                  </div>
                  {getStatusBadge(status)}
                </div>
              );
            })}

            {/* Link to full monitoring page */}
            <div className="pt-2 border-t mt-3">
              <Link href="/admin/monitoring">
                <Button variant="ghost" size="sm" className="w-full justify-center gap-2">
                  Xem chi tiết
                  <ExternalLink className="h-3 w-3" />
                </Button>
              </Link>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
