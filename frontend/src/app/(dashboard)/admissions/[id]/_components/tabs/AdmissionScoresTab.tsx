"use client"

/**
 * Admission Scores Tab Component
 * 
 * Form for GPA and subject scores.
 */

import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Calculator } from "lucide-react"
import type { AdmissionProfileUpdate } from "@/lib/zod/admissions"

interface AdmissionScoresTabProps {
  form: UseFormReturn<AdmissionProfileUpdate>
  isEditable: boolean
}

export function AdmissionScoresTab({ form, isEditable }: AdmissionScoresTabProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Calculator className="h-5 w-5" />
          Điểm tuyển sinh
        </CardTitle>
        <CardDescription>
          Điểm GPA và các môn thi (thang điểm 10)
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 md:grid-cols-2">
          <FormField
            control={form.control}
            name="admission_scores.gpa"
            render={({ field }) => (
              <FormItem>
                <FormLabel>GPA tổng</FormLabel>
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
            name="admission_scores.math_score"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Điểm Toán</FormLabel>
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
            name="admission_scores.literature_score"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Điểm Văn</FormLabel>
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
            name="admission_scores.english_score"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Điểm Tiếng Anh</FormLabel>
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
        </div>
        
        {/* Score Summary */}
        <div className="mt-6 p-4 bg-muted/50 rounded-lg">
          <p className="text-sm text-muted-foreground">
            Điểm xét tuyển được tính dựa trên quy tắc được áp dụng cho chương trình học.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
