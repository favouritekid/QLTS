"use client"

/**
 * Personal Info Tab Component
 * 
 * Handles CCCD input and displays lead information.
 */

import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { User, Phone, Mail, GraduationCap } from "lucide-react"
import type { AdmissionProfileResponse, AdmissionProfileUpdate } from "@/lib/zod/admissions"

interface PersonalInfoTabProps {
  profile: AdmissionProfileResponse
  form: UseFormReturn<AdmissionProfileUpdate>
  isEditable: boolean
}

export function PersonalInfoTab({ profile, form, isEditable }: PersonalInfoTabProps) {
  return (
    <div className="space-y-6">
      {/* CCCD Input */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Thông tin cá nhân</CardTitle>
          <CardDescription>
            Căn cước công dân / Chứng minh nhân dân
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FormField
            control={form.control}
            name="citizen_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>CCCD/CMND</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    placeholder="Nhập 12 số CCCD"
                    maxLength={12}
                    disabled={!isEditable}
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>

      {/* Lead Info (Read-only) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Thông tin từ Lead</CardTitle>
          <CardDescription>
            Dữ liệu được lấy tự động từ hồ sơ Lead
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <User className="h-5 w-5 text-muted-foreground" />
              <div>
                <Label className="text-xs text-muted-foreground">Họ và tên</Label>
                <p className="font-medium">{profile.lead?.full_name || "—"}</p>
              </div>
            </div>
            
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <Phone className="h-5 w-5 text-muted-foreground" />
              <div>
                <Label className="text-xs text-muted-foreground">Số điện thoại</Label>
                <p className="font-mono">{profile.lead?.phone || "—"}</p>
              </div>
            </div>
            
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <Mail className="h-5 w-5 text-muted-foreground" />
              <div>
                <Label className="text-xs text-muted-foreground">Email</Label>
                <p>{profile.lead?.email || "—"}</p>
              </div>
            </div>
            
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <GraduationCap className="h-5 w-5 text-muted-foreground" />
              <div>
                <Label className="text-xs text-muted-foreground">Ngành học</Label>
                <p>{profile.lead?.offering?.program?.name || "—"}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
