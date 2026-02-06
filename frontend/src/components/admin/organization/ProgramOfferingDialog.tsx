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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Loader2 } from "lucide-react";
import {
  useCreateProgramOffering,
  useUpdateProgramOffering,
  useOfferingTypes,
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
  // Scoring Rules fields
  hot_level: z.number().min(0).max(2).optional(),
  target_age_min: z.number().int().min(16).max(100).nullish().or(z.literal("")),
  target_age_max: z.number().int().min(16).max(100).nullish().or(z.literal("")),
  required_education: z.string().optional().nullable(),
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

  // Queries
  const { data: offeringTypes = [], isLoading: offeringTypesLoading } = useOfferingTypes(true); // Only active

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
      hot_level: 0,
      target_age_min: null,
      target_age_max: null,
      required_education: null,
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
          hot_level: offering.scoring_rules?.hot_level ?? 0,
          target_age_min: offering.scoring_rules?.target_age_min ?? null,
          target_age_max: offering.scoring_rules?.target_age_max ?? null,
          required_education: offering.scoring_rules?.required_education ?? null,
        });
      } else {
        form.reset({
          offering_type: "",
          duration_semesters: null,
          total_credits: null,
          is_active: true,
          hot_level: 0,
          target_age_min: null,
          target_age_max: null,
          required_education: null,
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
      scoring_rules: {
        hot_level: values.hot_level ?? 0,
        target_age_min: values.target_age_min ?? null,
        target_age_max: values.target_age_max ?? null,
        required_education: values.required_education ?? null,
      },
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
                    Loại hình đào tạo <span className="text-error-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting || offeringTypesLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder={
                          offeringTypesLoading ? "Đang tải…" : "Chọn loại hình đào tạo"
                        } />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {offeringTypesLoading ? (
                        <SelectItem value="loading" disabled>
                          Đang tải…
                        </SelectItem>
                      ) : offeringTypes.length === 0 ? (
                        <SelectItem value="empty" disabled>
                          Chưa có loại hình nào. Vui lòng tạo trong Cấu hình hệ thống.
                        </SelectItem>
                      ) : (
                        offeringTypes.map((type) => (
                          <SelectItem key={type.id} value={type.name}>
                            {type.name}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Loại hình đào tạo (vd: Chính quy, Liên thông)
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

            {/* === SCORING RULES SECTION === */}
            <div className="border-t pt-4 mt-4">
              <h4 className="font-medium text-sm mb-3">Cấu hình chấm điểm Fit Score</h4>
              
              {/* Hot Level */}
              <FormField
                control={form.control}
                name="hot_level"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mức độ Hot</FormLabel>
                    <Select
                      onValueChange={(val) => field.onChange(parseInt(val))}
                      value={field.value?.toString() ?? "0"}
                      disabled={isSubmitting}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn mức độ" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="0">Bình thường</SelectItem>
                        <SelectItem value="1">🔥 Hot (+5 điểm)</SelectItem>
                        <SelectItem value="2">🔥🔥 Rất Hot (+10 điểm)</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>Ngành hot sẽ được ưu tiên khi tính điểm Fit Score</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Target Age Range */}
              <div className="grid grid-cols-2 gap-4 mt-4">
                <FormField
                  control={form.control}
                  name="target_age_min"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tuổi tối thiểu</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          placeholder="VD: 18"
                          {...field}
                          value={field.value ?? ""}
                          onChange={(e) =>
                            field.onChange(e.target.value ? parseInt(e.target.value) : null)
                          }
                          disabled={isSubmitting}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="target_age_max"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tuổi tối đa</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          placeholder="VD: 25"
                          {...field}
                          value={field.value ?? ""}
                          onChange={(e) =>
                            field.onChange(e.target.value ? parseInt(e.target.value) : null)
                          }
                          disabled={isSubmitting}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <p className="text-[0.8rem] text-muted-foreground mt-1">Độ tuổi lý tưởng để đạt điểm Fit Score cao nhất</p>

              {/* Required Education */}
              <FormField
                control={form.control}
                name="required_education"
                render={({ field }) => (
                  <FormItem className="mt-4">
                    <FormLabel>Trình độ yêu cầu</FormLabel>
                    <Select
                      onValueChange={(val) => field.onChange(val === "none" ? null : val)}
                      value={field.value ?? "none"}
                      disabled={isSubmitting}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn trình độ" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="none">Không yêu cầu</SelectItem>
                        <SelectItem value="high_school">THPT / Tương đương</SelectItem>
                        <SelectItem value="diploma">Trung cấp / Cao đẳng</SelectItem>
                        <SelectItem value="bachelor">Đại học</SelectItem>
                        <SelectItem value="master">Thạc sĩ</SelectItem>
                        <SelectItem value="phd">Tiến sĩ</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>Lead đạt yêu cầu sẽ được cộng điểm học vấn</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
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
                {isEditMode ? "Cập nhật" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
