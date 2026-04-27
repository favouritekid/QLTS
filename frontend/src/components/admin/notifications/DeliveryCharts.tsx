"use client";

/**
 * D5: Time series charts for delivery monitoring.
 * Line chart for volume trend, stacked bar for status breakdown.
 */
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useDeliveryTimeSeries,
  type TimeSeriesBucket,
} from "@/hooks/useNotificationDeliveries";

function formatBucket(bucket: string): string {
  const d = new Date(bucket);
  if (isNaN(d.getTime())) return bucket;
  return d.toLocaleString("vi-VN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function DeliveryCharts() {
  const { data, isLoading } = useDeliveryTimeSeries({ interval: "hour" });

  const buckets: TimeSeriesBucket[] = data?.buckets ?? [];

  const chartData = buckets.map((b) => ({
    ...b,
    label: formatBucket(b.bucket),
    success: b.sent,
  }));

  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>Xu hướng gửi thông báo</CardTitle></CardHeader>
        <CardContent className="h-64 flex items-center justify-center text-muted-foreground">
          Đang tải...
        </CardContent>
      </Card>
    );
  }

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Xu hướng gửi thông báo</CardTitle></CardHeader>
        <CardContent className="h-64 flex items-center justify-center text-muted-foreground">
          Chưa có dữ liệu
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Volume trend */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Volume theo giờ</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="total" stroke="#6366f1" name="Tổng" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="success" stroke="#22c55e" name="Thành công" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="failed" stroke="#ef4444" name="Thất bại" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Status breakdown */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Phân loại theo trạng thái</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="success" stackId="a" fill="#22c55e" name="Đã gửi" />
              <Bar dataKey="failed" stackId="a" fill="#ef4444" name="Thất bại" />
              <Bar dataKey="queued" stackId="a" fill="#f59e0b" name="Đang chờ" />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
