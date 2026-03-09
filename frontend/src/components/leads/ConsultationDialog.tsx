// src/components/leads/ConsultationDialog.tsx
"use client";

import { useEffect, useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormDialog, useFormDialogClose } from "@/components/ui/form-dialog";
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormActions } from "@/components/common/form/ResponsiveFormLayout";
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
import { Textarea } from "@/components/ui/textarea";
import { DateTimePicker } from "@/components/common/form";

import { toast } from "sonner";
import { useAddConsultation, useUpdateConsultation, useLead } from "@/hooks/useLeads";
import { useAllowedNextStatuses, useConsultationStatuses } from "@/hooks/usePipeline";
import { useWorkflowContext, getAllowedStatusIds } from "@/hooks/useWorkflowContext";
import { SmartConsultationStatusSelector } from "@/components/common/selectors";
import { LossReasonQuickSelect, requiresLossReason } from "@/components/leads/LossReasonQuickSelect";
import type { Consultation, ConsultationUpdate } from "@/types/lead.types";

// Unified validation schema with optional fields for flexibility
const consultationSchema = z.object({
  scheduled_at: z.date().optional().nullable(),
  status_id: z.string().optional(),
  notes: z.string().max(1000, "Ghi chú không được quá 1000 ký tự").optional(),
  method: z.enum(["phone", "email", "in_person", "sms", "video_call"]).optional(),
  duration_minutes: z.number().min(0).max(480).optional(),
  // Loss Reason fields (required when status is final negative)
  loss_reason_code: z.string().optional().nullable(),
  loss_reason_note: z.string().max(200, "Ghi chú lý do không được quá 200 ký tự").optional(),
});

type ConsultationFormValues = z.infer<typeof consultationSchema>;

interface ConsultationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leadId: number;
  /** Existing consultation for edit mode (null/undefined = create mode) */
  consultation?: Consultation | null;
  /** Dialog mode: "create" for new consultation, "edit" for updating existing */
  mode: "create" | "edit";
}

/**
 * Cancel button that uses FormDialog's close interceptor
 */
function CancelButton({ disabled }: { disabled?: boolean }) {
  const requestClose = useFormDialogClose();
  return (
    <Button
      type="button"
      variant="outline"
      onClick={requestClose}
      disabled={disabled}
    >
      Hủy
    </Button>
  );
}

/**
 * Unified Consultation Dialog for both create and edit modes
 *
 * Create mode: Lên lịch tư vấn mới (required: scheduled_at, status_id)
 * Edit mode: Cập nhật thông tin tư vấn (all fields optional, includes method/duration)
 *
 * Features:
 * - FormDialog wrapper prevents accidental data loss
 * - isDirty check shows confirmation when closing with unsaved changes
 * - Allowed next statuses for workflow compliance in edit mode
 * - ✅ Phase-based filtering via useWorkflowContext
 */
export function ConsultationDialog({
  open,
  onOpenChange,
  leadId,
  consultation,
  mode,
}: ConsultationDialogProps) {
  const isCreate = mode === "create";
  const isEdit = mode === "edit";

  const addMutation = useAddConsultation();
  const updateMutation = useUpdateConsultation();

  // ✅ FIX: Fetch lead data to get current consultation status for CREATE mode
  const { data: lead } = useLead(leadId, open && isCreate);

  // Determine current status ID based on mode:
  // - CREATE mode: use lead's current consultation_status_id
  // - EDIT mode: use the consultation's status (for editing existing consultation)
  const currentStatusId = isCreate
    ? (lead?.consultation_status_id || null)
    : (consultation?.consultation_status_id || null);

  // Get allowed next statuses using FSM engine (filtered by selectable_mode)
  // This ensures officers only see statuses they're allowed to select
  const { data: allowedStatuses, isLoading: statusesLoading } = useAllowedNextStatuses(
    currentStatusId,
    leadId
  );

  // ✅ PHASE-BASED WORKFLOW: Get workflow context for phase filtering
  const { data: workflowContext } = useWorkflowContext(leadId, { enabled: open });
  const allowedByPhase = getAllowedStatusIds(workflowContext);

  // Combine transition-based and phase-based filtering for BOTH modes
  const filteredAllowedStatusIds = useMemo(() => {
    const transitionIds = allowedStatuses?.map(s => s.id) || [];

    // If no allowed statuses yet (loading), return undefined to show loading state
    if (transitionIds.length === 0 && statusesLoading) {
      return undefined;
    }

    // If no phase context, use transition-based filtering only
    if (allowedByPhase.size === 0) {
      return transitionIds.length > 0 ? transitionIds : undefined;
    }

    // Intersect: status must be allowed by BOTH transitions AND phase
    const filtered = transitionIds.filter(id => allowedByPhase.has(id));
    return filtered.length > 0 ? filtered : transitionIds; // Fallback to transition-only if phase filter returns empty
  }, [allowedStatuses, allowedByPhase, statusesLoading]);

  // Fetch all consultation statuses to check is_final/outcome_type
  const { data: allStatuses = [] } = useConsultationStatuses();

  const form = useForm<ConsultationFormValues>({
    resolver: zodResolver(consultationSchema),
    defaultValues: {
      scheduled_at: undefined,
      status_id: "",
      notes: "",
      method: "phone",
      duration_minutes: undefined,
      loss_reason_code: null,
      loss_reason_note: "",
    },
  });

  // Watch status_id to conditionally show loss reason
  const watchedStatusId = useWatch({ control: form.control, name: "status_id" });
  const selectedStatus = useMemo(() => {
    return allStatuses.find(s => s.id === watchedStatusId) || null;
  }, [allStatuses, watchedStatusId]);
  const showLossReason = requiresLossReason(selectedStatus);


  // Reset/populate form when dialog opens
  useEffect(() => {
    if (!open) {
      form.reset();
      return;
    }

    if (isEdit && consultation) {
      // Populate form with existing consultation data
      form.reset({
        scheduled_at: consultation.scheduled_at
          ? new Date(consultation.scheduled_at)
          : undefined,
        status_id: consultation.consultation_status_id || "",
        notes: consultation.notes || "",
        method: consultation.method || "phone",
        duration_minutes: consultation.duration_minutes || undefined,
        // Loss reason from consultation (if available)
        loss_reason_code: (consultation as unknown as { loss_reason_code?: string })?.loss_reason_code || null,
        loss_reason_note: (consultation as unknown as { loss_reason_note?: string })?.loss_reason_note || "",
      });
    } else if (isCreate) {
      // Reset to empty for create mode
      form.reset({
        scheduled_at: undefined,
        status_id: "",
        notes: "",
        method: "phone",
        duration_minutes: undefined,
        loss_reason_code: null,
        loss_reason_note: "",
      });
    }
  }, [open, consultation, isEdit, isCreate, form]);

  const onSubmit = async (data: ConsultationFormValues) => {
    // Check if loss reason is required for the selected status
    const targetStatus = allStatuses.find(s => s.id === data.status_id);
    const needsLossReason = requiresLossReason(targetStatus);

    if (needsLossReason && !data.loss_reason_code) {
      form.setError("loss_reason_code", {
        type: "required",
        message: "Vui lòng chọn lý do không tiếp tục",
      });
      return;
    }

    if (isCreate) {
      // Create mode: validate required fields
      if (!data.scheduled_at) {
        form.setError("scheduled_at", {
          type: "required",
          message: "Vui lòng chọn ngày giờ hẹn",
        });
        toast.error("Vui lòng chọn ngày giờ hẹn");
        return;
      }
      if (!data.status_id) {
        form.setError("status_id", {
          type: "required",
          message: "Vui lòng chọn trạng thái",
        });
        toast.error("Vui lòng chọn trạng thái");
        return;
      }

      addMutation.mutate(
        {
          leadId,
          data: {
            scheduled_at: data.scheduled_at.toISOString(),
            status_id: data.status_id,
            notes: data.notes,
            method: data.method || "phone",
            // Include loss reason if provided
            ...(data.loss_reason_code && {
              loss_reason_code: data.loss_reason_code,
              loss_reason_note: data.loss_reason_note,
            }),
          },
        },
        {
          onSuccess: () => {
            onOpenChange(false);
          },
        }
      );
    } else if (isEdit && consultation) {
      // Edit mode: partial update
      const updateData: ConsultationUpdate & {
        loss_reason_code?: string | null;
        loss_reason_note?: string;
      } = {};
      if (data.scheduled_at) updateData.scheduled_at = data.scheduled_at.toISOString();
      if (data.status_id) updateData.status_id = data.status_id;
      if (data.notes !== undefined) updateData.notes = data.notes;
      if (data.method) updateData.method = data.method;
      if (data.duration_minutes !== undefined) updateData.duration_minutes = data.duration_minutes;
      // Include loss reason
      if (needsLossReason) {
        updateData.loss_reason_code = data.loss_reason_code;
        if (data.loss_reason_note) updateData.loss_reason_note = data.loss_reason_note;
      } else {
        // Clear loss reason if status is not final negative
        updateData.loss_reason_code = null;
      }

      updateMutation.mutate(
        {
          leadId,
          consultationId: consultation.id,
          data: updateData,
        },
        {
          onSuccess: () => {
            onOpenChange(false);
          },
        }
      );
    }
  };

  const isSubmitting = addMutation.isPending || updateMutation.isPending;
  const { isDirty } = form.formState;

  // Don't render if edit mode but no consultation
  if (isEdit && !consultation) return null;

  return (
    <FormDialog open={open} onOpenChange={onOpenChange} isDirty={isDirty}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isCreate ? "Lên lịch tư vấn" : "Sửa Ghi Nhận Tư Vấn"}
          </DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Tạo lịch hẹn tư vấn mới cho lead này"
              : "Cập nhật thông tin ghi nhận tư vấn"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Method - only shown in edit mode */}
            {isEdit && (
              <FormField
                control={form.control}
                name="method"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phương thức</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn phương thức" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="phone">Điện thoại</SelectItem>
                        <SelectItem value="email">Email</SelectItem>
                        <SelectItem value="in_person">Gặp trực tiếp</SelectItem>
                        <SelectItem value="video_call">Video call</SelectItem>
                        <SelectItem value="sms">SMS</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Scheduled At */}
            <FormField
              control={form.control}
              name="scheduled_at"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {isCreate ? "Ngày giờ hẹn *" : "Lịch hẹn tiếp theo"}
                  </FormLabel>
                  <FormControl>
                    <DateTimePicker
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Chọn ngày giờ"
                      minDate={new Date()}
                      error={form.formState.errors.scheduled_at?.message}
                    />
                  </FormControl>
                  <FormDescription>
                    {isCreate
                      ? "Thời gian dự kiến tư vấn"
                      : "Thời gian hẹn tư vấn tiếp theo (nếu có)"}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Status */}
            <FormField
              control={form.control}
              name="status_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {isCreate ? "Trạng thái *" : "Trạng thái"}
                  </FormLabel>
                  <FormControl>
                    <SmartConsultationStatusSelector
                      value={field.value}
                      onChange={(value) => {
                        field.onChange(value);
                        // Clear loss reason error when status changes
                        form.clearErrors("loss_reason_code");
                      }}
                      placeholder="Chọn trạng thái"
                      allowedStatusIds={filteredAllowedStatusIds}
                      disabled={statusesLoading}
                      variant="select"
                      showOutcomeType
                    />
                  </FormControl>
                  <FormDescription>
                    {isCreate
                      ? "Trạng thái hiện tại của lịch hẹn"
                      : "Trạng thái tư vấn hiện tại"}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Loss Reason - Only shown when status is final negative */}
            {showLossReason && (
              <FormField
                control={form.control}
                name="loss_reason_code"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <LossReasonQuickSelect
                        value={field.value ?? null}
                        onChange={(code, note) => {
                          field.onChange(code);
                          if (note !== undefined) {
                            form.setValue("loss_reason_note", note);
                          }
                          // Clear error on selection
                          form.clearErrors("loss_reason_code");
                        }}
                        note={form.watch("loss_reason_note")}
                        onNoteChange={(note) => form.setValue("loss_reason_note", note)}
                        error={form.formState.errors.loss_reason_code?.message}
                        required
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            )}

            {/* Notes */}
            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{isCreate ? "Ghi chú (Tùy chọn)" : "Ghi chú"}</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder={
                        isCreate
                          ? "Thêm ghi chú về buổi tư vấn..."
                          : "Thêm ghi chú về cuộc tư vấn..."
                      }
                      className="resize-none"
                      rows={4}
                      {...field}
                    />
                  </FormControl>
                  {isCreate && (
                    <FormDescription>
                      Thông tin thêm hoặc nội dung tư vấn
                    </FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Duration - only shown in edit mode */}
            {isEdit && (
              <FormField
                control={form.control}
                name="duration_minutes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Thời lượng (phút)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="30"
                        {...field}
                        onChange={(e) =>
                          field.onChange(e.target.value ? Number(e.target.value) : undefined)
                        }
                        value={field.value || ""}
                      />
                    </FormControl>
                    <FormDescription>Thời lượng cuộc tư vấn</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormActions stackOnMobile showDivider>
              <CancelButton disabled={isSubmitting} />
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isCreate ? "Lưu lịch hẹn" : "Cập Nhật"}
              </Button>
            </FormActions>
          </form>
        </Form>
      </DialogContent>
    </FormDialog>
  );
}
