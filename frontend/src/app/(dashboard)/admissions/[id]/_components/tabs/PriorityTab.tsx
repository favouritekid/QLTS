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
import { Award, ShieldCheck, AlertCircle, Info, Lightbulb, Loader2, Lock, CheckCircle2 } from "lucide-react"
import { usePreviewPriorityKv } from "@/lib/hooks/use-preview-priority-kv"
import type { PreviewPriorityKvRequest } from "@/lib/api/priority-kv"
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

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

const KV_BADGE: Record<string, { color: string; label: string }> = {
  KV1: { color: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "KV1 (+0,75đ)" },
  "KV2-NT": { color: "bg-blue-100 text-blue-800 border-blue-300", label: "KV2-NT (+0,50đ)" },
  KV2: { color: "bg-amber-100 text-amber-800 border-amber-300", label: "KV2 (+0,25đ)" },
  KV3: { color: "bg-gray-100 text-gray-800 border-gray-300", label: "KV3 (không cộng)" },
}

const PATHWAY_LABEL_VI: Record<string, string> = {
  thpt_multi_school: "Theo lịch sử học các trường THPT (3 năm cấp 3)",
  commune_fallback: "Theo nơi thường trú",
  commune_special: "Theo nơi thường trú (trường hợp đặc biệt)",
  manual: "Cán bộ ấn định thủ công",
  not_resolved: "Chưa xác định được",
}

const RULE_LABEL_VI: Record<string, string> = {
  longest_duration: "Trường học lâu nhất",
  tiebreak_graduation_school: "Trường tốt nghiệp (khi thời gian học bằng nhau)",
  ambiguous_requires_manual: "Cần cán bộ xem xét (2 lựa chọn ngang nhau)",
  commune_lookup: "Tra cứu theo mã xã/phường nơi thường trú",
  manual_override: "Cán bộ ấn định thủ công",
}

const REASON_VI: Record<string, string> = {
  cultural_not_set: "Chưa khai trình độ văn hóa",
  no_qualifying_entries: "Lịch sử học chưa đủ trường phù hợp với trình độ",
  tied_graduation_year_and_grade: "Có 2 trường ngang nhau về thời gian + lớp tốt nghiệp — cần cán bộ xem xét",
}

function localizeReason(reason: string | null | undefined): string | null {
  if (!reason) return null
  return REASON_VI[reason] ?? reason
}

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

  // BE-frozen snapshot (post T1 submit)
  const frozenSnapshot = profile.priority_resolution_snapshot as
    | {
        kv_resolved?: string
        rule_applied?: string
        pathway?: string
        breakdown?: Record<string, unknown>
        requires_manual_override?: boolean
        reason?: string
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

  const kvBadge = displayKv ? KV_BADGE[displayKv] : null
  const isSpecialCase = areaBasis === "permanent_address_special"

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

      {/* ───────── 2. LIVE / FROZEN SNAPSHOT (prominent, top) ───────── */}
      <Card className={`border-2 shadow-sm ${isFrozen ? "border-primary/40 bg-primary/5" : kvBadge ? "border-emerald-200" : "border-muted"}`}>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            {isFrozen ? <Lock className="h-5 w-5 text-primary" /> : <Award className="h-5 w-5 text-emerald-600" />}
            {isFrozen ? "Khu vực ưu tiên (đã chốt)" : "Khu vực ưu tiên (tạm tính)"}
          </CardTitle>
          <CardDescription className="text-sm">
            {isFrozen
              ? "Đã khóa khi nộp hồ sơ — không thể thay đổi (chỉ admin override được)."
              : "Hệ thống tính theo thời gian thực dựa vào thông tin bạn khai. KV chính thức sẽ được chốt khi nộp hồ sơ."}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-2 space-y-3">
          {/* Loading state */}
          {previewLoading && !preview && !isFrozen && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Đang tính...
            </div>
          )}

          {/* Has KV resolved */}
          {kvBadge && (
            <div className="flex items-center gap-3">
              <span className={`inline-flex items-center px-4 py-2 rounded-md text-base font-bold border ${kvBadge.color}`}>
                {kvBadge.label}
              </span>
              {!isFrozen && <span className="text-xs text-muted-foreground">(sẽ chốt khi nộp hồ sơ)</span>}
              {isFrozen && (
                <span className="text-xs text-primary flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" /> Đã chốt
                </span>
              )}
            </div>
          )}

          {/* No KV yet — explain why */}
          {!previewLoading && !kvBadge && (
            <div className="rounded-lg border border-dashed p-3 bg-muted/30 text-sm flex gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
              <div>
                <p className="font-medium text-muted-foreground">Chưa đủ thông tin để tính KV</p>
                {displayReason && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Lý do: {localizeReason(displayReason)}
                  </p>
                )}
                {!cultural && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Vui lòng khai trình độ văn hóa ở phần dưới.
                  </p>
                )}
                {cultural && !academicHistory?.length && !isSpecialCase && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Vui lòng khai lịch sử học ở tab <em>Học tập</em>.
                  </p>
                )}
                {displayRequiresManual && (
                  <p className="text-xs text-warning-700 mt-1">
                    → Cần cán bộ xem xét/ấn định thủ công.
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Details: pathway + rule */}
          {(displayPathway || displayRule) && kvBadge && (
            <div className="grid grid-cols-2 gap-3 text-sm pt-2 border-t">
              {displayPathway && (
                <div>
                  <span className="text-xs text-muted-foreground block">Cách tính</span>
                  <span className="text-sm">{PATHWAY_LABEL_VI[displayPathway] ?? displayPathway}</span>
                </div>
              )}
              {displayRule && (
                <div>
                  <span className="text-xs text-muted-foreground block">Quy tắc</span>
                  <span className="text-sm">{RULE_LABEL_VI[displayRule] ?? displayRule}</span>
                </div>
              )}
            </div>
          )}

          {displayBreakdown && kvBadge && (
            <details className="text-xs border rounded p-2 bg-muted/30">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Xem chi tiết tính toán (cán bộ kiểm tra)
              </summary>
              <pre className="mt-2 overflow-auto text-[10px]">
                {JSON.stringify(displayBreakdown, null, 2)}
              </pre>
            </details>
          )}
        </CardContent>
      </Card>

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

          {/* Admin/manager-only manual override (advanced) */}
          {areaBasis === "manual_override" && (
            <div className="rounded-lg border p-3 bg-warning-50 border-warning-200 flex gap-2">
              <AlertCircle className="h-4 w-4 mt-0.5 text-warning-700 shrink-0" />
              <div className="text-sm space-y-1">
                <p className="font-medium text-warning-800">Manual Override (cán bộ ấn định)</p>
                <p className="text-xs text-warning-700">
                  KV được cán bộ tuyển sinh chỉ định sau khi thí sinh nộp hồ sơ. Lý do thay đổi <strong>bắt buộc</strong> khai báo và lưu vào nhật ký kiểm toán.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
