// src/components/sms/admin/contacts/SmsGroupContactsDialog.tsx
"use client"

import { useState } from "react"
import { Search, Upload } from "lucide-react"

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
import { useGroupContacts } from "@/hooks/useSmsContacts"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import type { SmsContactGroup } from "@/lib/zod/sms"

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
  const search = useDebouncedValue(searchInput.trim())

  // Reset khi ĐÓNG (event handler → tránh setState-trong-effect).
  const handleOpenChange = (o: boolean) => {
    if (!o) {
      setSearchInput("")
      setImportOpen(false)
    }
    onOpenChange(o)
  }

  const groupId = open && group ? group.id : null
  const { data, isLoading } = useGroupContacts(groupId, {
    search: search || undefined,
    limit: 100,
  })

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle>{group?.name ?? "Nhóm"}</DialogTitle>
            <DialogDescription>
              Liên hệ trong nhóm{" "}
              {group?.member_count != null
                ? `(${formatInt(group.member_count)} thành viên)`
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
    </>
  )
}
