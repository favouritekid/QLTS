// src/components/admin/PipelineStageDialog.tsx
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
import { Loader2 } from "lucide-react";
import {
  useCreatePipelineStage,
  useUpdatePipelineStage,
} from "@/hooks/usePipeline";
import type {
  PipelineStage,
  PipelineStageCreate,
  PipelineStageUpdate,
} from "@/types/pipeline.types";
import { Checkbox as ShadcnCheckbox } from "@/components/ui/checkbox";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const stageFormSchema = z.object({
  id: z
    .string()
    .min(1, "Mã giai đoạn là bắt buộc")
    .regex(/^[a-z0-9_]+$/, "Mã giai đoạn chỉ được chứa chữ thường, số và gạch dưới")
    .max(50, "Mã giai đoạn không vượt quá 50 ký tự"),
  name: z
    .string()
    .min(1, "Tên giai đoạn là bắt buộc")
    .min(2, "Tên giai đoạn phải có ít nhất 2 ký tự")
    .max(100, "Tên giai đoạn không vượt quá 100 ký tự"),
  order: z
    .number()
    .int("Thứ tự phải là số nguyên")
    .min(0, "Thứ tự phải lớn hơn hoặc bằng 0"),
  is_final_stage: z.boolean(),
});

type StageFormValues = z.infer<typeof stageFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface PipelineStageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stage?: PipelineStage | null; // null = create mode, non-null = edit mode
  maxOrder?: number; // For suggesting next order number
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function PipelineStageDialog({
  open,
  onOpenChange,
  stage,
  maxOrder = 0,
}: PipelineStageDialogProps) {
  const isEditMode = !!stage;

  // Mutations
  const createMutation = useCreatePipelineStage();
  const updateMutation = useUpdatePipelineStage();

  // Form
  const form = useForm<StageFormValues>({
    resolver: zodResolver(stageFormSchema),
    defaultValues: {
      id: "",
      name: "",
      order: maxOrder + 1,
      is_final_stage: false,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && stage) {
        form.reset({
          id: stage.id,
          name: stage.name,
          order: stage.order,
          is_final_stage: stage.is_final_stage || false,
        });
      } else {
        form.reset({
          id: "",
          name: "",
          order: maxOrder + 1,
          is_final_stage: false,
        });
      }
    }
  }, [open, isEditMode, stage, maxOrder, form]);

  // Handle form submission
  const onSubmit = async (values: StageFormValues) => {
    try {
      if (isEditMode && stage) {
        await updateMutation.mutateAsync({
          id: stage.id,
          data: {
            name: values.name,
            order: values.order,
            is_final_stage: values.is_final_stage,
          } as PipelineStageUpdate,
        });
      } else {
        await createMutation.mutateAsync({
          id: values.id,
          name: values.name,
          order: values.order,
          is_final_stage: values.is_final_stage,
        } as PipelineStageCreate);
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
            {isEditMode ? "Chỉnh sửa Giai đoạn" : "Tạo Giai đoạn Mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật thông tin giai đoạn pipeline"
              : "Nhập thông tin để tạo giai đoạn pipeline mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* ID Field - Only for create mode */}
            {!isEditMode && (
              <FormField
                control={form.control}
                name="id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Mã giai đoạn <span className="text-error-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="VD: Theo dõi cuộc gọi"
                        {...field}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Mã định danh duy nhất (chữ thường, số, gạch dưới)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên giai đoạn <span className="text-error-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Gọi theo dõi"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Tên hiển thị của giai đoạn này
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Order Field */}
            <FormField
              control={form.control}
              name="order"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Thứ tự <span className="text-error-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      placeholder="0"
                      {...field}
                      onChange={(e) => field.onChange(parseInt(e.target.value, 10))}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Vị trí trong pipeline (0 = đầu tiên)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Is Final Stage Field */}
            <FormField
              control={form.control}
              name="is_final_stage"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                  <FormControl>
                    <ShadcnCheckbox
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>
                      Giai đoạn cuối
                    </FormLabel>
                    <FormDescription>
                      Đánh dấu đây là giai đoạn cuối cùng (Thắng/Thua/Đóng).
                      Giai đoạn cuối đại diện cho điểm kết thúc của phễu chuyển đổi.
                    </FormDescription>
                  </div>
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
