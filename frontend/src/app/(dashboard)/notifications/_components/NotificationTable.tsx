"use client";

import { formatDistanceToNow } from "date-fns";
import { Check, MoreHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Notification } from "@/types/api.types";

interface NotificationTableProps {
  notifications: Notification[];
  selectedIds: number[];
  onSelect: (id: number, checked: boolean) => void;
  onSelectAll: (checked: boolean) => void;
  onMarkAsRead: (id: number) => void;
  onDelete: (id: number) => void;
  getNotificationIcon: (type: Notification["type"]) => React.ReactNode;
  getNotificationTypeBadge: (type: Notification["type"]) => React.ReactNode;
}

export function NotificationTable({
  notifications,
  selectedIds,
  onSelect,
  onSelectAll,
  onMarkAsRead,
  onDelete,
  getNotificationIcon,
}: NotificationTableProps) {
  const allSelected =
    notifications.length > 0 &&
    notifications.every((n) => selectedIds.includes(n.id));

  const someSelected =
    notifications.some((n) => selectedIds.includes(n.id)) && !allSelected;

  // Empty state
  if (notifications.length === 0) {
    return (
      <div className="rounded-md border p-8 text-center text-muted-foreground">
        Không có thông báo nào.
      </div>
    );
  }

  return (
    <>
      {/* ===== MOBILE VIEW: Card-based layout ===== */}
      <div className="space-y-2 md:hidden">
        {/* Select All header for mobile */}
        <div className="flex items-center gap-2 px-1 py-2">
          <Checkbox
            checked={allSelected || (someSelected ? "indeterminate" : false)}
            onCheckedChange={(checked) => onSelectAll(checked === true)}
            aria-label="Chọn tất cả"
          />
          <span className="text-sm text-muted-foreground">Chọn tất cả</span>
        </div>

        {/* Notification Cards */}
        {notifications.map((notification) => (
          <Card
            key={notification.id}
            className={cn(
              "p-3",
              !notification.is_read && "border-l-4 border-l-primary bg-muted/30"
            )}
          >
            <div className="flex gap-3">
              {/* Checkbox */}
              <div className="pt-0.5">
                <Checkbox
                  checked={selectedIds.includes(notification.id)}
                  onCheckedChange={(checked) =>
                    onSelect(notification.id, checked === true)
                  }
                  aria-label={`Chọn ${notification.title}`}
                />
              </div>

              {/* Icon */}
              <div className="flex-shrink-0 pt-0.5">
                {getNotificationIcon(notification.type)}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    {notification.link ? (
                      <Link
                        href={notification.link}
                        className={cn(
                          "text-sm hover:underline line-clamp-2",
                          !notification.is_read && "font-semibold"
                        )}
                      >
                        {notification.title}
                      </Link>
                    ) : (
                      <p
                        className={cn(
                          "text-sm line-clamp-2",
                          !notification.is_read && "font-semibold"
                        )}
                      >
                        {notification.title}
                      </p>
                    )}
                  </div>

                  {/* Actions dropdown */}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-7 w-7 flex-shrink-0">
                        <MoreHorizontal className="h-4 w-4" />
                        <span className="sr-only">Mở menu</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {!notification.is_read && (
                        <DropdownMenuItem onClick={() => onMarkAsRead(notification.id)}>
                          <Check className="mr-2 h-4 w-4" />
                          Đánh dấu đã đọc
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem
                        onClick={() => onDelete(notification.id)}
                        className="text-destructive focus:text-destructive"
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Xóa
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                <p className="text-xs text-muted-foreground line-clamp-1">
                  {notification.message}
                </p>

                <p
                  className="text-xs text-muted-foreground"
                  suppressHydrationWarning
                >
                  {formatDistanceToNow(new Date(notification.created_at), {
                    addSuffix: true,
                  })}
                </p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* ===== DESKTOP VIEW: Table layout ===== */}
      <div className="hidden md:block rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[40px]">
                <Checkbox
                  checked={allSelected || (someSelected ? "indeterminate" : false)}
                  onCheckedChange={(checked) => onSelectAll(checked === true)}
                  aria-label="Chọn tất cả"
                />
              </TableHead>
              <TableHead className="w-[50px]">Type</TableHead>
              <TableHead>Thông báo</TableHead>
              <TableHead className="w-[140px]">Thời gian</TableHead>
              <TableHead className="w-[80px] text-right">Thao tác</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {notifications.map((notification) => (
              <TableRow
                key={notification.id}
                className={cn(
                  !notification.is_read && "bg-muted/30"
                )}
              >
                <TableCell>
                  <Checkbox
                    checked={selectedIds.includes(notification.id)}
                    onCheckedChange={(checked) =>
                      onSelect(notification.id, checked === true)
                    }
                    aria-label={`Chọn ${notification.title}`}
                  />
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {!notification.is_read && (
                      <div className="bg-primary h-2 w-2 rounded-full" title="Chưa đọc" />
                    )}
                    <div title={notification.type}>
                      {getNotificationIcon(notification.type)}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="space-y-1">
                    {notification.link ? (
                      <Link
                        href={notification.link}
                        className={cn(
                          "text-sm hover:underline",
                          !notification.is_read && "font-semibold"
                        )}
                      >
                        {notification.title}
                      </Link>
                    ) : (
                      <span
                        className={cn(
                          "text-sm",
                          !notification.is_read && "font-semibold"
                        )}
                      >
                        {notification.title}
                      </span>
                    )}
                    <p className="text-xs text-muted-foreground line-clamp-1">
                      {notification.message}
                    </p>
                  </div>
                </TableCell>
                <TableCell
                  className="text-muted-foreground text-xs"
                  suppressHydrationWarning
                >
                  {formatDistanceToNow(new Date(notification.created_at), {
                    addSuffix: true,
                  })}
                </TableCell>
                <TableCell className="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" className="h-8 w-8 p-0">
                        <MoreHorizontal className="h-4 w-4" />
                        <span className="sr-only">Mở menu</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {!notification.is_read && (
                        <DropdownMenuItem onClick={() => onMarkAsRead(notification.id)}>
                          <Check className="mr-2 h-4 w-4" />
                          Đánh dấu đã đọc
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem
                        onClick={() => onDelete(notification.id)}
                        className="text-destructive focus:text-destructive"
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Xóa
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
