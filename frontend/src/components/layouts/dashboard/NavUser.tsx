// src/components/layouts/dashboard/NavUser.tsx
"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button"; // Import Button
import { useAuth } from "@/hooks/useAuth";
import { LogOut, Settings, User as UserIcon, ChevronsUpDown } from "lucide-react";
import Link from "next/link";
import { cn, getAvatarUrl } from "@/lib/utils";

export function NavUser({ isCollapsed }: { isCollapsed: boolean }) {
  const { user, logout, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="bg-muted h-8 w-8 animate-pulse rounded-full" />
        {!isCollapsed && <div className="bg-muted h-6 w-24 animate-pulse rounded-md" />}
      </div>
    );
  }

  const fallback = user?.username ? user.username.slice(0, 2).toUpperCase() : "??";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            "flex w-full items-center justify-between px-3 py-2 text-left",
            isCollapsed && "h-10 w-10 justify-center p-0"
          )}
          {...(isCollapsed ? { "aria-label": "Menu người dùng" } : {})}
        >
          {/* Phần nội dung button */}
          <div className="flex items-center gap-2">
            <Avatar className="h-8 w-8">
              <AvatarImage src={getAvatarUrl(user?.avatar_url)} alt={user?.username} />
              <AvatarFallback>{fallback}</AvatarFallback>
            </Avatar>
            <div className={cn("flex flex-col", isCollapsed && "hidden")}>
              <span className="text-sm font-medium">{user?.full_name || user?.username}</span>
              <span className="text-muted-foreground text-xs">{user?.email}</span>
            </div>
          </div>
          {/* Icon expand/collapse (chỉ hiển thị khi mở rộng) */}
          {!isCollapsed && <ChevronsUpDown aria-hidden="true" className="text-muted-foreground h-4 w-4" />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm leading-none font-medium">{user?.full_name || user?.username}</p>
            <p className="text-muted-foreground text-xs leading-none">{user?.email}</p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/profile">
            {" "}
            {/* Cần tạo trang /profile sau */}
            <UserIcon className="mr-2 h-4 w-4" />
            <span>Hồ sơ</span>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            {" "}
            {/* Cần tạo trang /settings sau */}
            <Settings className="mr-2 h-4 w-4" />
            <span>Cài đặt</span>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout()} className="text-destructive">
          <LogOut className="mr-2 h-4 w-4" />
          <span>Đăng xuất</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
