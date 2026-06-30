// src/app/(dashboard)/admin/sms/opt-out/page.tsx
/**
 * SMS Marketing — Quản lý số từ chối nhận tin (admin, PR-6).
 * Gate: proxy /admin/* + sidebar roles:["admin"]; BE require_admin là chốt
 * cuối.
 */
import { BellOff } from "lucide-react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { SmsOptOutClient } from "@/components/sms/admin/SmsOptOutClient"

export default function SmsOptOutPage() {
  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Từ chối nhận tin (SMS)"
        description="Danh sách số chặn gửi toàn cục và thêm thủ công từ kênh ngoài."
        icon={<BellOff className="h-6 w-6" />}
      />
      <SmsOptOutClient />
    </PageContainer>
  )
}
