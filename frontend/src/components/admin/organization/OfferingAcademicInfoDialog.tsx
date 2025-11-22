// src/components/admin/organization/OfferingAcademicInfoDialog.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Dialog,
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
import { CurrencyInput } from "@/components/ui/currency-input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2, Plus, Trash, Save, SaveAll, FileText, Percent } from "lucide-react";
import {
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
} from "@/hooks/useOrganization";
import { useTuitionDiscountPolicies } from "@/hooks/useTuitionDiscount";
import type {
  OfferingAcademicInfo,
  ProgramOffering,
  AdmissionCriterion,
} from "@/types/organization.types";
import { DocumentTypesSelector } from "./DocumentTypesSelector"; // 👈 THÊM DÒNG NÀY

// =====================================================================
// FORM TYPES & SCHEMA
// =====================================================================

interface RequiredDocumentFormData {
  code: string;
  label: string;
}

interface AdmissionCriterionFormData {
  id: string;
  method_name: string;
  program_type?: string;
  subject_groups?: string; // String trong form (A00, B00), Array trong API
  min_score?: number | null;
  required_documents?: RequiredDocumentFormData[]; // Danh sách hồ sơ bắt buộc
}

// Schema cho hồ sơ bắt buộc
const requiredDocumentSchema = z.object({
  code: z.string().min(1, "Mã hồ sơ là bắt buộc"),
  label: z.string().min(1, "Tên hồ sơ là bắt buộc"),
});

// 1. Schema cho từng item
const admissionCriterionSchema = z.object({
  id: z.string().min(1, "Mã phương thức là bắt buộc"),
  method_name: z.string().min(1, "Tên phương thức là bắt buộc"),
  program_type: z.string().optional(),
  subject_groups: z.string().optional(),
  min_score: z.number().min(0).max(30).nullish(),
  required_documents: z.array(requiredDocumentSchema).optional(),
});

// 2. Schema tổng thể (CẬP NHẬT THÊM superRefine)
const academicInfoFormSchema = z.object({
  academic_year: z
    .number()
    .int("Năm học phải là số nguyên")
    .min(2000, "Năm học phải từ 2000 trở lên")
    .max(2100, "Năm học không được vượt quá 2100"),
  tuition_fee_per_year: z.number().min(0, "Học phí không được âm").nullish(),
  annual_admission_quota: z.number().int().min(0, "Chỉ tiêu không được âm").nullish(),
  target_audience: z.string().max(1000).optional(),
  cutoff_score_previous_year: z.number().min(0).max(30).nullish(),

  // Chính sách ưu đãi học phí
  applied_discount_policy_ids: z.array(z.number()).optional().nullable(),

  // 👇 VALIDATE DANH SÁCH: Không cho phép trùng ID hoặc Tên
  admission_criteria: z.array(admissionCriterionSchema).superRefine((items, ctx) => {
    const seenIds = new Set();
    const seenNames = new Set();

    items.forEach((item, index) => {
      // Kiểm tra trùng Mã (ID)
      const id = item.id?.trim().toUpperCase(); // Chuẩn hóa để so sánh
      if (id) {
        if (seenIds.has(id)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Mã phương thức bị trùng lặp",
            path: [index, "id"], // Đánh dấu lỗi vào đúng dòng index, trường id
          });
        } else {
          seenIds.add(id);
        }
      }

      // Kiểm tra trùng Tên (Method Name)
      const name = item.method_name?.trim().toLowerCase();
      if (name) {
        if (seenNames.has(name)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Tên phương thức bị trùng lặp",
            path: [index, "method_name"], // Đánh dấu lỗi vào đúng dòng index, trường name
          });
        } else {
          seenNames.add(name);
        }
      }
    });
  }),

  is_published: z.boolean(),
});

type AcademicInfoFormValues = z.infer<typeof academicInfoFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface OfferingAcademicInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  offering: ProgramOffering;
  academicInfo?: OfferingAcademicInfo | null;
  existingYears?: number[]; // Danh sách các năm đã có dữ liệu (để check trùng)
  onSaveSuccess?: (data: OfferingAcademicInfo, shouldClose: boolean) => void;
}

// =====================================================================
// HELPER FUNCTIONS (Data Transformation)
// =====================================================================

function convertApiToFormData(apiCriteria: AdmissionCriterion[]): AdmissionCriterionFormData[] {
  if (!Array.isArray(apiCriteria)) return [];
  return apiCriteria.map((criterion) => ({
    id: criterion.id || "",
    method_name: criterion.method_name || "",
    program_type: criterion.program_type || "",
    // Chuyển mảng ["A00", "B00"] thành chuỗi "A00, B00"
    subject_groups: Array.isArray(criterion.subject_groups)
      ? criterion.subject_groups.join(", ")
      : typeof criterion.subject_groups === "string"
        ? criterion.subject_groups
        : "",
    // Ép kiểu số an toàn
    min_score:
      criterion.min_score !== null && criterion.min_score !== undefined
        ? Number(criterion.min_score)
        : null,
    // Chuyển đổi required_documents
    required_documents: Array.isArray(criterion.required_documents)
      ? criterion.required_documents.map((doc) => ({
          code: doc.code || "",
          label: doc.label || "",
        }))
      : [],
  }));
}

function convertFormToApiData(formCriteria: AdmissionCriterionFormData[]): AdmissionCriterion[] {
  return formCriteria.map((criterion) => {
    // Xử lý required_documents - lọc và đảm bảo có dữ liệu hợp lệ
    const validDocuments = criterion.required_documents
      ? criterion.required_documents
          .filter((doc) => doc.code && doc.label)
          .map((doc) => ({
            code: doc.code,
            label: doc.label,
          }))
      : [];

    return {
      id: criterion.id,
      method_name: criterion.method_name,
      program_type: criterion.program_type || "",
      // Chuyển chuỗi "A00, B00" thành mảng ["A00", "B00"]
      subject_groups: criterion.subject_groups
        ? criterion.subject_groups
            .split(",")
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
        : [],
      min_score: criterion.min_score ?? null,
      // Chuyển đổi required_documents - trả về mảng rỗng thay vì null nếu không có
      required_documents: validDocuments.length > 0 ? validDocuments : null,
    };
  });
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function OfferingAcademicInfoDialog({
  open,
  onOpenChange,
  offering,
  academicInfo,
  existingYears = [],
  onSaveSuccess,
}: OfferingAcademicInfoDialogProps) {
  const isEditMode = !!academicInfo;
  const currentYear = new Date().getFullYear();

  // Kiểm tra logic nghiệp vụ: Năm trong quá khứ thì không cho sửa dữ liệu tài chính
  const isPastYear = useMemo(() => {
    if (!academicInfo) return false;
    return academicInfo.academic_year < currentYear;
  }, [academicInfo, currentYear]);

  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();

  const form = useForm<AcademicInfoFormValues>({
    resolver: zodResolver(academicInfoFormSchema),
    defaultValues: {
      academic_year: currentYear,
      tuition_fee_per_year: null,
      annual_admission_quota: null,
      target_audience: "",
      cutoff_score_previous_year: null,
      applied_discount_policy_ids: [],
      admission_criteria: [],
      is_published: false,
    },
  });

  // Fetch discount policies for selection
  const { data: discountPoliciesData, isLoading: isLoadingDiscounts } = useTuitionDiscountPolicies({
    isActive: true,
    includeExpired: false,
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "admission_criteria",
  });

  // --- DATA LOADING & PARSING ---
  useEffect(() => {
    if (open) {
      form.clearErrors(); // Reset lỗi cũ khi mở lại form

      if (isEditMode && academicInfo) {
        // --- EDIT MODE ---
        let parsedCriteria: AdmissionCriterionFormData[] = [];
        try {
          // Xử lý field JSON từ API (có thể là string hoặc object)
          let apiCriteria: AdmissionCriterion[] = [];
          if (typeof academicInfo.admission_criteria === "string") {
            apiCriteria = JSON.parse(academicInfo.admission_criteria);
          } else if (Array.isArray(academicInfo.admission_criteria)) {
            apiCriteria = academicInfo.admission_criteria;
          }
          parsedCriteria = convertApiToFormData(apiCriteria);
        } catch (e) {
          console.error("Failed to parse admission criteria:", e);
        }

        // 🛡️ CRITICAL FIX: Ép kiểu dữ liệu từ API (Decimal/String -> Number)
        // Backend có thể trả về "20000.00" (String) -> cần chuyển thành 20000 (Number)
        form.reset({
          academic_year: Number(academicInfo.academic_year),
          tuition_fee_per_year:
            academicInfo.tuition_fee_per_year !== null
              ? Number(academicInfo.tuition_fee_per_year)
              : null,
          annual_admission_quota:
            academicInfo.annual_admission_quota !== null
              ? Number(academicInfo.annual_admission_quota)
              : null,
          cutoff_score_previous_year:
            academicInfo.cutoff_score_previous_year !== null
              ? Number(academicInfo.cutoff_score_previous_year)
              : null,
          target_audience: academicInfo.target_audience || "",
          applied_discount_policy_ids: academicInfo.applied_discount_policy_ids || [],
          admission_criteria: parsedCriteria,
          is_published: academicInfo.is_published,
        });
      } else {
        // --- CREATE MODE ---
        // Gợi ý năm tiếp theo chưa có trong danh sách
        let nextYear = currentYear;
        while (existingYears.includes(nextYear)) {
          nextYear++;
        }

        form.reset({
          academic_year: nextYear,
          tuition_fee_per_year: null,
          annual_admission_quota: null,
          target_audience: "",
          cutoff_score_previous_year: null,
          applied_discount_policy_ids: [],
          admission_criteria: [],
          is_published: false,
        });
      }
    }
  }, [open, isEditMode, academicInfo, form, existingYears, currentYear]);

  const [saveAction, setSaveAction] = useState<"close" | "continue">("close");

  const onSubmit = async (values: AcademicInfoFormValues) => {
    // 🛡️ CLIENT-SIDE VALIDATION: Unique Year Constraint
    if (!isEditMode && existingYears.includes(values.academic_year)) {
      form.setError("academic_year", {
        type: "manual",
        message: `Thông tin tuyển sinh năm ${values.academic_year} đã tồn tại. Vui lòng chọn năm khác hoặc chỉnh sửa bản ghi cũ.`,
      });
      return;
    }

    try {
      const apiCriteria = convertFormToApiData(values.admission_criteria);
      let resultData: OfferingAcademicInfo;

      if (isEditMode && academicInfo) {
        // Update logic
        resultData = await updateMutation.mutateAsync({
          id: academicInfo.id,
          data: {
            ...values,
            admission_criteria: apiCriteria,
          },
        });
      } else {
        // Create logic
        resultData = await createMutation.mutateAsync({
          offeringId: offering.id,
          offering_id: offering.id,
          ...values,
          admission_criteria: apiCriteria,
        });
      }

      // ✅ Gọi callback thay vì tự đóng
      if (onSaveSuccess) {
        onSaveSuccess(resultData, saveAction === "close");
      } else {
        // Fallback nếu không có callback (logic cũ)
        onOpenChange(false);
      }
      // Nếu "Lưu & Tiếp tục", ta reset form với dữ liệu mới nhất từ Server
      // để đảm bảo form clean (isDirty = false)
      if (saveAction === "continue") {
        // Logic reset form sẽ được useEffect xử lý khi prop `academicInfo` thay đổi
        // nhờ hàm handleSaveSuccess ở component cha.
      }
    } catch (error) {
      console.error("Form submission failed:", error);
      // Error toast handled in hooks
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[800px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode
              ? `Chỉnh sửa thông tin - Năm ${academicInfo?.academic_year}`
              : "Tạo thông tin tuyển sinh mới"}
          </DialogTitle>
          <DialogDescription>
            Loại hình: <strong>{offering.offering_type}</strong>
            {isPastYear && isEditMode && (
              <span className="mt-1 block font-medium text-yellow-600">
                ⚠️ Đây là dữ liệu lịch sử (năm {academicInfo?.academic_year}). Chỉ có thể cập nhật
                thông tin mô tả, không thể sửa dữ liệu tài chính.
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Academic Year */}
            <FormField
              control={form.control}
              name="academic_year"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Năm học <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      {...field}
                      onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
                      // Edit mode: Luôn disable năm học (khóa chính)
                      disabled={isSubmitting || isEditMode}
                      className={isEditMode ? "bg-muted font-bold" : ""}
                    />
                  </FormControl>
                  {!isEditMode && (
                    <FormDescription>
                      Nhập năm tuyển sinh (VD: 2025). Không được trùng với năm đã có.
                    </FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Tuition Fee */}
              <FormField
                control={form.control}
                name="tuition_fee_per_year"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Học phí/năm</FormLabel>
                    <FormControl>
                      <CurrencyInput
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="VD: 15.000.000"
                        // 🛡️ Disable nếu là năm quá khứ
                        disabled={isSubmitting || (isEditMode && isPastYear)}
                        currency="VND"
                        locale="vi-VN"
                        className={isEditMode && isPastYear ? "bg-muted cursor-not-allowed" : ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Admission Quota */}
              <FormField
                control={form.control}
                name="annual_admission_quota"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Chỉ tiêu tuyển sinh</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="VD: 100"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) =>
                          field.onChange(e.target.value ? parseInt(e.target.value) : null)
                        }
                        // 🛡️ Disable nếu là năm quá khứ
                        disabled={isSubmitting || (isEditMode && isPastYear)}
                        className={isEditMode && isPastYear ? "bg-muted cursor-not-allowed" : ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Tuition Discount Policies */}
            <FormField
              control={form.control}
              name="applied_discount_policy_ids"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="flex items-center gap-2">
                    <Percent className="h-4 w-4" />
                    Chính sách ưu đãi học phí
                  </FormLabel>
                  <FormDescription>
                    Chọn các chính sách ưu đãi áp dụng cho chương trình này
                  </FormDescription>
                  {isLoadingDiscounts ? (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </div>
                  ) : discountPoliciesData?.items && discountPoliciesData.items.length > 0 ? (
                    <div className="max-h-[200px] overflow-y-auto rounded-md border p-3 space-y-2">
                      {discountPoliciesData.items.map((policy) => {
                        const isChecked = (field.value || []).includes(policy.id);
                        return (
                          <div
                            key={policy.id}
                            className="flex items-center space-x-3 rounded-md p-2 hover:bg-muted/50"
                          >
                            <Checkbox
                              id={`policy-${policy.id}`}
                              checked={isChecked}
                              onCheckedChange={(checked) => {
                                const currentIds = field.value || [];
                                if (checked) {
                                  field.onChange([...currentIds, policy.id]);
                                } else {
                                  field.onChange(currentIds.filter((id: number) => id !== policy.id));
                                }
                              }}
                              disabled={isSubmitting}
                            />
                            <label
                              htmlFor={`policy-${policy.id}`}
                              className="flex-1 cursor-pointer text-sm"
                            >
                              <div className="font-medium">{policy.name}</div>
                              <div className="text-muted-foreground text-xs">
                                {policy.code} -{" "}
                                {policy.discount_type === "percentage"
                                  ? `${policy.discount_value}%`
                                  : `${new Intl.NumberFormat("vi-VN").format(policy.discount_value)} VNĐ`}
                              </div>
                            </label>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
                      Chưa có chính sách ưu đãi nào. Vui lòng tạo chính sách trong mục Quản lý Ưu đãi.
                    </div>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Target Audience */}
            <FormField
              control={form.control}
              name="target_audience"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đối tượng tuyển sinh</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả đối tượng tuyển sinh phù hợp..."
                      className="min-h-[100px] resize-y"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Cutoff Score */}
            <FormField
              control={form.control}
              name="cutoff_score_previous_year"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Điểm chuẩn năm trước</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="VD: 18.5"
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(e.target.value ? parseFloat(e.target.value) : null)
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Dynamic Criteria */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="text-base font-medium">Phương thức xét tuyển</div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    append({
                      id: "",
                      method_name: "",
                      program_type: "",
                      subject_groups: "",
                      min_score: null,
                      required_documents: [],
                    })
                  }
                  disabled={isSubmitting}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Thêm phương thức
                </Button>
              </div>

              {fields.length === 0 && (
                <div className="text-muted-foreground rounded-lg border-2 border-dashed py-4 text-center text-sm">
                  Chưa có phương thức xét tuyển nào.
                </div>
              )}

              <div className="space-y-3">
                {fields.map((field, index) => (
                  <Card key={field.id} className="relative">
                    <CardHeader className="pt-4 pb-2">
                      <div className="flex items-center justify-between">
                        <Badge variant="secondary" className="px-3 py-1 text-sm font-medium">
                          Phương thức {index + 1}
                        </Badge>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => remove(index)}
                          disabled={isSubmitting}
                          className="text-destructive hover:text-destructive h-8 w-8 p-0"
                        >
                          <Trash className="h-4 w-4" />
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="grid grid-cols-1 gap-4 pb-4 md:grid-cols-2">
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.id`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs">Mã phương thức *</FormLabel>
                            <FormControl>
                              <Input placeholder="VD: HB2025" {...field} disabled={isSubmitting} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.method_name`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs">Tên phương thức *</FormLabel>
                            <FormControl>
                              <Input
                                placeholder="VD: Xét học bạ"
                                {...field}
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.subject_groups`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs">Tổ hợp môn</FormLabel>
                            <FormControl>
                              <Input
                                placeholder="VD: A00, A01"
                                {...field}
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.min_score`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs">Điểm sàn</FormLabel>
                            <FormControl>
                              <Input
                                type="number"
                                step="0.01"
                                {...field}
                                value={field.value ?? ""}
                                onChange={(e) =>
                                  field.onChange(e.target.value ? parseFloat(e.target.value) : null)
                                }
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* Required Documents Section - Using Standardized DocumentTypesSelector */}
                      <div className="mt-4 border-t pt-4 md:col-span-2">
                        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                          <FileText className="h-4 w-4" />
                          Hồ sơ bắt buộc
                        </div>

                        <DocumentTypesSelector
                          value={
                            form.watch(`admission_criteria.${index}.required_documents`) || []
                          }
                          onChange={(documents) => {
                            form.setValue(
                              `admission_criteria.${index}.required_documents`,
                              documents,
                              { shouldDirty: true, shouldValidate: true }
                            );
                          }}
                          disabled={isSubmitting}
                        />
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>

            <FormField
              control={form.control}
              name="is_published"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Công khai</FormLabel>
                    <FormDescription>Cho phép hiển thị thông tin này ra công chúng</FormDescription>
                  </div>
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                Hủy
              </Button>

              {/* Nút 1: Lưu & Đóng */}
              <Button type="submit" disabled={isSubmitting} onClick={() => setSaveAction("close")}>
                {isSubmitting && saveAction === "close" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Save className="mr-2 h-4 w-4" />
                )}
                {isEditMode ? "Lưu thay đổi" : "Tạo và Đóng"}
              </Button>

              {/* Nút 2: Lưu & Tiếp tục (Chỉ hiện khi Tạo mới hoặc muốn giữ form) */}
              <Button
                type="submit"
                variant="secondary"
                disabled={isSubmitting}
                onClick={() => setSaveAction("continue")}
              >
                {isSubmitting && saveAction === "continue" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <SaveAll className="mr-2 h-4 w-4" />
                )}
                {isEditMode ? "Lưu và Tiếp tục" : "Tạo và Tiếp tục"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
