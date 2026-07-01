// src/components/sms/admin/campaigns/SmsCampaignGroupsSection.tsx
"use client"

import { useMemo, useState } from "react"
import { Plus, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useAttachCampaignGroup,
  useCampaignGroups,
  useDetachCampaignGroup,
} from "@/hooks/useSmsCampaigns"
import { useSmsContactGroups } from "@/hooks/useSmsContacts"

import { formatInt, groupTypeLabel } from "../labels"

interface Props {
  campaignId: number
  /** Cho sửa audience (draft/ready/exported) — handed_off/closed → khóa. */
  editable: boolean
}

export function SmsCampaignGroupsSection({ campaignId, editable }: Props) {
  const [toAdd, setToAdd] = useState<string>("")
  const { data, isLoading } = useCampaignGroups(campaignId)
  const { data: allGroups } = useSmsContactGroups(
    { limit: 200, is_active: true },
    { enabled: editable },
  )
  const attachMut = useAttachCampaignGroup()
  const detachMut = useDetachCampaignGroup()

  const attachedIds = useMemo(
    () => new Set((data?.items ?? []).map((g) => g.id)),
    [data],
  )
  const available = (allGroups?.items ?? []).filter(
    (g) => !attachedIds.has(g.id),
  )

  const attached = data?.items ?? []

  const handleAttach = () => {
    if (!toAdd) return
    attachMut.mutate(
      { campaignId, groupId: Number(toAdd) },
      { onSuccess: () => setToAdd("") },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Nhóm liên hệ ({attached.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {editable && (
          <div className="flex gap-2">
            <Select
              value={toAdd}
              onValueChange={setToAdd}
              disabled={attachMut.isPending}
            >
              <SelectTrigger className="flex-1">
                <SelectValue placeholder="— Chọn nhóm để gắn —" />
              </SelectTrigger>
              <SelectContent>
                {available.length === 0 ? (
                  <div className="text-muted-foreground px-2 py-1.5 text-sm">
                    Không còn nhóm để gắn.
                  </div>
                ) : (
                  available.map((g) => (
                    <SelectItem key={g.id} value={String(g.id)}>
                      {g.name}
                      {g.member_count != null
                        ? ` (${formatInt(g.member_count)})`
                        : ""}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            <Button
              onClick={handleAttach}
              disabled={!toAdd || attachMut.isPending}
            >
              <Plus className="mr-2 h-4 w-4" /> Gắn
            </Button>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : attached.length === 0 ? (
          <p className="text-muted-foreground py-4 text-center text-sm">
            Chưa gắn nhóm nào. Cần ít nhất 1 nhóm để build.
          </p>
        ) : (
          <div className="divide-y">
            {attached.map((g) => (
              <div
                key={g.id}
                className="flex items-center justify-between py-2"
              >
                <div>
                  <span className="text-sm font-medium">{g.name}</span>
                  <span className="text-muted-foreground ml-2 text-xs">
                    {groupTypeLabel(g.group_type)}
                    {g.member_count != null
                      ? ` · ${formatInt(g.member_count)} liên hệ`
                      : ""}
                  </span>
                </div>
                {editable && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Bỏ nhóm"
                    disabled={detachMut.isPending}
                    onClick={() =>
                      detachMut.mutate({ campaignId, groupId: g.id })
                    }
                  >
                    <X className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
