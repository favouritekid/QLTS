// src/app/(dashboard)/finance/invoices/_components/CalculateFeePickerDialog.tsx
/**
 * Profile picker for the GLOBAL "+ Tính phí" CTA: search an admission profile by
 * name / HS-code / phone, pick one, then hand off to CalculateFeeDialog (which
 * is profile-bound + asks for the semester). NEVER a raw-id text box.
 *
 * From the drawer the CTA is already profile-bound (prefill), so this picker is
 * only the entry point when no student is selected yet.
 */

"use client"

import * as React from "react"
import { useQuery } from "@tanstack/react-query"
import { Search, Loader2, UserSearch } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { admissionsApi } from "@/lib/api/admissions"
import { Monogram } from "@/app/(dashboard)/admissions/_components/roster-parts"

function formatProfileCode(id: number): string {
  return `HS-${String(id).padStart(6, "0")}`
}

interface CalculateFeePickerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onPick: (profileId: number) => void
}

export function CalculateFeePickerDialog({
  open,
  onOpenChange,
  onPick,
}: CalculateFeePickerDialogProps) {
  const [search, setSearch] = React.useState("")
  const [debounced, setDebounced] = React.useState("")

  // Debounce the search so we don't query on every keystroke.
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  // Reset when reopened.
  React.useEffect(() => {
    if (!open) {
      setSearch("")
      setDebounced("")
    }
  }, [open])

  const enabled = open && debounced.length >= 2
  const { data, isFetching } = useQuery({
    queryKey: ["admissions", "fee-picker", debounced],
    queryFn: () => admissionsApi.listAdmissions({ search: debounced, page_size: 8 }),
    enabled,
    staleTime: 1000 * 30,
  })

  const profiles = data?.profiles ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Tính phí — chọn học sinh</DialogTitle>
          <DialogDescription>
            Tìm theo tên, mã hồ sơ (HS-…) hoặc số điện thoại, rồi chọn để tính phí.
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            autoFocus
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Nhập tên / mã hồ sơ / SĐT…"
            className="pl-9"
            aria-label="Tìm học sinh để tính phí"
          />
        </div>

        <div className="max-h-72 overflow-y-auto overscroll-contain" role="listbox" aria-label="Kết quả học sinh">
          {debounced.length < 2 ? (
            <p className="px-1 py-6 text-center text-sm text-muted-foreground">
              Nhập ít nhất 2 ký tự để tìm.
            </p>
          ) : isFetching ? (
            <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Đang tìm…
            </p>
          ) : profiles.length === 0 ? (
            <p className="flex flex-col items-center gap-2 py-6 text-center text-sm text-muted-foreground">
              <UserSearch className="size-6" aria-hidden="true" />
              Không tìm thấy học sinh phù hợp.
            </p>
          ) : (
            <ul className="space-y-1">
              {profiles.map((p) => {
                const name = p.full_name ?? "Chưa rõ học sinh"
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => onPick(p.id)}
                      className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                    >
                      <Monogram name={name} className="size-9" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{name}</span>
                        <span className="block truncate text-xs text-muted-foreground tabular-nums">
                          {formatProfileCode(p.id)}
                          {p.phone ? ` · ${p.phone}` : ""}
                        </span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default CalculateFeePickerDialog
