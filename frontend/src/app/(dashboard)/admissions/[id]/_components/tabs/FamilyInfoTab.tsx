"use client"

/**
 * Family Info Tab Component
 * 
 * Dynamic form for managing family members using useFieldArray.
 */

import { useFieldArray, UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Plus, Trash2, Users } from "lucide-react"
import type { AdmissionProfileUpdate } from "@/lib/zod/admissions"

interface FamilyInfoTabProps {
  form: UseFormReturn<AdmissionProfileUpdate>
  isEditable: boolean
}

export function FamilyInfoTab({ form, isEditable }: FamilyInfoTabProps) {
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "family_info",
  })

  const addMember = () => {
    append({
      relationship: "",
      full_name: "",
      occupation: "",
      phone: "",
    })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <Users className="h-5 w-5" />
              Thông tin gia đình
            </CardTitle>
            <CardDescription>
              Thêm thông tin phụ huynh hoặc người giám hộ
            </CardDescription>
          </div>
          {isEditable && (
            <Button type="button" variant="outline" size="sm" onClick={addMember}>
              <Plus className="h-4 w-4 mr-1" />
              Thêm thành viên
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {fields.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Users className="h-12 w-12 mx-auto mb-3 opacity-20" />
            <p>Chưa có thông tin gia đình</p>
            {isEditable && (
              <Button type="button" variant="link" onClick={addMember}>
                Thêm thành viên đầu tiên
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {fields.map((field, index) => (
              <div key={field.id} className="p-4 border rounded-lg bg-muted/30">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-medium">Thành viên #{index + 1}</span>
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
                  <FormField
                    control={form.control}
                    name={`family_info.${index}.relationship`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Quan hệ</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            placeholder="VD: Cha, Mẹ, Anh..."
                            disabled={!isEditable}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  
                  <FormField
                    control={form.control}
                    name={`family_info.${index}.full_name`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Họ và tên</FormLabel>
                        <FormControl>
                          <Input {...field} disabled={!isEditable} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  
                  <FormField
                    control={form.control}
                    name={`family_info.${index}.occupation`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nghề nghiệp</FormLabel>
                        <FormControl>
                          <Input {...field} disabled={!isEditable} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  
                  <FormField
                    control={form.control}
                    name={`family_info.${index}.phone`}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Số điện thoại</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            placeholder="0xxxxxxxxx"
                            disabled={!isEditable}
                          />
                        </FormControl>
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
