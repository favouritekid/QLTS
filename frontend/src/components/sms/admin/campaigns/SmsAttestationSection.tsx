// src/components/sms/admin/campaigns/SmsAttestationSection.tsx
"use client"

import { useState } from "react"
import { CheckCircle2, Circle, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useAddAttestation } from "@/hooks/useSmsExport"
import {
  SMS_ATTESTATION_KINDS,
  type SmsAttestationKind,
  type SmsCampaign,
} from "@/lib/zod/sms"

import { attestationKindLabel, formatDateTimeVN } from "../labels"

interface Props {
  campaign: SmsCampaign
  /** Ghi attestation được khi chưa bàn giao/đóng (BE cũng gate). */
  editable: boolean
}

interface KindState {
  at: string | null | undefined
  byId: number | null | undefined
  reference: string | null | undefined
  revision: number | null | undefined
}

/** Đọc trạng thái attestation của 1 kind từ campaign (field theo tiền tố kind). */
function readKind(c: SmsCampaign, kind: SmsAttestationKind): KindState {
  const g = (suffix: string) =>
    (c as unknown as Record<string, unknown>)[`${kind}_${suffix}`] as
      | string
      | number
      | null
      | undefined
  return {
    at: g("checked_at") as string | null | undefined,
    byId: g("checked_by_id") as number | null | undefined,
    reference: g("reference") as string | null | undefined,
    revision: g("checked_build_revision") as number | null | undefined,
  }
}

export function SmsAttestationSection({ campaign, editable }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const addMut = useAddAttestation(campaign.id)

  const submit = (kind: SmsAttestationKind) => {
    const reference = (drafts[kind] ?? "").trim()
    if (!reference) return
    addMut.mutate(
      { kind, reference },
      { onSuccess: () => setDrafts((d) => ({ ...d, [kind]: "" })) },
    )
  }

  const validCount = SMS_ATTESTATION_KINDS.filter((k) => {
    const s = readKind(campaign, k)
    return s.revision != null && s.revision === campaign.build_revision
  }).length

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Xác nhận trước export</CardTitle>
        <Badge variant={validCount === 3 ? "default" : "outline"}>
          {validCount}/3 đã xác nhận
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-muted-foreground text-xs">
          Cả 3 xác nhận phải khớp bản dựng hiện tại (#{campaign.build_revision}).
          Build lại sẽ vô hiệu các xác nhận cũ.
        </p>
        {SMS_ATTESTATION_KINDS.map((kind) => {
          const s = readKind(campaign, kind)
          const valid =
            s.revision != null && s.revision === campaign.build_revision
          const staleAttested = s.revision != null && !valid
          return (
            <div key={kind} className="rounded border p-3">
              <div className="flex items-start gap-2">
                {valid ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                ) : (
                  <Circle className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {attestationKindLabel(kind)}
                  </p>
                  {valid ? (
                    <p className="text-muted-foreground text-xs">
                      ✓ {formatDateTimeVN(s.at)}
                      {s.byId != null ? ` · bởi #${s.byId}` : ""} · ref:{" "}
                      {s.reference}
                    </p>
                  ) : staleAttested ? (
                    <p className="text-xs text-amber-600">
                      Đã xác nhận cho bản dựng #{s.revision} (cũ) — cần xác nhận
                      lại cho #{campaign.build_revision}.
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-xs">
                      Chưa xác nhận.
                    </p>
                  )}

                  {editable && (
                    <div className="mt-2 flex gap-2">
                      <Input
                        className="h-8 text-sm"
                        placeholder="Tham chiếu (link/mã hồ sơ bằng chứng)"
                        maxLength={512}
                        value={drafts[kind] ?? ""}
                        disabled={addMut.isPending}
                        onChange={(e) =>
                          setDrafts((d) => ({ ...d, [kind]: e.target.value }))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault()
                            submit(kind)
                          }
                        }}
                      />
                      <Button
                        size="sm"
                        variant={valid ? "outline" : "default"}
                        disabled={!drafts[kind]?.trim() || addMut.isPending}
                        onClick={() => submit(kind)}
                      >
                        {addMut.isPending && (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        )}
                        {valid ? "Cập nhật" : "Xác nhận"}
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
