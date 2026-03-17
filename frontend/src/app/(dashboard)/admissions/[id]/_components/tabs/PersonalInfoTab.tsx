"use client"

import { UseFormReturn, useWatch } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Combobox } from "@/components/ui/combobox"

import { useState } from "react"
import type { AddressMode } from "@/lib/api/administrative"
import { AdaptiveAddressSelect } from "@/components/forms/AdaptiveAddressSelect"
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions"
import { useConfigData } from "@/lib/hooks/useConfigData"
import { format } from "date-fns" // Optional if needed for display, but input date handles ISO

interface PersonalInfoTabProps {
  profile: AdmissionProfileResponse
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

export function PersonalInfoTab({ profile, form, isEditable }: PersonalInfoTabProps) {
  // Fetch dynamic categories
  const { data: ethnicities } = useConfigData("ethnicity")
  const { data: religions } = useConfigData("religion")
  const { data: nationalities } = useConfigData("nationality")
  const { data: disabilities } = useConfigData("disability_type")
  const { data: provinces } = useConfigData("province")

  // Watch address fields for reactivity (useWatch triggers re-render on change)
  const permanentProvince = useWatch({ control: form.control, name: "permanent_province" }) || ""
  const permanentDistrict = useWatch({ control: form.control, name: "permanent_district" }) || null
  const permanentWard = useWatch({ control: form.control, name: "permanent_ward" }) || ""

  // Address mode: local state, re-derived when profile.version changes.
  // Uses React's "adjusting state during render" pattern — no useEffect.
  // See: https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  //
  // IMPORTANT: Derive from profile prop (always fresh), NOT from useWatch
  // (which may still reflect old form values before useEffect calls form.reset).
  const [addressMode, setAddressMode] = useState<AddressMode>(
    profile.permanent_district ? "legacy" : "current",
  )
  const [prevVersion, setPrevVersion] = useState(profile.version)
  if (prevVersion !== profile.version) {
    setPrevVersion(profile.version)
    const serverMode: AddressMode = profile.permanent_district ? "legacy" : "current"
    if (addressMode !== serverMode) {
      setAddressMode(serverMode)
    }
  }

  return (
    <div className="space-y-6">
      
      {/* 1. ĐỊNH DANH & CƠ BẢN */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin cơ bản</CardTitle>
          <CardDescription>Thông tin định danh và cá nhân</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-2">
          {/* Họ tên */}
          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem className="col-span-2 md:col-span-1">
                <FormLabel>Họ và tên</FormLabel>
                <FormControl>
                  <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Nhập họ và tên" />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Giới tính */}
          <FormField
            control={form.control}
            name="gender"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Giới tính</FormLabel>
                <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn giới tính" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="Nam">Nam</SelectItem>
                    <SelectItem value="Nữ">Nữ</SelectItem>
                    <SelectItem value="Khác">Khác</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Ngày sinh */}
          <FormField
            control={form.control}
            name="dob" // Zod handles date coercion
            render={({ field }) => (
              <FormItem>
                <FormLabel>Ngày sinh</FormLabel>
                <FormControl>
                  <Input 
                    type="date" 
                    {...field}
                    value={field.value ? format(new Date(field.value), 'yyyy-MM-dd') : ""}
                    onChange={(e) => field.onChange(e.target.value)} 
                    disabled={!isEditable} 
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

           {/* CCCD */}
           <FormField
            control={form.control}
            name="citizen_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>CCCD/CMND</FormLabel>
                <FormControl>
                  <Input {...field} value={field.value || ""} maxLength={12} disabled={!isEditable} placeholder="Số CCCD" />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* BHXH */}
          <FormField
            control={form.control}
            name="social_insurance_number"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Số BHXH (nếu có)</FormLabel>
                <FormControl>
                  <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Mã số BHXH" />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Nơi sinh */}
          <FormField
            control={form.control}
            name="place_of_birth"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Nơi sinh</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    suggestions={provinces?.map(p => p.name) || []}
                    placeholder="Chọn tỉnh/thành phố"
                    searchPlaceholder="Tìm kiếm tỉnh/thành phố..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Quê quán */}
          <FormField
            control={form.control}
            name="native_place"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Quê quán</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    suggestions={provinces?.map(p => p.name) || []}
                    placeholder="Chọn tỉnh/thành phố"
                    searchPlaceholder="Tìm kiếm tỉnh/thành phố..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>

      {/* 2. LIÊN HỆ & ĐỊA CHỈ */}
      <Card>
        <CardHeader>
          <CardTitle>Liên hệ & Địa chỉ</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-2">
            <FormField
              control={form.control}
              name="phone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Số điện thoại</FormLabel>
                  <FormControl>
                    <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Số điện thoại" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Email" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            
            <AdaptiveAddressSelect
              label="Hộ khẩu thường trú"
              provinceValue={permanentProvince}
              districtValue={permanentDistrict}
              wardValue={permanentWard}
              onProvinceChange={(value) => form.setValue("permanent_province", value)}
              onDistrictChange={(value) => form.setValue("permanent_district", value || "")}
              onWardChange={(value) => form.setValue("permanent_ward", value)}
              mode={addressMode}
              onModeChange={setAddressMode}
              disabled={!isEditable}
            />
        </CardContent>
      </Card>

      {/* 3. ĐẶC ĐIỂM (Danh mục động) */}
      <Card>
        <CardHeader>
          <CardTitle>Đặc điểm nhân thân</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-2">
          {/* Quốc tịch */}
          <FormField
            control={form.control}
            name="nationality"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Quốc tịch</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    options={nationalities?.map(n => ({ value: n.code, label: n.name })) || []}
                    placeholder="Chọn quốc tịch"
                    searchPlaceholder="Tìm kiếm quốc tịch..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

           {/* Dân tộc */}
           <FormField
            control={form.control}
            name="ethnicity"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Dân tộc</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    options={ethnicities?.map(e => ({ value: e.code, label: e.name })) || []}
                    placeholder="Chọn dân tộc"
                    searchPlaceholder="Tìm kiếm dân tộc..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

           {/* Tôn giáo */}
           <FormField
            control={form.control}
            name="religion"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Tôn giáo</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    options={religions?.map(r => ({ value: r.code, label: r.name })) || []}
                    placeholder="Chọn tôn giáo"
                    searchPlaceholder="Tìm kiếm tôn giáo..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

           {/* Khuyết tật */}
           <FormField
            control={form.control}
            name="disability_type"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Loại khuyết tật (nếu có)</FormLabel>
                <FormControl>
                  <Combobox
                    value={field.value || ""}
                    onChange={field.onChange}
                    options={disabilities?.map(d => ({ value: d.code, label: d.name })) || []}
                    placeholder="Chọn loại khuyết tật"
                    searchPlaceholder="Tìm kiếm..."
                    emptyText="Không tìm thấy"
                    disabled={!isEditable}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>

      {/* 4. CHÍNH TRỊ */}
      <Card>
        <CardHeader>
          <CardTitle>Chính trị & Xã hội</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-3">
          <FormField
            control={form.control}
            name="union_entry_date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Ngày vào Đoàn</FormLabel>
                <FormControl>
                  <Input 
                    type="date" 
                    {...field} 
                    value={field.value ? format(new Date(field.value), 'yyyy-MM-dd') : ""}
                    onChange={(e) => field.onChange(e.target.value)} 
                    disabled={!isEditable} 
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="party_entry_date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Ngày vào Đảng (Dự bị)</FormLabel>
                <FormControl>
                  <Input 
                    type="date" 
                    {...field} 
                    value={field.value ? format(new Date(field.value), 'yyyy-MM-dd') : ""}
                    onChange={(e) => field.onChange(e.target.value)} 
                    disabled={!isEditable} 
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="party_official_entry_date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Ngày vào Đảng (Chính thức)</FormLabel>
                <FormControl>
                  <Input 
                    type="date" 
                    {...field} 
                    value={field.value ? format(new Date(field.value), 'yyyy-MM-dd') : ""}
                    onChange={(e) => field.onChange(e.target.value)} 
                    disabled={!isEditable} 
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </CardContent>
      </Card>

    </div>
  )
}
