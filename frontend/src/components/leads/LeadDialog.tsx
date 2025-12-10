// src/components/leads/LeadDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { 
  Loader2, 
  Info, 
  User, 
  Mail, 
  Phone, 
  Building2, 
  GraduationCap, 
  MapPin,
  Users,
  Megaphone
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { leadsApi } from "@/lib/api/leads";

import { Button } from "@/components/ui/button";
import { FormDialog } from "@/components/ui/form-dialog";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useCreateLead, useUpdateLead } from "@/hooks/useLeads";
import { useAuth } from "@/hooks/useAuth";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { SmartUnitSelector, SmartOfferingSelector } from "@/components/common/selectors";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import type { Lead } from "@/types/lead.types";

// Vietnam phone regex - matches backend validation
// Format: 0 + (3|5|7|8|9|2) + 8-9 digits = 10-11 total
// Supports: 0xxxxxxxxx, +84xxxxxxxxx, 84xxxxxxxxx
const VIETNAM_PHONE_REGEX = /^(0|\+?84)(3|5|7|8|9|2)\d{8,9}$/;

// Helper to normalize phone for validation (remove spaces, dashes)
const normalizePhone = (phone: string): string => {
  return phone.replace(/[\s\-.()/]/g, "");
};

// Validation schema - unit_id is optional (can be auto-determined from offering)
const leadSchema = z.object({
  full_name: z
    .string()
    .min(1, "Họ và tên là bắt buộc")
    .max(120, "Họ và tên tối đa 120 ký tự"),
  email: z
    .string()
    .email("Email không hợp lệ")
    .optional()
    .or(z.literal(""))
    .nullable(),
  phone: z
    .string()
    .min(1, "Số điện thoại là bắt buộc")
    .transform(normalizePhone)
    .refine((val) => VIETNAM_PHONE_REGEX.test(val), {
      message: "Số điện thoại Việt Nam không hợp lệ (VD: 0901234567, +84901234567)",
    }),
  phone2: z
    .string()
    .transform((val) => (val?.trim() === "" ? null : normalizePhone(val || "")))
    .refine((val) => val === null || VIETNAM_PHONE_REGEX.test(val), {
      message: "Số điện thoại phụ không hợp lệ (VD: 0901234567, +84901234567)",
    })
    .nullable()
    .optional(),
  source: z.enum([
    "website",
    "referral",
    "social_media",
    "walk_in",
    "email",
    "phone",
    "event",
    "other",
  ] as const),
  education_level: z
    .enum([
      "high_school",
      "diploma",
      "bachelor",
      "master",
      "phd",
      "other",
    ] as const)
    .optional()
    .nullable(),
  gpa: z
    .number()
    .min(0, "GPA phải từ 0")
    .max(4, "GPA tối đa 4.0")
    .optional()
    .nullable(),
  location: z.string().max(255, "Địa điểm tối đa 255 ký tự").optional().nullable(),
  offering_id: z.number().optional().nullable(),
  // unit_id is optional for Admin when offering_id is provided (auto-determined from distribution config)
  unit_id: z.string().optional().nullable(),
  // For Admin/Manager: choose officer or use auto-assignment
  // "auto" = automatic distribution, number string = specific officer ID
  assigned_officer_id: z.string().optional().nullable(),
  // Fit Score fields
  birth_year: z.number().min(1900).max(2100).optional().nullable(),
  location_proximity: z.number().min(0).max(2).default(0), // 0=Xa, 1=Lân cận, 2=Gần
  occupation_relevance: z.number().min(0).max(2).default(0), // 0=Không, 1=Gián tiếp, 2=Trực tiếp
  academic_performance: z.number().min(0).max(3).default(0), // 0=Yếu, 1=TB, 2=Khá, 3=Giỏi
}).refine(
  (data) => {
    // phone2 must differ from phone (if both provided)
    if (data.phone2 && data.phone) {
      return data.phone2 !== data.phone;
    }
    return true;
  },
  {
    message: "Số điện thoại phụ phải khác số điện thoại chính",
    path: ["phone2"],
  }
);

// Distribution preview response type
interface DistributionPreview {
  offering_id: number;
  has_config: boolean;
  next_unit_id: number | null;
  next_unit_name: string | null;
  configs: Array<{
    unit_id: number;
    unit_name: string;
    weight: number;
    priority: number;
  }>;
  total_slots: number;
}

type LeadFormValues = z.infer<typeof leadSchema>;

interface LeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead?: Lead | null;
  mode: "create" | "edit";
}

export function LeadDialog({ open, onOpenChange, lead, mode }: LeadDialogProps) {
  const createMutation = useCreateLead();
  const updateMutation = useUpdateLead();
  const { user } = useAuth(); // Get current user for unit auto-fill

  const isCreate = mode === "create";
  const isEdit = mode === "edit";
  const isOfficer = user?.role === "officer"; // Officers can only create in their own unit
  const isAdmin = user?.role === "admin";
  const isManager = user?.role === "manager";
  const canSelectOfficer = isCreate && (isAdmin || isManager); // Only Admin/Manager can select officer when creating

  const form = useForm<LeadFormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: isEdit && lead
      ? {
          full_name: lead.full_name,
          email: lead.email || "",
          phone: lead.phone,
          phone2: lead.phone2 || null,
          source: lead.source,
          education_level: lead.education_level || null,
          gpa: lead.gpa ?? null,
          location: lead.location || null,
          offering_id: lead.offering_id ?? null,
          unit_id: lead.unit_id?.toString() || "",
          // Fit Score fields
          birth_year: lead.birth_year ?? null,
          location_proximity: lead.location_proximity ?? 0,
          occupation_relevance: lead.occupation_relevance ?? 0,
          academic_performance: lead.academic_performance ?? 0,
        }
      : {
          full_name: "",
          email: "",
          phone: "",
          phone2: null,
          source: "website" as const,
          education_level: null,
          gpa: null,
          location: null,
          offering_id: null,
          unit_id: user?.unit_id?.toString() || "", // Auto-fill with current user's unit
          assigned_officer_id: "auto", // Default to auto-assignment
          // Fit Score defaults
          birth_year: null,
          location_proximity: 0,
          occupation_relevance: 0,
          academic_performance: 0,
        },
  });

  // Watch unit_id and offering_id
  const selectedUnitId = form.watch("unit_id");
  const selectedOfferingId = form.watch("offering_id");
  const selectedOfficerId = form.watch("assigned_officer_id");

  // Manager uses distribution when they select "auto" (not a specific officer)
  const managerUsesDistribution = isManager && (!selectedOfficerId || selectedOfficerId === "auto");

  // Fetch distribution preview when offering is selected (Admin or Manager with auto-assign)
  const { data: distributionPreview, isLoading: isLoadingPreview } = useQuery<DistributionPreview>({
    queryKey: ["distribution-preview", selectedOfferingId],
    queryFn: async () => {
      const response = await leadsApi.getDistributionPreview(selectedOfferingId!);
      return response;
    },
    enabled: isCreate && (isAdmin || managerUsesDistribution) && !!selectedOfferingId,
    staleTime: 30000, // Cache for 30 seconds
  });

  // Fetch officers for the selected unit (only for Admin/Manager when creating)
  const { data: officersData } = useAdminUsersList({
    unit_id: selectedUnitId ? parseInt(selectedUnitId, 10) : undefined,
    role: "officer",
    status: "active",
    page_size: 100, // Get all officers in unit
  });

  // Filter to only show available officers
  const availableOfficers = officersData?.users?.filter(
    (u) => u.availability_status === "available" || u.availability_status === undefined
  ) || [];

  // Reset form when dialog opens or lead changes
  useEffect(() => {
    if (!open) {
      form.reset();
      return;
    }

    if (isEdit && lead) {
      form.reset({
        full_name: lead.full_name,
        email: lead.email || "",
        phone: lead.phone,
        phone2: lead.phone2 || null,
        source: lead.source,
        education_level: lead.education_level || null,
        gpa: lead.gpa ?? null,
        location: lead.location || null,
        offering_id: lead.offering_id ?? null,
        unit_id: lead.unit_id?.toString() || "",
      });
    } else if (isCreate) {
      form.reset({
        full_name: "",
        email: "",
        phone: "",
        phone2: null,
        source: "website" as const,
        education_level: null,
        gpa: null,
        location: null,
        offering_id: null,
        unit_id: user?.unit_id?.toString() || "", // Auto-fill with current user's unit
        assigned_officer_id: "auto", // Default to auto-assignment
      });
    }
  }, [open, lead, isEdit, isCreate, form, user]);

  const onSubmit = async (data: LeadFormValues) => {
    // Convert unit_id string to number for API (null if not provided - will be auto-determined)
    // Convert assigned_officer_id: "auto" -> null, number string -> number
    const apiData = {
      ...data,
      unit_id: data.unit_id ? parseInt(data.unit_id, 10) : null,
      assigned_officer_id:
        data.assigned_officer_id && data.assigned_officer_id !== "auto"
          ? parseInt(data.assigned_officer_id, 10)
          : null, // null = auto-assignment
    };

    if (isCreate) {
      createMutation.mutate(apiData, {
        onSuccess: () => {
          onOpenChange(false);
        },
      });
    } else if (isEdit && lead) {
      // Don't send assigned_officer_id for updates (use separate assign endpoint)
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { assigned_officer_id: _assigned_officer_id, ...updateData } = apiData;
      updateMutation.mutate(
        { id: lead.id, data: updateData },
        {
          onSuccess: () => {
            onOpenChange(false);
          },
        }
      );
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;
  const { isDirty } = form.formState;

  return (
    <FormDialog open={open} onOpenChange={onOpenChange} isDirty={isDirty}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Tạo Lead Mới" : "Chỉnh sửa Lead"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Thêm lead mới vào hệ thống. Vui lòng điền các thông tin bên dưới."
              : "Cập nhật thông tin lead. Các thay đổi sẽ được lưu ngay lập tức."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Basic Information Section */}
            <div className="space-y-4">
              <div className="flex items-center gap-2 pb-2 border-b">
                <User className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Thông tin cơ bản</h3>
              </div>

              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Họ và tên <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <div className="relative">
                        <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <Input className="pl-10" placeholder="Nguyễn Văn A" {...field} />
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="email"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Email</FormLabel>
                      <FormControl>
                        <div className="relative">
                          <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                          <Input 
                            className="pl-10" 
                            type="email" 
                            placeholder="email@example.com" 
                            {...field} 
                            value={field.value ?? ""} 
                          />
                        </div>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="phone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Số điện thoại <span className="text-destructive">*</span></FormLabel>
                      <FormControl>
                        <div className="relative">
                          <Phone className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                          <Input className="pl-10" placeholder="0901234567" {...field} />
                        </div>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="phone2"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số điện thoại phụ</FormLabel>
                    <FormControl>
                      <div className="relative">
                        <Phone className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                        <Input
                          className="pl-10"
                          placeholder="0901234567"
                          {...field}
                          value={field.value ?? ""}
                        />
                      </div>
                    </FormControl>
                    <FormDescription>Số liên hệ phụ (không bắt buộc)</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="source"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Megaphone className="h-3.5 w-3.5" />
                        Nguồn lead <span className="text-destructive">*</span>
                      </FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn nguồn" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {LEAD_SOURCE_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="unit_id"
                  render={({ field }) => {
                    // Unit is optional for Admin when offering has distribution config
                    const unitOptional = isAdmin && distributionPreview?.has_config;
                    // Hide unit selector for Officer/Manager (auto-filled)
                    const hideUnitSelector = isOfficer || isManager;

                    return (
                      <FormItem>
                        <FormLabel className="flex items-center gap-1.5">
                          <Building2 className="h-3.5 w-3.5" />
                          Đơn vị tổ chức {!unitOptional && !hideUnitSelector && <span className="text-destructive">*</span>}
                        </FormLabel>
                        <FormControl>
                          <SmartUnitSelector
                            value={field.value ?? ""}
                            onChange={(val) => field.onChange(val || "")}
                            placeholder={unitOptional ? "Tự động (từ cấu hình phân phối)" : "Chọn đơn vị"}
                            disabled={hideUnitSelector}
                            variant="select"
                          />
                        </FormControl>
                        {isOfficer && (
                          <FormDescription>
                            Bạn chỉ có thể tạo lead trong đơn vị được phân công
                          </FormDescription>
                        )}
                        {isManager && (
                          <FormDescription>
                            Lead sẽ được tạo trong đơn vị của bạn
                          </FormDescription>
                        )}
                        {unitOptional && (
                          <FormDescription className="text-blue-600">
                            Tùy chọn - đơn vị sẽ được xác định từ cấu hình phân phối
                          </FormDescription>
                        )}
                        <FormMessage />
                      </FormItem>
                    );
                  }}
                />
              </div>

              <FormField
                control={form.control}
                name="offering_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Chương trình đào tạo</FormLabel>
                    <FormControl>
                      <SmartOfferingSelector
                        value={field.value?.toString()}
                        onChange={(val) => field.onChange(val ? parseInt(val, 10) : null)}
                        placeholder="Chọn chương trình (tùy chọn)"
                        allowAll
                        allLabel="Không chọn"
                        variant="combobox"
                      />
                    </FormControl>
                    <FormDescription>Chương trình mà lead quan tâm</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Distribution Preview - Show when Admin/Manager(auto) selects an offering */}
              {isCreate && (isAdmin || managerUsesDistribution) && selectedOfferingId && (
                <div className="rounded-lg border bg-muted/50 p-4 space-y-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Info className="h-4 w-4 text-blue-500" />
                    Xem trước phân phối
                  </div>
                  {isLoadingPreview ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Đang tải cấu hình phân phối...
                    </div>
                  ) : distributionPreview?.has_config ? (
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Đơn vị tiếp theo nhận lead:</span>
                        <span className="font-medium text-green-600">
                          {distributionPreview.next_unit_name}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Phân phối: {distributionPreview.configs.map(c =>
                          `${c.unit_name} (trọng số: ${c.weight})`
                        ).join(", ")}
                      </div>
                      <div className="text-xs text-blue-600">
                        {isManager
                          ? "Lead sẽ được chuyển đến đơn vị này theo cấu hình phân phối."
                          : "Đơn vị sẽ được xác định tự động. Bạn không cần chọn đơn vị thủ công."}
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-amber-600">
                      {isManager
                        ? "Không có cấu hình phân phối. Lead sẽ ở lại đơn vị của bạn."
                        : "Không có cấu hình phân phối cho chương trình này. Vui lòng chọn đơn vị thủ công."}
                    </div>
                  )}
                </div>
              )}

              {/* Officer Assignment - Only for Admin/Manager when creating */}
              {canSelectOfficer && (
                <FormField
                  control={form.control}
                  name="assigned_officer_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Phân công cho tư vấn viên</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value || "auto"}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn tư vấn viên" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="auto">
                            🔄 Phân công tự động (Round Robin)
                          </SelectItem>
                          {availableOfficers.map((officer) => (
                            <SelectItem key={officer.id} value={officer.id.toString()}>
                              {officer.full_name} ({officer.email})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        {field.value === "auto" || !field.value
                          ? "Hệ thống sẽ tự động phân công cho tư vấn viên có sẵn"
                          : "Lead sẽ được phân công trực tiếp cho tư vấn viên đã chọn"}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>

            {/* Academic Information Section */}
            <div className="space-y-4">
              <div className="flex items-center gap-2 pb-2 border-b">
                <GraduationCap className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Thông tin học vấn</h3>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="education_level"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <GraduationCap className="h-3.5 w-3.5" />
                        Trình độ học vấn
                      </FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value || undefined}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn trình độ" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="high_school">THPT</SelectItem>
                          <SelectItem value="diploma">Trung cấp / Cao đẳng</SelectItem>
                          <SelectItem value="bachelor">Đại học</SelectItem>
                          <SelectItem value="master">Thạc sĩ</SelectItem>
                          <SelectItem value="phd">Tiến sĩ</SelectItem>
                          <SelectItem value="other">Khác</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="gpa"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>GPA</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          max="4"
                          placeholder="3.5"
                          {...field}
                          value={field.value ?? ""}
                          onChange={(e) =>
                            field.onChange(
                              e.target.value ? parseFloat(e.target.value) : null
                            )
                          }
                        />
                      </FormControl>
                      <FormDescription>Thang điểm: 0.0 - 4.0</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="location"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5" />
                      Địa điểm
                    </FormLabel>
                    <FormControl>
                      <div className="relative">
                        <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <Input
                          className="pl-10"
                          placeholder="TP. Hồ Chí Minh"
                          {...field}
                          value={field.value ?? ""}
                        />
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Fit Score Assessment Section */}
              <div className="pt-4 mt-4 border-t space-y-4">
                <div className="flex items-center gap-2 pb-2">
                  <span className="text-sm font-semibold">📊 Đánh giá Fit Score</span>
                  <span className="text-xs text-muted-foreground">(Officer đánh giá)</span>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <FormField
                    control={form.control}
                    name="birth_year"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Năm sinh</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min="1900"
                            max="2100"
                            placeholder="2000"
                            {...field}
                            value={field.value ?? ""}
                            onChange={(e) =>
                              field.onChange(
                                e.target.value ? parseInt(e.target.value) : null
                              )
                            }
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="academic_performance"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Học lực</FormLabel>
                        <Select
                          onValueChange={(val) => field.onChange(parseInt(val))}
                          value={field.value?.toString() || "0"}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Chọn học lực" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="0">Yếu / Chưa xác định</SelectItem>
                            <SelectItem value="1">Trung bình (+1đ)</SelectItem>
                            <SelectItem value="2">Khá (+2đ)</SelectItem>
                            <SelectItem value="3">Giỏi (+3đ)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="location_proximity"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Khu vực</FormLabel>
                        <Select
                          onValueChange={(val) => field.onChange(parseInt(val))}
                          value={field.value?.toString() || "0"}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Chọn mức độ gần" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="0">Xa / Không xác định</SelectItem>
                            <SelectItem value="1">Tỉnh lân cận (+2đ)</SelectItem>
                            <SelectItem value="2">Gần cơ sở (+5đ)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="occupation_relevance"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nghề nghiệp liên quan</FormLabel>
                        <Select
                          onValueChange={(val) => field.onChange(parseInt(val))}
                          value={field.value?.toString() || "0"}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Chọn mức độ" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="0">Không liên quan</SelectItem>
                            <SelectItem value="1">Liên quan gián tiếp (+2đ)</SelectItem>
                            <SelectItem value="2">Liên quan trực tiếp (+5đ)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isCreate ? "Tạo Lead" : "Lưu thay đổi"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </FormDialog>
  );
}
