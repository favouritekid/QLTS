// src/app/(dashboard)/admin/notification-rules/page.tsx
/**
 * ✅ PHASE 2.4: Admin Notification Rules Page
 *
 * Admin page for managing notification rules visually.
 * Allows administrators to create, edit, enable/disable, and delete
 * notification rules without code changes.
 */
"use client";

import { NotificationRuleList } from "@/components/admin/notifications/NotificationRuleList";

export default function NotificationRulesPage() {
  return <NotificationRuleList />;
}
