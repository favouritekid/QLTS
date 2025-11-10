// src/components/admin/organization/UserListTab.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Users,
  Search,
  Mail,
  Phone,
  AlertCircle,
  UserPlus,
} from "lucide-react";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import type { OrganizationUnit } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UserListTabProps {
  unit: OrganizationUnit;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UserListTab({ unit }: UserListTabProps) {
  const [searchQuery, setSearchQuery] = useState("");

  // Fetch users with unit filter
  const {
    data: usersData,
    isLoading,
    error,
  } = useAdminUsersList({
    page: 1,
    page_size: 100,
    unit_id: unit.id, // Filter by current unit
    search: searchQuery || undefined,
  });

  const users = usersData?.users || [];
  const total = usersData?.total || 0;

  // Get user initials for avatar
  const getUserInitials = (fullName: string) => {
    const words = fullName.trim().split(/\s+/);
    if (words.length >= 2) {
      return (words[0][0] + words[words.length - 1][0]).toUpperCase();
    }
    return fullName.substring(0, 2).toUpperCase();
  };

  // Role badge variant
  const getRoleBadgeVariant = (role: string) => {
    switch (role) {
      case "admin":
        return "destructive";
      case "manager":
        return "default";
      default:
        return "secondary";
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Người dùng</h3>
            <p className="text-sm text-muted-foreground">
              {total} người dùng thuộc đơn vị này
            </p>
          </div>
          <Button>
            <UserPlus className="h-4 w-4 mr-2" />
            Thêm người dùng
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm kiếm theo tên, email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Users List */}
      <ScrollArea className="flex-1">
        {/* Loading State */}
        {isLoading && (
          <div className="p-6 space-y-4">
            {[1, 2, 3, 4].map((i) => (
              <Card key={i}>
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <Skeleton className="h-10 w-10 rounded-full" />
                    <div className="space-y-2 flex-1">
                      <Skeleton className="h-4 w-40" />
                      <Skeleton className="h-3 w-60" />
                    </div>
                  </div>
                </CardHeader>
              </Card>
            ))}
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-6">
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Không thể tải danh sách người dùng. Vui lòng thử lại sau.
              </AlertDescription>
            </Alert>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !error && users.length === 0 && (
          <div className="p-12 text-center">
            <Users className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
            <h4 className="text-lg font-medium mb-2">
              {searchQuery
                ? "Không tìm thấy người dùng"
                : "Chưa có người dùng"}
            </h4>
            <p className="text-sm text-muted-foreground mb-4">
              {searchQuery
                ? "Thử tìm kiếm với từ khóa khác"
                : "Thêm người dùng vào đơn vị này"}
            </p>
            {!searchQuery && (
              <Button size="sm">
                <UserPlus className="h-4 w-4 mr-2" />
                Thêm người dùng
              </Button>
            )}
          </div>
        )}

        {/* Data List */}
        {!isLoading && !error && users.length > 0 && (
          <div className="p-6 space-y-4">
            {users.map((user) => (
              <Card key={user.id}>
                <CardHeader>
                  <div className="flex items-start gap-4">
                    {/* Avatar */}
                    <Avatar className="h-10 w-10">
                      <AvatarImage src={user.avatar_url || undefined} />
                      <AvatarFallback>
                        {getUserInitials(user.full_name)}
                      </AvatarFallback>
                    </Avatar>

                    {/* User Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <CardTitle className="text-base">
                            {user.full_name}
                          </CardTitle>
                          <CardDescription className="mt-1">
                            @{user.username}
                          </CardDescription>
                        </div>
                        <Badge variant={getRoleBadgeVariant(user.role)}>
                          {user.role}
                        </Badge>
                      </div>

                      {/* Contact Info */}
                      <div className="mt-3 space-y-1">
                        {user.email && (
                          <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Mail className="h-3.5 w-3.5" />
                            <span>{user.email}</span>
                          </div>
                        )}
                        {user.phone_number && (
                          <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Phone className="h-3.5 w-3.5" />
                            <span>{user.phone_number}</span>
                          </div>
                        )}
                      </div>

                      {/* Status */}
                      <div className="mt-2 flex items-center gap-2">
                        <Badge
                          variant={user.is_active ? "default" : "secondary"}
                          className="text-xs"
                        >
                          {user.is_active ? "Hoạt động" : "Không hoạt động"}
                        </Badge>
                        {user.is_email_verified && (
                          <Badge variant="outline" className="text-xs">
                            Email đã xác thực
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                </CardHeader>
              </Card>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
