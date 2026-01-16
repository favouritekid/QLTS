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
import type { AdmissionProfileUpdate } from "@/lib/zod/admissions"

interface AcademicHistoryTabProps {
  form: UseFormReturn<AdmissionProfileUpdate>
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
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <GraduationCap className="h-5 w-5" />
              Lịch sử học tập
            </CardTitle>
            <CardDescription>
              Thông tin các trường đã học
            </CardDescription>
          </div>
          {isEditable && (
            <Button type="button" variant="outline" size="sm" onClick={addRecord}>
              <Plus className="h-4 w-4 mr-1" />
              Thêm trường
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {fields.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <GraduationCap className="h-12 w-12 mx-auto mb-3 opacity-20" />
            <p>Chưa có lịch sử học tập</p>
            {isEditable && (
              <Button type="button" variant="link" onClick={addRecord}>
                Thêm trường học đầu tiên
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {fields.map((field, index) => (
              <div key={field.id} className="p-4 border rounded-lg bg-muted/30">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-medium">Trường #{index + 1}</span>
                  {isEditable && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => remove(index)}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <FormField
                      control={form.control}
                      name={`academic_history.${index}.school_name`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Tên trường</FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              placeholder="VD: THPT Nguyễn Huệ"
                              disabled={!isEditable}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                  
                  <FormField
                    control={form.control}
                    name={`academic_history.${index}.year_from`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Năm bắt đầu</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="number"
                            min={1900}
                            max={2100}
                            disabled={!isEditable}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
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
                        <FormLabel>Năm kết thúc</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="number"
                            min={1900}
                            max={2100}
                            disabled={!isEditable}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
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
                        <FormLabel>Điểm trung bình (GPA)</FormLabel>
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
                        <FormLabel>Trình độ / Loại tốt nghiệp</FormLabel>
                         <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Chọn trình độ" />
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
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
