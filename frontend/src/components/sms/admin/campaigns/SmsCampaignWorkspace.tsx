// src/components/sms/admin/campaigns/SmsCampaignWorkspace.tsx
"use client"

import { useState } from "react"
import { AlertCircle, Link2Off, LinkIcon, Pencil } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/layouts/PageHeader"
import { Skeleton } from "@/components/ui/skeleton"
import { useSmsCampaign } from "@/hooks/useSmsCampaigns"

import { campaignStatusLabel } from "../labels"
import { SmsAttestationSection } from "./SmsAttestationSection"
import { SmsBuildPreflightSection } from "./SmsBuildPreflightSection"
import { SmsCampaignFormDialog } from "./SmsCampaignFormDialog"
import { SmsCampaignGroupsSection } from "./SmsCampaignGroupsSection"
import { SmsExportSection } from "./SmsExportSection"

const CLOSED_STATUSES = ["handed_off", "closed"]

export function SmsCampaignWorkspace({ campaignId }: { campaignId: number }) {
  const [editOpen, setEditOpen] = useState(false)
  const { data: campaign, isLoading, isError, refetch } =
    useSmsCampaign(campaignId)

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    )
  }

  if (isError || !campaign) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <AlertCircle className="text-destructive h-8 w-8" />
          <p className="text-muted-foreground text-sm">
            Không tải được chiến dịch (không tồn tại hoặc lỗi).
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Thử lại
          </Button>
        </CardContent>
      </Card>
    )
  }

  const canEdit = campaign.status === "draft"
  const audienceEditable = !CLOSED_STATUSES.includes(campaign.status)
  const hasBuild = campaign.build_revision > 0
  // Đã build rồi nhưng status quay lại draft = đổi nhóm sau build → snapshot +
  // preflight cũ đã stale, buộc build lại (BE _mark_audience_changed).
  const staleBuild = campaign.status === "draft" && hasBuild

  return (
    <div className="space-y-4">
      <PageHeader
        title={campaign.name}
        description={campaign.code}
        backButton={{ href: "/admin/sms/campaigns", label: "Danh sách chiến dịch" }}
        actions={
          canEdit ? (
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="mr-2 h-4 w-4" /> Sửa
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge>{campaignStatusLabel(campaign.status)}</Badge>
        {campaign.build_revision > 0 && (
          <Badge variant="secondary">Bản dựng #{campaign.build_revision}</Badge>
        )}
        {campaign.has_link ? (
          <Badge variant="outline" className="gap-1">
            <LinkIcon className="h-3 w-3" /> Có short-link
          </Badge>
        ) : (
          <Badge variant="outline" className="gap-1 text-amber-600">
            <Link2Off className="h-3 w-3" /> Không đo click
          </Badge>
        )}
      </div>

      <SmsCampaignGroupsSection
        campaignId={campaignId}
        editable={audienceEditable}
      />

      <SmsBuildPreflightSection
        campaignId={campaignId}
        hasBuild={hasBuild}
        canBuild={audienceEditable}
        staleBuild={staleBuild}
      />

      {hasBuild && (
        <>
          <SmsAttestationSection
            campaign={campaign}
            editable={audienceEditable}
          />
          <SmsExportSection
            campaign={campaign}
            hasBuild={hasBuild}
            editable={audienceEditable}
          />
        </>
      )}

      <SmsCampaignFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        campaign={campaign}
      />
    </div>
  )
}
