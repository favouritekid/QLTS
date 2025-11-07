// src/app/(dashboard)/profile/page.tsx
"use client";

import { useAuth } from "@/hooks/useAuth";
import { EditProfileForm } from "@/components/forms/EditProfileForm";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

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
          <CardHeader className="space-y-2">
            <Skeleton className="h-7 w-32 rounded-md" />
            <Skeleton className="h-4 w-96 rounded-md" />
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex items-center gap-6">
              <Skeleton className="h-24 w-24 rounded-full" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-32 rounded-md" />
                <Skeleton className="h-3 w-64 rounded-md" />
              </div>
            </div>
            <Skeleton className="h-10 w-full rounded-md" />
            <Skeleton className="h-10 w-full rounded-md" />
            <Skeleton className="h-10 w-full rounded-md" />
            <Skeleton className="mt-4 h-10 w-32 rounded-md" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Profile</h1>
        <p className="text-muted-foreground">Manage your profile information and settings.</p>
      </header>

      <EditProfileForm />
    </div>
  );
}
