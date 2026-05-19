"use client"

/**
 * UtEvidenceTab — officer-side UT evidence verify/reject (Q9 #07 Phase E.3).
 *
 * **DISTINCT** từ candidate `UtEvidenceCard` (Wave 1 d599d16f): same UT
 * domain, hai audiences khác. Candidate-side card cho phép multi-select
 * + pending evidence. Officer-side tab cho phép verify/reject từng diện
 * candidate đã submit.
 *
 * Layout per plan v3 Wave 3:
 * - Iterate profile.priority_object_codes (candidate submitted)
 * - Per row: code label + catalog description + status badge + verify/reject buttons
 * - Reject sub-dialog: reason textarea min 10 chars
 * - Permission gate via profile.permissions.verify_priority_object
 *
 * Decision D3: candidate uploads minh chứng qua existing DocumentsTab
 * (step 6); officer picks document_id tại verify time. MVP defers document
 * Select to Wave 5 polish — verify accepts null document_id (BE optional).
 *
 * Service-layer (priority_override_service):
 * - Version guard FIRST per memory `version-guard-before-state-machine`
 * - sub_code must be trong profile.priority_object_codes → 400
 * - Recomputes snapshot.ut_verified_bucket (engine T6 actual rate freeze)
 * - INSERT priority_audit_log + dispatch PRIORITY_OBJECT_{VERIFIED,REJECTED}
 *   via outbox.
 */
import { useMemo, useState } from "react"
import {
  Award,
  CheckCircle2,
  Clock,
  Loader2,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog"
import { Textarea } from "@/components/ui/textarea"

import { useUtCatalog } from "@/lib/hooks/use-priority-object-catalog"
import {
  useRejectObjectEvidence,
  useVerifyObjectEvidence,
} from "@/lib/hooks/use-priority-evidence"
import type {
  AdmissionProfileResponse,
  PriorityObjectEvidenceEntry,
} from "@/lib/zod/admissions"

const MIN_REJECT_REASON = 10
const MAX_REJECT_REASON = 500

type EvidenceStatus = PriorityObjectEvidenceEntry["status"]

interface UtEvidenceTabProps {
  profile: AdmissionProfileResponse
}

function StatusBadge({ status }: { status: EvidenceStatus | "missing" }) {
  if (status === "verified") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
        <CheckCircle2 className="h-3 w-3" /> Đã duyệt
      </span>
    )
  }
  if (status === "rejected") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-800 border border-red-200">
        <XCircle className="h-3 w-3" /> Bị từ chối
      </span>
    )
  }
  if (status === "missing") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-800 border border-gray-200">
        Chưa có dữ liệu
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
      <Clock className="h-3 w-3" /> Chờ duyệt
    </span>
  )
}

function RejectDialog({
  open,
  onOpenChange,
  profileId,
  profileVersion,
  subCode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  profileId: number
  profileVersion: number
  subCode: string
}) {
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const mutation = useRejectObjectEvidence(profileId, subCode)
  const reasonLen = reason.trim().length
  const valid = reasonLen >= MIN_REJECT_REASON && reasonLen <= MAX_REJECT_REASON

  const handleClose = (next: boolean) => {
    if (!next) {
      setReason("")
      setError(null)
    }
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    if (!valid || mutation.isPending) return
    setError(null)
    try {
      await mutation.mutateAsync({
        version: profileVersion,
        reject_reason: reason.trim(),
      })
      toast.success(`Đã từ chối UT${subCode} thành công`)
      handleClose(false)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        toast.error("Hồ sơ vừa cập nhật, vui lòng refresh.")
        setError("Phiên bản đã thay đổi — đóng dialog và mở lại.")
      } else {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail
        toast.error(detail || "Không thể từ chối. Vui lòng thử lại.")
        setError(detail || "Lỗi server.")
      }
    }
  }

  return (
    <ResponsiveDialog open={open} onOpenChange={handleClose}>
      <ResponsiveDialogContent className="sm:max-w-[440px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle className="flex items-center gap-2">
            <ThumbsDown className="h-5 w-5 text-red-600" />
            Từ chối UT{subCode}
          </ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            Lý do từ chối sẽ được lưu vào audit log và hiển thị cho candidate.
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

        <div className="grid gap-2 py-4">
          <Label htmlFor={`reject-reason-${subCode}`}>
            Lý do từ chối <span className="text-error-500">*</span>
          </Label>
          <Textarea
            id={`reject-reason-${subCode}`}
            data-testid={`ut-reject-reason-${subCode}`}
            placeholder={`Nhập lý do từ chối (tối thiểu ${MIN_REJECT_REASON} ký tự)...`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            maxLength={MAX_REJECT_REASON}
          />
          <p
            className={`text-xs text-right ${
              reasonLen < MIN_REJECT_REASON || reasonLen > MAX_REJECT_REASON
                ? "text-error-500"
                : "text-muted-foreground"
            }`}
          >
            {reasonLen}/{MAX_REJECT_REASON} (tối thiểu {MIN_REJECT_REASON})
          </p>
          {error && (
            <p
              className="text-sm text-error-600"
              data-testid={`ut-reject-error-${subCode}`}
              role="alert"
            >
              {error}
            </p>
          )}
        </div>

        <ResponsiveDialogFooter>
          <Button
            variant="outline"
            onClick={() => handleClose(false)}
            disabled={mutation.isPending}
          >
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={handleSubmit}
            disabled={!valid || mutation.isPending}
            data-testid={`ut-reject-submit-${subCode}`}
          >
            {mutation.isPending ? "Đang xử lý..." : "Từ chối"}
          </Button>
        </ResponsiveDialogFooter>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  )
}

export function UtEvidenceTab({ profile }: UtEvidenceTabProps) {
  const canVerify = !!profile.permissions?.verify_priority_object
  const codes = useMemo(
    () => profile.priority_object_codes ?? [],
    [profile.priority_object_codes],
  )
  const evidence = (profile.priority_object_evidence ?? {}) as Record<
    string,
    PriorityObjectEvidenceEntry
  >
  const { data: catalog = [], isLoading } = useUtCatalog(
    profile.academic_year ?? 2026,
  )
  const [rejectingCode, setRejectingCode] = useState<string | null>(null)

  if (!canVerify) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          Bạn không có quyền duyệt UT trên hồ sơ này.
        </CardContent>
      </Card>
    )
  }

  if (codes.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Award className="h-5 w-5 text-purple-600" />
            Duyệt đối tượng ưu tiên (UT)
          </CardTitle>
        </CardHeader>
        <CardContent className="py-8 text-center text-muted-foreground">
          Candidate chưa khai diện UT nào. Không có gì để duyệt.
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            Duyệt đối tượng ưu tiên (UT)
          </CardTitle>
          <CardDescription>
            Kiểm tra minh chứng từng diện candidate đã khai. Chỉ diện đã duyệt
            mới được tính vào engine T6.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && (
            <div
              className="flex items-center gap-2 text-sm text-muted-foreground py-4"
              data-testid="ut-evidence-tab-loading"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Đang tải danh mục...
            </div>
          )}
          {!isLoading &&
            codes.map((code) => {
              const entry = evidence[code] ?? null
              const status = entry?.status ?? ("missing" as const)
              const catalogItem = catalog.find((c) => c.sub_code === code)
              const label = `UT${code.padStart(2, "0")}`

              return (
                <UtRow
                  key={code}
                  code={code}
                  label={label}
                  description={catalogItem?.description ?? "(Không có trong catalog)"}
                  status={status}
                  entry={entry}
                  profileId={profile.id}
                  profileVersion={profile.version ?? 0}
                  onReject={() => setRejectingCode(code)}
                />
              )
            })}
        </CardContent>
      </Card>

      {rejectingCode && (
        <RejectDialog
          open={!!rejectingCode}
          onOpenChange={(open) => !open && setRejectingCode(null)}
          profileId={profile.id}
          profileVersion={profile.version ?? 0}
          subCode={rejectingCode}
        />
      )}
    </>
  )
}

function UtRow({
  code,
  label,
  description,
  status,
  entry,
  profileId,
  profileVersion,
  onReject,
}: {
  code: string
  label: string
  description: string
  status: EvidenceStatus | "missing"
  entry: PriorityObjectEvidenceEntry | null
  profileId: number
  profileVersion: number
  onReject: () => void
}) {
  const verifyMutation = useVerifyObjectEvidence(profileId, code)

  const handleVerify = async () => {
    if (verifyMutation.isPending) return
    try {
      await verifyMutation.mutateAsync({
        version: profileVersion,
        document_id: null,
      })
      toast.success(`Đã duyệt ${label}`)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        toast.error("Hồ sơ vừa cập nhật, vui lòng refresh.")
      } else {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail
        toast.error(detail || `Không thể duyệt ${label}. Vui lòng thử lại.`)
      }
    }
  }

  return (
    <div
      className="flex items-start gap-3 p-3 rounded-md border bg-background"
      data-testid={`ut-officer-row-${code}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-semibold text-sm">{label}</span>
          <span className="text-sm text-foreground">{description}</span>
        </div>
        <div className="mt-1.5">
          <StatusBadge status={status} />
        </div>
        {status === "rejected" && entry?.reject_reason && (
          <p className="text-xs text-red-700 mt-1 italic">
            Lý do từ chối: {entry.reject_reason}
          </p>
        )}
      </div>

      <div className="flex gap-1">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleVerify}
          disabled={verifyMutation.isPending || status === "verified"}
          data-testid={`ut-verify-${code}`}
        >
          <ThumbsUp className="h-3.5 w-3.5 mr-1" />
          Duyệt
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onReject}
          disabled={status === "rejected"}
          data-testid={`ut-reject-${code}`}
        >
          <ThumbsDown className="h-3.5 w-3.5 mr-1" />
          Từ chối
        </Button>
      </div>
    </div>
  )
}
