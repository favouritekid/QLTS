// src/components/admin/ConsultationStatusDialog.tsx
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
import { Loader2 } from "lucide-react";
import {
  useCreateConsultationStatus,
  useUpdateConsultationStatus,
  usePipelineStages,
} from "@/hooks/usePipeline";
import type {
  ConsultationStatus,
  ConsultationStatusCreate,
  ConsultationStatusUpdate,
  OutcomeType,
} from "@/types/pipeline.types";
import { Checkbox as ShadcnCheckbox } from "@/components/ui/checkbox";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const statusFormSchema = z.object({
  id: z
    .string()
    .min(1, "Status ID is required")
    .regex(/^[a-z0-9_]+$/, "Status ID must contain only lowercase letters, numbers, and underscores")
    .max(50, "Status ID must not exceed 50 characters"),
  name: z
    .string()
    .min(1, "Status name is required")
    .min(2, "Status name must be at least 2 characters")
    .max(100, "Status name must not exceed 100 characters"),
  color_code: z
    .string()
    .min(1, "Color is required")
    .regex(/^#[0-9A-Fa-f]{6}$/, "Color must be a valid hex color (e.g., #FF5733)"),
  stage_id: z
    .string()
    .min(1, "Stage is required"),
  outcome_type: z.enum(["positive", "neutral", "negative"]),
  is_final_status: z.boolean(),
});

type StatusFormValues = z.infer<typeof statusFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface ConsultationStatusDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status?: ConsultationStatus | null; // null = create mode, non-null = edit mode
}

// =====================================================================
// PRESET COLORS
// =====================================================================

const PRESET_COLORS = [
  { name: "Blue", value: "#3B82F6" },
  { name: "Green", value: "#10B981" },
  { name: "Yellow", value: "#F59E0B" },
  { name: "Red", value: "#EF4444" },
  { name: "Purple", value: "#8B5CF6" },
  { name: "Pink", value: "#EC4899" },
  { name: "Indigo", value: "#6366F1" },
  { name: "Gray", value: "#6B7280" },
];

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function ConsultationStatusDialog({
  open,
  onOpenChange,
  status,
}: ConsultationStatusDialogProps) {
  const isEditMode = !!status;

  // Queries
  const { data: stages = [], isLoading: stagesLoading } = usePipelineStages();

  // Mutations
  const createMutation = useCreateConsultationStatus();
  const updateMutation = useUpdateConsultationStatus();

  // Form
  const form = useForm<StatusFormValues>({
    resolver: zodResolver(statusFormSchema),
    defaultValues: {
      id: "",
      name: "",
      color_code: "#3B82F6",
      stage_id: "",
      outcome_type: "neutral",
      is_final_status: false,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && status) {
        form.reset({
          id: status.id,
          name: status.name,
          color_code: status.color_code,
          stage_id: status.stage_id,
          outcome_type: status.outcome_type || "neutral",
          is_final_status: status.is_final_status || false,
        });
      } else {
        form.reset({
          id: "",
          name: "",
          color_code: "#3B82F6",
          stage_id: "",
          outcome_type: "neutral",
          is_final_status: false,
        });
      }
    }
  }, [open, isEditMode, status, form]);

  // Handle form submission
  const onSubmit = async (values: StatusFormValues) => {
    try {
      if (isEditMode && status) {
        await updateMutation.mutateAsync({
          id: status.id,
          data: {
            name: values.name,
            color_code: values.color_code,
            stage_id: values.stage_id,
            outcome_type: values.outcome_type as OutcomeType,
            is_final_status: values.is_final_status,
          } as ConsultationStatusUpdate,
        });
      } else {
        await createMutation.mutateAsync({
          id: values.id,
          name: values.name,
          color_code: values.color_code,
          stage_id: values.stage_id,
          outcome_type: values.outcome_type as OutcomeType,
          is_final_status: values.is_final_status,
        } as ConsultationStatusCreate);
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
            {isEditMode ? "Edit Consultation Status" : "Create New Consultation Status"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Update the consultation status information"
              : "Enter information to create a new consultation status"}
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
                      Status ID <span className="text-red-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., rescheduled"
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
                    Status Name <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Rescheduled"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormDescription>
                    Display name for this status
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Stage Field */}
            <FormField
              control={form.control}
              name="stage_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Pipeline Stage <span className="text-red-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting || stagesLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a stage" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {stagesLoading ? (
                        <SelectItem value="loading" disabled>
                          Loading...
                        </SelectItem>
                      ) : stages.length === 0 ? (
                        <SelectItem value="empty" disabled>
                          No stages available
                        </SelectItem>
                      ) : (
                        stages.map((stage) => (
                          <SelectItem key={stage.id} value={stage.id}>
                            {stage.name}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Which pipeline stage this status applies to
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Color Field */}
            <FormField
              control={form.control}
              name="color_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Color <span className="text-red-500">*</span>
                  </FormLabel>
                  <div className="flex gap-2">
                    <FormControl>
                      <Input
                        placeholder="#3B82F6"
                        {...field}
                        disabled={isSubmitting}
                        className="flex-1"
                      />
                    </FormControl>
                    <div
                      className="w-10 h-10 rounded border"
                      style={{ backgroundColor: field.value }}
                    />
                  </div>
                  <FormDescription>
                    Hex color code for this status
                  </FormDescription>
                  {/* Color Presets */}
                  <div className="flex gap-2 mt-2">
                    {PRESET_COLORS.map((color) => (
                      <button
                        key={color.value}
                        type="button"
                        className="w-6 h-6 rounded border-2 hover:scale-110 transition-transform"
                        style={{
                          backgroundColor: color.value,
                          borderColor: field.value === color.value ? "#000" : "transparent",
                        }}
                        onClick={() => field.onChange(color.value)}
                        title={color.name}
                      />
                    ))}
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Outcome Type Field */}
            <FormField
              control={form.control}
              name="outcome_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Outcome Type <span className="text-red-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select outcome type" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="positive">
                        <span className="flex items-center gap-2">
                          <span className="text-green-500">●</span> Positive
                        </span>
                      </SelectItem>
                      <SelectItem value="neutral">
                        <span className="flex items-center gap-2">
                          <span className="text-gray-500">●</span> Neutral
                        </span>
                      </SelectItem>
                      <SelectItem value="negative">
                        <span className="flex items-center gap-2">
                          <span className="text-red-500">●</span> Negative
                        </span>
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Classify this status outcome (used for reporting and analytics)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Is Final Status Field */}
            <FormField
              control={form.control}
              name="is_final_status"
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
                      Final Status
                    </FormLabel>
                    <FormDescription>
                      Mark this as end of lead lifecycle (e.g., "Enrolled", "Rejected").
                      Leads with final status won&apos;t be counted in active pipeline.
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
