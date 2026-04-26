"use client";

/**
 * Phase B11: Delivery Ops Table — admin read-only view of delivery records.
 *
 * Features: filter bar (event, channel, status, date range), data table, pagination.
 */
import { useState } from "react";
import {
  AlertCircle,
  Bot,
  Filter,
  Loader2,
  Mail,
  MessageSquare,
  Monitor,
  Search,
  Smartphone,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/table/Pagination";
import {
  useNotificationDeliveries,
  useDeliveryStats,
  useReplayDelivery,
  type UseNotificationDeliveriesParams,
} from "@/hooks/useNotificationDeliveries";
import type {
  NotificationDeliveriesPage,
  NotificationDelivery,
} from "@/types/api.types";

// ============================================
// STATUS + CHANNEL DISPLAY HELPERS
// ============================================

const STATUS_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  queued: { label: "Đang chờ", variant: "secondary" },
  sent: { label: "Đã gửi", variant: "default" },
  delivered: { label: "Đã nhận", variant: "default" },
  read: { label: "Đã đọc", variant: "default" },
  failed: { label: "Thất bại", variant: "destructive" },
  dead_lettered: { label: "Dead Letter", variant: "destructive" },
  skipped: { label: "Bỏ qua", variant: "outline" },
};

const REPLAYABLE_STATUSES = new Set(["failed", "dead_lettered", "skipped"]);

const CHANNEL_ICON: Record<string, React.ReactNode> = {
  browser: <Monitor className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  zalo: <MessageSquare className="h-4 w-4" />,
  zalo_bot: <Bot className="h-4 w-4" />,
  sms: <Smartphone className="h-4 w-4" />,
};

// v5 Step 24: only override the display string for zalo_bot (raw value
// "zalo_bot" is technical, "Zalo Bot" is what operators read in tickets).
// Other channels keep their lowercase raw value so the existing test
// surface stays stable.
const CHANNEL_LABEL: Record<string, string> = {
  zalo_bot: "Zalo Bot",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ============================================
// COMPONENT
// ============================================

interface DeliveryOpsTableProps {
  initialData?: NotificationDeliveriesPage;
}

export default function DeliveryOpsTable({ initialData }: DeliveryOpsTableProps) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [eventFilter, setEventFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const params: UseNotificationDeliveriesParams = {
    page,
    page_size: pageSize,
    event: eventFilter || undefined,
    channel: channelFilter !== "all" ? channelFilter : undefined,
    status: statusFilter !== "all" ? statusFilter : undefined,
  };

  const { data, isLoading, error } = useNotificationDeliveries(params, {
    initialData,
  });
  const { data: stats } = useDeliveryStats();
  const replayMutation = useReplayDelivery();

  const deliveries = data?.deliveries ?? [];
  const total = data?.total_count ?? 0;

  const handleReplay = (deliveryId: number) => {
    replayMutation.mutate(deliveryId);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Delivery Tracking
          </h1>
          <p className="text-muted-foreground">
            Theo dõi trạng thái gửi thông báo theo kênh
          </p>
        </div>
      </div>

      {/* Stats Cards (C2: real data from API) */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Tổng deliveries</CardDescription>
            <CardTitle className="text-3xl">{stats?.total ?? total}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Thành công</CardDescription>
            <CardTitle className="text-3xl text-green-600">
              {(stats?.by_status?.sent ?? 0) + (stats?.by_status?.delivered ?? 0) + (stats?.by_status?.read ?? 0)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Thất bại</CardDescription>
            <CardTitle className="text-3xl text-red-600">
              {(stats?.by_status?.failed ?? 0) + (stats?.by_status?.dead_lettered ?? 0)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Success Rate</CardDescription>
            <CardTitle className="text-3xl">
              {stats?.success_rate != null ? `${stats.success_rate}%` : "—"}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Filter className="h-5 w-5" />
            Bộ lọc
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Lọc theo event..."
                value={eventFilter}
                onChange={(e) => {
                  setEventFilter(e.target.value);
                  setPage(1);
                }}
                className="pl-10"
              />
            </div>

            <Select
              value={channelFilter}
              onValueChange={(v) => {
                setChannelFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="Kênh" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả kênh</SelectItem>
                <SelectItem value="browser">Browser</SelectItem>
                <SelectItem value="email">Email</SelectItem>
                <SelectItem value="zalo">Zalo</SelectItem>
                <SelectItem value="zalo_bot">Zalo Bot</SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
              </SelectContent>
            </Select>

            <Select
              value={statusFilter}
              onValueChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="Trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả</SelectItem>
                <SelectItem value="queued">Đang chờ</SelectItem>
                <SelectItem value="sent">Đã gửi</SelectItem>
                <SelectItem value="delivered">Đã nhận</SelectItem>
                <SelectItem value="failed">Thất bại</SelectItem>
                <SelectItem value="dead_lettered">Dead Letter</SelectItem>
                <SelectItem value="skipped">Bỏ qua</SelectItem>
              </SelectContent>
            </Select>

            {(eventFilter || channelFilter !== "all" || statusFilter !== "all") && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setEventFilter("");
                  setChannelFilter("all");
                  setStatusFilter("all");
                  setPage(1);
                }}
              >
                Xóa lọc
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Error */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-3 py-4">
            <AlertCircle className="h-5 w-5 text-destructive" />
            <p className="text-sm text-destructive">
              Không thể tải dữ liệu delivery: {error.message}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && !error && deliveries.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Mail className="h-12 w-12 text-muted-foreground/50" />
            <p className="mt-4 text-lg font-medium">Chưa có delivery record</p>
            <p className="text-sm text-muted-foreground">
              Các delivery record sẽ xuất hiện khi hệ thống gửi thông báo
            </p>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      {!isLoading && deliveries.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[160px]">Thời gian</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead className="w-[100px]">Kênh</TableHead>
                  <TableHead>Người nhận</TableHead>
                  <TableHead className="w-[110px]">Trạng thái</TableHead>
                  <TableHead>Lỗi</TableHead>
                  <TableHead className="w-[80px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {deliveries.map((d: NotificationDelivery) => {
                  const sc = STATUS_CONFIG[d.status] ?? STATUS_CONFIG.queued;
                  return (
                    <TableRow key={d.id}>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(d.created_at)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {d.event}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          {CHANNEL_ICON[d.channel]}
                          <span className="text-sm">
                            {CHANNEL_LABEL[d.channel] ?? d.channel}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm">
                        {d.recipient_kind === "internal"
                          ? `User #${d.user_id}`
                          : d.destination ?? "—"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={sc.variant}>{sc.label}</Badge>
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                        {d.error_reason ?? "—"}
                      </TableCell>
                      <TableCell>
                        {REPLAYABLE_STATUSES.has(d.status) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => handleReplay(d.id)}
                            disabled={replayMutation.isPending}
                          >
                            Replay
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>

          {/* Pagination */}
          <div className="border-t px-4 py-3">
            <Pagination
              page={page}
              pageSize={pageSize}
              total={total}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              showPageSizeSelector
              pageSizeOptions={[20, 50, 100]}
              isLoading={isLoading}
            />
          </div>
        </Card>
      )}
    </div>
  );
}
