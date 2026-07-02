// src/components/sms/admin/SmsReportsClient.tsx
"use client"

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"

import { SmsCampaignDashboardPanel } from "./SmsCampaignDashboardPanel"
import { SmsClickReportPanel } from "./SmsClickReportPanel"
import { SmsProgramInterestPanel } from "./SmsProgramInterestPanel"

/**
 * Trang báo cáo SMS Marketing (admin). 3 tab:
 * - "Tổng hợp click": báo cáo click theo ngày/tháng/năm + CTR (§9).
 * - "Theo chiến dịch": dashboard 1 chiến dịch (CTR + nhà mạng + danh sách).
 * - "Quan tâm ngành": ngành nóng theo tổng dwell (Phase 2 §16.7).
 */
export function SmsReportsClient() {
  return (
    <Tabs defaultValue="overview" className="space-y-4">
      <TabsList>
        <TabsTrigger value="overview">Tổng hợp click</TabsTrigger>
        <TabsTrigger value="campaign">Theo chiến dịch</TabsTrigger>
        <TabsTrigger value="interest">Quan tâm ngành</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <SmsClickReportPanel />
      </TabsContent>
      <TabsContent value="campaign">
        <SmsCampaignDashboardPanel />
      </TabsContent>
      <TabsContent value="interest">
        <SmsProgramInterestPanel />
      </TabsContent>
    </Tabs>
  )
}
