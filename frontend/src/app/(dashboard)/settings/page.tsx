// src/app/(dashboard)/settings/page.tsx (ĐÃ CẬP NHẬT)
"use client";

import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

/**
 * Trang này giờ đây CHỈ chứa nội dung cho tab "Password".
 * Tiêu đề "Settings" và thanh Tab đã được chuyển lên layout.tsx.
 */
export default function SettingsPasswordPage() {
  return (
    // XÓA <header> và <p> mô tả khỏi đây

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

    // XÓA Card "Manage Active Sessions" khỏi đây
  );
}
