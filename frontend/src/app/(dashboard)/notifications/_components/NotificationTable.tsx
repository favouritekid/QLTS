"use client";

import { useEffect, useState } from "react";
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
import { Badge } from "@/components/ui/badge";
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
  getNotificationTypeBadge,
}: NotificationTableProps) {
  const allSelected =
    notifications.length > 0 &&
    notifications.every((n) => selectedIds.includes(n.id));
  
  const someSelected =
    notifications.some((n) => selectedIds.includes(n.id)) && !allSelected;

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[40px]">
              <Checkbox
                checked={allSelected || (someSelected ? "indeterminate" : false)}
                onCheckedChange={(checked) => onSelectAll(checked === true)}
                aria-label="Select all"
              />
            </TableHead>
            <TableHead className="w-[50px]">Type</TableHead>
            <TableHead className="min-w-[200px]">Thông báo</TableHead>
            <TableHead className="w-[150px]">Thời gian</TableHead>
            <TableHead className="w-[100px] text-right">Thao tác</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {notifications.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="h-24 text-center">
                Không có thông báo nào.
              </TableCell>
            </TableRow>
          ) : (
            notifications.map((notification) => (
              <TableRow
                key={notification.id}
                className={cn(
                  !notification.is_read && "bg-muted/30 font-medium"
                )}
              >
                <TableCell>
                  <Checkbox
                    checked={selectedIds.includes(notification.id)}
                    onCheckedChange={(checked) =>
                      onSelect(notification.id, checked === true)
                    }
                    aria-label={`Select notification ${notification.title}`}
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
                  <div className="flex flex-col gap-1">
                    <span className={cn("text-sm", !notification.is_read && "font-bold")}>
                      {notification.link ? (
                        <Link href={notification.link} className="hover:underline">
                          {notification.title}
                        </Link>
                      ) : (
                        notification.title
                      )}
                    </span>
                    <span className="text-muted-foreground line-clamp-1 text-xs">
                      {notification.message}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                  {formatDistanceToNow(new Date(notification.created_at), {
                    addSuffix: true,
                  })}
                </TableCell>
                <TableCell className="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" className="h-8 w-8 p-0">
                        <span className="sr-only">Open menu</span>
                        <MoreHorizontal className="h-4 w-4" />
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
                        Xóa thông báo
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
