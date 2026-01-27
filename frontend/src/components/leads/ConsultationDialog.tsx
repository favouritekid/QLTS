// src/components/leads/ConsultationDialog.tsx
"use client";

import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormDialog, useFormDialogClose } from "@/components/ui/form-dialog";
import {
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
import { Textarea } from "@/components/ui/textarea";
import { DateTimePicker } from "@/components/common/form";

import { useAddConsultation, useUpdateConsultation } from "@/hooks/useLeads";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { useWorkflowContext, getAllowedStatusIds } from "@/hooks/useWorkflowContext";
import { SmartConsultationStatusSelector } from "@/components/common/selectors";
import type { Consultation, ConsultationUpdate } from "@/types/lead.types";

// Unified validation schema with optional fields for flexibility
const consultationSchema = z.object({
  scheduled_at: z.date().optional().nullable(),
  status_id: z.string().optional(),
  notes: z.string().max(1000, "Ghi chú không được quá 1000 ký tự").optional(),
  method: z.enum(["phone", "email", "in_person", "sms", "video_call"]).optional(),
  duration_minutes: z.number().min(0).max(480).optional(),
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

  // Get allowed next statuses for edit mode (workflow compliance)
  // ✅ FIX: Pass leadId to derive correct phase from admission_profile
  const { data: allowedStatuses, isLoading: statusesLoading } = useAllowedNextStatuses(
    isEdit ? (consultation?.consultation_status_id || null) : null,
    leadId
  );
  
  // ✅ PHASE-BASED WORKFLOW: Get workflow context for phase filtering
  const { data: workflowContext } = useWorkflowContext(leadId, { enabled: open });
  const allowedByPhase = getAllowedStatusIds(workflowContext);
  
  // Combine transition-based and phase-based filtering
  const filteredAllowedStatusIds = useMemo(() => {
    if (!isEdit) return undefined; // Create mode: let selector handle it
    
    const transitionIds = allowedStatuses?.map(s => s.id) || [];
    
    // If no phase context, use transition-based filtering only
    if (allowedByPhase.size === 0) {
      return transitionIds;
    }
    
    // Intersect: status must be allowed by BOTH transitions AND phase
    return transitionIds.filter(id => allowedByPhase.has(id));
  }, [isEdit, allowedStatuses, allowedByPhase]);

  const form = useForm<ConsultationFormValues>({
    resolver: zodResolver(consultationSchema),
    defaultValues: {
      scheduled_at: undefined,
      status_id: "",
      notes: "",
      method: "phone",
      duration_minutes: undefined,
    },
  });


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
      });
    } else if (isCreate) {
      // Reset to empty for create mode
      form.reset({
        scheduled_at: undefined,
        status_id: "",
        notes: "",
        method: "phone",
        duration_minutes: undefined,
      });
    }
  }, [open, consultation, isEdit, isCreate, form]);

  const onSubmit = async (data: ConsultationFormValues) => {
    if (isCreate) {
      // Create mode: validate required fields
      if (!data.scheduled_at || !data.status_id) {
        return; // Let zod validation handle this
      }

      addMutation.mutate(
        {
          leadId,
          data: {
            scheduled_at: data.scheduled_at.toISOString(),
            status_id: data.status_id,
            notes: data.notes,
            method: data.method || "phone",
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
      const updateData: ConsultationUpdate = {};
      if (data.scheduled_at) updateData.scheduled_at = data.scheduled_at.toISOString();
      if (data.status_id) updateData.status_id = data.status_id;
      if (data.notes !== undefined) updateData.notes = data.notes;
      if (data.method) updateData.method = data.method;
      if (data.duration_minutes !== undefined) updateData.duration_minutes = data.duration_minutes;

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
                      onChange={field.onChange}
                      placeholder="Chọn trạng thái"
                      allowedStatusIds={filteredAllowedStatusIds}
                      disabled={isEdit && statusesLoading}
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

            <DialogFooter>
              <CancelButton disabled={isSubmitting} />
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isCreate ? "Lưu lịch hẹn" : "Cập Nhật"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </FormDialog>
  );
}
