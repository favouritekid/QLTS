// src/components/sms/admin/contacts/SmsContactDetailDialog.tsx
"use client"

import { useState } from "react"
import { Pencil, Plus, ShieldCheck } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useAddContactToGroup,
  useConsentEvents,
  useSmsContactGroups,
} from "@/hooks/useSmsContacts"
import type { SmsContact } from "@/lib/zod/sms"

import {
  consentBasisLabel,
  consentEventTypeLabel,
  consentStatusLabel,
  consentStatusVariant,
  formatDateTimeVN,
  optOutSourceLabel,
} from "../labels"
import { SmsConsentEventDialog } from "./SmsConsentEventDialog"
import { SmsContactFormDialog } from "./SmsContactFormDialog"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  contact: SmsContact | null
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-sm">{children}</p>
    </div>
  )
}

export function SmsContactDetailDialog({ open, onOpenChange, contact }: Props) {
  const [editOpen, setEditOpen] = useState(false)
  const [consentOpen, setConsentOpen] = useState(false)
  const [groupToAdd, setGroupToAdd] = useState<string>("")

  const contactId = open && contact ? contact.id : null
  const { data: events, isLoading: eventsLoading } = useConsentEvents(contactId)
  // Chỉ tải danh sách nhóm cho picker khi dialog mở (tránh fetch thừa lúc tab
  // liên hệ render mà chưa mở chi tiết).
  const { data: groupsData } = useSmsContactGroups({ limit: 200 }, { enabled: open })
  const addToGroup = useAddContactToGroup()

  // Reset state khi ĐÓNG (event handler → tránh setState-trong-effect) để
  // mở lại liên hệ khác không kẹt picker/sub-dialog cũ.
  const handleOpenChange = (o: boolean) => {
    if (!o) {
      setGroupToAdd("")
      setEditOpen(false)
      setConsentOpen(false)
    }
    onOpenChange(o)
  }

  if (!contact) return null

  const handleAddToGroup = () => {
    if (!groupToAdd) return
    addToGroup.mutate(
      { contactId: contact.id, group_id: Number(groupToAdd) },
      { onSuccess: () => setGroupToAdd("") },
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {contact.full_name}
              <Badge variant={consentStatusVariant(contact.marketing_consent_status)}>
                {consentStatusLabel(contact.marketing_consent_status)}
              </Badge>
            </DialogTitle>
            <DialogDescription>
              {contact.phone_normalized} · {contact.phone_international}
            </DialogDescription>
          </DialogHeader>

          {/* Hành động */}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Pencil className="mr-2 h-4 w-4" /> Sửa
            </Button>
            <Button size="sm" onClick={() => setConsentOpen(true)}>
              <ShieldCheck className="mr-2 h-4 w-4" /> Ghi consent
            </Button>
          </div>

          {/* Thông tin */}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Nhãn nguồn">{contact.source_label || "—"}</Field>
            <Field label="Ghi chú">{contact.note || "—"}</Field>
            <Field label="Căn cứ consent">
              {contact.marketing_consent_basis
                ? consentBasisLabel(contact.marketing_consent_basis)
                : "—"}
            </Field>
            <Field label="Đồng ý lúc">
              {formatDateTimeVN(contact.marketing_consented_at)}
            </Field>
            <Field label="Phiên bản công bố">
              {contact.consent_disclosure_version || "—"}
            </Field>
            <Field label="Tham chiếu bằng chứng">
              {contact.marketing_consent_proof_ref || "—"}
            </Field>
          </div>

          {/* Thêm vào nhóm */}
          <div className="space-y-1.5 border-t pt-3">
            <Label htmlFor="add-group">Thêm vào nhóm</Label>
            <div className="flex gap-2">
              <Select
                value={groupToAdd}
                onValueChange={setGroupToAdd}
                disabled={addToGroup.isPending}
              >
                <SelectTrigger id="add-group" className="flex-1">
                  <SelectValue placeholder="— Chọn nhóm —" />
                </SelectTrigger>
                <SelectContent>
                  {groupsData?.items.map((g) => (
                    <SelectItem key={g.id} value={String(g.id)}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                onClick={handleAddToGroup}
                disabled={!groupToAdd || addToGroup.isPending}
              >
                <Plus className="mr-2 h-4 w-4" /> Thêm
              </Button>
            </div>
          </div>

          {/* Ledger consent */}
          <div className="space-y-2 border-t pt-3">
            <p className="text-sm font-medium">Lịch sử consent</p>
            {eventsLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : !events || events.items.length === 0 ? (
              <p className="text-muted-foreground py-2 text-sm">
                Chưa có sự kiện consent nào.
              </p>
            ) : (
              <div className="space-y-2">
                {events.items.map((e) => (
                  <div
                    key={e.id}
                    className="flex items-start justify-between gap-3 border-b pb-2 text-sm last:border-0"
                  >
                    <div>
                      <Badge
                        variant={
                          e.event_type === "granted" ? "default" : "destructive"
                        }
                      >
                        {consentEventTypeLabel(e.event_type)}
                      </Badge>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {e.event_type === "granted"
                          ? `${e.basis ? consentBasisLabel(e.basis) : ""}${
                              e.disclosure_version
                                ? ` · ${e.disclosure_version}`
                                : ""
                            }`
                          : e.revoke_source
                            ? optOutSourceLabel(e.revoke_source)
                            : ""}
                      </p>
                    </div>
                    <span className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
                      {formatDateTimeVN(e.occurred_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <SmsContactFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        contact={contact}
      />
      <SmsConsentEventDialog
        open={consentOpen}
        onOpenChange={setConsentOpen}
        contactId={contact.id}
      />
    </>
  )
}
