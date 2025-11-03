// src/app/(dashboard)/profile/page.tsx
"use client";

import { useAuth } from "@/hooks/useAuth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton"; // Dùng Skeleton cho trạng thái loading

export default function ProfilePage() {
  const { user, isLoading } = useAuth();

  if (isLoading || !user) {
    // Hiển thị Skeleton loading
    return (
      <div className="space-y-6">
        <header>
          <Skeleton className="h-9 w-48 rounded-md" />
          <Skeleton className="mt-2 h-5 w-72 rounded-md" />
        </header>
        <Card className="max-w-2xl">
          <CardHeader className="flex flex-row items-center gap-4 space-y-0">
            <Skeleton className="h-16 w-16 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-6 w-32 rounded-md" />
              <Skeleton className="h-4 w-48 rounded-md" />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-5 w-24 rounded-md" />
            <Skeleton className="h-5 w-32 rounded-md" />
            <Skeleton className="mt-4 h-9 w-24 rounded-md" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Profile</h1>
        <p className="text-muted-foreground">View and update your profile details.</p>
      </header>

      <Card className="max-w-2xl">
        <CardHeader className="flex flex-row items-center gap-4 space-y-0">
          <Avatar className="h-16 w-16">
            <AvatarImage src={user.avatar_url || ""} alt={user.username} />
            <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <div className="space-y-1">
            <CardTitle>{user.full_name || user.username}</CardTitle>
            <CardDescription>{user.email}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Username</p>
            <p>{user.username}</p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Role</p>
            <p className="capitalize">{user.role}</p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm font-medium">Phone Number</p>
            <p>{user.phone_number || "Not provided"}</p>
          </div>
          {/* Nút này sẽ được dùng để mở form edit (ở phase sau) */}
          <Button variant="outline" className="mt-4">
            Edit Profile (TBD)
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
