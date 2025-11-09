// src/app/(dashboard)/admin/users/[id]/page.tsx
"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Edit, Key, Shield, Activity, User as UserIcon } from "lucide-react";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { useAdminUserDetail } from "@/hooks/useAdminUsers";
import { useActivityLogs } from "@/hooks/useActivityLogs";
import { getAvatarUrl } from "@/lib/utils";
import { UserDialog } from "@/components/admin/UserDialog";
import { SetPasswordDialog } from "@/components/admin/SetPasswordDialog";
import { ManageRolesDialog } from "@/components/admin/ManageRolesDialog";

export default function UserDetailPage() {
  const params = useParams();
  const router = useRouter();
  const userId = parseInt(params.id as string, 10);

  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [setPasswordDialogOpen, setSetPasswordDialogOpen] = useState(false);
  const [manageRolesDialogOpen, setManageRolesDialogOpen] = useState(false);

  // Fetch user details
  const { data: user, isLoading: isLoadingUser, error: userError } = useAdminUserDetail(userId);

  // Fetch activity logs for this user
  const { data: activityData, isLoading: isLoadingActivity } = useActivityLogs({
    target_user_id: userId,
    page: 1,
    page_size: 20,
  });

  if (userError) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <h1 className="text-3xl font-bold">User Not Found</h1>
        </div>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Error loading user details. The user may have been deleted.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isLoadingUser || !user) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="grid gap-6 md:grid-cols-3">
          <Skeleton className="h-64" />
          <Skeleton className="h-64 md:col-span-2" />
        </div>
      </div>
    );
  }

  const statusColors: Record<string, string> = {
    active: "bg-green-500/10 text-green-500 border-green-500/20",
    pending: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    banned: "bg-red-500/10 text-red-500 border-red-500/20",
  };

  const roleColors: Record<string, string> = {
    admin: "bg-purple-500/10 text-purple-500 border-purple-500/20",
    manager: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    officer: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
    user: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold">{user.full_name || user.username}</h1>
            <p className="text-muted-foreground">@{user.username}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setUserDialogOpen(true)}>
            <Edit className="mr-2 h-4 w-4" />
            Edit
          </Button>
          <Button variant="outline" onClick={() => setSetPasswordDialogOpen(true)}>
            <Key className="mr-2 h-4 w-4" />
            Set Password
          </Button>
          <Button variant="outline" onClick={() => setManageRolesDialogOpen(true)}>
            <Shield className="mr-2 h-4 w-4" />
            Manage Roles
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* User Info Card */}
        <Card>
          <CardHeader>
            <CardTitle>User Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-col items-center gap-4">
              <Avatar className="h-24 w-24">
                <AvatarImage src={getAvatarUrl(user.avatar_url)} alt={user.username} />
                <AvatarFallback className="text-2xl">
                  {user.username.substring(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="text-center">
                <p className="font-semibold">{user.full_name || "No name"}</p>
                <p className="text-sm text-muted-foreground">{user.email}</p>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <p className="text-sm font-medium text-muted-foreground">User ID</p>
                <p className="text-sm">{user.id}</p>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Role</p>
                <Badge variant="outline" className={roleColors[user.role] || roleColors.user}>
                  {user.role.toUpperCase()}
                </Badge>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Status</p>
                <Badge variant="outline" className={statusColors[user.status] || statusColors.active}>
                  {user.status.toUpperCase()}
                </Badge>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">Phone</p>
                <p className="text-sm">{user.phone_number || "Not provided"}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Tabs Section */}
        <div className="md:col-span-2">
          <Tabs defaultValue="activity" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="activity">
                <Activity className="mr-2 h-4 w-4" />
                Activity Logs
              </TabsTrigger>
              <TabsTrigger value="details">
                <UserIcon className="mr-2 h-4 w-4" />
                Additional Details
              </TabsTrigger>
            </TabsList>

            {/* Activity Logs Tab */}
            <TabsContent value="activity">
              <Card>
                <CardHeader>
                  <CardTitle>Recent Activity</CardTitle>
                  <CardDescription>
                    Actions performed on this user account
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {isLoadingActivity ? (
                    <div className="space-y-2">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                      ))}
                    </div>
                  ) : activityData?.logs && activityData.logs.length > 0 ? (
                    <div className="rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Action</TableHead>
                            <TableHead>Actor</TableHead>
                            <TableHead>Description</TableHead>
                            <TableHead>Date</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {activityData.logs.map((log) => (
                            <TableRow key={log.id}>
                              <TableCell className="font-medium">
                                <Badge variant="outline">{log.action}</Badge>
                              </TableCell>
                              <TableCell>
                                {log.actor_username || "System"}
                              </TableCell>
                              <TableCell className="max-w-md truncate">
                                {log.description || "No description"}
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground">
                                {format(new Date(log.created_at), "MMM d, yyyy HH:mm")}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  ) : (
                    <p className="text-center text-muted-foreground py-8">
                      No activity logs found for this user.
                    </p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Additional Details Tab */}
            <TabsContent value="details">
              <Card>
                <CardHeader>
                  <CardTitle>Additional Information</CardTitle>
                  <CardDescription>
                    Extended user profile and system data
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Username</p>
                      <p className="text-sm">{user.username}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Email</p>
                      <p className="text-sm">{user.email}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Full Name</p>
                      <p className="text-sm">{user.full_name || "Not provided"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Phone Number</p>
                      <p className="text-sm">{user.phone_number || "Not provided"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Organization Unit</p>
                      <p className="text-sm">{user.unit_id ? `Unit #${user.unit_id}` : "Not assigned"}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-muted-foreground">Availability</p>
                      <p className="text-sm">{user.availability_status || "N/A"}</p>
                    </div>
                  </div>
                  {user.skills && user.skills.length > 0 && (
                    <div>
                      <p className="text-sm font-medium text-muted-foreground mb-2">Skills</p>
                      <div className="flex flex-wrap gap-2">
                        {user.skills.map((skill, index) => (
                          <Badge key={index} variant="secondary">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>

      {/* Dialogs */}
      <UserDialog
        open={userDialogOpen}
        onOpenChange={setUserDialogOpen}
        mode="edit"
        user={user}
      />
      <SetPasswordDialog
        open={setPasswordDialogOpen}
        onOpenChange={setSetPasswordDialogOpen}
        user={user}
      />
      <ManageRolesDialog
        open={manageRolesDialogOpen}
        onOpenChange={setManageRolesDialogOpen}
        user={user}
      />
    </div>
  );
}
