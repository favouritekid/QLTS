// src/components/admin/organization/OfferingAcademicInfoDialog.tsx
"use client";

import { useEffect } from "react";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, Plus, Trash } from "lucide-react";
import {
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
} from "@/hooks/useOrganization";
import type {
  OfferingAcademicInfo,
  OfferingAcademicInfoCreate,
  OfferingAcademicInfoUpdate,
  ProgramOffering,
  AdmissionCriterion,
} from "@/types/organization.types";

// =====================================================================
// FORM-SPECIFIC TYPES (differs from API types)
// =====================================================================

// Form uses string for subject_groups (comma-separated input)
// API uses string[] (array)
interface AdmissionCriterionFormData {
  id: string;
  method_name: string;
  program_type?: string;
  subject_groups?: string; // ✅ String in form (comma-separated)
  min_score?: number | null;
}

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const admissionCriterionSchema = z.object({
  id: z.string().min(1, "Mã phương thức là bắt buộc"),
  method_name: z.string().min(1, "Tên phương thức là bắt buộc"),
  program_type: z.string().optional(),
  subject_groups: z.string().optional(), // Comma-separated string in form
  min_score: z
    .number()
    .min(0, "Điểm phải lớn hơn hoặc bằng 0")
    .max(30, "Điểm không được vượt quá 30")
    .nullish(),
});

const academicInfoFormSchema = z.object({
  academic_year: z
    .number()
    .int("Năm học phải là số nguyên")
    .min(2000, "Năm học phải từ 2000 trở lên")
    .max(2100, "Năm học không được vượt quá 2100"),
  tuition_fee_per_year: z
    .number()
    .min(0, "Học phí không thể âm")
    .nullish(),
  annual_admission_quota: z
    .number()
    .int("Chỉ tiêu tuyển sinh phải là số nguyên")
    .min(0, "Chỉ tiêu tuyển sinh không thể âm")
    .nullish(),
  target_audience: z
    .string()
    .max(1000, "Đối tượng tuyển sinh không được vượt quá 1000 ký tự")
    .optional(),
  cutoff_score_previous_year: z
    .number()
    .min(0, "Điểm chuẩn không thể âm")
    .max(30, "Điểm chuẩn không được vượt quá 30")
    .nullish(),
  admission_criteria: z.array(admissionCriterionSchema).default([]),
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
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Convert API data (AdmissionCriterion[]) to form data
 * - subject_groups: string[] → comma-separated string
 */
function convertApiToFormData(
  apiCriteria: AdmissionCriterion[]
): AdmissionCriterionFormData[] {
  return apiCriteria.map((criterion) => ({
    id: criterion.id,
    method_name: criterion.method_name,
    program_type: criterion.program_type || undefined,
    subject_groups: criterion.subject_groups
      ? criterion.subject_groups.join(", ")
      : undefined,
    min_score: criterion.min_score ?? null,
  }));
}

/**
 * Convert form data to API data (AdmissionCriterion[])
 * - subject_groups: comma-separated string → string[]
 */
function convertFormToApiData(
  formCriteria: AdmissionCriterionFormData[]
): AdmissionCriterion[] {
  return formCriteria.map((criterion) => ({
    id: criterion.id,
    method_name: criterion.method_name,
    program_type: criterion.program_type || "",
    subject_groups: criterion.subject_groups
      ? criterion.subject_groups
          .split(",")
          .map((s) => s.trim())
          .filter((s) => s.length > 0)
      : null,
    min_score: criterion.min_score ?? null,
  }));
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function OfferingAcademicInfoDialog({
  open,
  onOpenChange,
  offering,
  academicInfo,
}: OfferingAcademicInfoDialogProps) {
  const isEditMode = !!academicInfo;

  // Mutations
  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();

  // Form
  const form = useForm<AcademicInfoFormValues>({
    resolver: zodResolver(academicInfoFormSchema),
    defaultValues: {
      academic_year: new Date().getFullYear(),
      tuition_fee_per_year: null,
      annual_admission_quota: null,
      target_audience: "",
      cutoff_score_previous_year: null,
      admission_criteria: [],
      is_published: false,
    },
  });

  // useFieldArray for dynamic admission criteria
  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "admission_criteria",
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && academicInfo) {
        // ✅ Parse admission_criteria from JSON string/array to form data
        let parsedCriteria: AdmissionCriterionFormData[] = [];
        if (academicInfo.admission_criteria) {
          try {
            let apiCriteria: AdmissionCriterion[] = [];

            // If it's a string, parse it
            if (typeof academicInfo.admission_criteria === "string") {
              apiCriteria = JSON.parse(academicInfo.admission_criteria);
            }
            // If it's already an array, use it directly
            else if (Array.isArray(academicInfo.admission_criteria)) {
              apiCriteria = academicInfo.admission_criteria;
            }

            // Convert API format to form format
            parsedCriteria = convertApiToFormData(apiCriteria);
          } catch (e) {
            console.error("Failed to parse admission criteria:", e);
            parsedCriteria = [];
          }
        }

        form.reset({
          academic_year: academicInfo.academic_year,
          tuition_fee_per_year: academicInfo.tuition_fee_per_year ?? null,
          annual_admission_quota: academicInfo.annual_admission_quota ?? null,
          target_audience: academicInfo.target_audience || "",
          cutoff_score_previous_year:
            academicInfo.cutoff_score_previous_year ?? null,
          admission_criteria: parsedCriteria,
          is_published: academicInfo.is_published,
        });
      } else {
        form.reset({
          academic_year: new Date().getFullYear(),
          tuition_fee_per_year: null,
          annual_admission_quota: null,
          target_audience: "",
          cutoff_score_previous_year: null,
          admission_criteria: [],
          is_published: false,
        });
      }
    }
  }, [open, isEditMode, academicInfo, form]);

  // Handle form submission
  const onSubmit = async (values: AcademicInfoFormValues) => {
    try {
      // ✅ Convert form data to API format
      const apiCriteria = convertFormToApiData(values.admission_criteria);

      if (isEditMode && academicInfo) {
        // Update existing
        const payload: OfferingAcademicInfoUpdate = {
          academic_year: values.academic_year,
          tuition_fee_per_year:
            typeof values.tuition_fee_per_year === "number"
              ? values.tuition_fee_per_year
              : null,
          annual_admission_quota:
            typeof values.annual_admission_quota === "number"
              ? values.annual_admission_quota
              : null,
          target_audience: values.target_audience || null,
          cutoff_score_previous_year:
            typeof values.cutoff_score_previous_year === "number"
              ? values.cutoff_score_previous_year
              : null,
          admission_criteria: apiCriteria.length > 0 ? apiCriteria : null,
          is_published: values.is_published,
        };
        await updateMutation.mutateAsync({
          id: academicInfo.id,
          data: payload,
        });
      } else {
        // Create new
        const payload: OfferingAcademicInfoCreate = {
          offering_id: offering.id,
          academic_year: values.academic_year,
          tuition_fee_per_year:
            typeof values.tuition_fee_per_year === "number"
              ? values.tuition_fee_per_year
              : null,
          annual_admission_quota:
            typeof values.annual_admission_quota === "number"
              ? values.annual_admission_quota
              : null,
          target_audience: values.target_audience || null,
          cutoff_score_previous_year:
            typeof values.cutoff_score_previous_year === "number"
              ? values.cutoff_score_previous_year
              : null,
          admission_criteria: apiCriteria.length > 0 ? apiCriteria : null,
          is_published: values.is_published,
        };
        await createMutation.mutateAsync({
          offeringId: offering.id,
          ...payload,
        } as OfferingAcademicInfoCreate & { offeringId: number });
      }

      // Close dialog on success
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error handling is done in mutation hooks (toast)
      console.error("Form submission error:", error);
    }
  };

  // Check if mutation is in progress
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[800px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditMode
              ? `Chỉnh sửa thông tin tuyển sinh - Năm ${academicInfo?.academic_year}`
              : "Tạo thông tin tuyển sinh mới"}
          </DialogTitle>
          <DialogDescription>
            Loại hình: <strong>{offering.offering_type}</strong>
            <br />
            {isEditMode
              ? "Cập nhật thông tin tuyển sinh cho năm học này"
              : "Nhập thông tin tuyển sinh cho năm học mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Academic Year Field (only for create) */}
            {!isEditMode && (
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
                        placeholder="VD: 2025"
                        {...field}
                        onChange={(e) =>
                          field.onChange(parseInt(e.target.value) || 0)
                        }
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Năm học áp dụng thông tin này (từ 2000 đến 2100)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Target Audience */}
            <FormField
              control={form.control}
              name="target_audience"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đối tượng tuyển sinh</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="VD: Học sinh tốt nghiệp THPT, có đam mê công nghệ..."
                      className="resize-none"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Mô tả đối tượng tuyển sinh phù hợp (tối đa 1000 ký tự)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Tuition Fee */}
            <FormField
              control={form.control}
              name="tuition_fee_per_year"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Học phí/năm</FormLabel>
                  <FormControl>
                    <CurrencyInput
                      value={
                        typeof field.value === "number" ? field.value : null
                      }
                      onChange={field.onChange}
                      placeholder="VD: 15.000.000"
                      disabled={isSubmitting}
                      currency="VND"
                      locale="vi-VN"
                    />
                  </FormControl>
                  <FormDescription>
                    Học phí một năm học (tự động định dạng với dấu phân cách
                    hàng nghìn)
                  </FormDescription>
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
                        field.onChange(
                          e.target.value ? parseInt(e.target.value) : null
                        )
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Số lượng sinh viên dự kiến tuyển trong năm
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Cutoff Score Previous Year */}
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
                        field.onChange(
                          e.target.value ? parseFloat(e.target.value) : null
                        )
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Điểm chuẩn năm trước (để tham khảo)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* ✅ DYNAMIC ADMISSION CRITERIA BUILDER */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <FormLabel className="text-base">
                    Tiêu chí tuyển sinh
                  </FormLabel>
                  <FormDescription>
                    Thêm các phương thức xét tuyển (học bạ, thi THPT, tuyển
                    thẳng...)
                  </FormDescription>
                </div>
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
                    })
                  }
                  disabled={isSubmitting}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Thêm phương thức xét tuyển
                </Button>
              </div>

              {/* Dynamic Cards for each criterion */}
              {fields.length === 0 && (
                <div className="text-center py-8 text-muted-foreground border-2 border-dashed rounded-lg">
                  <p>Chưa có phương thức xét tuyển nào</p>
                  <p className="text-sm mt-1">
                    Nhấn nút &quot;Thêm phương thức xét tuyển&quot; để bắt đầu
                  </p>
                </div>
              )}

              <div className="space-y-3">
                {fields.map((field, index) => (
                  <Card key={field.id} className="relative">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium">
                          Phương thức #{index + 1}
                        </CardTitle>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => remove(index)}
                          disabled={isSubmitting}
                          className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                        >
                          <Trash className="h-4 w-4" />
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* ID Field */}
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.id`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>
                              Mã phương thức{" "}
                              <span className="text-red-500">*</span>
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder="VD: HB2025"
                                {...field}
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* Method Name Field */}
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.method_name`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>
                              Tên phương thức{" "}
                              <span className="text-red-500">*</span>
                            </FormLabel>
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

                      {/* Subject Groups Field */}
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.subject_groups`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Khối thi</FormLabel>
                            <FormControl>
                              <Input
                                placeholder="VD: A00, A01, D07"
                                {...field}
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormDescription className="text-xs">
                              Các khối thi, phân cách bằng dấu phẩy
                            </FormDescription>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* Min Score Field */}
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.min_score`}
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Điểm chuẩn</FormLabel>
                            <FormControl>
                              <Input
                                type="number"
                                step="0.01"
                                placeholder="VD: 18.0"
                                {...field}
                                value={field.value ?? ""}
                                onChange={(e) =>
                                  field.onChange(
                                    e.target.value
                                      ? parseFloat(e.target.value)
                                      : null
                                  )
                                }
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* Program Type Field (full width) */}
                      <FormField
                        control={form.control}
                        name={`admission_criteria.${index}.program_type`}
                        render={({ field }) => (
                          <FormItem className="md:col-span-2">
                            <FormLabel>Loại chương trình</FormLabel>
                            <FormControl>
                              <Input
                                placeholder="VD: Chính quy, Liên thông..."
                                {...field}
                                disabled={isSubmitting}
                              />
                            </FormControl>
                            <FormDescription className="text-xs">
                              Loại chương trình áp dụng phương thức này (tùy
                              chọn)
                            </FormDescription>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>

            {/* Is Published Switch */}
            <FormField
              control={form.control}
              name="is_published"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Công khai</FormLabel>
                    <FormDescription>
                      Cho phép hiển thị thông tin này ra công chúng
                    </FormDescription>
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
                {isSubmitting && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {isEditMode ? "Cập nhật" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
