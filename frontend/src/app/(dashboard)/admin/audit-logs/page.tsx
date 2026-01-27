// src/app/(dashboard)/admin/audit-logs/page.tsx
"use client";

import { AuditLogsManager } from "./_components/AuditLogsManager";

export default function AuditLogsPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Audit Logs</h1>
        <p className="text-muted-foreground">
          Xem lịch sử thay đổi dữ liệu trong hệ thống.
        </p>
      </header>

      {/* Audit Logs Manager */}
      <AuditLogsManager />
    </div>
  );
}
