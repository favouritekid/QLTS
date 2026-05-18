"use client"

/**
 * Priority Tab (Q9 #07 Phase D.2 + UX polish)
 *
 * Xác định Khu vực ưu tiên (KV) tuyển sinh per TT 05/2021/TT-BLĐTBXH
 * Phụ lục 01 + Luật GDNN 2014/2025.
 *
 * Layout (officer-focused):
 *   1. Intro card — mục đích + KV rates + 4 trường hợp đặc biệt
 *   2. Snapshot card — KV đã xác định (BE authoritative, prominent)
 *   3. Trình độ học vấn — 2 dropdowns cultural + vocational
 *   4. Cơ sở xác định — area_resolution_basis + commune_code khi cần
 *
 * BE source of truth (frontend CLAUDE.md thin-client):
 * - FE preview matrix is informational only
 * - profile.priority_resolution_snapshot is authoritative (frozen T1/T6)
 */
import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { FormField, FormItem, FormLabel, FormControl, FormMessage, FormDescription } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Award, ShieldCheck, AlertCircle, Info, Lightbulb } from "lucide-react"
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

const AREA_BASIS_OPTIONS = [
  {
    value: "high_school",
    label: "Bình thường — tự động tính theo trường đã học",
    description: "Phù hợp với đa số thí sinh. Hệ thống lấy KV từ lịch sử các trường THPT/THCS đã ghi ở tab Học tập.",
  },
  {
    value: "permanent_address_special",
    label: "Đặc biệt — học PT DTNT / lớp dự bị / quân nhân / xuất ngũ",
    description: "Dành cho 4 nhóm: học sinh PT Dân tộc Nội trú, lớp dự bị đại học, đang là quân nhân, hoặc bộ đội xuất ngũ. KV tính theo xã/phường hộ khẩu thường trú.",
  },
  {
    value: "manual_override",
    label: "Cán bộ ấn định khu vực khác (cần lý do)",
    description: "Trường hợp ngoại lệ — cán bộ tuyển sinh chỉ định KV thủ công với lý do bắt buộc. Áp dụng khi tình huống không khớp 2 nhóm trên.",
  },
] as const

const KV_TONE_VI: Record<string, { color: string; label: string }> = {
  KV1: { color: "bg-emerald-100 text-emerald-800 border-emerald-200", label: "KV1 (+0,75đ)" },
  "KV2-NT": { color: "bg-blue-100 text-blue-800 border-blue-200", label: "KV2-NT (+0,50đ)" },
  KV2: { color: "bg-amber-100 text-amber-800 border-amber-200", label: "KV2 (+0,25đ)" },
  KV3: { color: "bg-gray-100 text-gray-800 border-gray-200", label: "KV3 (không cộng điểm)" },
}

const PATHWAY_LABEL_VI: Record<string, string> = {
  thpt_multi_school: "Theo lịch sử học các trường THPT",
  tc_multi_school: "Theo lịch sử học các trường Trung cấp",
  commune_fallback: "Theo hộ khẩu thường trú",
  commune_special: "Theo hộ khẩu (trường hợp đặc biệt)",
  manual: "Cán bộ ấn định thủ công",
  not_resolved: "Chưa xác định được",
}

const RULE_LABEL_VI: Record<string, string> = {
  longest_duration: "Trường học lâu nhất",
  tiebreak_graduation_school: "Trường tốt nghiệp (khi thời gian học bằng nhau)",
  ambiguous_requires_manual: "Cần cán bộ xem xét — có 2 lựa chọn ngang nhau",
  commune_lookup: "Tra cứu theo mã xã/phường hộ khẩu",
  manual_override: "Cán bộ ấn định thủ công",
}

/**
 * FE preview cách tính KV (giải thích cho user, không phải BE authoritative).
 * Mirror logic `_derive_kv_basis_level()` trong app/services/priority_service.py.
 */
function previewBasis(
  cultural: string | null | undefined,
  vocational: string | null | undefined,
  areaBasis: string | null | undefined,
): { label: string; tone: "info" | "warn"; description: string } | null {
  if (areaBasis === "permanent_address_special") {
    return {
      label: "Theo hộ khẩu (trường hợp đặc biệt)",
      tone: "info",
      description: "Hệ thống sẽ tra mã xã/phường hộ khẩu để xác định KV.",
    }
  }
  if (areaBasis === "manual_override") {
    return {
      label: "Cán bộ ấn định thủ công",
      tone: "warn",
      description: "Cán bộ tuyển sinh sẽ chỉ định KV với lý do bắt buộc khai báo.",
    }
  }
  if (!cultural) {
    return {
      label: "Chưa đủ thông tin",
      tone: "warn",
      description: "Vui lòng chọn trình độ văn hóa để tiếp tục.",
    }
  }

  const grad_thpt = ["graduated_thpt", "graduated_gdtx"].includes(cultural)
  const completed_thpt = cultural === "completed_thpt"
  const grad_thcs = cultural === "graduated_thcs"
  const completed_thcs = cultural === "completed_thcs"
  const has_higher_voc = ["trung_cap", "cao_dang"].includes(vocational ?? "none")

  if (grad_thpt) return {
    label: "Theo trường THPT/GDTX đã học",
    tone: "info",
    description: "KV tự động tính từ các trường THPT/GDTX ghi ở tab Học tập. Thông tư 05/2021 áp dụng quy tắc trường học lâu nhất + ưu tiên trường tốt nghiệp khi thời gian học bằng nhau.",
  }
  if (completed_thpt && has_higher_voc) return {
    label: "Theo trường THPT đã học (liên thông từ TC/CĐ)",
    tone: "info",
    description: "Chưa tốt nghiệp THPT nhưng đã có bằng Trung cấp/Cao đẳng → áp dụng đường liên thông, KV vẫn tính theo lịch sử THPT.",
  }
  if (grad_thcs && has_higher_voc) return {
    label: "Theo trường Trung cấp đã học",
    tone: "info",
    description: "Đã tốt nghiệp THCS + có bằng Trung cấp/Cao đẳng → KV tính từ trường Trung cấp đã học ghi ở tab Học tập.",
  }
  if (completed_thpt || grad_thcs || completed_thcs) return {
    label: "Theo hộ khẩu thường trú",
    tone: "info",
    description: "Trình độ chưa đủ để dùng lịch sử trường học → hệ thống lấy KV theo xã/phường hộ khẩu thường trú (cần khai mã xã ở tab Thông tin cá nhân).",
  }
  return null
}

export function PriorityTab({ form, profile, isEditable }: PriorityTabProps) {
  const cultural = form.watch("cultural_education_level")
  const vocational = form.watch("vocational_qualification")
  const areaBasis = form.watch("area_resolution_basis")
  const preview = previewBasis(cultural, vocational, areaBasis)

  // BE-computed snapshot (authoritative — frozen T1/T6)
  const snapshot = (profile as any).priority_resolution_snapshot as
    | { kv_resolved?: string; rule_applied?: string; pathway?: string; breakdown?: any; requires_manual_override?: boolean; reason?: string }
    | null
    | undefined

  const kvBadge = snapshot?.kv_resolved ? KV_TONE_VI[snapshot.kv_resolved] : null

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
            Thông tư 05/2021/TT-BLĐTBXH Phụ lục 01.
          </p>
          <ul className="text-xs space-y-1 list-disc pl-5">
            <li><strong>KV1</strong>: cộng <strong>0,75đ</strong> — vùng miền núi, dân tộc thiểu số, biên giới, hải đảo</li>
            <li><strong>KV2-NT</strong>: cộng <strong>0,50đ</strong> — nông thôn không thuộc KV1</li>
            <li><strong>KV2</strong>: cộng <strong>0,25đ</strong> — thành phố thuộc tỉnh, thị xã, phường ngoại thành TP trực thuộc TƯ</li>
            <li><strong>KV3</strong>: <strong>không cộng điểm</strong> — nội thành TP trực thuộc TƯ (Hà Nội, HCM, ...)</li>
          </ul>
          <p className="text-xs pt-1">
            <strong>Cách tính:</strong> Mặc định KV lấy tự động từ lịch sử các trường đã học (tab <em>Học tập</em>).
            Có 4 trường hợp đặc biệt dùng hộ khẩu thay vì trường học: <em>Phổ thông Dân tộc Nội trú, lớp dự bị đại học, quân nhân tại ngũ, bộ đội xuất ngũ</em>.
          </p>
        </CardContent>
      </Card>

      {/* ───────── 2. SNAPSHOT KV (BE result, prominent) ───────── */}
      <Card className="border-2 border-primary/20 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <Award className="h-5 w-5 text-primary" />
            Khu vực ưu tiên đã xác định
          </CardTitle>
          <CardDescription className="text-sm">
            Kết quả tự động từ hệ thống — được khóa lại khi nộp hồ sơ (T1) và khi công bố trúng tuyển (T6).
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-2">
          {!snapshot && (
            <div className="rounded-lg border border-dashed p-4 bg-muted/30 text-sm text-muted-foreground flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>
                <strong>Chưa được tính.</strong> KV sẽ tự động xác định khi hồ sơ được nộp.
                Vui lòng khai đầy đủ trình độ học vấn ở phần dưới.
              </span>
            </div>
          )}
          {snapshot && (
            <div className="space-y-3">
              {kvBadge ? (
                <div className="flex items-center gap-3">
                  <span className={`inline-flex items-center px-3 py-1.5 rounded-md text-base font-bold border ${kvBadge.color}`}>
                    {kvBadge.label}
                  </span>
                </div>
              ) : (
                <div className="rounded-lg border border-warning-200 bg-warning-50 p-3 text-sm flex gap-2">
                  <AlertCircle className="h-4 w-4 mt-0.5 text-warning-700 shrink-0" />
                  <div>
                    <p className="font-medium text-warning-800">Chưa xác định được KV</p>
                    {snapshot.reason && (
                      <p className="text-xs text-warning-700 mt-1">Lý do: {snapshot.reason}</p>
                    )}
                    {snapshot.requires_manual_override && (
                      <p className="text-xs text-warning-700 mt-1">→ Cần cán bộ ấn định thủ công.</p>
                    )}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-sm">
                {snapshot.pathway && (
                  <div>
                    <span className="text-xs text-muted-foreground block">Cách tính</span>
                    <span className="text-sm">
                      {PATHWAY_LABEL_VI[snapshot.pathway] ?? snapshot.pathway}
                    </span>
                  </div>
                )}
                {snapshot.rule_applied && (
                  <div>
                    <span className="text-xs text-muted-foreground block">Quy tắc áp dụng</span>
                    <span className="text-sm">
                      {RULE_LABEL_VI[snapshot.rule_applied] ?? snapshot.rule_applied}
                    </span>
                  </div>
                )}
              </div>

              {snapshot.breakdown && (
                <details className="text-xs border rounded p-2 bg-muted/30">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                    Xem chi tiết kỹ thuật (dành cho cán bộ kiểm tra)
                  </summary>
                  <pre className="mt-2 overflow-auto text-[10px]">
                    {JSON.stringify(snapshot.breakdown, null, 2)}
                  </pre>
                </details>
              )}
            </div>
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
            Khai 2 trình độ song song: văn hóa (THCS/THPT/GDTX) và chuyên môn nghề (Sơ cấp/Trung cấp/Cao đẳng nếu có).
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

          {/* Preview cách tính (dựa trên input hiện tại, BE quyết định cuối) */}
          {preview && (
            <div className={`rounded-lg border p-3 ${preview.tone === "warn" ? "bg-warning-50 border-warning-200" : "bg-info-50/50 border-info-200"} flex gap-2`}>
              <Info className={`h-4 w-4 mt-0.5 shrink-0 ${preview.tone === "warn" ? "text-warning-700" : "text-info-700"}`} />
              <div className="text-sm space-y-1">
                <div>
                  <span className="text-xs text-muted-foreground">Dự kiến cách tính KV:</span>{" "}
                  <strong>{preview.label}</strong>
                </div>
                <p className="text-xs text-muted-foreground">{preview.description}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ───────── 4. CƠ SỞ XÁC ĐỊNH KV ───────── */}
      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <ShieldCheck className="h-5 w-5" />
            Cách tính khu vực ưu tiên
          </CardTitle>
          <CardDescription className="text-sm">
            Mặc định <strong>Bình thường</strong> (tự động theo trường đã học). Chỉ đổi nếu thí sinh thuộc trường hợp đặc biệt hoặc cần cán bộ ấn định thủ công.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6 pt-4">
          <FormField
            control={form.control}
            name="area_resolution_basis"
            render={({ field }) => {
              const selectedOption = AREA_BASIS_OPTIONS.find((o) => o.value === field.value)
              return (
                <FormItem>
                  <FormLabel className="text-sm">Cách tính</FormLabel>
                  <Select
                    onValueChange={(v) => field.onChange(v === "_none" ? null : v)}
                    value={field.value ?? "_none"}
                    disabled={!isEditable}
                  >
                    <FormControl>
                      <SelectTrigger className="bg-background h-auto py-2">
                        <SelectValue placeholder="Bình thường — tự động theo trường đã học" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="_none">— Bình thường (mặc định) —</SelectItem>
                      {AREA_BASIS_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {selectedOption && (
                    <FormDescription className="text-xs leading-relaxed">
                      {selectedOption.description}
                    </FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )
            }}
          />

          {areaBasis === "permanent_address_special" && (
            <FormField
              control={form.control}
              name="permanent_commune_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-sm">Mã xã/phường hộ khẩu thường trú</FormLabel>
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
                    Lấy từ giấy CCCD hoặc sổ hộ khẩu mặt sau.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}

          {areaBasis === "manual_override" && (
            <div className="rounded-lg border p-3 bg-warning-50 border-warning-200 flex gap-2">
              <AlertCircle className="h-4 w-4 mt-0.5 text-warning-700 shrink-0" />
              <div className="text-sm space-y-1">
                <p className="font-medium text-warning-800">Lưu ý — chế độ thủ công</p>
                <p className="text-xs text-warning-700">
                  KV sẽ được cán bộ tuyển sinh chỉ định sau khi thí sinh nộp hồ sơ.
                  Lý do thay đổi <strong>bắt buộc</strong> khai báo và lưu vào nhật ký kiểm toán.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
