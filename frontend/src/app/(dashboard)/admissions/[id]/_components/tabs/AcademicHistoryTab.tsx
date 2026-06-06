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
import type { AdmissionProfileUpdate, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

interface AcademicHistoryTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

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

  // Commit 5 — quick-add 3 năm THPT. Tạo 3 record lớp 10/11/12 mặc định
  // dùng năm hiện tại làm tốt nghiệp; officer chỉ cần điền tên trường +
  // GPA. Engine yêu cầu lịch sử THPT để xác định KV → tăng tốc nhập hồ
  // sơ tốt nghiệp năm hiện tại.
  const addThreeYearsThpt = () => {
    const gradYear = new Date().getFullYear()
    for (let i = 0; i < 3; i++) {
      const grade = 10 + i
      const year = gradYear - 2 + i
      append({
        school_id: null,
        school_name: "",
        level: null,
        year_from: year,
        year_to: year,
        grade_to: grade,
        gpa: null,
        graduation_type: grade === 12 ? "THPT" : null,
      } as Parameters<typeof append>[0])
    }
  }

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
                {/* LIST */}
                <div className="space-y-4">
                    {fields.map((field, index) => (
                    <div key={field.id} className="p-4 border rounded-lg bg-muted/50 relative group transition-colors hover:bg-card hover:border-info-200 hover:shadow-sm">
                        <div className="flex items-center justify-between mb-4">
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
                        
                        <div className="grid gap-6 md:grid-cols-2">
                        <div className="md:col-span-2 space-y-2">
                            <div className="space-y-1">
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
                                    in that case the free-text fallback below is unmounted, so its
                                    <FormMessage/> can't show the error. When school_id is null the
                                    free-text FormField already renders the message — gating here avoids
                                    showing "Tên trường không được để trống" twice. */}
                                {form.watch(`academic_history.${index}.school_id`) &&
                                    form.formState.errors.academic_history?.[index]?.school_name?.message && (
                                    <p className="text-xs text-destructive">
                                        {form.formState.errors.academic_history[index]?.school_name?.message as string}
                                    </p>
                                )}
                            </div>
                            {/* Free-text fallback if no school_id picked */}
                            {!form.watch(`academic_history.${index}.school_id`) && (
                                <>
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
                                    {/* Commit 5 — free-text school warning. Engine resolve KV
                                        cần school_id (administrative_nodes link). Trường nhập
                                        tay sẽ không kết nối, KV chỉ resolve được khi quản lý
                                        ấn định thủ công. */}
                                    {(form.watch(`academic_history.${index}.school_name`) ?? "").trim().length > 0 && (
                                        <div
                                            role="alert"
                                            data-testid={`academic-freetext-warning-${index}`}
                                            className="rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-xs text-warning-900 flex items-start gap-2"
                                        >
                                            <span aria-hidden="true">⚠</span>
                                            <span>
                                                Trường nhập tay sẽ không dùng được để tự xác định
                                                KV. Vui lòng chọn từ danh mục bên trên, hoặc đề
                                                nghị quản lý ấn định KV thủ công.
                                            </span>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                        
                        <div className="grid grid-cols-2 gap-4">
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
                        
                        <div className="grid grid-cols-3 gap-4">
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
                                        <SelectTrigger className="bg-background" aria-label="Chọn trình độ tốt nghiệp">
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
                    </div>
                )}
            </CardContent>
        </Card>
    </div>
  )
}
