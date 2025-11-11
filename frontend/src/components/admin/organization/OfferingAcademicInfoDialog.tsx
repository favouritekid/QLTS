// src/components/admin/organization/OfferingAcademicInfoDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
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
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import {
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
} from "@/hooks/useOrganization";
import type {
  OfferingAcademicInfo,
  OfferingAcademicInfoCreate,
  OfferingAcademicInfoUpdate,
  ProgramOffering,
} from "@/types/organization.types";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const academicInfoFormSchema = z.object({
  academic_year: z
    .number()
    .int("Năm học phải là số nguyên")
    .min(2000, "Năm học phải từ 2000 trở lên")
    .max(2100, "Năm học không được vượt quá 2100"),
  tuition_fee_per_year: z
    .number()
    .min(0, "Học phí không thể âm")
    .nullish()
    .or(z.literal("")),
  annual_admission_quota: z
    .number()
    .int("Chỉ tiêu tuyển sinh phải là số nguyên")
    .min(0, "Chỉ tiêu tuyển sinh không thể âm")
    .nullish()
    .or(z.literal("")),
  target_audience: z
    .string()
    .max(1000, "Đối tượng tuyển sinh không được vượt quá 1000 ký tự")
    .optional(),
  cutoff_score_previous_year: z
    .number()
    .min(0, "Điểm chuẩn không thể âm")
    .max(30, "Điểm chuẩn không được vượt quá 30")
    .nullish()
    .or(z.literal("")),
  admission_criteria: z.string().optional(), // JSON as string for simplicity
  is_published: z.boolean(),
});

type AcademicInfoFormValues = z.infer<typeof academicInfoFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface OfferingAcademicInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  offering: ProgramOffering; // Parent ProgramOffering (Tier 2)
  academicInfo?: OfferingAcademicInfo | null; // null = create mode
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
      admission_criteria: "",
      is_published: false,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && academicInfo) {
        form.reset({
          academic_year: academicInfo.academic_year,
          tuition_fee_per_year: academicInfo.tuition_fee_per_year ?? null,
          annual_admission_quota: academicInfo.annual_admission_quota ?? null,
          target_audience: academicInfo.target_audience || "",
          cutoff_score_previous_year: academicInfo.cutoff_score_previous_year ?? null,
          admission_criteria: academicInfo.admission_criteria
            ? JSON.stringify(academicInfo.admission_criteria, null, 2)
            : "",
          is_published: academicInfo.is_published,
        });
      } else {
        form.reset({
          academic_year: new Date().getFullYear(),
          tuition_fee_per_year: null,
          annual_admission_quota: null,
          target_audience: "",
          cutoff_score_previous_year: null,
          admission_criteria: "",
          is_published: false,
        });
      }
    }
  }, [open, isEditMode, academicInfo, form]);

  // Handle form submission
  const onSubmit = async (values: AcademicInfoFormValues) => {
    // Parse admission_criteria JSON
    let parsedAdmissionCriteria = null;
    if (values.admission_criteria && values.admission_criteria.trim()) {
      try {
        parsedAdmissionCriteria = JSON.parse(values.admission_criteria);
      } catch (e) {
        form.setError("admission_criteria", {
          message: "JSON không hợp lệ. Vui lòng kiểm tra lại.",
        });
        return;
      }
    }

    try {
      if (isEditMode && academicInfo) {
        // Update existing
        const payload: OfferingAcademicInfoUpdate = {
          academic_year: values.academic_year,
          tuition_fee_per_year: values.tuition_fee_per_year ?? null,
          annual_admission_quota: values.annual_admission_quota ?? null,
          target_audience: values.target_audience || null,
          cutoff_score_previous_year: values.cutoff_score_previous_year ?? null,
          admission_criteria: parsedAdmissionCriteria,
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
          tuition_fee_per_year: values.tuition_fee_per_year ?? null,
          annual_admission_quota: values.annual_admission_quota ?? null,
          target_audience: values.target_audience || null,
          cutoff_score_previous_year: values.cutoff_score_previous_year ?? null,
          admission_criteria: parsedAdmissionCriteria,
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
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
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
                        onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
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
                  <FormLabel>Học phí/năm (VND)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      placeholder="VD: 15000000"
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(e.target.value ? parseFloat(e.target.value) : null)
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Học phí một năm học (đơn vị: VND)
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
                        field.onChange(e.target.value ? parseInt(e.target.value) : null)
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
                        field.onChange(e.target.value ? parseFloat(e.target.value) : null)
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

            {/* Admission Criteria (JSON) */}
            <FormField
              control={form.control}
              name="admission_criteria"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tiêu chí tuyển sinh (JSON)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder={`Ví dụ:\n[\n  {\n    "id": "hocba_2025",\n    "method_name": "Xét học bạ",\n    "program_type": "Chính quy",\n    "subject_groups": ["A00", "D07"],\n    "min_score": 18.0\n  }\n]`}
                      className="resize-none font-mono text-xs min-h-[150px]"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Nhập tiêu chí tuyển sinh dưới dạng JSON (tùy chọn)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditMode ? "Cập nhật" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
