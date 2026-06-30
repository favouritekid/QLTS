// src/components/sms/admin/contacts/SmsImportDialog.tsx
"use client"

import { useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, Upload } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useUploadContacts } from "@/hooks/useSmsContacts"
import type { SmsImportResult } from "@/lib/zod/sms"

import { CONSENT_BASIS_OPTIONS, formatInt } from "../labels"

const NONE = "none"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  groupId: number
  groupName: string
}

/**
 * Import liên hệ (CSV/XLSX) vào nhóm + (tùy chọn) bằng chứng consent cho cả
 * lô. Đủ basis + phiên bản công bố + tham chiếu + thời điểm → BE áp granted.
 */
export function SmsImportDialog({
  open,
  onOpenChange,
  groupId,
  groupName,
}: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [sourceLabel, setSourceLabel] = useState("")
  const [basis, setBasis] = useState<string>(NONE)
  const [disclosure, setDisclosure] = useState("")
  const [proofRef, setProofRef] = useState("")
  const [obtainedAt, setObtainedAt] = useState("")
  const [result, setResult] = useState<SmsImportResult | null>(null)

  const mutation = useUploadContacts()

  // Reset khi ĐÓNG (event handler, không dùng effect → tránh cascading render).
  const handleOpenChange = (o: boolean) => {
    if (!o) {
      setFile(null)
      setSourceLabel("")
      setBasis(NONE)
      setDisclosure("")
      setProofRef("")
      setObtainedAt("")
      setResult(null)
    }
    onOpenChange(o)
  }

  const consentComplete =
    basis !== NONE &&
    disclosure.trim() !== "" &&
    proofRef.trim() !== "" &&
    obtainedAt !== ""
  const consentPartial =
    (basis !== NONE ||
      disclosure.trim() !== "" ||
      proofRef.trim() !== "" ||
      obtainedAt !== "") &&
    !consentComplete

  function onSubmit() {
    if (!file) return
    let consentObtainedAt: string | undefined
    if (consentComplete) {
      const parsed = new Date(obtainedAt)
      if (Number.isNaN(parsed.getTime())) {
        toast.error("Thời điểm đồng ý không hợp lệ.")
        return
      }
      consentObtainedAt = parsed.toISOString()
    }
    mutation.mutate(
      {
        groupId,
        payload: {
          file,
          source_label: sourceLabel.trim() || undefined,
          consent_basis: consentComplete ? basis : undefined,
          consent_disclosure_version: consentComplete
            ? disclosure.trim()
            : undefined,
          consent_proof_ref: consentComplete ? proofRef.trim() : undefined,
          consent_obtained_at: consentObtainedAt,
        },
      },
      { onSuccess: (res) => setResult(res) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Import liên hệ vào «{groupName}»</DialogTitle>
          <DialogDescription>
            File .csv hoặc .xlsx (cột số điện thoại + họ tên). Số cố định / không
            hợp lệ sẽ bị bỏ qua và liệt kê ở kết quả.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <ImportResultView result={result} />
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="import-file">Tệp danh sách *</Label>
              <Input
                id="import-file"
                type="file"
                accept=".csv,.xlsx,.xls"
                disabled={mutation.isPending}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="import-source">Nhãn nguồn</Label>
              <Input
                id="import-source"
                placeholder="VD: Hội thảo tuyển sinh 06/2026"
                maxLength={255}
                value={sourceLabel}
                disabled={mutation.isPending}
                onChange={(e) => setSourceLabel(e.target.value)}
              />
            </div>

            <div className="space-y-3 rounded border p-3">
              <p className="text-sm font-medium">
                Bằng chứng đồng ý (tùy chọn)
              </p>
              <p className="text-muted-foreground text-xs">
                Điền ĐỦ 4 trường để áp trạng thái “đã đồng ý” cho cả lô. Thiếu
                bất kỳ → import nhưng giữ trạng thái “chưa rõ”.
              </p>

              <div className="space-y-1.5">
                <Label htmlFor="import-basis">Căn cứ</Label>
                <Select
                  value={basis}
                  onValueChange={setBasis}
                  disabled={mutation.isPending}
                >
                  <SelectTrigger id="import-basis">
                    <SelectValue placeholder="— Chọn căn cứ —" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>— Không khai báo —</SelectItem>
                    {CONSENT_BASIS_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="import-disclosure">Phiên bản công bố</Label>
                  <Input
                    id="import-disclosure"
                    maxLength={50}
                    placeholder="VD: v2026.1"
                    value={disclosure}
                    disabled={mutation.isPending}
                    onChange={(e) => setDisclosure(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="import-obtained">Thời điểm đồng ý</Label>
                  <Input
                    id="import-obtained"
                    type="datetime-local"
                    value={obtainedAt}
                    disabled={mutation.isPending}
                    onChange={(e) => setObtainedAt(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="import-proof">Tham chiếu bằng chứng</Label>
                <Input
                  id="import-proof"
                  maxLength={512}
                  placeholder="VD: link file scan, mã hồ sơ"
                  value={proofRef}
                  disabled={mutation.isPending}
                  onChange={(e) => setProofRef(e.target.value)}
                />
              </div>

              {consentPartial && (
                <p className="flex items-center gap-1.5 text-xs text-amber-600">
                  <AlertTriangle className="h-3.5 w-3.5" /> Chưa đủ 4 trường —
                  lô sẽ giữ trạng thái “chưa rõ”.
                </p>
              )}
              {consentComplete && (
                <p className="flex items-center gap-1.5 text-xs text-green-700">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Đủ bằng chứng — cả lô
                  sẽ được đánh dấu “đã đồng ý”.
                </p>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={() => handleOpenChange(false)}>Đóng</Button>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={mutation.isPending}
              >
                Hủy
              </Button>
              <Button
                type="button"
                onClick={onSubmit}
                disabled={!file || mutation.isPending}
              >
                {mutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-2 h-4 w-4" />
                )}
                Import
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ResultRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between border-b py-1 last:border-0">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-sm font-semibold tabular-nums">
        {formatInt(value)}
      </span>
    </div>
  )
}

function ImportResultView({ result }: { result: SmsImportResult }) {
  return (
    <div className="space-y-4">
      <div
        className={
          result.consent_applied
            ? "flex items-center gap-2 rounded border border-green-300 bg-green-50 p-2 text-sm text-green-800"
            : "flex items-center gap-2 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-800"
        }
      >
        {result.consent_applied ? (
          <CheckCircle2 className="h-4 w-4 shrink-0" />
        ) : (
          <AlertTriangle className="h-4 w-4 shrink-0" />
        )}
        {result.consent_applied
          ? "Đã áp trạng thái “đã đồng ý” cho cả lô."
          : "Lô giữ trạng thái “chưa rõ” (chưa đủ bằng chứng consent)."}
      </div>

      <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        <ResultRow label="Tổng dòng" value={result.row_count} />
        <ResultRow label="Hợp lệ" value={result.valid_count} />
        <ResultRow label="Không hợp lệ" value={result.invalid_count} />
        <ResultRow label="Liên hệ mới" value={result.inserted_contact_count} />
        <ResultRow label="Thêm vào nhóm" value={result.added_member_count} />
        <ResultRow label="Đã có sẵn" value={result.existing_member_count} />
        <ResultRow label="Trùng" value={result.duplicate_contact_count} />
        <ResultRow label="Bỏ qua" value={result.skipped_count} />
      </div>

      {result.errors.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-sm font-medium">
            Dòng lỗi ({formatInt(result.errors.length)})
          </p>
          <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2 text-xs">
            {result.errors.map((e, i) => (
              <div key={i} className="text-muted-foreground">
                Dòng {e.row_number}
                {e.phone_raw ? ` (${e.phone_raw})` : ""}: {e.reason}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
