"use client"

/**
 * Academic History Tab Component
 * 
 * Dynamic form for managing school records.
 */

import { useFieldArray, UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Plus, Trash2, GraduationCap } from "lucide-react"
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
      school_name: "",
      year_from: new Date().getFullYear() - 3,
      year_to: new Date().getFullYear(),
      gpa: null,
    })
  }

  return (
    <div className="space-y-8">
        <Card className="shadow-sm border-border">
            <CardHeader className="pb-2">
                <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
                <GraduationCap className="h-5 w-5" />
                Lịch sử học tập
                </CardTitle>
                <CardDescription className="text-sm">
                Thông tin các trường đã học (từ cấp 2, cấp 3...)
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
                                <Trash2 className="h-4 w-4" />
                                </Button>
                            )}
                        </div>
                        
                        <div className="grid gap-6 md:grid-cols-2">
                        <div className="md:col-span-2">
                            <FormField
                            control={form.control}
                            name={`academic_history.${index}.school_name`}
                            render={({ field }) => (
                                <FormItem>
                                <FormLabel className="text-xs">Tên trường</FormLabel>
                                <FormControl>
                                    <Input
                                    {...field}
                                    placeholder="VD: THPT Nguyễn Huệ"
                                    disabled={!isEditable}
                                    className="bg-background"
                                    />
                                </FormControl>
                                <FormMessage />
                                </FormItem>
                            )}
                            />
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
                        
                        <div className="grid grid-cols-2 gap-4">
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
                                        <SelectTrigger className="bg-background">
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

                {/* ADD BUTTON */}
                {isEditable && (
                     <Button 
                        variant="outline"
                        className="w-full sm:w-auto mt-4"
                        onClick={addRecord}
                    >
                        <Plus className="w-4 h-4 mr-2" />
                        Thêm trường
                    </Button>
                )}
            </CardContent>
        </Card>
    </div>
  )
}
