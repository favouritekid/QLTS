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
    .min(1, "Stage ID is required")
    .regex(/^[a-z0-9_]+$/, "Stage ID must contain only lowercase letters, numbers, and underscores")
    .max(50, "Stage ID must not exceed 50 characters"),
  name: z
    .string()
    .min(1, "Stage name is required")
    .min(2, "Stage name must be at least 2 characters")
    .max(100, "Stage name must not exceed 100 characters"),
  order: z
    .number()
    .int("Order must be an integer")
    .min(0, "Order must be 0 or greater"),
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
            {isEditMode ? "Edit Pipeline Stage" : "Create New Pipeline Stage"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Update the pipeline stage information"
              : "Enter information to create a new pipeline stage"}
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
                      Stage ID <span className="text-red-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., follow_up_call"
                        {...field}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Unique identifier (lowercase, numbers, underscores only)
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
                    Stage Name <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Follow-up Call"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Display name for this stage
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
                    Order <span className="text-red-500">*</span>
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
                    Position in the pipeline (0 = first)
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
                      Final Stage
                    </FormLabel>
                    <FormDescription>
                      Mark this as a final stage (Won/Lost/Closed).
                      Final stages represent end of the conversion funnel.
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
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditMode ? "Update" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
