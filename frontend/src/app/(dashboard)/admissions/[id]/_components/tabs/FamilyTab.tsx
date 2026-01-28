"use client"

import { useFieldArray, UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Plus, Trash2, Users, UserCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import type { AdmissionProfileUpdate, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

interface FamilyMember {
  id: string;
  full_name: string;
  relationship: string;
  phone: string;
  occupation: string;
  is_primary_guardian: boolean;
}

interface FamilyTabProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

export function FamilyTab({ form, isEditable }: FamilyTabProps) {
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "family_info",
  })

  // Helper to get original index
  const getOriginalIndex = (id: string) => fields.findIndex(f => f.id === id)

  const guardians = fields.filter((f: Partial<FamilyMember>) => f.is_primary_guardian)
  const others = fields.filter((f: Partial<FamilyMember>) => !f.is_primary_guardian)

  const addMember = (isPrimary: boolean) => {
    append({
        full_name: "",
        relationship: isPrimary ? "Bố" : "", // Default hint
        phone: "",
        occupation: "",
        is_primary_guardian: isPrimary
    })
  }

  return (
    <div className="space-y-8">
      {/* 1. NGƯỜI GIÁM HỘ CHÍNH (MANDATORY) */}
      <Card className="shadow-sm">
        <CardHeader className="pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
                <UserCheck className="w-5 h-5 text-primary" />
                Người giám hộ chính
            </CardTitle>
            <CardDescription className="text-sm">
                Người chịu trách nhiệm pháp lý (Bắt buộc)
            </CardDescription>
        </CardHeader>
        
        <CardContent className="space-y-6 pt-6">
           {/* List of Guardians */}
           <div className="space-y-4">
               {guardians.map((field, idx) => {
                   const index = getOriginalIndex(field.id)
                   return (
                       <MemberRow 
                            key={field.id} 
                            form={form} 
                            index={index} 
                            isEditable={isEditable} 
                            onRemove={() => remove(index)}
                            isPrimary={true}
                        />
                   )
               })}
           </div>

           {/* Empty State / Validation Alert */}
           {guardians.length === 0 && (
               <div className="flex items-start gap-3 p-4 bg-warning-50 border border-warning-200 rounded-md text-warning-800">
                  <div className="mt-0.5">⚠️</div>
                  <div className="text-sm">
                      <p className="font-medium">Chưa có người giám hộ chính</p>
                      <p className="opacity-90">Vui lòng thêm ít nhất 01 người giám hộ hợp lệ để tiếp tục.</p>
                  </div>
               </div>
           )}

           {/* ADD BUTTON - Bottom of content */}
           {isEditable && (
               <Button 
                    variant={guardians.length === 0 ? "default" : "outline"}
                    className="w-full sm:w-auto mt-4"
                    onClick={() => addMember(true)}
                >
                    <Plus className="w-4 h-4 mr-2" />
                    Thêm người giám hộ chính
                </Button>
           )}
        </CardContent>
      </Card>

      {/* 2. THÀNH VIÊN KHÁC (OPTIONAL) */}
      <Card className="shadow-sm border-border">
        <CardHeader className="pb-2">
            <CardTitle className="text-lg font-semibold flex items-center gap-2 text-foreground">
                <Users className="w-5 h-5" />
                Thành viên khác
            </CardTitle>
            <CardDescription className="text-sm">
                Bố, mẹ, anh, chị, em (không bắt buộc)
            </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6 pt-6">
           {/* List of Other Members */}
           <div className="space-y-4">
               {others.map((field, idx) => {
                   const index = getOriginalIndex(field.id)
                   return (
                       <MemberRow 
                            key={field.id} 
                            form={form} 
                            index={index} 
                            isEditable={isEditable} 
                            onRemove={() => remove(index)}
                            isPrimary={false}
                        />
                   )
               })}
           </div>

           {/* Empty State - Neutral */}
           {others.length === 0 && (
               <div className="text-center py-8 text-muted-foreground bg-muted/50 rounded-lg border border-dashed border-border">
                  <p>— Chưa có thông tin thành viên khác —</p>
               </div>
           )}

            {/* ADD BUTTON - Bottom */}
            {isEditable && (
                <Button 
                    variant="outline"
                    className="w-full sm:w-auto mt-4"
                    onClick={() => addMember(false)}
                >
                    <Plus className="w-4 h-4 mr-2" />
                    Thêm thành viên
                </Button>
            )}
        </CardContent>
      </Card>
    </div>
  )
}

function MemberRow({ form, index, isEditable, onRemove, isPrimary }: { form: UseFormReturn<AdmissionProfileUpdateInput>, index: number, isEditable: boolean, onRemove: () => void, isPrimary: boolean }) {
    return (
        <div className="p-4 border rounded-lg bg-white relative group">
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                <div className="md:col-span-3">
                    <FormField
                      control={form.control}
                      name={`family_info.${index}.full_name`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Họ và tên</FormLabel>
                          <FormControl>
                            <Input {...field} placeholder="Nguyễn Văn A" disabled={!isEditable} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                </div>
                <div className="md:col-span-2">
                    <FormField
                      control={form.control}
                      name={`family_info.${index}.relationship`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Quan hệ</FormLabel>
                          <FormControl>
                            <Input {...field} placeholder={isPrimary ? "Bố/Mẹ" : "Anh/Chị"} disabled={!isEditable} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                </div>
                <div className="md:col-span-3">
                    <FormField
                      control={form.control}
                      name={`family_info.${index}.phone`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">SĐT</FormLabel>
                          <FormControl>
                            <Input {...field} placeholder="09xxxxxxxx" disabled={!isEditable} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                </div>
                <div className="md:col-span-3">
                    <FormField
                      control={form.control}
                      name={`family_info.${index}.occupation`}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs">Nghề nghiệp</FormLabel>
                          <FormControl>
                            <Input {...field} placeholder="Công nhân..." disabled={!isEditable} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                </div>
                
                {isEditable && (
                    <div className="md:col-span-1 flex items-end justify-end pb-2">
                        <Button variant="ghost" size="icon" onClick={onRemove} className="text-destructive hover:bg-error-50">
                            <Trash2 className="w-4 h-4" />
                        </Button>
                    </div>
                )}
            </div>
            {isPrimary && (
                <div className="absolute top-2 right-2">
                    <Badge variant="secondary" className="bg-info-100 text-info-700">Giám hộ chính</Badge>
                </div>
            )}
        </div>
    )
}
