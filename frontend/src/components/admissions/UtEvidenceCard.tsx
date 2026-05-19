"use client"

/**
 * UtEvidenceCard — multi-select UT (đối tượng ưu tiên) picker per Phase E wireframe.
 *
 * Q9 #07 Phase E wireframe (2026-05-19) — Step 4 "Đối tượng ưu tiên (UT)":
 *
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │ 🎖️ Đối tượng ưu tiên (UT)                                    │
 *   │ Chọn các diện áp dụng — hệ thống cộng diện CAO NHẤT.         │
 *   │                                                              │
 *   │ ☑ UT04 — Con thương binh, con liệt sĩ          +1,00đ        │
 *   │                                       ⏳ Chờ duyệt           │
 *   │ ☑ UT06 — Dân tộc thiểu số rất ít người         +0,50đ        │
 *   │                                       ✅ Đã duyệt            │
 *   │ ☐ UT01 — Anh hùng LLVTND                       +2,00đ        │
 *   │ ☐ UT02 — Thương binh ≥81%                      +2,00đ        │
 *   │                                                              │
 *   │ ▾ Xem thêm 4 đối tượng                                       │
 *   └─────────────────────────────────────────────────────────────┘
 *
 * MVP scope (candidate-side only):
 * - Multi-select catalog → bind to form `priority_object_codes` array
 * - Init `priority_object_evidence[code] = { status: 'pending' }` khi tick
 * - Remove code → also remove key từ evidence dict
 * - Display evidence status badge inline (read-only — officer flow updates)
 * - Evidence upload UI defer to Phase E.3 (officer-side verify endpoint)
 *
 * Empty catalog handle gracefully — admin chưa seed `priority_object_config`
 * cho year hiện tại, hiển thị empty state với CTA contact admin.
 *
 * BE schemas:
 * - `priorityObjectsApi.getCatalog(year)` → list[PriorityObjectCatalogItem]
 * - Form `priority_object_codes: string[]` + `priority_object_evidence: dict`
 * - Per-code evidence shape: `{ status: 'pending'|'verified'|'rejected', ... }`
 */
import { useMemo, useState } from "react"
import { UseFormReturn } from "react-hook-form"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import {
  Award,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
  Mail,
  XCircle,
} from "lucide-react"

import { useUtCatalog } from "@/lib/hooks/use-priority-object-catalog"
import type { PriorityObjectCatalogItem } from "@/lib/api/priority-objects"
import type {
  AdmissionProfileUpdateInput,
  PriorityObjectEvidenceEntry,
} from "@/lib/zod/admissions"
import { formatBonus } from "./PrioritySnapshotCard"

const INITIAL_VISIBLE = 5

type EvidenceStatus = PriorityObjectEvidenceEntry["status"]

export interface UtEvidenceCardProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  /** Academic year để fetch catalog. Default 2026. */
  academicYear?: number
  /** Disable interactions (vd post-T1 freeze). */
  disabled?: boolean
}

function StatusBadge({ status }: { status: EvidenceStatus }) {
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
  // pending
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
      <Clock className="h-3 w-3" /> Chờ duyệt
    </span>
  )
}

function UtRow({
  item,
  checked,
  evidence,
  disabled,
  onToggle,
}: {
  item: PriorityObjectCatalogItem
  checked: boolean
  evidence?: PriorityObjectEvidenceEntry | null
  disabled: boolean
  onToggle: (checked: boolean) => void
}) {
  const code = `UT${item.sub_code.padStart(2, "0")}`
  return (
    <div
      className={`flex items-start gap-3 p-3 rounded-md border transition-colors ${
        checked
          ? "bg-purple-50 border-purple-200"
          : "bg-background border-border hover:bg-muted/30"
      }`}
      data-testid={`ut-row-${item.sub_code}`}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={(v) => onToggle(!!v)}
        disabled={disabled}
        className="mt-0.5"
        aria-label={`Chọn diện ${code}`}
        data-testid={`ut-checkbox-${item.sub_code}`}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-semibold text-sm">{code}</span>
          <span className="text-sm text-foreground">{item.description}</span>
          <span className="text-sm font-bold text-purple-800 ml-auto">
            {formatBonus(item.bonus_points)}
          </span>
        </div>
        {item.evidence_doc_type && (
          <p className="text-xs text-muted-foreground mt-0.5">
            Minh chứng yêu cầu: {item.evidence_doc_type}
          </p>
        )}
        {checked && evidence && (
          <div className="mt-2" data-testid={`ut-status-${item.sub_code}`}>
            <StatusBadge status={evidence.status} />
            {evidence.status === "rejected" && evidence.reject_reason && (
              <p className="text-xs text-red-700 mt-1 italic">
                Lý do từ chối: {evidence.reject_reason}
              </p>
            )}
          </div>
        )}
        {checked && !evidence && (
          <p className="text-xs text-amber-700 mt-1">
            ⚠ Chưa có minh chứng — vui lòng nộp tài liệu ở tab <em>Giấy tờ</em>{" "}
            để cán bộ duyệt.
          </p>
        )}
      </div>
    </div>
  )
}

export function UtEvidenceCard({
  form,
  academicYear = 2026,
  disabled = false,
}: UtEvidenceCardProps) {
  const { data: catalog = [], isLoading, error } = useUtCatalog(academicYear)
  const [expanded, setExpanded] = useState(false)

  const watchedCodes = form.watch("priority_object_codes")
  const evidence = form.watch("priority_object_evidence") ?? {}

  // Selected items go first (sorted by bonus desc, same as catalog order); rest hidden
  // until "Xem thêm" expanded.
  const { selectedItems, unselectedItems } = useMemo(() => {
    const codes = watchedCodes ?? []
    const selected: PriorityObjectCatalogItem[] = []
    const unselected: PriorityObjectCatalogItem[] = []
    for (const item of catalog) {
      if (codes.includes(item.sub_code)) {
        selected.push(item)
      } else {
        unselected.push(item)
      }
    }
    return { selectedItems: selected, unselectedItems: unselected }
  }, [catalog, watchedCodes])

  const visibleUnselected = expanded
    ? unselectedItems
    : unselectedItems.slice(0, Math.max(0, INITIAL_VISIBLE - selectedItems.length))
  const hiddenCount = unselectedItems.length - visibleUnselected.length

  const handleToggle = (subCode: string, checked: boolean) => {
    const currentCodes = form.getValues("priority_object_codes") ?? []
    const currentEvidence =
      form.getValues("priority_object_evidence") ?? {}

    if (checked) {
      if (currentCodes.includes(subCode)) return
      form.setValue(
        "priority_object_codes",
        [...currentCodes, subCode],
        { shouldDirty: true, shouldValidate: true },
      )
      // Initialize evidence entry as pending — officer flow upgrades to verified
      if (!currentEvidence[subCode]) {
        form.setValue(
          "priority_object_evidence",
          {
            ...currentEvidence,
            [subCode]: { status: "pending" },
          },
          { shouldDirty: true, shouldValidate: true },
        )
      }
    } else {
      form.setValue(
        "priority_object_codes",
        currentCodes.filter((c) => c !== subCode),
        { shouldDirty: true, shouldValidate: true },
      )
      // Remove evidence entry too — keep dict in sync với codes array
      if (currentEvidence[subCode]) {
        const rest = { ...currentEvidence }
        delete rest[subCode]
        form.setValue("priority_object_evidence", rest, {
          shouldDirty: true,
          shouldValidate: true,
        })
      }
    }
  }

  return (
    <Card className="shadow-sm border-border" data-testid="ut-evidence-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
          <Award className="h-5 w-5 text-purple-600" />
          Đối tượng ưu tiên (UT)
        </CardTitle>
        <CardDescription className="text-sm">
          Chọn các diện áp dụng — hệ thống cộng diện <strong>CAO NHẤT</strong>{" "}
          theo TT 05/2021. Mỗi diện cần đính kèm minh chứng và sẽ được cán bộ
          duyệt.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-2 space-y-2">
        {/* Loading */}
        {isLoading && (
          <div
            className="flex items-center gap-2 text-sm text-muted-foreground py-4"
            data-testid="ut-loading"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Đang tải danh mục đối tượng ưu tiên...
          </div>
        )}

        {/* Error */}
        {error && !isLoading && (
          <div
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
            data-testid="ut-error"
          >
            Không tải được danh mục đối tượng ưu tiên. Vui lòng tải lại trang.
          </div>
        )}

        {/* Empty catalog */}
        {!isLoading && !error && catalog.length === 0 && (
          <div
            className="rounded-lg border border-dashed border-muted-foreground/30 bg-muted/20 p-4 text-sm"
            data-testid="ut-empty-catalog"
          >
            <div className="flex items-start gap-2">
              <Mail className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
              <div>
                <p className="font-medium text-foreground">
                  Chưa có danh mục đối tượng ưu tiên cho năm {academicYear}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Vui lòng liên hệ phòng tuyển sinh để được cập nhật danh mục
                  diện ưu tiên áp dụng cho mùa tuyển sinh này.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Catalog rows */}
        {!isLoading && !error && catalog.length > 0 && (
          <div className="space-y-2">
            {/* Selected first */}
            {selectedItems.map((item) => (
              <UtRow
                key={item.sub_code}
                item={item}
                checked
                evidence={evidence[item.sub_code]}
                disabled={disabled}
                onToggle={(v) => handleToggle(item.sub_code, v)}
              />
            ))}

            {/* Unselected — initial slice */}
            {visibleUnselected.map((item) => (
              <UtRow
                key={item.sub_code}
                item={item}
                checked={false}
                disabled={disabled}
                onToggle={(v) => handleToggle(item.sub_code, v)}
              />
            ))}

            {/* Expand toggle */}
            {hiddenCount > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-full"
                onClick={() => setExpanded(true)}
                data-testid="ut-expand"
              >
                <ChevronDown className="h-4 w-4 mr-1" />
                Xem thêm {hiddenCount} đối tượng
              </Button>
            )}
            {expanded && unselectedItems.length > INITIAL_VISIBLE && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-full"
                onClick={() => setExpanded(false)}
                data-testid="ut-collapse"
              >
                <ChevronUp className="h-4 w-4 mr-1" />
                Thu gọn
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
