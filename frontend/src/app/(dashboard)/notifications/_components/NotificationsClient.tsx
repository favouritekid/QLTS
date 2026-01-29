"use client";

import { useState } from "react";
import { Bell, Check, CheckCheck, Trash2, X, LayoutList, LayoutGrid, Search } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/common/EmptyState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  useNotifications,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
  useBulkDeleteNotifications,
} from "@/hooks/useNotifications";
import type { Notification, NotificationsPage } from "@/types/api.types";
import { NotificationTable } from "./NotificationTable";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

interface NotificationsClientProps {
  initialData?: NotificationsPage;
}

export function NotificationsClient({ initialData }: NotificationsClientProps) {
  const [currentTab, setCurrentTab] = useState<"all" | "unread">("all");
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useState<"list" | "table">("table");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const pageSize = 20;

  // Fetch based on current tab
  const { data, isLoading } = useNotifications({
    page,
    page_size: pageSize,
    unread_only: currentTab === "unread",
  }, {
    initialData: page === 1 && currentTab === "all" ? initialData : undefined,
  });

  const markAsRead = useMarkAsRead();
  const markAllAsRead = useMarkAllAsRead();
  const deleteNotification = useDeleteNotification();
  const bulkDeleteNotifications = useBulkDeleteNotifications();

  const notifications = data?.notifications || [];
  const unreadCount = data?.unread_count || 0;
  const totalCount = data?.total_count || 0;

  // Filter logic
  const filteredNotifications = notifications.filter((notification) => {
    const searchMatch =
      searchQuery === "" ||
      notification.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      notification.message.toLowerCase().includes(searchQuery.toLowerCase());

    const typeMatch =
      typeFilter === "all" || notification.type === typeFilter;

    return searchMatch && typeMatch;
  });

  // Handle single actions
  const handleMarkAsRead = (notificationId: number) => {
    markAsRead.mutate({ notification_ids: [notificationId] });
  };

  const handleMarkAllAsRead = () => {
    markAllAsRead.mutate();
    toast.success("Đã đánh dấu tất cả là đã đọc");
  };

  const handleDelete = (id: number) => {
    deleteNotification.mutate(id);
    setSelectedIds((prev) => prev.filter((itemId) => itemId !== id));
    toast.success("Đã xóa thông báo");
  };

  // Handle bulk actions
  const handleSelect = (id: number, checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => [...prev, id]);
    } else {
      setSelectedIds((prev) => prev.filter((itemId) => itemId !== id));
    }
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(filteredNotifications.map((n) => n.id));
    } else {
      setSelectedIds([]);
    }
  };

  const handleBulkMarkAsRead = () => {
    if (selectedIds.length === 0) return;
    markAsRead.mutate(
      { notification_ids: selectedIds },
      {
        onSuccess: () => {
          setSelectedIds([]);
          toast.success(`Đã đánh dấu ${selectedIds.length} thông báo là đã đọc`);
        },
      }
    );
  };

  const handleBulkDelete = () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Bạn chắc chắn muốn xóa ${selectedIds.length} thông báo?`)) return;

    // ✅ TECHNICAL DEBT FIX: Use bulk delete API instead of loop
    bulkDeleteNotifications.mutate(
      { notification_ids: selectedIds },
      {
        onSuccess: (data) => {
          setSelectedIds([]);
          toast.success(`Đã xóa ${data.deleted} thông báo`);
        },
        onError: () => {
          toast.error("Có lỗi khi xóa thông báo");
        },
      }
    );
  };

  const getNotificationIcon = (type: Notification["type"]) => {
    const iconClass = "h-5 w-5";
    switch (type) {
      case "success":
        return <Check className={cn(iconClass, "text-success-500")} />;
      case "error":
        return <X className={cn(iconClass, "text-error-500")} />;
      case "warning":
        return <Bell className={cn(iconClass, "text-warning-500")} />;
      case "admin_update":
        return <Bell className={cn(iconClass, "text-info-500")} />;
      default:
        return <Bell className={cn(iconClass, "text-muted-foreground")} />;
    }
  };

  const getNotificationTypeBadge = (type: Notification["type"]) => {
    const variants: Record<
      Notification["type"],
      "default" | "secondary" | "destructive" | "outline"
    > = {
      info: "default",
      success: "default",
      warning: "default",
      error: "destructive",
      admin_update: "secondary",
      system: "outline",
      reminder: "default",
    };

    const labels: Record<Notification["type"], string> = {
      info: "Thông tin",
      success: "Thành công",
      warning: "Cảnh báo",
      error: "Lỗi",
      admin_update: "Admin cập nhật",
      system: "Hệ thống",
      reminder: "Nhắc nhở",
    };

    return (
      <Badge variant={variants[type]} className="text-xs">
        {labels[type]}
      </Badge>
    );
  };

  return (
    <PageContainer maxWidth="md">
      {/* Header */}
      <PageHeader
        title="Thông Báo"
        description="Cập nhật thông báo mới nhất của bạn"
        actions={
          <div className="flex gap-2">
            <ToggleGroup type="single" value={viewMode} onValueChange={(v) => v && setViewMode(v as "list" | "table")}>
              <ToggleGroupItem value="list" aria-label="List view">
                <LayoutList className="h-4 w-4" />
              </ToggleGroupItem>
              <ToggleGroupItem value="table" aria-label="Table view">
                <LayoutGrid className="h-4 w-4" />
              </ToggleGroupItem>
            </ToggleGroup>

            {unreadCount > 0 && (
              <Button onClick={handleMarkAllAsRead} disabled={markAllAsRead.isPending} variant="outline" size="sm">
                <CheckCheck className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Đánh dấu tất cả đã đọc</span>
              </Button>
            )}
          </div>
        }
      />

      {/* Bulk Action Bar */}
      {selectedIds.length > 0 && (
        <div className="sticky top-0 z-10 mb-4 flex items-center justify-between rounded-lg border bg-background p-4 shadow-sm animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm">{selectedIds.length} đã chọn</span>
            <Button variant="ghost" size="sm" onClick={() => setSelectedIds([])}>
              Hủy
            </Button>
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={handleBulkMarkAsRead}>
              <Check className="mr-2 h-4 w-4" />
              Đã đọc
            </Button>
            <Button size="sm" variant="destructive" onClick={handleBulkDelete}>
              <Trash2 className="mr-2 h-4 w-4" />
              Xóa
            </Button>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Tổng Thông Báo</CardDescription>
            <CardTitle className="text-3xl">{totalCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Chưa Đọc</CardDescription>
            <CardTitle className="text-3xl">{unreadCount}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={currentTab} onValueChange={(v) => {
        setCurrentTab(v as typeof currentTab);
        setPage(1); // Reset page on tab change
        setSelectedIds([]); // Clear selection on tab change
      }}>
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="all">
            Tất cả
            {totalCount > 0 && (
              <Badge variant="secondary" className="ml-2">
                {totalCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="unread">
            Chưa đọc
            {unreadCount > 0 && (
              <Badge variant="destructive" className="ml-2">
                {unreadCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Filter Bar */}
        <div className="mt-4 flex flex-col gap-4 sm:flex-row">
            <div className="relative flex-1">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                placeholder="Tìm kiếm thông báo..."
                className="pl-8"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                />
            </div>
            <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger className="w-full sm:w-[180px]">
                <SelectValue placeholder="Loại thông báo" />
                </SelectTrigger>
                <SelectContent>
                <SelectItem value="all">Tất cả loại</SelectItem>
                <SelectItem value="info">Thông tin</SelectItem>
                <SelectItem value="warning">Cảnh báo</SelectItem>
                <SelectItem value="error">Lỗi</SelectItem>
                <SelectItem value="success">Thành công</SelectItem>
                <SelectItem value="reminder">Nhắc nhở</SelectItem>
                </SelectContent>
            </Select>
        </div>

        <TabsContent value={currentTab} className="mt-6 space-y-4">
          {isLoading ? (
            // Loading skeletons
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <Card key={i}>
                  <CardContent className="p-6">
                    <div className="flex items-start gap-4">
                      <Skeleton className="h-10 w-10 rounded-full" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-3/4" />
                        <Skeleton className="h-3 w-full" />
                        <Skeleton className="h-3 w-1/2" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : filteredNotifications.length === 0 ? (
            // Empty state - using standardized EmptyState component
            <Card>
              <CardContent className="p-0">
                <EmptyState
                  icon={<Bell className="h-12 w-12" />}
                  variant={searchQuery || typeFilter !== "all" ? "search" : "default"}
                  title={
                    searchQuery || typeFilter !== "all"
                      ? "Không tìm thấy kết quả"
                      : "Không có thông báo"
                  }
                  description={
                    searchQuery || typeFilter !== "all"
                      ? "Thử thay đổi bộ lọc tìm kiếm của bạn"
                      : currentTab === "unread"
                        ? "Bạn đã đọc hết!"
                        : "Bạn chưa có thông báo nào."
                  }
                  action={
                    (searchQuery || typeFilter !== "all") && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setSearchQuery("");
                          setTypeFilter("all");
                        }}
                      >
                        Xóa bộ lọc
                      </Button>
                    )
                  }
                />
              </CardContent>
            </Card>
          ) : viewMode === "table" ? (
             <NotificationTable
              notifications={filteredNotifications}
              selectedIds={selectedIds}
              onSelect={handleSelect}
              onSelectAll={handleSelectAll}
              onMarkAsRead={handleMarkAsRead}
              onDelete={handleDelete}
              getNotificationIcon={getNotificationIcon}
              getNotificationTypeBadge={getNotificationTypeBadge}
            />
          ) : (
            // List view (Original Card List)
            <div className="space-y-3">
              {filteredNotifications.map((notification) => {
                const notificationContent = (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3
                        className={cn(
                          "text-base leading-tight",
                          !notification.is_read && "font-semibold"
                        )}
                      >
                        {notification.title}
                      </h3>
                      {!notification.is_read && (
                        <div className="bg-primary h-2 w-2 shrink-0 rounded-full" />
                      )}
                    </div>
                    <p className="text-muted-foreground text-sm leading-relaxed">
                      {notification.message}
                    </p>
                  </div>
                );

                return (
                  <div key={notification.id} className="group relative">
                     {/* Checkbox for list view - optional, but good for consistency */}
                     <div className="absolute left-[-2rem] top-6 opacity-0 transition-opacity group-hover:opacity-100 data-[state=checked]:opacity-100">
                        {/* Checkbox implementation in List view can be complex due to layout. Skipping for now as requested Table View for this. */}
                     </div>

                    <Card
                      className={cn(
                        "transition-all hover:shadow-md",
                        !notification.is_read && "border-l-4 border-l-primary bg-muted/30"
                      )}
                    >
                      <CardContent className="p-6">
                        <div className="flex items-start gap-4">
                          {/* Icon */}
                          <div
                            className={cn(
                              "bg-muted flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                              !notification.is_read && "bg-primary/10"
                            )}
                          >
                            {getNotificationIcon(notification.type)}
                          </div>

                          {/* Content */}
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex items-start justify-between gap-4">
                              {notification.link ? (
                                <Link href={notification.link} className="flex-1">
                                  {notificationContent}
                                </Link>
                              ) : (
                                <div className="flex-1">{notificationContent}</div>
                              )}

                              {/* Actions */}
                              <div className="flex shrink-0 gap-1">
                                {!notification.is_read && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => handleMarkAsRead(notification.id)}
                                    title="Đánh dấu đã đọc"
                                    aria-label="Đánh dấu đã đọc"
                                  >
                                    <Check className="h-4 w-4" />
                                  </Button>
                                )}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive"
                                  onClick={() => handleDelete(notification.id)}
                                  title="Xoá"
                                  aria-label="Xóa thông báo"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </div>

                            {/* Metadata */}
                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                              {getNotificationTypeBadge(notification.type)}
                              <span>•</span>
                              <span>
                                {formatDistanceToNow(new Date(notification.created_at), {
                                  addSuffix: true,
                                })}
                              </span>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Pagination */}
      {!isLoading && notifications.length > 0 && totalCount > pageSize && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-t pt-4">
          <p className="text-muted-foreground text-sm text-center sm:text-left">
            Hiển thị {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, totalCount)} / {totalCount}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              Trước
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page * pageSize >= totalCount}
            >
              Sau
            </Button>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
