// src/app/(dashboard)/settings/page.tsx
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Settings Password Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - Static rendering (no runtime overhead)
 * - Faster initial page load
 * - ChangePasswordForm remains interactive as Client Component
 */

import { ChangePasswordForm } from "@/components/forms/ChangePasswordForm";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

/**
 * Settings Password Page (Server Component)
 * This page only contains the Change Password form.
 * Navigation tabs are in layout.tsx.
 */
export default function SettingsPasswordPage() {
  return (
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
  );
}
