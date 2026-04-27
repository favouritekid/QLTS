"use client";

/**
 * D5: Per-channel health cards — breaker state, quota, failure rate.
 */
import { AlertTriangle, CheckCircle, XCircle, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  useNotificationHealth,
  useResetCircuitBreaker,
  type ChannelHealthItem,
} from "@/hooks/useNotificationDeliveries";

const FAIL_RATE_WARN_THRESHOLD = 0.1;

function BreakerBadge({ state }: { state: string }) {
  switch (state) {
    case "closed":
      return <Badge variant="default" className="gap-1"><CheckCircle className="h-3 w-3" /> Hoạt động</Badge>;
    case "half_open":
      return <Badge variant="secondary" className="gap-1"><AlertTriangle className="h-3 w-3" /> Bán mở</Badge>;
    case "open":
      return <Badge variant="destructive" className="gap-1"><XCircle className="h-3 w-3" /> Ngắt mạch</Badge>;
    default:
      return <Badge variant="outline">{state}</Badge>;
  }
}

function ChannelCard({ ch }: { ch: ChannelHealthItem }) {
  const resetMutation = useResetCircuitBreaker();
  const quotaPct = ch.quota_limit != null && ch.quota_limit > 0
    ? Math.round((ch.quota_used ?? 0) / ch.quota_limit * 100)
    : null; // H4: null = no quota configured or zero limit

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium uppercase">{ch.channel}</CardTitle>
          <BreakerBadge state={ch.breaker_state} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Quota */}
        {ch.quota_limit != null && ch.quota_used != null && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Hạn mức</span>
              <span>{ch.quota_used}/{ch.quota_limit} ({quotaPct != null ? `${quotaPct}%` : "N/A"})</span>
            </div>
            <Progress value={quotaPct ?? 0} className="h-2" />
          </div>
        )}

        {/* Failure rate */}
        {ch.failure_rate_24h != null && (
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Tỷ lệ lỗi (24h)</span>
            <span className={ch.failure_rate_24h > FAIL_RATE_WARN_THRESHOLD ? "text-red-600 font-medium" : ""}>
              {(ch.failure_rate_24h * 100).toFixed(1)}%
            </span>
          </div>
        )}

        {/* Reset button for open breakers */}
        {ch.breaker_state === "open" && (
          <Button
            size="sm"
            variant="outline"
            className="w-full"
            disabled={resetMutation.isPending}
            onClick={() => resetMutation.mutate(ch.channel)}
          >
            <RotateCcw className="mr-1 h-3 w-3" />
            Reset ngắt mạch
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function ChannelHealthPanel() {
  const { data, isLoading } = useNotificationHealth();

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}><CardContent className="h-32 animate-pulse" /></Card>
        ))}
      </div>
    );
  }

  const channels = data?.channels ?? [];

  return (
    <div className="space-y-4">
      {/* Summary row */}
      <div className="grid gap-4 md:grid-cols-3" data-testid="status-cards">
        <Card data-testid="card-queued">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Đang chờ</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{data?.total_queued ?? 0}</p>
          </CardContent>
        </Card>
        <Card data-testid="card-fail-rate">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Tỷ lệ lỗi (30 phút)</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              {data?.failure_rate_30m != null ? `${(data.failure_rate_30m * 100).toFixed(1)}%` : "—"}
            </p>
          </CardContent>
        </Card>
        <Card data-testid="card-active-alerts">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">Cảnh báo đang hoạt động</CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${(data?.alerts_active ?? 0) > 0 ? "text-red-600" : ""}`}>
              {data?.alerts_active ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Per-channel cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {channels.map((ch) => (
          <ChannelCard key={ch.channel} ch={ch} />
        ))}
      </div>
    </div>
  );
}
