// src/app/(dashboard)/admin/sms/reports/page.tsx
/**
 * SMS Marketing — Báo cáo click + dashboard chiến dịch (admin, PR-6).
 * Gate: proxy /admin/* + sidebar roles:["admin"]; BE require_admin là chốt
 * cuối. Server component bọc client Tabs.
 */
import { BarChart3 } from "lucide-react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { SmsReportsClient } from "@/components/sms/admin/SmsReportsClient"

export default function SmsReportsPage() {
  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Báo cáo SMS Marketing"
        description="Hiệu quả click theo thời gian và theo từng chiến dịch."
        icon={<BarChart3 className="h-6 w-6" />}
      />
      <SmsReportsClient />
    </PageContainer>
  )
}
