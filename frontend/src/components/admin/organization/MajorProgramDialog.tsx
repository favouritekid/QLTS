// src/components/admin/organization/MajorProgramDialog.tsx
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
  useCreateMajorProgram,
  useUpdateMajorProgram,
  useDegreeLevels,
} from "@/hooks/useOrganization";
import { SmartUnitSelector } from "@/components/common/selectors";
import type {
  MajorProgram,
  MajorProgramCreate,
  MajorProgramUpdate,
} from "@/types/organization.types";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const majorProgramFormSchema = z.object({
  name: z
    .string()
    .min(1, "Tên chương trình là bắt buộc")
    .min(3, "Tên chương trình phải có ít nhất 3 ký tự")
    .max(255, "Tên chương trình không được vượt quá 255 ký tự"),
  degree_level: z
    .string()
    .min(1, "Trình độ là bắt buộc")
    .max(50, "Trình độ không được vượt quá 50 ký tự"),
  code: z
    .string()
    .min(1, "Mã ngành là bắt buộc")
    .min(2, "Mã ngành phải có ít nhất 2 ký tự")
    .max(50, "Mã ngành không được vượt quá 50 ký tự")
    .regex(/^[A-Z0-9_-]+$/, "Mã ngành chỉ bao gồm chữ in hoa, số, dấu gạch ngang và gạch dưới"),
  unit_id: z.string().min(1, "Đơn vị quản lý là bắt buộc"), // String vì Select dùng string
  is_active: z.boolean(),
  is_heavy: z.boolean(), // Ngành nghề nặng nhọc, độc hại
});

type MajorProgramFormValues = z.infer<typeof majorProgramFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface MajorProgramDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  majorProgram?: MajorProgram | null; // null = create mode, non-null = edit mode
  preselectedUnitId?: number | null; // Pre-select unit when creating
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function MajorProgramDialog({
  open,
  onOpenChange,
  majorProgram,
  preselectedUnitId,
}: MajorProgramDialogProps) {
  const isEditMode = !!majorProgram;

  // Queries
  const { data: degreeLevels = [], isLoading: degreeLevelsLoading } = useDegreeLevels(true); // Only active

  // Mutations
  const createMutation = useCreateMajorProgram();
  const updateMutation = useUpdateMajorProgram();

  // Form
  const form = useForm<MajorProgramFormValues>({
    resolver: zodResolver(majorProgramFormSchema),
    defaultValues: {
      name: "",
      degree_level: "",
      code: "",
      unit_id: "",
      is_active: true,
      is_heavy: false,
    },
  });

  // Populate form when editing or preselecting
  useEffect(() => {
    if (open) {
      if (isEditMode && majorProgram) {
        form.reset({
          name: majorProgram.name || "",
          degree_level: majorProgram.degree_level || "",
          code: majorProgram.code || "",
          unit_id: String(majorProgram.unit_id),
          is_active: majorProgram.is_active,
          is_heavy: majorProgram.is_heavy ?? false,
        });
      } else {
        form.reset({
          name: "",
          degree_level: "",
          code: "",
          unit_id: preselectedUnitId ? String(preselectedUnitId) : "",
          is_active: true,
          is_heavy: false,
        });
      }
    }
  }, [open, isEditMode, majorProgram, preselectedUnitId, form]);

  // Handle form submission
  const onSubmit = async (values: MajorProgramFormValues) => {
    const payload = {
      name: values.name,
      degree_level: values.degree_level,
      code: values.code.toUpperCase(), // Ensure uppercase
      unit_id: Number(values.unit_id),
      is_active: values.is_active,
      is_heavy: values.is_heavy,
    };

    try {
      if (isEditMode && majorProgram) {
        // Cannot update 'code' - remove it from payload
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { code: _code, ...updatePayload } = payload;
        await updateMutation.mutateAsync({
          id: majorProgram.id,
          data: updatePayload as MajorProgramUpdate,
        });
      } else {
        await createMutation.mutateAsync(payload as MajorProgramCreate);
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

  // Helper to format code as user types (uppercase, no spaces)
  const handleCodeChange = (value: string) => {
    const formatted = value.toUpperCase().replace(/\s+/g, "_");
    form.setValue("code", formatted, { shouldValidate: true });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Chỉnh sửa chương trình đào tạo" : "Tạo chương trình đào tạo mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật thông tin của chương trình đào tạo"
              : "Nhập thông tin để tạo chương trình đào tạo mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên chương trình <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Cao đẳng Công nghệ Thông tin"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Degree Level Field */}
            <FormField
              control={form.control}
              name="degree_level"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Trình độ đào tạo <span className="text-red-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting || degreeLevelsLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder={
                          degreeLevelsLoading ? "Đang tải..." : "Chọn trình độ đào tạo"
                        } />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {degreeLevelsLoading ? (
                        <SelectItem value="loading" disabled>
                          Đang tải...
                        </SelectItem>
                      ) : degreeLevels.length === 0 ? (
                        <SelectItem value="empty" disabled>
                          Chưa có trình độ nào. Vui lòng tạo trình độ trong Cấu hình hệ thống.
                        </SelectItem>
                      ) : (
                        degreeLevels.map((level) => (
                          <SelectItem key={level.id} value={level.name}>
                            {level.name}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Trình độ đào tạo của chương trình (vd: Cao đẳng, Đại học)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Code Field */}
            <FormField
              control={form.control}
              name="code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Mã ngành <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    {isEditMode ? (
                      <div className="flex items-center gap-2 py-2 px-3 bg-muted rounded-md border border-input">
                        <span className="text-sm font-mono font-semibold tracking-wide">
                          {field.value}
                        </span>
                        <span className="text-xs text-muted-foreground ml-auto">
                          (Không thể thay đổi)
                        </span>
                      </div>
                    ) : (
                      <Input
                        placeholder="VD: 6480201"
                        {...field}
                        onChange={(e) => handleCodeChange(e.target.value)}
                        disabled={isSubmitting}
                        className="uppercase"
                      />
                    )}
                  </FormControl>
                  <FormDescription>
                    Mã ngành tuyển sinh - Định danh duy nhất (chữ in hoa, số, gạch ngang hoặc gạch dưới)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit Field - Using SmartUnitSelector */}
            <FormField
              control={form.control}
              name="unit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Đơn vị quản lý <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <SmartUnitSelector
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Chọn đơn vị quản lý"
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Đơn vị tổ chức quản lý chương trình này
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
                      Chương trình có đang hoạt động hay không
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

            {/* Is Heavy Switch - Ngành nghề nặng nhọc, độc hại */}
            <FormField
              control={form.control}
              name="is_heavy"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border border-amber-200 bg-amber-50/50 p-4">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Ngành nghề nặng nhọc, độc hại</FormLabel>
                    <FormDescription>
                      Ngành nghề nặng nhọc, độc hại, nguy hiểm (được hưởng chính sách đặc biệt)
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
