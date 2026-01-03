"use client"

import { UseFormReturn, FieldValues } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Calculator, CheckCircle2, XCircle } from "lucide-react"

interface ScoresTabProps {
  form: UseFormReturn<FieldValues>
  isEditable: boolean
  minGpa: number
}

export function ScoresTab({ form, isEditable, minGpa }: ScoresTabProps) {
  // Real-time Calculation Logic
  const gpa = form.watch("admission_scores.gpa") || 0
  const math = form.watch("admission_scores.math_score") || 0
  const literature = form.watch("admission_scores.literature_score") || 0
  const english = form.watch("admission_scores.english_score") || 0

  // Ensure gpa is valid number for comparison
  const currentGpa = gpa ? parseFloat(gpa) : 0

  const rules = [
    { label: `GPA ≥ ${minGpa.toFixed(1)}`, passed: currentGpa >= minGpa, value: currentGpa > 0 ? currentGpa.toFixed(1) : "--" },
    { label: "Điểm thành phần có nhập", passed: (math > 0 || literature > 0 || english > 0), value: "Đã kiểm tra" }
  ]

  const isQualified = currentGpa >= minGpa && currentGpa > 0

  return (
    <div className="space-y-6">
       <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* LEFT: INPUTS */}
          <Card className="lg:col-span-2">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Calculator className="w-5 h-5" />
                    Nhập điểm xét tuyển
                </CardTitle>
                <CardDescription>Nhập điểm để hệ thống tính toán điều kiện</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="admission_scores.gpa"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Điểm trung bình (GPA) *</FormLabel>
                      <FormControl>
                        <Input 
                            type="number" 
                            step="0.1" 
                            max={10} 
                            disabled={!isEditable} 
                            {...field}
                            value={field.value ?? ""}
                            onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : undefined)}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="grid grid-cols-3 gap-4">
                    <FormField
                      control={form.control}
                      name="admission_scores.math_score"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Toán</FormLabel>
                          <FormControl>
                            <Input 
                                type="number" step="0.1" 
                                disabled={!isEditable} 
                                {...field}
                                value={field.value ?? ""}
                                onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : undefined)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                     <FormField
                      control={form.control}
                      name="admission_scores.literature_score"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Văn</FormLabel>
                          <FormControl>
                            <Input 
                                type="number" step="0.1" 
                                disabled={!isEditable} 
                                {...field}
                                value={field.value ?? ""}
                                onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : undefined)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                     <FormField
                      control={form.control}
                      name="admission_scores.english_score"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Anh</FormLabel>
                          <FormControl>
                            <Input 
                                type="number" step="0.1" 
                                disabled={!isEditable} 
                                {...field}
                                value={field.value ?? ""}
                                onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : undefined)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                </div>
            </CardContent>
          </Card>

          {/* RIGHT: RESULT PANEL (Col span 1) */}
          <Card className={isQualified ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"}>
              <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                      {isQualified ? <CheckCircle2 className="text-green-600" /> : <XCircle className="text-red-600" />}
                      KẾT QUẢ XÉT TUYỂN
                  </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                  <div className="space-y-2">
                      {rules.map((rule, idx) => (
                          <div key={idx} className="flex justify-between items-center text-sm">
                              <span>{rule.label}</span>
                              <div className="flex items-center gap-2">
                                  <span className="font-medium text-muted-foreground">{rule.value}</span>
                                  {rule.passed ? <CheckCircle2 className="w-4 h-4 text-green-600" /> : <XCircle className="w-4 h-4 text-red-600" />}
                              </div>
                          </div>
                      ))}
                  </div>

                  <div className="pt-4 border-t border-dashed">
                      <div className="flex justify-between items-center font-semibold">
                          <span>Trạng thái:</span>
                          <span className={isQualified ? "text-green-700" : "text-red-700"}>
                              {isQualified ? "ĐẠT" : "CHƯA ĐẠT"}
                          </span>
                      </div>
                      {!isQualified && (
                          <p className="text-xs text-red-600 mt-2">
                              → Thiếu: {currentGpa < minGpa ? "GPA thấp hơn quy định" : "Chưa nhập đủ điểm"}
                          </p>
                      )}
                  </div>
              </CardContent>
          </Card>
       </div>
    </div>
  )
}
