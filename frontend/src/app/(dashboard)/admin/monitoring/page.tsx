// src/app/(dashboard)/admin/monitoring/page.tsx
"use client";

import { SystemMonitoringDashboard } from "@/components/admin/monitoring/SystemMonitoringDashboard";

export default function MonitoringPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold font-display tracking-tight">System Monitoring</h1>
        <p className="text-muted-foreground">
          Theo dõi sức khỏe và trạng thái của hệ thống theo thời gian thực.
        </p>
      </header>

      {/* Monitoring Dashboard */}
      <SystemMonitoringDashboard />
    </div>
  );
}
