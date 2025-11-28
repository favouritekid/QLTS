// src/app/(dashboard)/admin/notification-templates/page.tsx
/**
 * ✅ PHASE 3.1: Admin Notification Templates Page
 *
 * Admin page for managing reusable notification templates.
 * Allows administrators to create, edit, and delete templates
 * that can be shared across multiple notification rules.
 */
"use client";

import { TemplateList } from "@/components/admin/notifications/TemplateList";

export default function NotificationTemplatesPage() {
  return <TemplateList />;
}
