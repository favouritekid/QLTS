// src/components/sms/admin/contacts/SmsGroupContactsDialog.tsx
"use client"

import { useState } from "react"
import { Search, Upload, X } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  useGroupContacts,
  useRemoveContactFromGroup,
  useSmsContactGroup,
} from "@/hooks/useSmsContacts"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import type { SmsContact, SmsContactGroup } from "@/lib/zod/sms"

import {
  consentStatusLabel,
  consentStatusVariant,
  formatInt,
} from "../labels"
import { SmsImportDialog } from "./SmsImportDialog"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  group: SmsContactGroup | null
}

export function SmsGroupContactsDialog({ open, onOpenChange, group }: Props) {
  const [searchInput, setSearchInput] = useState("")
  const [importOpen, setImportOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<SmsContact | null>(null)
  const search = useDebouncedValue(searchInput.trim())
  const removeMut = useRemoveContactFromGroup()

  // Reset khi ĐÓNG (event handler → tránh setState-trong-effect).
  const handleOpenChange = (o: boolean) => {
    if (!o) {
      setSearchInput("")
      setImportOpen(false)
      setRemoveTarget(null)
    }
    onOpenChange(o)
  }

  const groupId = open && group ? group.id : null
  const { data, isLoading } = useGroupContacts(groupId, {
    search: search || undefined,
    limit: 100,
  })
  // Refetch single group (BE có GET /contact-groups/{id}) → member_count/name
  // luôn tươi sau import, kể cả khi group rớt khỏi bộ lọc list ngoài.
  const { data: freshGroup } = useSmsContactGroup(groupId)
  const g = freshGroup ?? group

  const confirmRemove = () => {
    if (!group || !removeTarget) return
    removeMut.mutate(
      { contactId: removeTarget.id, groupId: group.id },
      { onSuccess: () => setRemoveTarget(null) },
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle>{g?.name ?? "Nhóm"}</DialogTitle>
            <DialogDescription>
              Liên hệ trong nhóm{" "}
              {g?.member_count != null
                ? `(${formatInt(g.member_count)} thành viên)`
                : ""}
              .
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center justify-between gap-3">
            <div className="relative max-w-xs flex-1">
              <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
              <Input
                className="pl-8"
                placeholder="Tìm tên/số…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                maxLength={64}
              />
            </div>
            <Button size="sm" onClick={() => setImportOpen(true)}>
              <Upload className="mr-2 h-4 w-4" /> Import
            </Button>
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : !data || data.items.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {search ? "Không có liên hệ khớp." : "Nhóm chưa có liên hệ nào."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Họ tên</TableHead>
                    <TableHead>Số điện thoại</TableHead>
                    <TableHead>Consent</TableHead>
                    <TableHead className="text-right">Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">
                        {c.full_name}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {c.phone_normalized}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={consentStatusVariant(
                            c.marketing_consent_status,
                          )}
                        >
                          {consentStatusLabel(c.marketing_consent_status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label="Gỡ khỏi nhóm"
                          onClick={() => setRemoveTarget(c)}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {data.total > data.items.length && (
                <p className="text-muted-foreground mt-2 text-center text-xs">
                  Hiển thị {formatInt(data.items.length)}/{formatInt(data.total)}{" "}
                  — lọc thêm bằng ô tìm kiếm.
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {group && (
        <SmsImportDialog
          open={importOpen}
          onOpenChange={setImportOpen}
          groupId={group.id}
          groupName={group.name}
        />
      )}

      <AlertDialog
        open={removeTarget != null}
        onOpenChange={(o) => !o && setRemoveTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Gỡ liên hệ khỏi nhóm?</AlertDialogTitle>
            <AlertDialogDescription>
              Gỡ «{removeTarget?.full_name}» khỏi nhóm «{group?.name}». Liên hệ
              vẫn còn trong hệ thống, chỉ rời khỏi nhóm này.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMut.isPending}>
              Hủy
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                confirmRemove()
              }}
              disabled={removeMut.isPending}
            >
              Gỡ
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
