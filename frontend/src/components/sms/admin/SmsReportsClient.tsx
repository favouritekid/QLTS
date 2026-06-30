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

/**
 * Trang báo cáo SMS Marketing (admin). 2 tab:
 * - "Tổng hợp click": báo cáo click theo ngày/tháng/năm + CTR (§9).
 * - "Theo chiến dịch": dashboard 1 chiến dịch (CTR + nhà mạng + danh sách).
 */
export function SmsReportsClient() {
  return (
    <Tabs defaultValue="overview" className="space-y-4">
      <TabsList>
        <TabsTrigger value="overview">Tổng hợp click</TabsTrigger>
        <TabsTrigger value="campaign">Theo chiến dịch</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <SmsClickReportPanel />
      </TabsContent>
      <TabsContent value="campaign">
        <SmsCampaignDashboardPanel />
      </TabsContent>
    </Tabs>
  )
}
