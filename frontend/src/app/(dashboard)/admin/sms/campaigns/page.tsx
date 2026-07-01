// src/app/(dashboard)/admin/sms/campaigns/page.tsx
/**
 * SMS Marketing — Danh sách chiến dịch (admin, PR-6d).
 * Gate: proxy /admin/* + sidebar roles:["admin"]; BE require_admin.
 */
import { Send } from "lucide-react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { SmsCampaignsListClient } from "@/components/sms/admin/campaigns/SmsCampaignsListClient"

export default function SmsCampaignsPage() {
  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Chiến dịch SMS"
        description="Tạo chiến dịch, gắn nhóm và build danh sách gửi (preflight)."
        icon={<Send className="h-6 w-6" />}
      />
      <SmsCampaignsListClient />
    </PageContainer>
  )
}
