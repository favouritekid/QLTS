// src/components/admin/organization/ProgramOfferingDialog.tsx
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
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Loader2 } from "lucide-react";
import {
  useCreateProgramOffering,
  useUpdateProgramOffering,
} from "@/hooks/useOrganization";
import type {
  ProgramOffering,
  ProgramOfferingCreate,
  ProgramOfferingUpdate,
  MajorProgram,
} from "@/types/organization.types";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const offeringFormSchema = z.object({
  offering_type: z
    .string()
    .min(1, "Loại hình đào tạo là bắt buộc")
    .max(100, "Loại hình không được vượt quá 100 ký tự"),
  duration_semesters: z
    .number()
    .int("Số kỳ học phải là số nguyên")
    .min(1, "Số kỳ học phải lớn hơn 0")
    .max(20, "Số kỳ học không được vượt quá 20")
    .nullish()
    .or(z.literal("")),
  total_credits: z
    .number()
    .int("Tổng số tín chỉ phải là số nguyên")
    .min(1, "Tổng số tín chỉ phải lớn hơn 0")
    .max(300, "Tổng số tín chỉ không được vượt quá 300")
    .nullish()
    .or(z.literal("")),
  is_active: z.boolean(),
});

type OfferingFormValues = z.infer<typeof offeringFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface ProgramOfferingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  majorProgram: MajorProgram; // Parent MajorProgram (Tier 1)
  offering?: ProgramOffering | null; // null = create mode, non-null = edit mode
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function ProgramOfferingDialog({
  open,
  onOpenChange,
  majorProgram,
  offering,
}: ProgramOfferingDialogProps) {
  const isEditMode = !!offering;

  // Mutations
  const createMutation = useCreateProgramOffering();
  const updateMutation = useUpdateProgramOffering();

  // Form
  const form = useForm<OfferingFormValues>({
    resolver: zodResolver(offeringFormSchema),
    defaultValues: {
      offering_type: "",
      duration_semesters: null,
      total_credits: null,
      is_active: true,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && offering) {
        form.reset({
          offering_type: offering.offering_type || "",
          duration_semesters: offering.duration_semesters ?? null,
          total_credits: offering.total_credits ?? null,
          is_active: offering.is_active,
        });
      } else {
        form.reset({
          offering_type: "",
          duration_semesters: null,
          total_credits: null,
          is_active: true,
        });
      }
    }
  }, [open, isEditMode, offering, form]);

  // Handle form submission
  const onSubmit = async (values: OfferingFormValues) => {
    const payload = {
      offering_type: values.offering_type,
      duration_semesters: values.duration_semesters ?? null,
      total_credits: values.total_credits ?? null,
      is_active: values.is_active,
    };

    try {
      if (isEditMode && offering) {
        await updateMutation.mutateAsync({
          id: offering.id,
          data: payload as ProgramOfferingUpdate,
        });
      } else {
        await createMutation.mutateAsync({
          programId: majorProgram.id,
          ...payload,
        } as ProgramOfferingCreate & { programId: number });
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
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Chỉnh sửa loại hình đào tạo" : "Tạo loại hình đào tạo mới"}
          </DialogTitle>
          <DialogDescription>
            Chương trình: <strong>{majorProgram.name}</strong>
            <br />
            {isEditMode
              ? "Cập nhật thông tin loại hình đào tạo"
              : "Nhập thông tin để tạo loại hình đào tạo mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Offering Type Field */}
            <FormField
              control={form.control}
              name="offering_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Loại hình đào tạo <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Chính quy, Liên thông, Vừa làm vừa học"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Tên loại hình đào tạo (vd: Chính quy, Liên thông)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Duration Semesters Field */}
            <FormField
              control={form.control}
              name="duration_semesters"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Số kỳ học</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      placeholder="VD: 6"
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(e.target.value ? parseInt(e.target.value) : null)
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Tổng số kỳ học của chương trình (tùy chọn)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Total Credits Field */}
            <FormField
              control={form.control}
              name="total_credits"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tổng số tín chỉ</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      placeholder="VD: 120"
                      {...field}
                      value={field.value ?? ""}
                      onChange={(e) =>
                        field.onChange(e.target.value ? parseInt(e.target.value) : null)
                      }
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Tổng số tín chỉ cần hoàn thành (tùy chọn)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Is Active Switch */}
            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Trạng thái hoạt động</FormLabel>
                    <FormDescription>
                      Loại hình đào tạo có đang hoạt động hay không
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
