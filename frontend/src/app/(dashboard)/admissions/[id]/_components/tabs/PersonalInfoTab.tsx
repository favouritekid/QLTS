"use client"

import { UseFormReturn } from "react-hook-form"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import type { AdmissionProfileResponse, AdmissionProfileUpdate } from "@/lib/zod/admissions"
import { useConfigData } from "@/lib/hooks/useConfigData"
import { format } from "date-fns" // Optional if needed for display, but input date handles ISO

interface PersonalInfoTabProps {
  profile: AdmissionProfileResponse
  form: UseFormReturn<AdmissionProfileUpdate>
  isEditable: boolean
}

export function PersonalInfoTab({ profile, form, isEditable }: PersonalInfoTabProps) {
  // Fetch dynamic categories
  const { data: ethnicities } = useConfigData("ethnicity")
  const { data: religions } = useConfigData("religion")
  const { data: nationalities } = useConfigData("nationality")
  const { data: disabilities } = useConfigData("disability_type")

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
                    value={field.value ? new Date(field.value).toISOString().split('T')[0] : ""}
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
                  <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Tỉnh/Thành phố nơi sinh" />
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
                  <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Quê quán" />
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
            
            <div className="col-span-2">
              <Label className="mb-2 block">Hộ khẩu thường trú</Label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <FormField
                  control={form.control}
                  name="permanent_province"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Tỉnh/Thành phố" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                 <FormField
                  control={form.control}
                  name="permanent_district"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Quận/Huyện" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                 <FormField
                  control={form.control}
                  name="permanent_ward"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input {...field} value={field.value || ""} disabled={!isEditable} placeholder="Phường/Xã" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </div>
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
                <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn quốc tịch" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {nationalities?.map(item => (
                        <SelectItem key={item.id} value={item.code}>{item.name}</SelectItem>
                    ))}
                    {!nationalities?.length && <SelectItem value="VN" disabled>Đang tải...</SelectItem>}
                  </SelectContent>
                </Select>
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
                <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn dân tộc" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {ethnicities?.map(item => (
                        <SelectItem key={item.id} value={item.code}>{item.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                <Select onValueChange={field.onChange} value={field.value || ""} disabled={!isEditable}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn tôn giáo" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                     {religions?.map(item => (
                        <SelectItem key={item.id} value={item.code}>{item.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                <Select 
                  onValueChange={(val) => field.onChange(val === "no_disability" ? "" : val)} 
                  value={field.value || "no_disability"} 
                  disabled={!isEditable}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Không / Chọn loại" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="no_disability">Không</SelectItem>
                     {disabilities?.map(item => (
                        <SelectItem key={item.id} value={item.code}>{item.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
                    value={field.value ? new Date(field.value).toISOString().split('T')[0] : ""}
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
                    value={field.value ? new Date(field.value).toISOString().split('T')[0] : ""}
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
                    value={field.value ? new Date(field.value).toISOString().split('T')[0] : ""}
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
