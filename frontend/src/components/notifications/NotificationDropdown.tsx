// src/components/notifications/NotificationDropdown.tsx
"use client";

import React, { useState } from "react";
import { Bell, Check, CheckCheck, Trash2, X } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
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

export function NotificationDropdown() {
  const [isOpen, setIsOpen] = useState(false);
  const { data, isLoading } = useNotifications({ page_size: 10 });
  const markAsRead = useMarkAsRead();
  const markAllAsRead = useMarkAllAsRead();
  const deleteNotification = useDeleteNotification();

  const notifications = data?.notifications || [];
  const unreadCount = data?.unread_count || 0;

  const handleMarkAsRead = (notification: Notification) => {
    if (!notification.is_read) {
      markAsRead.mutate({ notification_ids: [notification.id] });
    }
  };

  const handleMarkAllAsRead = () => {
    markAllAsRead.mutate();
  };

  const handleDelete = (id: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    deleteNotification.mutate(id);
  };

  const getNotificationIcon = (type: Notification["type"]) => {
    const iconClass = "h-4 w-4";
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

  return (
    <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative h-9 w-9 rounded-full"
        >
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className="bg-destructive text-destructive-foreground absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
          <span className="sr-only">Notifications</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[380px] p-0"
        sideOffset={8}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b p-4">
          <div className="flex items-center gap-2">
            <DropdownMenuLabel className="p-0 text-base font-semibold">
              Notifications
            </DropdownMenuLabel>
            {unreadCount > 0 && (
              <Badge variant="secondary" className="text-xs">
                {unreadCount} new
              </Badge>
            )}
          </div>
          {unreadCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={handleMarkAllAsRead}
              disabled={markAllAsRead.isPending}
            >
              <CheckCheck className="mr-1 h-3 w-3" />
              Mark all read
            </Button>
          )}
        </div>

        {/* Notifications List */}
        <ScrollArea className="h-[400px]">
          {isLoading ? (
            <div className="space-y-2 p-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="p-3">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="mt-2 h-3 w-full" />
                  <Skeleton className="mt-2 h-3 w-1/2" />
                </div>
              ))}
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Bell className="text-muted-foreground mb-2 h-10 w-10" />
              <p className="text-muted-foreground text-sm">
                No notifications yet
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((notification) => {
                const NotificationWrapper = notification.link ? Link : "div";
                const wrapperProps = notification.link
                  ? { href: notification.link }
                  : {};

                return (
                  <NotificationWrapper
                    key={notification.id}
                    {...wrapperProps}
                    onClick={() => handleMarkAsRead(notification)}
                    className={cn(
                      "block transition-colors hover:bg-muted/50",
                      !notification.is_read && "bg-muted/30"
                    )}
                  >
                    <div className="flex items-start gap-3 p-3">
                      {/* Icon */}
                      <div
                        className={cn(
                          "bg-muted flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                          !notification.is_read && "bg-primary/10"
                        )}
                      >
                        {getNotificationIcon(notification.type)}
                      </div>

                      {/* Content */}
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-start justify-between gap-2">
                          <p
                            className={cn(
                              "text-sm leading-tight",
                              !notification.is_read && "font-semibold"
                            )}
                          >
                            {notification.title}
                          </p>
                          {!notification.is_read && (
                            <div className="bg-primary mt-1 h-2 w-2 shrink-0 rounded-full" />
                          )}
                        </div>
                        <p className="text-muted-foreground text-xs leading-snug">
                          {notification.message}
                        </p>
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-muted-foreground text-xs">
                            {formatDistanceToNow(
                              new Date(notification.created_at),
                              { addSuffix: true }
                            )}
                          </p>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 shrink-0"
                            onClick={(e) => handleDelete(notification.id, e)}
                          >
                            <Trash2 className="h-3 w-3" />
                            <span className="sr-only">Delete</span>
                          </Button>
                        </div>
                      </div>
                    </div>
                  </NotificationWrapper>
                );
              })}
            </div>
          )}
        </ScrollArea>

        {/* Footer */}
        {notifications.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <div className="p-2">
              <Link href="/notifications" onClick={() => setIsOpen(false)}>
                <Button
                  variant="ghost"
                  className="h-8 w-full text-xs font-medium"
                >
                  View all notifications
                </Button>
              </Link>
            </div>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
