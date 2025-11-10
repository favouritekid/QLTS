// src/components/admin/organization/AcademicInfoDialog.tsx
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
  useCreateAcademicInfo,
  useUpdateAcademicInfo,
} from "@/hooks/useOrganization";
import type {
  MajorAcademicInfo,
  MajorAcademicInfoCreate,
  MajorAcademicInfoUpdate,
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
  target_audience: z
    .string()
    .max(1000, "Đối tượng tuyển sinh không được vượt quá 1000 ký tự")
    .optional(),
  detailed_info: z.string().optional(),
  current_year_benefits: z.string().optional(),
  tuition_fee_per_year: z
    .number()
    .min(0, "Học phí không thể âm")
    .nullish(),
  annual_admission_quota: z
    .number()
    .int("Chỉ tiêu tuyển sinh phải là số nguyên")
    .min(0, "Chỉ tiêu tuyển sinh không thể âm")
    .nullish(),
  is_published: z.boolean(),
});

type AcademicInfoFormValues = z.infer<typeof academicInfoFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface AcademicInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  majorId: number;
  majorName: string;
  academicInfo?: MajorAcademicInfo | null; // null = create mode
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function AcademicInfoDialog({
  open,
  onOpenChange,
  majorId,
  majorName,
  academicInfo,
}: AcademicInfoDialogProps) {
  const isEditMode = !!academicInfo;

  // Mutations
  const createMutation = useCreateAcademicInfo();
  const updateMutation = useUpdateAcademicInfo();

  // Form
  const form = useForm<AcademicInfoFormValues>({
    resolver: zodResolver(academicInfoFormSchema),
    defaultValues: {
      academic_year: new Date().getFullYear(),
      target_audience: "",
      detailed_info: "",
      current_year_benefits: "",
      tuition_fee_per_year: null,
      annual_admission_quota: null,
      is_published: false,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && academicInfo) {
        form.reset({
          academic_year: academicInfo.academic_year,
          target_audience: academicInfo.target_audience || "",
          detailed_info: academicInfo.detailed_info || "",
          current_year_benefits: academicInfo.current_year_benefits || "",
          tuition_fee_per_year: academicInfo.tuition_fee_per_year ?? null,
          annual_admission_quota: academicInfo.annual_admission_quota ?? null,
          is_published: academicInfo.is_published,
        });
      } else {
        form.reset({
          academic_year: new Date().getFullYear(),
          target_audience: "",
          detailed_info: "",
          current_year_benefits: "",
          tuition_fee_per_year: null,
          annual_admission_quota: null,
          is_published: false,
        });
      }
    }
  }, [open, isEditMode, academicInfo, form]);

  // Handle form submission
  const onSubmit = async (values: AcademicInfoFormValues) => {
    try {
      if (isEditMode && academicInfo) {
        // Update existing
        const payload: MajorAcademicInfoUpdate = {
          target_audience: values.target_audience || null,
          detailed_info: values.detailed_info || null,
          current_year_benefits: values.current_year_benefits || null,
          tuition_fee_per_year: values.tuition_fee_per_year ?? null,
          annual_admission_quota: values.annual_admission_quota ?? null,
          is_published: values.is_published,
        };
        await updateMutation.mutateAsync({
          id: academicInfo.id,
          data: payload,
        });
      } else {
        // Create new
        const payload: MajorAcademicInfoCreate = {
          major_id: majorId,
          academic_year: values.academic_year,
          target_audience: values.target_audience || null,
          detailed_info: values.detailed_info || null,
          current_year_benefits: values.current_year_benefits || null,
          tuition_fee_per_year: values.tuition_fee_per_year ?? null,
          annual_admission_quota: values.annual_admission_quota ?? null,
          is_published: values.is_published,
        };
        await createMutation.mutateAsync(payload);
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
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditMode
              ? `Chỉnh sửa thông tin học thuật - Năm ${academicInfo.academic_year}`
              : "Tạo thông tin học thuật mới"}
          </DialogTitle>
          <DialogDescription>
            {majorName}
            <br />
            {isEditMode
              ? "Cập nhật thông tin học thuật cho năm học này"
              : "Nhập thông tin học thuật cho năm học mới"}
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
                        placeholder="VD: 2024"
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

            {/* Detailed Info */}
            <FormField
              control={form.control}
              name="detailed_info"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Thông tin chi tiết</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả chi tiết về ngành học, nội dung đào tạo..."
                      className="resize-none min-h-[100px]"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Thông tin chi tiết về ngành học trong năm này
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Current Year Benefits */}
            <FormField
              control={form.control}
              name="current_year_benefits"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Lợi ích trong năm</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="VD: Miễn học phí năm đầu, học bổng 50%..."
                      className="resize-none"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Các chính sách ưu đãi, học bổng trong năm học này
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
