"use client"

import { UseFormReturn, FieldValues } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Calculator, CheckCircle2, XCircle } from "lucide-react"

interface ScoresTabProps {
  form: UseFormReturn<FieldValues>
  isEditable: boolean
}

export function ScoresTab({ form, isEditable }: ScoresTabProps) {
  // Real-time Calculation Logic
  const gpa = form.watch("admission_scores.gpa") || 0
  const math = form.watch("admission_scores.math_score") || 0
  const literature = form.watch("admission_scores.literature_score") || 0
  const english = form.watch("admission_scores.english_score") || 0

  // Hardcoded rules for demo (should come from backend config)
  const rules = [
    { label: "GPA ≥ 5.0", passed: gpa >= 5.0 },
    { label: "Toán hoặc Văn ≥ 5.0", passed: math >= 5.0 || literature >= 5.0 }
  ]

  const isQualified = rules.every(r => r.passed)

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

          {/* RIGHT: RULES */}
          <Card className={`border-l-4 ${isQualified ? "border-l-green-500" : "border-l-red-500"}`}>
             <CardHeader>
                <CardTitle>Quy tắc xét tuyển</CardTitle>
                <CardDescription>Kết quả tự động</CardDescription>
             </CardHeader>
             <CardContent className="space-y-4">
                {rules.map((rule, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                        {rule.passed ? (
                            <CheckCircle2 className="w-5 h-5 text-green-600" />
                        ) : (
                            <XCircle className="w-5 h-5 text-red-600" />
                        )}
                        <span className={rule.passed ? "text-foreground" : "text-muted-foreground"}>
                            {rule.label}
                        </span>
                    </div>
                ))}
                
                <div className={`mt-6 p-4 rounded-lg font-bold text-center border ${isQualified ? "bg-green-50 text-green-700 border-green-200" : "bg-red-50 text-red-700 border-red-200"}`}>
                    {isQualified ? "ĐỦ ĐIỀU KIỆN" : "CHƯA ĐẠT"}
                </div>
             </CardContent>
          </Card>
       </div>
    </div>
  )
}
