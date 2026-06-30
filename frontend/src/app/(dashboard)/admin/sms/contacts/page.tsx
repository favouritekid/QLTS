// src/app/(dashboard)/admin/sms/contacts/page.tsx
/**
 * SMS Marketing — Quản lý liên hệ & nhóm & consent (admin, PR-6b).
 * Gate: proxy /admin/* + sidebar roles:["admin"]; BE require_admin là chốt cuối.
 */
import { Users } from "lucide-react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { SmsContactsClient } from "@/components/sms/admin/contacts/SmsContactsClient"

export default function SmsContactsPage() {
  return (
    <PageContainer maxWidth="full">
      <PageHeader
        title="Liên hệ SMS"
        description="Quản lý nhóm, liên hệ và bằng chứng đồng ý (consent) cho chiến dịch SMS."
        icon={<Users className="h-6 w-6" />}
      />
      <SmsContactsClient />
    </PageContainer>
  )
}
