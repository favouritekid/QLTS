// src/app/(dashboard)/notifications/page.tsx
"use client";

import { useState } from "react";
import { Bell, Check, CheckCheck, Trash2, X } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  useNotifications,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
} from "@/hooks/useNotifications";
import type { Notification } from "@/types/api.types";

export default function NotificationsPage() {
  const [currentTab, setCurrentTab] = useState<"all" | "unread">("all");
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // Fetch based on current tab
  const { data, isLoading } = useNotifications({
    page,
    page_size: pageSize,
    unread_only: currentTab === "unread",
  });

  const markAsRead = useMarkAsRead();
  const markAllAsRead = useMarkAllAsRead();
  const deleteNotification = useDeleteNotification();

  const notifications = data?.notifications || [];
  const unreadCount = data?.unread_count || 0;
  const totalCount = data?.total_count || 0;

  const handleMarkAsRead = (notificationId: number) => {
    markAsRead.mutate({ notification_ids: [notificationId] });
  };

  const handleMarkAllAsRead = () => {
    markAllAsRead.mutate();
  };

  const handleDelete = (id: number) => {
    deleteNotification.mutate(id);
  };

  const getNotificationIcon = (type: Notification["type"]) => {
    const iconClass = "h-5 w-5";
    switch (type) {
      case "success":
        return <Check className={cn(iconClass, "text-green-500")} />;
      case "error":
        return <X className={cn(iconClass, "text-red-500")} />;
      case "warning":
        return <Bell className={cn(iconClass, "text-yellow-500")} />;
      case "admin_update":
        return <Bell className={cn(iconClass, "text-blue-500")} />;
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
      info: "Info",
      success: "Success",
      warning: "Warning",
      error: "Error",
      admin_update: "Admin Update",
      system: "System",
      reminder: "Reminder",
    };

    return (
      <Badge variant={variants[type]} className="text-xs">
        {labels[type]}
      </Badge>
    );
  };

  return (
    <div className="container mx-auto max-w-4xl py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Notifications</h1>
          <p className="text-muted-foreground mt-1">
            Stay updated with your latest notifications
          </p>
        </div>
        {unreadCount > 0 && (
          <Button onClick={handleMarkAllAsRead} disabled={markAllAsRead.isPending}>
            <CheckCheck className="mr-2 h-4 w-4" />
            Mark all as read
          </Button>
        )}
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Total Notifications</CardDescription>
            <CardTitle className="text-3xl">{totalCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Unread Notifications</CardDescription>
            <CardTitle className="text-3xl">{unreadCount}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={currentTab} onValueChange={(v) => setCurrentTab(v as typeof currentTab)}>
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="all">
            All
            {totalCount > 0 && (
              <Badge variant="secondary" className="ml-2">
                {totalCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="unread">
            Unread
            {unreadCount > 0 && (
              <Badge variant="destructive" className="ml-2">
                {unreadCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

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
          ) : notifications.length === 0 ? (
            // Empty state
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <Bell className="text-muted-foreground mb-4 h-16 w-16" />
                <h3 className="text-lg font-semibold">No notifications</h3>
                <p className="text-muted-foreground text-sm">
                  {currentTab === "unread"
                    ? "You're all caught up!"
                    : "You don't have any notifications yet."}
                </p>
              </CardContent>
            </Card>
          ) : (
            // Notifications list
            <div className="space-y-3">
              {notifications.map((notification) => {
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
                  <Card
                    key={notification.id}
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
                                  title="Mark as read"
                                >
                                  <Check className="h-4 w-4" />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-destructive hover:text-destructive"
                                onClick={() => handleDelete(notification.id)}
                                title="Delete"
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
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Pagination */}
      {!isLoading && notifications.length > 0 && totalCount > pageSize && (
        <div className="flex items-center justify-between border-t pt-4">
          <p className="text-muted-foreground text-sm">
            Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalCount)} of{" "}
            {totalCount} notifications
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page * pageSize >= totalCount}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
