"use client"

/**
 * Academic History Tab Component
 *
 * Q9 #07 Phase D.1: dynamic form for managing school records với
 * VnSchool autocomplete dropdown. Selected school populates school_id +
 * level + current_kv display. Free-text fallback nếu trường ngoài hệ
 * thống. Engine `resolve_kv_for_profile()` chỉ resolve KV cho entries
 * có school_id link.
 */

import { useFieldArray, UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Plus, Trash2, GraduationCap } from "lucide-react"
import { VnSchoolPicker } from "@/components/admissions/VnSchoolPicker"
import { VN_SCHOOL_LEVELS } from "@/lib/zod/admissions"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

interface AcademicHistoryTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

// Dải lớp theo cấp học — nguồn DUY NHẤT cho quick-add + phân loại notices,
// tránh magic number rải rác (vd đổi range quick-add nhưng quên đổi filter
// notices → lệch âm thầm). graduationType gán ở lớp cuối cấp. Engine KV chỉ
// dùng entry THPT; THCS display-only.
const GRADE_BANDS = {
  THCS: { start: 6, end: 9, graduationType: "THCS" },
  THPT: { start: 10, end: 12, graduationType: "THPT" },
} as const

type GradeBand = (typeof GRADE_BANDS)[keyof typeof GRADE_BANDS]
const bandYears = (b: { start: number; end: number }) => b.end - b.start + 1
const bandGradesLabel = (b: { start: number; end: number }) =>
  Array.from({ length: bandYears(b) }, (_, i) => b.start + i).join("/")

export function AcademicHistoryTab({ form, isEditable }: AcademicHistoryTabProps) {
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "academic_history",
  })

  const addRecord = () => {
    append({
      school_id: null,
      school_name: "",
      level: null,
      year_from: new Date().getFullYear() - 3,
      year_to: new Date().getFullYear(),
      grade_to: null,
      gpa: null,
    })
  }

  // Quick-add toàn bộ các lớp của một cấp (THPT 10→12, THCS 6→9). Mỗi lớp 1
  // năm, lớp cuối cấp = endYear; officer chỉ cần điền trường + GPA. Trình độ
  // (graduation_type) gán cho MỌI lớp = cấp học quick-add (cả thẻ tương xứng
  // THPT/THCS). Engine yêu cầu lịch sử THPT có school_id để xác định KV.
  const addBand = (band: GradeBand, endYear: number) => {
    const count = bandYears(band)
    for (let i = 0; i < count; i++) {
      const grade = band.start + i
      const year = endYear - (count - 1) + i // lớp đầu = endYear−(count−1) … lớp cuối = endYear
      append({
        school_id: null,
        school_name: "",
        level: null,
        year_from: year,
        year_to: year,
        grade_to: grade,
        gpa: null,
        graduation_type: band.graduationType,
      } as Parameters<typeof append>[0])
    }
  }

  // 3 năm THPT (lớp 10/11/12), tốt nghiệp = năm hiện tại.
  const addThreeYearsThpt = () => addBand(GRADE_BANDS.THPT, new Date().getFullYear())

  // 4 năm THCS (lớp 6/7/8/9). Năm tự lùi: lớp 9 = năm ngay trước khi vào lớp 10
  // nếu hồ sơ đã có THPT (chuỗi liền mạch), else năm hiện tại − 3. Engine KV
  // KHÔNG dùng entry THCS (chỉ lưu hồ sơ).
  const addFourYearsThcs = () => {
    const existing = form.getValues("academic_history") ?? []
    const thptStartYears = existing
      .filter(
        (r) =>
          r?.grade_to != null &&
          r.grade_to >= GRADE_BANDS.THPT.start &&
          r.grade_to <= GRADE_BANDS.THPT.end &&
          r?.year_from != null,
      )
      .map((r) => r.year_from as number)
    const grade9Year = thptStartYears.length
      ? Math.min(...thptStartYears) - 1
      : new Date().getFullYear() - 3
    addBand(GRADE_BANDS.THCS, grade9Year)
  }

  // ── Vệ sinh nhập liệu (Tầng 2) + gợi ý KV (Tầng 3) ─────────────────────────
  // Thuần data-quality hints (cảnh báo MỀM, KHÔNG chặn lưu/nộp) — engine BE
  // mới là nguồn KV/eligibility chính thức (xem priority_service). Đếm theo
  // grade_to (10-12 = THPT, 6-9 = THCS) để hoạt động ngay cả khi chưa chọn
  // trường (level chỉ set sau khi pick từ danh mục).
  const records = (form.watch("academic_history") ?? []) as Array<{
    grade_to?: number | null
    year_to?: number | null
    school_id?: number | null
  }>
  const currentYear = new Date().getFullYear()
  const inBand = (g: number | null | undefined, lo: number, hi: number): boolean =>
    g != null && g >= lo && g <= hi
  const thptRecords = records.filter((r) =>
    inBand(r?.grade_to, GRADE_BANDS.THPT.start, GRADE_BANDS.THPT.end),
  )
  const thcsRecords = records.filter((r) =>
    inBand(r?.grade_to, GRADE_BANDS.THCS.start, GRADE_BANDS.THCS.end),
  )

  const gradeCount = new Map<number, number>()
  records.forEach((r) => {
    if (r?.grade_to != null)
      gradeCount.set(r.grade_to, (gradeCount.get(r.grade_to) ?? 0) + 1)
  })
  const dupGrades = [...gradeCount.entries()]
    .filter(([, c]) => c > 1)
    .map(([g]) => g)
    .sort((a, b) => a - b)
  const hasFutureYear = records.some(
    (r) => r?.year_to != null && r.year_to > currentYear + 1,
  )

  const softNotices: string[] = []
  if (dupGrades.length > 0)
    softNotices.push(
      `Lớp ${dupGrades.join(", ")} xuất hiện nhiều lần — kiểm tra lại nếu không phải chuyển trường giữa năm.`,
    )
  if (thptRecords.length > bandYears(GRADE_BANDS.THPT))
    softNotices.push(
      `Đang có ${thptRecords.length} năm THPT (thường ${bandYears(GRADE_BANDS.THPT)} năm: lớp ${bandGradesLabel(GRADE_BANDS.THPT)}). Nhiều hơn là bình thường nếu chuyển trường.`,
    )
  if (thcsRecords.length > bandYears(GRADE_BANDS.THCS))
    softNotices.push(
      `Đang có ${thcsRecords.length} năm THCS (thường ${bandYears(GRADE_BANDS.THCS)} năm: lớp ${bandGradesLabel(GRADE_BANDS.THCS)}).`,
    )
  if (hasFutureYear)
    softNotices.push(
      `Có năm kết thúc lớn hơn ${currentYear + 1} — kiểm tra lại năm học.`,
    )

  // Tầng 3 — engine chỉ resolve KV từ entry THPT CÓ school_id (chọn từ danh
  // mục). Có dòng THPT nhưng chưa chọn trường nào từ danh mục → KV chưa tính
  // được (fail-closed "insufficient_data"). Hint mềm, không chặn.
  const needsThptCatalogPick =
    thptRecords.length > 0 && !thptRecords.some((r) => r?.school_id != null)

  return (
    <div className="space-y-8">
        <Card className="shadow-sm border-border">
            <CardHeader className="pb-2">
                <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
                <GraduationCap className="h-5 w-5" aria-hidden="true" />
                Lịch sử học tập
                </CardTitle>
                <CardDescription className="text-sm">
                Thông tin các trường đã học (từ cấp 2, cấp 3…)
                </CardDescription>
            </CardHeader>

            <CardContent className="space-y-6 pt-6">
                {/* NOTICES — soft data-quality hints (Tầng 2) + KV-readiness (Tầng 3).
                    KHÔNG chặn lưu/nộp; engine BE là nguồn KV/eligibility chính thức. */}
                {(softNotices.length > 0 || needsThptCatalogPick) && (
                    <div className="space-y-2" data-testid="academic-notices">
                        {needsThptCatalogPick && (
                            <div
                                role="status"
                                data-testid="academic-kv-hint"
                                className="rounded-md border border-info-300 bg-info-50 px-3 py-2 text-xs text-info-900 flex items-start gap-2"
                            >
                                <span aria-hidden="true">ℹ</span>
                                <span>
                                    Để hệ thống tự xác định KV ưu tiên, hãy chọn ít nhất một
                                    trường THPT <strong>từ danh mục</strong> (trường nhập tay
                                    không tự resolve được KV).
                                </span>
                            </div>
                        )}
                        {softNotices.map((msg, i) => (
                            <div
                                key={msg}
                                role="status"
                                data-testid={`academic-notice-${i}`}
                                className="rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-xs text-warning-900 flex items-start gap-2"
                            >
                                <span aria-hidden="true">⚠</span>
                                <span>{msg}</span>
                            </div>
                        ))}
                    </div>
                )}

                {/* LIST */}
                <div className="space-y-3">
                    {fields.map((field, index) => (
                    <div key={field.id} className="p-3 border rounded-lg bg-muted/50 relative group transition-colors hover:bg-card hover:border-info-200 hover:shadow-sm">
                        <div className="flex items-center justify-between mb-3">
                            <span className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Trường #{index + 1}</span>
                            {isEditable && (
                                <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => remove(index)}
                                className="text-muted-foreground hover:text-destructive hover:bg-destructive/10 -mr-2"
                                aria-label="Xóa lịch sử học tập"
                                >
                                <Trash2 className="h-4 w-4" aria-hidden="true" />
                                </Button>
                            )}
                        </div>
                        
                        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                        <div className="col-span-2 md:col-span-5 space-y-2">
                            {/* Picker + ô nhập tay trên CÙNG 1 dòng (tên trường thường ngắn).
                                Khi đã chọn từ danh mục, ô nhập tay ẩn → picker chiếm full width. */}
                            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 items-start">
                                <div
                                    className={
                                        form.watch(`academic_history.${index}.school_id`)
                                            ? "space-y-1 md:col-span-2"
                                            : "space-y-1"
                                    }
                                >
                                    <label className="text-xs font-medium leading-none">
                                        Tên trường (tìm trong danh mục)
                                    </label>
                                    <VnSchoolPicker
                                        value={{
                                            school_id: form.watch(`academic_history.${index}.school_id`) ?? null,
                                            school_name: form.watch(`academic_history.${index}.school_name`) ?? "",
                                            level: form.watch(`academic_history.${index}.level`) ?? null,
                                            current_kv: null,
                                        }}
                                        onChange={(v) => {
                                            form.setValue(`academic_history.${index}.school_id`, v.school_id, { shouldDirty: true })
                                            // `shouldValidate: true` — picking a school sets the value
                                            // programmatically, which does NOT re-run validation by default;
                                            // without it a prior "Tên trường không được để trống" error
                                            // (set when the row was empty) would persist even after a school
                                            // is selected. Re-validating clears the stale error.
                                            form.setValue(`academic_history.${index}.school_name`, v.school_name, {
                                                shouldDirty: true,
                                                shouldValidate: true,
                                            })
                                            form.setValue(
                                                `academic_history.${index}.level`,
                                                v.level as (typeof VN_SCHOOL_LEVELS)[number] | null,
                                                { shouldDirty: true },
                                            )
                                        }}
                                        disabled={!isEditable}
                                    />
                                    {/* Manual error display ONLY when a school is picked (school_id set):
                                        the free-text fallback is unmounted then, so its <FormMessage/>
                                        can't show the error. Gating avoids showing it twice. */}
                                    {form.watch(`academic_history.${index}.school_id`) &&
                                        form.formState.errors.academic_history?.[index]?.school_name?.message && (
                                        <p className="text-xs text-destructive">
                                            {form.formState.errors.academic_history[index]?.school_name?.message as string}
                                        </p>
                                    )}
                                </div>
                                {/* Free-text fallback (ô bên phải) — chỉ khi chưa chọn từ danh mục */}
                                {!form.watch(`academic_history.${index}.school_id`) && (
                                    <FormField
                                        control={form.control}
                                        name={`academic_history.${index}.school_name`}
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel className="text-xs text-muted-foreground">
                                                    Hoặc nhập tên thủ công (trường ngoài danh mục)
                                                </FormLabel>
                                                <FormControl>
                                                    <Input
                                                        {...field}
                                                        value={field.value ?? ""}
                                                        placeholder="VD: THPT Nguyễn Huệ"
                                                        disabled={!isEditable}
                                                        className="bg-background"
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                )}
                            </div>
                            {/* Free-text KV warning — full width dưới 2 ô. Engine resolve KV cần
                                school_id; trường nhập tay không tự resolve được. */}
                            {!form.watch(`academic_history.${index}.school_id`) &&
                                (form.watch(`academic_history.${index}.school_name`) ?? "").trim().length > 0 && (
                                <div
                                    role="alert"
                                    data-testid={`academic-freetext-warning-${index}`}
                                    className="rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-xs text-warning-900 flex items-start gap-2"
                                >
                                    <span aria-hidden="true">⚠</span>
                                    <span>
                                        Trường nhập tay sẽ không dùng được để tự xác định KV. Vui
                                        lòng chọn từ danh mục bên trên, hoặc đề nghị quản lý ấn
                                        định KV thủ công.
                                    </span>
                                </div>
                            )}
                        </div>
                        
                        <div className="contents">
                             <FormField
                                control={form.control}
                                name={`academic_history.${index}.year_from`}
                                render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-xs">Từ năm</FormLabel>
                                    <FormControl>
                                    <Input
                                        {...field}
                                        type="number"
                                        min={1900}
                                        max={2100}
                                        disabled={!isEditable}
                                        className="bg-background"
                                        onChange={(e) => field.onChange(parseInt(e.target.value) || undefined)}
                                    />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                                )}
                            />
                            
                            <FormField
                                control={form.control}
                                name={`academic_history.${index}.year_to`}
                                render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-xs">Đến năm</FormLabel>
                                    <FormControl>
                                    <Input
                                        {...field}
                                        type="number"
                                        min={1900}
                                        max={2100}
                                        disabled={!isEditable}
                                        className="bg-background"
                                        onChange={(e) => field.onChange(parseInt(e.target.value) || undefined)}
                                    />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                                )}
                            />
                        </div>
                        
                        <div className="contents">
                            <FormField
                                control={form.control}
                                name={`academic_history.${index}.grade_to`}
                                render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-xs">Lớp cuối</FormLabel>
                                    <FormControl>
                                    <Input
                                        {...field}
                                        type="number"
                                        min={1}
                                        max={12}
                                        placeholder="VD: 12"
                                        disabled={!isEditable}
                                        value={field.value ?? ""}
                                        className="bg-background"
                                        onChange={(e) => field.onChange(e.target.value ? parseInt(e.target.value) : null)}
                                    />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                                )}
                            />

                             <FormField
                                control={form.control}
                                name={`academic_history.${index}.gpa`}
                                render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-xs">Điểm TB (GPA)</FormLabel>
                                    <FormControl>
                                    <Input
                                        {...field}
                                        type="number"
                                        step="0.1"
                                        min={0}
                                        max={10}
                                        placeholder="0.0 - 10.0"
                                        disabled={!isEditable}
                                        value={field.value ?? ""}
                                        className="bg-background"
                                        onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : null)}
                                    />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                                )}
                            />

                            <FormField
                                control={form.control}
                                name={`academic_history.${index}.graduation_type`}
                                render={({ field }) => (
                                <FormItem>
                                    <FormLabel className="text-xs">Trình độ</FormLabel>
                                    <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                                    <FormControl>
                                        <SelectTrigger className="bg-background h-11 md:h-9" aria-label="Chọn trình độ tốt nghiệp">
                                        <SelectValue placeholder="Chọn" />
                                        </SelectTrigger>
                                    </FormControl>
                                    <SelectContent> 
                                        <SelectItem value="THCS">THCS</SelectItem>
                                        <SelectItem value="THPT">THPT</SelectItem>
                                        <SelectItem value="GDTX">GDTX</SelectItem>
                                        <SelectItem value="Sơ cấp">Sơ cấp</SelectItem>
                                        <SelectItem value="Trung cấp">Trung cấp</SelectItem>
                                        <SelectItem value="Cao đẳng">Cao đẳng</SelectItem>
                                        <SelectItem value="Đại học">Đại học</SelectItem>
                                        <SelectItem value="Khác">Khác</SelectItem>
                                    </SelectContent>
                                    </Select>
                                    <FormMessage />
                                </FormItem>
                                )}
                            />
                        </div>
                        </div>
                    </div>
                    ))}
                </div>

                {/* EMPTY STATE */}
                {fields.length === 0 && (
                     <div className="text-center py-8 text-muted-foreground bg-muted/50 rounded-lg border border-dashed border-border">
                        <p>— Chưa có lịch sử học tập —</p>
                    </div>
                )}

                {/* ADD BUTTONS */}
                {isEditable && (
                    <div className="flex flex-wrap gap-2 mt-4">
                        <Button
                            type="button"
                            variant="outline"
                            onClick={addRecord}
                        >
                            <Plus className="w-4 h-4 mr-2" aria-hidden="true" />
                            Thêm trường
                        </Button>
                        {/* Commit 5 — quick-add 3 năm THPT */}
                        <Button
                            type="button"
                            variant="outline"
                            onClick={addThreeYearsThpt}
                            data-testid="academic-quick-add-thpt"
                        >
                            <Plus className="w-4 h-4 mr-2" aria-hidden="true" />
                            Thêm 3 năm THPT (lớp 10/11/12)
                        </Button>
                        {/* Quick-add 4 năm THCS (lớp 6/7/8/9) */}
                        <Button
                            type="button"
                            variant="outline"
                            onClick={addFourYearsThcs}
                            data-testid="academic-quick-add-thcs"
                        >
                            <Plus className="w-4 h-4 mr-2" aria-hidden="true" />
                            Thêm 4 năm THCS (lớp 6/7/8/9)
                        </Button>
                    </div>
                )}
            </CardContent>
        </Card>
    </div>
  )
}
