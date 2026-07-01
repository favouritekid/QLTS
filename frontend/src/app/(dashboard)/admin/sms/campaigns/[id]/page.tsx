// src/app/(dashboard)/admin/sms/campaigns/[id]/page.tsx
/**
 * SMS Marketing — Workspace 1 chiến dịch (admin, PR-6d).
 * Gate: proxy /admin/* + sidebar roles:["admin"]; BE require_admin.
 */
import { notFound } from "next/navigation"

import { PageContainer } from "@/components/layouts/PageContainer"
import { SmsCampaignWorkspace } from "@/components/sms/admin/campaigns/SmsCampaignWorkspace"

export default async function SmsCampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const campaignId = Number(id)
  if (!Number.isInteger(campaignId) || campaignId < 1) {
    notFound()
  }

  return (
    <PageContainer maxWidth="full">
      <SmsCampaignWorkspace campaignId={campaignId} />
    </PageContainer>
  )
}
