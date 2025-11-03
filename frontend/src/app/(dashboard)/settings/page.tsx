// src/app/(dashboard)/settings/page.tsx
"use client";

import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

// (Bạn có thể thêm Metadata nếu muốn, nhưng vì đây là Client Component,
// bạn có thể quản lý title động nếu cần)

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage your account settings and password.</p>
      </header>

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Change Password</CardTitle>
          <CardDescription>
            Enter your current password and a new password. You will be logged out after success.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm />
        </CardContent>
      </Card>

      {/* Thêm các Card cài đặt khác ở đây (ví dụ: Cài đặt Profile, Notifications...) */}
    </div>
  );
}
