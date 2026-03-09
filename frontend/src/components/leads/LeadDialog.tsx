// src/components/leads/LeadDialog.tsx
"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Loader2,
  Info,
  ChevronDown,
  ChevronUp,
  Check,
  AlertCircle,
  Plus,
  ChevronsUpDown,
  Users,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { leadsApi } from "@/lib/api/leads"; // architecture-allow legacy
import { getCollaborators } from "@/lib/api/collaborators";

import { Button } from "@/components/ui/button";
import { FormDialog } from "@/components/ui/form-dialog";
import {
  DialogContent,
  DialogDescription,
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

import { useCreateLead, useUpdateLead } from "@/hooks/useLeads";
import { useAuth } from "@/hooks/useAuth";
import {
  isAdmin as checkIsAdmin,
  isManagerOrAbove,
  canSelectOfficer as checkCanSelectOfficer,
} from "@/lib/utils/permissions";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { SmartUnitSelector, SmartOfferingSelector } from "@/components/common/selectors";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import { useDuplicateValidation } from "@/hooks/useDuplicateValidation";
import { cn } from "@/lib/utils";
import { FormRow, FormActions } from "@/components/common/form/ResponsiveFormLayout";
import type { Lead } from "@/types/lead.types";

// Vietnam phone regex - matches backend validation
const VIETNAM_PHONE_REGEX = /^(0|\+?84)(3|5|7|8|9|2)\d{8,9}$/;

// Helper to normalize phone for validation
const normalizePhone = (phone: string): string => {
  return phone.replace(/[\s\-.()/]/g, "");
};

// Validation schema
const leadSchema = z
  .object({
    full_name: z
      .string()
      .min(1, "Họ và tên là bắt buộc")
      .max(120, "Họ và tên tối đa 120 ký tự"),
    email: z.string().email("Email không hợp lệ").optional().or(z.literal("")).nullable(),
    phone: z
      .string()
      .min(1, "Số điện thoại là bắt buộc")
      .transform(normalizePhone)
      .refine((val) => VIETNAM_PHONE_REGEX.test(val), {
        message: "Số điện thoại không hợp lệ (VD: 0901234567)",
      }),
    phone2: z
      .string()
      .transform((val) => (val?.trim() === "" ? null : normalizePhone(val || "")))
      .refine((val) => val === null || VIETNAM_PHONE_REGEX.test(val), {
        message: "Số điện thoại phụ không hợp lệ",
      })
      .nullable()
      .optional(),
    source: z.enum(
      ["website", "referral", "social_media", "walk_in", "email", "phone", "event", "other"],
      { message: "Vui lòng chọn nguồn lead" }
    ),
    education_level: z
      .enum(["high_school", "diploma", "bachelor", "master", "phd", "other"])
      .optional()
      .nullable(),
    gpa: z.number().min(0).max(10).optional().nullable(),
    location: z.string().max(255).optional().nullable(),
    offering_id: z.number().optional().nullable(),
    unit_id: z.string().optional().nullable(),
    assigned_officer_id: z.string().optional().nullable(),
    referrer_id: z.number().optional().nullable(),
    birth_year: z.number().min(1900).max(2100).optional().nullable(),
    location_proximity: z.number().min(0).max(2).optional(),
    occupation_relevance: z.number().min(0).max(2).optional(),
    academic_performance: z.number().min(0).max(3).optional(),
  })
  .refine((data) => !data.phone2 || !data.phone || data.phone2 !== data.phone, {
    message: "Số điện thoại phụ phải khác số chính",
    path: ["phone2"],
  });

// Distribution preview response type
interface DistributionPreview {
  offering_id: number;
  has_config: boolean;
  next_unit_id: number | null;
  next_unit_name: string | null;
  configs: Array<{ unit_id: number; unit_name: string; weight: number; priority: number }>;
  total_slots: number;
}

type LeadFormValues = z.infer<typeof leadSchema>;

interface LeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead?: Lead | null;
  mode: "create" | "edit";
  /** Called after a lead is successfully created (not edit) */
  onCreated?: () => void;
}

// Validation status indicator component
function ValidationIndicator({
  state,
  message,
}: {
  state: "idle" | "checking" | "valid" | "invalid";
  message: string | null;
}) {
  if (state === "idle" && !message) return null;
  if (state === "idle" && message) {
    return (
      <div className="flex items-center gap-1.5 mt-1" role="status" aria-live="polite">
        <Info className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs text-muted-foreground">{message}</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 mt-1" role="status" aria-live="polite">
      {state === "checking" && (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
          <span className="text-xs text-muted-foreground">Đang kiểm tra...</span>
        </>
      )}
      {state === "valid" && (
        <>
          <Check className="h-3.5 w-3.5 text-success-600" aria-hidden="true" />
          <span className="text-xs text-success-600">Hợp lệ</span>
        </>
      )}
      {state === "invalid" && (
        <>
          <AlertCircle className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />
          <span className="text-xs text-destructive">{message}</span>
        </>
      )}
    </div>
  );
}

export function LeadDialog({ open, onOpenChange, lead, mode, onCreated }: LeadDialogProps) {
  const createMutation = useCreateLead();
  const updateMutation = useUpdateLead();
  const { user } = useAuth();

  const isCreate = mode === "create";
  const isEdit = mode === "edit";
  const isOfficer = !isManagerOrAbove(user);
  const isAdmin = checkIsAdmin(user);
  const isManager = isManagerOrAbove(user) && !checkIsAdmin(user);
  const canSelectOfficerInForm = isCreate && checkCanSelectOfficer(user);

  // State for expandable section
  const [showDetails, setShowDetails] = useState(false);
  // State for "Save & Create Another"
  const [createAnother, setCreateAnother] = useState(false);

  const form = useForm<LeadFormValues>({
    resolver: zodResolver(leadSchema),
    defaultValues: {
      full_name: "",
      email: "",
      phone: "",
      phone2: null,
      source: "website",
      education_level: null,
      gpa: null,
      location: null,
      offering_id: null,
      unit_id: user?.unit_id?.toString() || "",
      assigned_officer_id: "auto",
      referrer_id: null,
      birth_year: null,
      location_proximity: 0,
      occupation_relevance: 0,
      academic_performance: 0,
    },
  });

  // State for CTV referrer popover
  const [ctvPopoverOpen, setCtvPopoverOpen] = useState(false);

  // Watch values for conditional rendering
  const selectedUnitId = form.watch("unit_id");
  const selectedOfferingId = form.watch("offering_id");
  const selectedOfficerId = form.watch("assigned_officer_id");
  const selectedSource = form.watch("source");
  const phoneValue = form.watch("phone");
  const emailValue = form.watch("email");

  // Real-time duplicate validation
  const duplicateValidation = useDuplicateValidation({
    unitId: selectedUnitId ? parseInt(selectedUnitId, 10) : undefined,
    excludeId: isEdit && lead ? lead.id : undefined,
  });

  // Trigger phone validation on change
  useEffect(() => {
    if (phoneValue) {
      duplicateValidation.validatePhone(phoneValue);
    }
  }, [phoneValue, duplicateValidation.validatePhone]);

  // Trigger email validation on change
  useEffect(() => {
    if (emailValue && selectedUnitId) {
      duplicateValidation.validateEmail(emailValue);
    }
  }, [emailValue, selectedUnitId, duplicateValidation.validateEmail]);

  // Manager uses distribution when selecting "auto"
  const managerUsesDistribution = isManager && (!selectedOfficerId || selectedOfficerId === "auto");

  // Fetch distribution preview
  const { data: distributionPreview, isLoading: isLoadingPreview } = useQuery<DistributionPreview>({
    queryKey: ["distribution-preview", selectedOfferingId],
    queryFn: () => leadsApi.getDistributionPreview(selectedOfferingId!),
    enabled: isCreate && (isAdmin || managerUsesDistribution) && !!selectedOfferingId,
    staleTime: 30000,
  });

  // Fetch officers for assignment
  const { data: officersData } = useAdminUsersList({
    unit_id: selectedUnitId ? parseInt(selectedUnitId, 10) : undefined,
    role: "officer",
    status: "active",
    page_size: 100,
  });

  const availableOfficers =
    officersData?.users?.filter(
      (u) => u.availability_status === "available" || u.availability_status === undefined
    ) || [];

  // Fetch CTV list when source = "referral"
  const { data: ctvData, isLoading: isLoadingCtv } = useQuery({
    queryKey: ["collaborators-for-referrer"],
    queryFn: () => getCollaborators({ status: "active", limit: 100 }),
    enabled: selectedSource === "referral",
    staleTime: 30000,
  });

  const availableCtv = ctvData?.collaborators || [];

  // Clear referrer_id when source changes away from "referral"
  useEffect(() => {
    if (selectedSource !== "referral") {
      form.setValue("referrer_id", null);
    }
  }, [selectedSource, form]);

  // Destructure stable function references from duplicateValidation
  const { reset: resetDuplicateValidation } = duplicateValidation;

  // Reset form when dialog opens/closes
  useEffect(() => {
    if (!open) {
      form.reset();
      resetDuplicateValidation();
      setShowDetails(false);
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
        referrer_id: lead.referrer_id ?? null,
        birth_year: lead.birth_year ?? null,
        location_proximity: lead.location_proximity ?? 0,
        occupation_relevance: lead.occupation_relevance ?? 0,
        academic_performance: lead.academic_performance ?? 0,
      });
      setShowDetails(true); // Show all fields in edit mode
    } else if (isCreate) {
      form.reset({
        full_name: "",
        email: "",
        phone: "",
        phone2: null,
        source: "website",
        education_level: null,
        gpa: null,
        location: null,
        offering_id: null,
        unit_id: user?.unit_id?.toString() || "",
        assigned_officer_id: "auto",
        referrer_id: null,
        birth_year: null,
        location_proximity: 0,
        occupation_relevance: 0,
        academic_performance: 0,
      });
    }
  }, [open, lead, isEdit, isCreate, form, user, resetDuplicateValidation]);

  const onSubmit = async (data: LeadFormValues, shouldCreateAnother: boolean = false) => {
    // Block submit if duplicate validation failed (phone or email)
    if (duplicateValidation.phone.state === "invalid" || duplicateValidation.email.state === "invalid") {
      return;
    }

    const apiData = {
      ...data,
      unit_id: data.unit_id ? parseInt(data.unit_id, 10) : null,
      assigned_officer_id:
        data.assigned_officer_id && data.assigned_officer_id !== "auto"
          ? parseInt(data.assigned_officer_id, 10)
          : null,
    };

    if (isCreate) {
      createMutation.mutate(apiData, {
        onSuccess: () => {
          onCreated?.();
          if (shouldCreateAnother) {
            // Reset form but keep unit_id and source
            form.reset({
              full_name: "",
              email: "",
              phone: "",
              phone2: null,
              source: data.source,
              education_level: null,
              gpa: null,
              location: null,
              offering_id: null,
              unit_id: data.unit_id,
              assigned_officer_id: "auto",
              referrer_id: null,
              birth_year: null,
              location_proximity: 0,
              occupation_relevance: 0,
              academic_performance: 0,
            });
            resetDuplicateValidation();
          } else {
            onOpenChange(false);
          }
        },
      });
    } else if (isEdit && lead) {
      const { assigned_officer_id: _, ...updateData } = apiData;
      updateMutation.mutate(
        { id: lead.id, data: { ...updateData, version: lead.version } },
        { onSuccess: () => onOpenChange(false) }
      );
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;
  const { isDirty } = form.formState;

  // Check if submit should be blocked (phone OR email invalid/checking)
  const isSubmitBlocked = duplicateValidation.phone.state === "invalid" || duplicateValidation.email.state === "invalid" || duplicateValidation.isChecking;

  return (
    <FormDialog open={open} onOpenChange={onOpenChange} isDirty={isDirty}>
      <DialogContent className="sm:max-w-[550px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Tạo Lead Nhanh" : "Chỉnh sửa Lead"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Nhập thông tin cơ bản để tạo lead mới. Có thể bổ sung chi tiết sau."
              : "Cập nhật thông tin lead."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit((data) => onSubmit(data, false))} className="space-y-4">
            {/* ========== ESSENTIAL FIELDS (Always visible) ========== */}
            <div className="space-y-4">
              {/* Row 1: Name + Phone */}
              <FormRow columns={2}>
                <FormField
                  control={form.control}
                  name="full_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        Họ và tên <span className="text-destructive">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input placeholder="Nguyễn Văn A" autoComplete="name" {...field} />
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
                      <FormLabel>
                        Số điện thoại <span className="text-destructive">*</span>
                      </FormLabel>
                      <FormControl>
                        <div className="relative">
                          <Input
                            className={cn(
                              "pr-8",
                              duplicateValidation.phone.state === "valid" && "border-success-500",
                              duplicateValidation.phone.state === "invalid" && "border-destructive"
                            )}
                            placeholder="0901234567"
                            autoComplete="tel"
                            {...field}
                          />
                          {duplicateValidation.phone.state === "checking" && (
                            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
                          )}
                          {duplicateValidation.phone.state === "valid" && (
                            <Check className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-success-600" />
                          )}
                          {duplicateValidation.phone.state === "invalid" && (
                            <AlertCircle className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-destructive" />
                          )}
                        </div>
                      </FormControl>
                      <FormMessage />
                      <ValidationIndicator
                        state={duplicateValidation.phone.state}
                        message={duplicateValidation.phone.message}
                      />
                    </FormItem>
                  )}
                />
              </FormRow>

              {/* Row 2: Source + Unit */}
              <FormRow columns={2}>
                <FormField
                  control={form.control}
                  name="source"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
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
                    const unitOptional = isAdmin && distributionPreview?.has_config;
                    const hideUnitSelector = isOfficer || isManager;

                    return (
                      <FormItem>
                        <FormLabel>
                          Đơn vị {!unitOptional && !hideUnitSelector && <span className="text-destructive">*</span>}
                        </FormLabel>
                        <FormControl>
                          <SmartUnitSelector
                            value={field.value ?? ""}
                            onChange={(val) => field.onChange(val || "")}
                            placeholder={unitOptional ? "Tự động" : "Chọn đơn vị"}
                            disabled={hideUnitSelector}
                            variant="select"
                            className="w-full"
                          />
                        </FormControl>
                        {hideUnitSelector && (
                          <FormDescription className="text-xs">
                            {isOfficer ? "Đơn vị được phân công" : "Đơn vị của bạn"}
                          </FormDescription>
                        )}
                        <FormMessage />
                      </FormItem>
                    );
                  }}
                />
              </FormRow>

              {/* CTV Referrer - shown when source = "referral" */}
              {selectedSource === "referral" && (
                <FormField
                  control={form.control}
                  name="referrer_id"
                  render={({ field }) => {
                    const selectedCtv = availableCtv.find((c) => c.id === field.value);
                    return (
                      <FormItem className="flex flex-col">
                        <FormLabel>
                          <span className="flex items-center gap-1.5">
                            <Users className="h-3.5 w-3.5" aria-hidden="true" />
                            CTV giới thiệu
                          </span>
                        </FormLabel>
                        <Popover open={ctvPopoverOpen} onOpenChange={setCtvPopoverOpen}>
                          <PopoverTrigger asChild>
                            <FormControl>
                              <Button
                                variant="outline"
                                role="combobox"
                                aria-expanded={ctvPopoverOpen}
                                className={cn(
                                  "w-full justify-between font-normal",
                                  !field.value && "text-muted-foreground"
                                )}
                              >
                                {selectedCtv
                                  ? `${selectedCtv.full_name} (${selectedCtv.code})`
                                  : "Chọn CTV giới thiệu"}
                                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                              </Button>
                            </FormControl>
                          </PopoverTrigger>
                          <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                            <Command>
                              <CommandInput placeholder="Tìm theo tên, SĐT, mã CTV…" />
                              <CommandList>
                                <CommandEmpty>
                                  {isLoadingCtv ? "Đang tải…" : "Không tìm thấy CTV"}
                                </CommandEmpty>
                                <CommandGroup>
                                  {availableCtv.map((ctv) => (
                                    <CommandItem
                                      key={ctv.id}
                                      value={`${ctv.full_name} ${ctv.phone} ${ctv.code}`}
                                      onSelect={() => {
                                        field.onChange(ctv.id);
                                        setCtvPopoverOpen(false);
                                      }}
                                    >
                                      <Check
                                        className={cn(
                                          "mr-2 h-4 w-4",
                                          field.value === ctv.id ? "opacity-100" : "opacity-0"
                                        )}
                                      />
                                      <div className="flex flex-col">
                                        <span className="font-medium">{ctv.full_name}</span>
                                        <span className="text-xs text-muted-foreground">
                                          {ctv.code} · {ctv.phone}
                                        </span>
                                      </div>
                                    </CommandItem>
                                  ))}
                                </CommandGroup>
                              </CommandList>
                            </Command>
                          </PopoverContent>
                        </Popover>
                        <FormMessage />
                      </FormItem>
                    );
                  }}
                />
              )}

              {/* Row 3: Offering (Ngành quan tâm) */}
              <FormField
                control={form.control}
                name="offering_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Ngành quan tâm</FormLabel>
                    <FormControl>
                      <SmartOfferingSelector
                        value={field.value?.toString()}
                        onChange={(val) => field.onChange(val ? parseInt(val, 10) : null)}
                        placeholder="Chọn ngành (tùy chọn)"
                        allowAll
                        allLabel="Chưa xác định"
                        variant="combobox"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Distribution Preview */}
              {isCreate && (isAdmin || managerUsesDistribution) && selectedOfferingId && (
                <div className="rounded-lg border bg-muted/50 p-3 space-y-1">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Info className="h-4 w-4 text-info-500" />
                    Xem trước phân phối
                  </div>
                  {isLoadingPreview ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Đang tải…
                    </div>
                  ) : distributionPreview?.has_config ? (
                    <div className="text-sm">
                      <span className="text-muted-foreground">Đơn vị nhận: </span>
                      <span className="font-medium text-success-600">{distributionPreview.next_unit_name}</span>
                    </div>
                  ) : (
                    <div className="text-sm text-warning-600">Chưa có cấu hình phân phối</div>
                  )}
                </div>
              )}

              {/* Officer Assignment - Only for Admin/Manager */}
              {canSelectOfficerInForm && (
                <FormField
                  control={form.control}
                  name="assigned_officer_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Phân công tư vấn viên</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value || "auto"}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn tư vấn viên" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="auto">🔄 Tự động (Round Robin)</SelectItem>
                          {availableOfficers.map((officer) => (
                            <SelectItem key={officer.id} value={officer.id.toString()}>
                              {officer.full_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>

            {/* ========== EXPANDABLE DETAILS SECTION ========== */}
            <Collapsible open={showDetails} onOpenChange={setShowDetails}>
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full justify-between text-muted-foreground hover:text-foreground"
                >
                  <span className="flex items-center gap-2">
                    {showDetails ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    {showDetails ? "Ẩn thông tin chi tiết" : "Thêm thông tin chi tiết"}
                  </span>
                  <span className="text-xs">(Email, năm sinh, học vấn...)</span>
                </Button>
              </CollapsibleTrigger>

              <CollapsibleContent className="space-y-4 pt-4">
                {/* Contact Info */}
                <div className="space-y-4">
                  <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Liên hệ bổ sung</h3>
                  </div>

                  <FormRow columns={2}>
                    <FormField
                      control={form.control}
                      name="email"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Email</FormLabel>
                          <FormControl>
                            <Input
                              type="email"
                              placeholder="email@example.com"
                              autoComplete="email"
                              {...field}
                              value={field.value ?? ""}
                            />
                          </FormControl>
                          <FormMessage />
                          <ValidationIndicator
                            state={duplicateValidation.email.state}
                            message={duplicateValidation.email.message}
                          />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="phone2"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>SĐT phụ</FormLabel>
                          <FormControl>
                            <Input placeholder="0901234567" autoComplete="tel" {...field} value={field.value ?? ""} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </FormRow>
                </div>

                {/* Personal Info */}
                <div className="space-y-4">
                  <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Thông tin cá nhân</h3>
                  </div>

                  <FormRow columns={3}>
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
                              onChange={(e) => field.onChange(e.target.value ? parseInt(e.target.value) : null)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="location"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Địa chỉ</FormLabel>
                          <FormControl>
                            <Input placeholder="TP.HCM" autoComplete="address-level1" {...field} value={field.value ?? ""} />
                          </FormControl>
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
                          <Select onValueChange={(val) => field.onChange(parseInt(val))} value={field.value?.toString() || "0"}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="0">Xa</SelectItem>
                              <SelectItem value="1">Lân cận (+2đ)</SelectItem>
                              <SelectItem value="2">Gần (+5đ)</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </FormRow>
                </div>

                {/* Academic Info */}
                <div className="space-y-4">
                  <div className="pb-2 border-b">
                    <h3 className="text-sm font-semibold">Thông tin học vấn</h3>
                  </div>

                  <FormRow columns={3}>
                    <FormField
                      control={form.control}
                      name="education_level"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Trình độ</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value || undefined}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Chọn" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="high_school">THPT</SelectItem>
                              <SelectItem value="diploma">Trung cấp/CĐ</SelectItem>
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
                      name="academic_performance"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Học lực</FormLabel>
                          <Select onValueChange={(val) => field.onChange(parseInt(val))} value={field.value?.toString() || "0"}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="0">Chưa xác định</SelectItem>
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
                      name="gpa"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>GPA</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="0.01"
                              min="0"
                              max="10"
                              placeholder="3.5"
                              {...field}
                              value={field.value ?? ""}
                              onChange={(e) => field.onChange(e.target.value ? parseFloat(e.target.value) : null)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </FormRow>

                  <FormField
                    control={form.control}
                    name="occupation_relevance"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nghề nghiệp liên quan</FormLabel>
                        <Select onValueChange={(val) => field.onChange(parseInt(val))} value={field.value?.toString() || "0"}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="0">Chưa xác định</SelectItem>
                            <SelectItem value="1">Gián tiếp (+2đ)</SelectItem>
                            <SelectItem value="2">Trực tiếp (+5đ)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </CollapsibleContent>
            </Collapsible>

            {/* ========== FOOTER BUTTONS ========== */}
            <FormActions stackOnMobile showDivider>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
                Hủy
              </Button>

              {isCreate && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={isSubmitting || isSubmitBlocked}
                  onClick={() => {
                    setCreateAnother(true);
                    form.handleSubmit((data) => onSubmit(data, true))();
                  }}
                >
                  {isSubmitting && createAnother && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Plus className="mr-1 h-4 w-4" />
                  Lưu & Tạo tiếp
                </Button>
              )}

              <Button
                type="submit"
                disabled={isSubmitting || isSubmitBlocked}
                onClick={() => setCreateAnother(false)}
              >
                {isSubmitting && !createAnother && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isCreate ? "Tạo Lead" : "Lưu thay đổi"}
              </Button>
            </FormActions>
          </form>
        </Form>
      </DialogContent>
    </FormDialog>
  );
}
