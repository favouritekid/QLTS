"use client";

/**
 * D5: Tabbed delivery dashboard — client component.
 *
 * Overview: charts + health panel + alert banner + top events
 * Deliveries: existing DeliveryOpsTable
 * Configuration: breaker states + quota readonly view
 */
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import AlertBanner from "@/components/admin/notifications/AlertBanner";
import ChannelHealthPanel from "@/components/admin/notifications/ChannelHealthPanel";
import DeliveryCharts from "@/components/admin/notifications/DeliveryCharts";
import DeliveryOpsTable from "@/components/admin/notifications/DeliveryOpsTable";
import TopEventsTable from "@/components/admin/notifications/TopEventsTable";

export default function DeliveryDashboard() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Delivery Monitoring</h1>
        <p className="text-muted-foreground">
          Theo dõi sức khỏe hệ thống thông báo
        </p>
      </div>

      {/* Alert banner — always visible */}
      <AlertBanner />

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="deliveries">Deliveries</TabsTrigger>
          <TabsTrigger value="configuration">Configuration</TabsTrigger>
        </TabsList>

        {/* Overview tab */}
        <TabsContent value="overview" className="space-y-6">
          <ChannelHealthPanel />
          <DeliveryCharts />
          <TopEventsTable />
        </TabsContent>

        {/* Deliveries tab — existing table */}
        <TabsContent value="deliveries">
          <DeliveryOpsTable />
        </TabsContent>

        {/* Configuration tab — breakers + quotas readonly */}
        <TabsContent value="configuration" className="space-y-6">
          <ChannelHealthPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
