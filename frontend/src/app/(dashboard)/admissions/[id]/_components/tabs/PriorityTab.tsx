"use client"

/**
 * Priority Tab (Q9 #07 Phase D.2 + UX polish + D.4 live preview)
 *
 * Xác định Khu vực ưu tiên (KV) tuyển sinh per TT 05/2021/TT-BLĐTBXH
 * Phụ lục 01 + Luật GDNN 2014/2025.
 *
 * Smart auto-resolve:
 * - Live preview via POST /api/v2/admissions/{id}/preview-priority-kv
 * - Debounced 500ms khi cultural/vocational/history thay đổi
 * - Hiển thị "Tạm tính: KV1 (+0,75đ)" trước T1 submit
 * - "Đã chốt: KV1" khi profile.priority_resolution_snapshot exists
 *
 * Layout:
 *   1. Intro card — mục đích + KV rates + 4 trường hợp đặc biệt
 *   2. Snapshot card — KV live preview hoặc frozen result (BE authoritative)
 *   3. Trình độ học vấn — 2 dropdowns cultural + vocational
 *   4. Trường hợp đặc biệt toggle (replaces dropdown — auto-detect basis)
 */
import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { FormField, FormItem, FormLabel, FormControl, FormMessage, FormDescription } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ShieldCheck, Lightbulb } from "lucide-react"
import { usePreviewPriorityKv } from "@/lib/hooks/use-preview-priority-kv"
import type { PreviewPriorityKvRequest } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"
import { KvBreakdownCard } from "@/components/admissions/KvBreakdownCard"

interface PriorityTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  profile: AdmissionProfileResponse
  isEditable: boolean
}

const CULTURAL_OPTIONS = [
  { value: "completed_thcs", label: "Hoàn thành chương trình THCS (chưa tốt nghiệp)" },
  { value: "graduated_thcs", label: "Tốt nghiệp THCS" },
  { value: "completed_thpt", label: "Hoàn thành chương trình THPT (chưa tốt nghiệp)" },
  { value: "graduated_thpt", label: "Tốt nghiệp THPT" },
  { value: "graduated_gdtx", label: "Tốt nghiệp GDTX (Giáo dục thường xuyên cấp 3)" },
]

const VOCATIONAL_OPTIONS = [
  { value: "none", label: "Chưa có bằng nghề" },
  { value: "so_cap", label: "Sơ cấp nghề" },
  { value: "trung_cap", label: "Trung cấp" },
  { value: "cao_dang", label: "Cao đẳng" },
]

// KV constants + labels extracted to `@/components/admissions/kv-labels` (Phase E.1).
// Reused by `KvBreakdownCard` + future `PriorityOverrideDialog` (E.2).

export function PriorityTab({ form, profile, isEditable }: PriorityTabProps) {
  const cultural = form.watch("cultural_education_level")
  const vocational = form.watch("vocational_qualification")
  const areaBasis = form.watch("area_resolution_basis")
  const communeCode = form.watch("permanent_commune_code")
  const academicHistory = form.watch("academic_history")

  // Live preview hook — debounced 500ms
  const { data: preview, isLoading: previewLoading } = usePreviewPriorityKv(
    profile.id,
    {
      cultural_education_level: cultural ?? null,
      vocational_qualification: vocational ?? null,
      area_resolution_basis: areaBasis ?? null,
      permanent_commune_code: communeCode ?? null,
      academic_history:
        (academicHistory as PreviewPriorityKvRequest["academic_history"]) ?? null,
    },
    !!cultural, // only fire when cultural set
  )

  // BE-frozen snapshot (post T1 submit + E.2 manual override keys)
  const frozenSnapshot = profile.priority_resolution_snapshot as
    | {
        kv_resolved?: string
        rule_applied?: string
        pathway?: string
        breakdown?: Record<string, unknown>
        requires_manual_override?: boolean
        reason?: string
        // Phase E.2 — manual override audit trail
        manual_override_reason?: string
        manual_override_by?: number | string
        manual_override_at?: string
        // Phase A — freeze metadata
        frozen_at?: string
        frozen_at_status?: string
        resolved_by?: string
      }
    | null
    | undefined
  const hasFrozen = !!frozenSnapshot?.kv_resolved
  const isFrozen = hasFrozen && profile.status !== "draft"

  // Pick which result to display: frozen wins if exists, else live preview
  const displayKv = isFrozen ? frozenSnapshot?.kv_resolved : preview?.kv_resolved
  const displayPathway = isFrozen ? frozenSnapshot?.pathway : preview?.pathway
  const displayRule = isFrozen ? frozenSnapshot?.rule_applied : preview?.rule_applied
  const displayReason = isFrozen ? frozenSnapshot?.reason : preview?.reason
  const displayBreakdown = isFrozen ? frozenSnapshot?.breakdown : preview?.breakdown
  const displayRequiresManual = isFrozen ? frozenSnapshot?.requires_manual_override : preview?.requires_manual_override

  const isSpecialCase = areaBasis === "permanent_address_special"

  // Empty-state hint depends on what's missing — parent supplies context.
  const emptyStateHint = (
    <>
      {!cultural && <p>Vui lòng khai trình độ văn hóa ở phần dưới.</p>}
      {cultural && !academicHistory?.length && !isSpecialCase && (
        <p>Vui lòng khai lịch sử học ở tab <em>Học tập</em>.</p>
      )}
    </>
  )

  return (
    <div className="space-y-6">
      {/* ───────── 1. INTRO CARD ───────── */}
      <Card className="border-info-200 bg-info-50/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold flex items-center gap-2 text-info-800">
            <Lightbulb className="h-5 w-5" />
            Về phần này
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-info-900/80">
          <p>
            Xác định <strong>Khu vực ưu tiên (KV)</strong> để cộng điểm tuyển sinh theo
            Thông tư <strong>05/2021/TT-BLĐTBXH</strong> Phụ lục 01 + Thông tư <strong>27/2017/TT-BLĐTBXH</strong> về liên thông
            (vẫn còn hiệu lực trong giai đoạn chuyển tiếp Luật GDNN 2025).
          </p>
          <ul className="text-xs space-y-1 list-disc pl-5">
            <li><strong>KV1</strong>: +<strong>0,75đ</strong> — vùng miền núi, dân tộc thiểu số, biên giới, hải đảo</li>
            <li><strong>KV2-NT</strong>: +<strong>0,50đ</strong> — nông thôn không thuộc KV1</li>
            <li><strong>KV2</strong>: +<strong>0,25đ</strong> — thành phố thuộc tỉnh, phường ngoại thành TP trực thuộc TƯ</li>
            <li><strong>KV3</strong>: <strong>không cộng</strong> — nội thành TP trực thuộc TƯ (Hà Nội, HCM, ...)</li>
          </ul>
          <p className="text-xs pt-1">
            <strong>Hệ thống tự động tính</strong> ngay khi khai đủ trình độ + trường đã học (tab <em>Học tập</em>).
            Bật <strong>Trường hợp đặc biệt</strong> nếu là <em>Phổ thông Dân tộc Nội trú, lớp dự bị đại học, lớp tạo nguồn, quân nhân/công an tại ngũ hoặc xuất ngũ</em>
            {" "}— KV theo nơi thường trú (riêng quân nhân: theo nơi đóng quân ≥18 tháng nếu cao hơn — cần cán bộ xác nhận).
          </p>
        </CardContent>
      </Card>

      {/* ───────── 2. LIVE / FROZEN SNAPSHOT (extracted Phase E.1) ───────── */}
      <KvBreakdownCard
        kv={displayKv}
        pathway={displayPathway}
        ruleApplied={displayRule}
        reason={displayReason}
        breakdown={displayBreakdown}
        requiresManual={displayRequiresManual}
        frozen={isFrozen}
        loading={previewLoading && !preview}
        emptyStateHint={emptyStateHint}
        // Phase E.1 audit footer wire — only shown khi ruleApplied='manual_override'
        manualOverrideReason={frozenSnapshot?.manual_override_reason ?? null}
        manualOverrideBy={
          frozenSnapshot?.manual_override_by != null
            ? String(frozenSnapshot.manual_override_by)
            : null
        }
        manualOverrideAt={frozenSnapshot?.manual_override_at ?? null}
      />
      {/* Phase E.2 (PriorityOverrideDialog) sẽ wire trigger button gated by
          profile.permissions.override_priority_kv here — chưa ship */}

      {/* ───────── 3. TRÌNH ĐỘ HỌC VẤN ───────── */}
      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <ShieldCheck className="h-5 w-5" />
            Trình độ học vấn
          </CardTitle>
          <CardDescription className="text-sm">
            Khai 2 trình độ song song — hệ thống dựa vào đây để tự xác định cách tính KV.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6 pt-4">
          <div className="grid gap-6 md:grid-cols-2">
            <FormField
              control={form.control}
              name="cultural_education_level"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-sm">Trình độ văn hóa</FormLabel>
                  <Select
                    onValueChange={(v) => field.onChange(v === "_none" ? null : v)}
                    value={field.value ?? "_none"}
                    disabled={!isEditable}
                  >
                    <FormControl>
                      <SelectTrigger className="bg-background">
                        <SelectValue placeholder="Chọn trình độ văn hóa..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="_none">— Chưa khai —</SelectItem>
                      {CULTURAL_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription className="text-xs">
                    Bằng cấp giáo dục phổ thông cao nhất hiện có
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="vocational_qualification"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-sm">Trình độ chuyên môn nghề</FormLabel>
                  <Select
                    onValueChange={(v) => field.onChange(v)}
                    value={field.value ?? "none"}
                    disabled={!isEditable}
                  >
                    <FormControl>
                      <SelectTrigger className="bg-background">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {VOCATIONAL_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription className="text-xs">
                    Bằng nghề/Trung cấp/Cao đẳng đã có (nếu chưa thì chọn &ldquo;Chưa có bằng nghề&rdquo;)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        </CardContent>
      </Card>

      {/* ───────── 4. TRƯỜNG HỢP ĐẶC BIỆT (toggle, replaces dropdown) ───────── */}
      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <ShieldCheck className="h-5 w-5" />
            Trường hợp đặc biệt
          </CardTitle>
          <CardDescription className="text-sm">
            Chỉ bật nếu thí sinh thuộc 1 trong 5 nhóm dùng nơi thường trú để xác định KV thay vì trường học (per TT 05/2021 Phụ lục 01 Mục 4+6).
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          <FormField
            control={form.control}
            name="area_resolution_basis"
            render={({ field }) => (
              <FormItem className="flex items-start gap-3 space-y-0">
                <FormControl>
                  <Switch
                    checked={field.value === "permanent_address_special"}
                    onCheckedChange={(checked) => {
                      field.onChange(checked ? "permanent_address_special" : null)
                    }}
                    disabled={!isEditable}
                    aria-label="Bật trường hợp đặc biệt"
                  />
                </FormControl>
                <div className="space-y-1 leading-none">
                  <FormLabel className="text-sm font-medium">
                    Thí sinh thuộc nhóm đặc biệt
                  </FormLabel>
                  <FormDescription className="text-xs leading-relaxed">
                    Bao gồm: học sinh <strong>Phổ thông Dân tộc Nội trú</strong>, <strong>lớp dự bị đại học</strong>, <strong>lớp tạo nguồn</strong> (theo QĐ Bộ/UBND tỉnh), <strong>quân nhân/CAND tại ngũ</strong> hoặc <strong>xuất ngũ</strong> (đóng quân ≥18 tháng). Khi bật, KV theo mã xã/phường nơi thường trú thay vì trường học. <em>Riêng quân nhân: pháp lý cho phép MAX(KV đóng quân, KV nơi thường trú trước nhập ngũ) — cần cán bộ xác nhận thủ công.</em>
                  </FormDescription>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />

          {isSpecialCase && (
            <FormField
              control={form.control}
              name="permanent_commune_code"
              render={({ field }) => (
                <FormItem className="pl-12">
                  <FormLabel className="text-sm">Mã xã/phường nơi thường trú</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      value={field.value ?? ""}
                      placeholder="VD: 01_00025 (= Phường Giảng Võ, Hà Nội)"
                      maxLength={20}
                      disabled={!isEditable}
                      className="bg-background font-mono"
                    />
                  </FormControl>
                  <FormDescription className="text-xs">
                    Định dạng: <code>{`{mã tỉnh 2 số}_{mã phường 5 số BNV}`}</code>.
                    Lấy từ CCCD chip / VNeID / xác nhận cư trú (theo Luật Cư trú 2020 — sổ hộ khẩu giấy đã bỏ từ 01/01/2023).
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}

          {/* Manual override admin path — handled trong KvBreakdownCard audit row
              (Phase E.1) + PriorityOverrideDialog (Phase E.2). KHÔNG hiển thị
              trong candidate special-case card vì đây là officer/admin action,
              không phải candidate self-service. */}
        </CardContent>
      </Card>
    </div>
  )
}
