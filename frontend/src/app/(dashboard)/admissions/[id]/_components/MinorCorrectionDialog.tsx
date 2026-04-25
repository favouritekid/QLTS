"use client"

import { useMemo, useState } from "react"
import { Loader2, Pencil } from "lucide-react"

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
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { useMinorCorrection } from "@/hooks/admissions/useAdmissions"
import {
  ALLOWED_GENDERS,
  FIELD_GROUPS_VI,
  FIELD_LABELS_VI,
} from "@/lib/constants/minor-correction"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface Props {
  profile: AdmissionProfileResponse
}

type FieldValue = string | null | undefined | unknown[] | Record<string, unknown>

/**
 * Officer/manager/admin entry to ``POST /minor-correction``.
 *
 * Renders a button only when the backend tells us we're allowed
 * (``permissions.minor_correction === true``) AND the resolved per-path
 * allowlist is non-empty (``minor_correction_fields.length > 0``). Both
 * gates come from the API response — FE never derives visibility itself.
 *
 * Form strategy: keep state lean (single ``values`` map keyed by field
 * code) and diff against ``profile`` on submit so the wire payload only
 * contains fields that actually changed. Date inputs use the model's
 * native ``YYYY-MM-DD`` shape; ``family_info`` falls back to a JSON
 * textarea — the officer copies the existing array, edits inline, and
 * the backend re-validates via ``FamilyMemberSchema``.
 */
export function MinorCorrectionDialog({ profile }: Props) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [values, setValues] = useState<Record<string, FieldValue>>({})
  const [familyInfoText, setFamilyInfoText] = useState<string>("")
  const [familyInfoError, setFamilyInfoError] = useState<string | null>(null)

  const mutation = useMinorCorrection(profile.id)

  // Visibility gate — strictly from API. Both checks must pass.
  const allowed = profile.permissions?.minor_correction === true
  const fieldsAvailable = profile.minor_correction_fields ?? []

  // Allowed field set, in display order grouped by FIELD_GROUPS_VI.
  const orderedGroups = useMemo(() => {
    const allowSet = new Set(fieldsAvailable)
    return Object.entries(FIELD_GROUPS_VI)
      .map(([groupName, keys]) => [
        groupName,
        keys.filter((k) => allowSet.has(k)),
      ] as const)
      .filter(([, keys]) => keys.length > 0)
  }, [fieldsAvailable])

  // Read current value from the profile for display in the input. Date
  // columns are emitted as ISO strings — slice to YYYY-MM-DD for the
  // native date input. Null values render as empty string so React
  // doesn't warn about controlled→uncontrolled flips.
  function readDisplay(field: string): string {
    const raw = (profile as unknown as Record<string, FieldValue>)[field]
    if (raw == null) return ""
    if (field.endsWith("_date") && typeof raw === "string") {
      return raw.slice(0, 10)
    }
    if (field === "family_info" && Array.isArray(raw)) {
      return JSON.stringify(raw, null, 2)
    }
    return String(raw)
  }

  function getCurrentValue(field: string): FieldValue {
    if (field === "family_info") {
      // Held in its own state because JSON parsing is deferred to submit.
      return familyInfoText !== "" ? familyInfoText : readDisplay(field)
    }
    return values[field] !== undefined ? values[field] : readDisplay(field)
  }

  function setFieldValue(field: string, next: FieldValue): void {
    setValues((prev) => ({ ...prev, [field]: next }))
  }

  // Build the diff against the original profile values. Returns null
  // if family_info JSON failed to parse (caller surfaces error).
  function buildChanges():
    | { ok: true; changes: Record<string, unknown> }
    | { ok: false; error: string } {
    const changes: Record<string, unknown> = {}
    for (const field of fieldsAvailable) {
      if (field === "family_info") {
        if (!familyInfoText) continue
        try {
          const parsed = JSON.parse(familyInfoText)
          const original = JSON.stringify(
            (profile as unknown as Record<string, FieldValue>).family_info ?? [],
          )
          if (JSON.stringify(parsed) !== original) {
            changes.family_info = parsed
          }
        } catch (e) {
          return {
            ok: false,
            error:
              "Trường gia đình không phải JSON hợp lệ. Vui lòng kiểm tra lại.",
          }
        }
        continue
      }
      const next = values[field]
      if (next === undefined) continue // user didn't touch
      const original = readDisplay(field)
      if (typeof next === "string" && next === original) continue
      // Empty string → null (clears the column)
      changes[field] = next === "" ? null : next
    }
    return { ok: true, changes }
  }

  const reasonTrimmed = reason.trim()
  const reasonValid = reasonTrimmed.length >= 10 && reasonTrimmed.length <= 1000

  function reset() {
    setReason("")
    setValues({})
    setFamilyInfoText("")
    setFamilyInfoError(null)
  }

  function handleSubmit() {
    setFamilyInfoError(null)
    const result = buildChanges()
    if (!result.ok) {
      setFamilyInfoError(result.error)
      return
    }
    if (Object.keys(result.changes).length === 0) {
      setFamilyInfoError("Chưa có thay đổi nào để lưu.")
      return
    }
    if (profile.version === undefined) {
      // Should never happen: an approved/confirmed profile always has
      // a version. Bail with a friendly error rather than ship an
      // optimistic-lock payload the server can't validate.
      setFamilyInfoError("Hồ sơ thiếu version — refresh trang rồi thử lại.")
      return
    }
    mutation.mutate(
      {
        version: profile.version,
        reason: reasonTrimmed,
        changes: result.changes,
      },
      {
        onSuccess: () => {
          reset()
          setOpen(false)
        },
      },
    )
  }

  if (!allowed || fieldsAvailable.length === 0) return null

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
      >
        <Pencil className="h-4 w-4 mr-2" />
        Hiệu chỉnh sau duyệt
      </Button>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (mutation.isPending) return
          setOpen(next)
          if (!next) reset()
        }}
      >
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Hiệu chỉnh hồ sơ sau duyệt</DialogTitle>
            <DialogDescription>
              Chỉ áp dụng cho các trường được admin cho phép. Mọi thay đổi
              được ghi lại với lý do.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-2">
            {orderedGroups.map(([groupName, keys]) => (
              <section key={groupName} className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground">
                  {groupName}
                </h3>
                <div className="space-y-3">
                  {keys.map((field) => (
                    <FieldRow
                      key={field}
                      field={field}
                      currentValue={getCurrentValue(field) as string}
                      onChange={(next) => {
                        if (field === "family_info") {
                          setFamilyInfoText(next)
                        } else {
                          setFieldValue(field, next)
                        }
                      }}
                      disabled={mutation.isPending}
                    />
                  ))}
                </div>
              </section>
            ))}

            {familyInfoError && (
              <p className="text-sm text-destructive">{familyInfoError}</p>
            )}

            <div className="space-y-2">
              <Label htmlFor="minor-correction-reason">
                Lý do hiệu chỉnh{" "}
                <span className="text-muted-foreground text-xs">
                  (≥ 10 ký tự, bắt buộc)
                </span>
              </Label>
              <Textarea
                id="minor-correction-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                disabled={mutation.isPending}
                rows={3}
                placeholder="Mô tả lý do — ví dụ: applicant báo qua điện thoại 25/04 yêu cầu sửa địa chỉ"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (mutation.isPending) return
                setOpen(false)
                reset()
              }}
              disabled={mutation.isPending}
            >
              Hủy
            </Button>
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={!reasonValid || mutation.isPending}
            >
              {mutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Lưu hiệu chỉnh
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// FieldRow — picks the right input shape per field key.
// ---------------------------------------------------------------------------

function FieldRow({
  field,
  currentValue,
  onChange,
  disabled,
}: {
  field: string
  currentValue: string
  onChange: (next: string) => void
  disabled: boolean
}) {
  const label = FIELD_LABELS_VI[field] ?? field

  if (field === "gender") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={`mc-${field}`}>{label}</Label>
        <Select
          value={currentValue || ""}
          onValueChange={onChange}
          disabled={disabled}
        >
          <SelectTrigger id={`mc-${field}`}>
            <SelectValue placeholder="Chọn giới tính" />
          </SelectTrigger>
          <SelectContent>
            {ALLOWED_GENDERS.map((g) => (
              <SelectItem key={g} value={g}>
                {g}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  if (field.endsWith("_date")) {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={`mc-${field}`}>{label}</Label>
        <Input
          id={`mc-${field}`}
          type="date"
          value={currentValue}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        />
      </div>
    )
  }

  if (field === "family_info") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={`mc-${field}`}>
          {label}{" "}
          <span className="text-xs text-muted-foreground">
            (JSON array — copy &amp; sửa)
          </span>
        </Label>
        <Textarea
          id={`mc-${field}`}
          value={currentValue}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          rows={6}
          className="font-mono text-xs"
        />
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={`mc-${field}`}>{label}</Label>
      <Input
        id={`mc-${field}`}
        value={currentValue}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      />
    </div>
  )
}
