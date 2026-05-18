"use client"

/**
 * Priority Tab (Q9 #07 Phase D.2)
 *
 * 2-field cultural/vocational entry per TT 05/2021/TT-BLĐTBXH Phụ lục 01
 * + Luật GDNN 2014/2025. Drives backend `resolve_kv_for_profile()`
 * algorithm (Phase C engine).
 *
 * Architecture (per memory `vercel-react-best-practices` + frontend
 * CLAUDE.md thin-client philosophy):
 * - FE displays BE-computed derived basis (priority_resolution_snapshot)
 * - FE preview matrix (informational only) — BE authoritative on KV resolve
 * - priority_object_codes multiselect DEFERRED to Phase E officer review
 *
 * Fields:
 * - cultural_education_level (5 enum)
 * - vocational_qualification (4 enum)
 * - area_resolution_basis (3 enum: high_school | permanent_address_special | manual_override)
 * - permanent_commune_code (active when basis=permanent_address_special)
 */
import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { FormField, FormItem, FormLabel, FormControl, FormMessage, FormDescription } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Award, ShieldCheck, AlertCircle, Info } from "lucide-react"
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
  { value: "graduated_gdtx", label: "Tốt nghiệp GDTX (cấp 3)" },
]

const VOCATIONAL_OPTIONS = [
  { value: "none", label: "Chưa có" },
  { value: "so_cap", label: "Sơ cấp" },
  { value: "trung_cap", label: "Trung cấp" },
  { value: "cao_dang", label: "Cao đẳng" },
]

const AREA_BASIS_OPTIONS = [
  { value: "high_school", label: "Theo lịch sử học tập (THPT/THCS)" },
  { value: "permanent_address_special", label: "Theo hộ khẩu (PT DTNT / lớp dự bị / quân nhân / xuất ngũ)" },
  { value: "manual_override", label: "Override thủ công (cần officer phê duyệt)" },
]

/**
 * FE preview derive basis level (informational only; BE authoritative).
 * Mirror of backend `_derive_kv_basis_level()` matrix in priority_service.py.
 */
function previewBasisLevel(
  cultural: string | null | undefined,
  vocational: string | null | undefined,
  areaBasis: string | null | undefined,
): { basis: string; description: string } | null {
  if (areaBasis === "permanent_address_special") {
    return { basis: "COMMUNE_SPECIAL", description: "KV xác định theo permanent_commune_code (hộ khẩu)" }
  }
  if (areaBasis === "manual_override") {
    return { basis: "MANUAL", description: "Officer/admin sẽ override KV thủ công với lý do bắt buộc" }
  }
  if (!cultural) {
    return { basis: "NOT_RESOLVED", description: "Cần khai trình độ văn hóa trước" }
  }

  const grad_thpt = ["graduated_thpt", "graduated_gdtx"].includes(cultural)
  const completed_thpt = cultural === "completed_thpt"
  const grad_thcs = cultural === "graduated_thcs"
  const completed_thcs = cultural === "completed_thcs"
  const has_higher_voc = ["trung_cap", "cao_dang"].includes(vocational ?? "none")

  if (grad_thpt) return { basis: "THPT", description: "KV resolve từ lịch sử học THPT" }
  if (completed_thpt && has_higher_voc) return { basis: "THPT", description: "Liên thông THPT + TC/CĐ → KV theo THPT" }
  if (grad_thcs && has_higher_voc) return { basis: "TC", description: "KV resolve từ lịch sử học TC" }
  if (completed_thpt) return { basis: "COMMUNE_FALLBACK", description: "Chưa TN THPT + không TC/CĐ → KV theo hộ khẩu" }
  if (grad_thcs) return { basis: "COMMUNE_FALLBACK", description: "Chỉ TN THCS không có TC/CĐ → KV theo hộ khẩu" }
  if (completed_thcs) return { basis: "COMMUNE_FALLBACK", description: "Chưa TN THCS → KV theo hộ khẩu" }
  return null
}

export function PriorityTab({ form, profile, isEditable }: PriorityTabProps) {
  const cultural = form.watch("cultural_education_level")
  const vocational = form.watch("vocational_qualification")
  const areaBasis = form.watch("area_resolution_basis")
  const preview = previewBasisLevel(cultural, vocational, areaBasis)

  // BE-computed snapshot (authoritative)
  const snapshot = (profile as any).priority_resolution_snapshot as
    | { kv_resolved?: string; rule_applied?: string; pathway?: string; breakdown?: any }
    | null
    | undefined

  return (
    <div className="space-y-8">
      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <Award className="h-5 w-5" />
            Trình độ học vấn (ưu tiên tuyển sinh)
          </CardTitle>
          <CardDescription className="text-sm">
            Theo TT 05/2021/TT-BLĐTBXH Phụ lục 01. Xác định cơ sở tính ưu tiên khu vực (KV).
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6 pt-6">
          <div className="grid gap-6 md:grid-cols-2">
            <FormField
              control={form.control}
              name="cultural_education_level"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs">Trình độ văn hóa</FormLabel>
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
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="vocational_qualification"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs">Trình độ chuyên môn (nghề nghiệp)</FormLabel>
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
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          {/* FE preview matrix derive basis */}
          {preview && (
            <div className="rounded-lg border p-3 bg-muted/50 flex gap-2">
              <Info className="h-4 w-4 mt-0.5 text-info-700 shrink-0" />
              <div className="text-sm">
                <span className="text-muted-foreground">Cơ sở xác định KV (xem trước, BE quyết định cuối):</span>{" "}
                <Badge variant="outline">{preview.basis}</Badge>
                <p className="text-xs text-muted-foreground mt-1">{preview.description}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
            <ShieldCheck className="h-5 w-5" />
            Cơ sở xác định KV
          </CardTitle>
          <CardDescription className="text-sm">
            Mặc định: theo lịch sử học. Đổi sang &ldquo;permanent_address_special&rdquo; nếu là PT DTNT / lớp dự bị / quân nhân / xuất ngũ.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6 pt-6">
          <FormField
            control={form.control}
            name="area_resolution_basis"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs">Cơ sở</FormLabel>
                <Select
                  onValueChange={(v) => field.onChange(v === "_none" ? null : v)}
                  value={field.value ?? "_none"}
                  disabled={!isEditable}
                >
                  <FormControl>
                    <SelectTrigger className="bg-background">
                      <SelectValue placeholder="Mặc định theo lịch sử học..." />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="_none">— Mặc định (theo lịch sử học) —</SelectItem>
                    {AREA_BASIS_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          {areaBasis === "permanent_address_special" && (
            <FormField
              control={form.control}
              name="permanent_commune_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs">Mã xã/phường hộ khẩu thường trú</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      value={field.value ?? ""}
                      placeholder="VD: 01_00025"
                      maxLength={20}
                      disabled={!isEditable}
                      className="bg-background font-mono"
                    />
                  </FormControl>
                  <FormDescription className="text-xs">
                    Format: {`{mã tỉnh}_{mã phường BNV}`} — bắt buộc cho 4 trường hợp đặc biệt
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}

          {areaBasis === "manual_override" && (
            <div className="rounded-lg border p-3 bg-warning-50 border-warning-200 flex gap-2">
              <AlertCircle className="h-4 w-4 mt-0.5 text-warning-700 shrink-0" />
              <div className="text-sm">
                <p className="font-medium text-warning-800">Manual Override</p>
                <p className="text-xs text-warning-700 mt-1">
                  KV sẽ được Officer/Admin set thủ công sau khi hồ sơ nộp. Lý do override bắt buộc khai báo.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* BE-computed snapshot (authoritative read-only display) */}
      {snapshot && (
        <Card className="shadow-sm border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
              <Award className="h-5 w-5" />
              Kết quả xác định KV (Backend)
            </CardTitle>
            <CardDescription className="text-sm">
              Snapshot từ engine resolve_kv_for_profile() — frozen tại submit/publish.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-3 pt-6">
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <span className="text-xs text-muted-foreground">KV resolved</span>
                <div className="mt-1">
                  {snapshot.kv_resolved ? (
                    <Badge className="text-base">{snapshot.kv_resolved}</Badge>
                  ) : (
                    <span className="text-muted-foreground">Chưa xác định</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">Pathway</span>
                <div className="mt-1 text-sm">
                  {snapshot.pathway ?? <span className="text-muted-foreground">—</span>}
                </div>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">Rule applied</span>
                <div className="mt-1 text-sm">
                  {snapshot.rule_applied ?? <span className="text-muted-foreground">—</span>}
                </div>
              </div>
            </div>

            {snapshot.breakdown && (
              <details className="text-xs text-muted-foreground border rounded p-2 bg-muted/50">
                <summary className="cursor-pointer font-medium">Chi tiết breakdown</summary>
                <pre className="mt-2 overflow-auto">{JSON.stringify(snapshot.breakdown, null, 2)}</pre>
              </details>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
