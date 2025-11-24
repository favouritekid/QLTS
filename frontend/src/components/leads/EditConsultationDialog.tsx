// src/components/leads/EditConsultationDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { DateTimePicker } from "@/components/common/form";

import { useUpdateConsultation } from "@/hooks/useLeads";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { SmartConsultationStatusSelector } from "@/components/common/selectors";
import type { Consultation, ConsultationUpdate } from "@/types/lead.types";

// Validation schema (all fields optional for partial update)
const editConsultationSchema = z.object({
  scheduled_at: z.date().optional().nullable(),
  status_id: z.string().optional(),
  notes: z
    .string()
    .max(1000, "Ghi chú không được quá 1000 ký tự")
    .optional(),
  method: z.enum(["phone", "email", "in_person", "online", "video_call"]).optional(),
  duration_minutes: z.number().min(0).max(480).optional(),
});

type EditConsultationFormValues = z.infer<typeof editConsultationSchema>;

interface EditConsultationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leadId: number;
  consultation: Consultation | null;
}

export function EditConsultationDialog({
  open,
  onOpenChange,
  leadId,
  consultation,
}: EditConsultationDialogProps) {
  const updateMutation = useUpdateConsultation();

  // Get allowed next statuses based on current status
  const { data: statuses, isLoading: statusesLoading } = useAllowedNextStatuses(
    consultation?.consultation_status_id || null
  );

  const form = useForm<EditConsultationFormValues>({
    resolver: zodResolver(editConsultationSchema),
    defaultValues: {
      scheduled_at: undefined,
      status_id: "",
      notes: "",
      method: "phone",
      duration_minutes: undefined,
    },
  });

  // Populate form with consultation data when dialog opens
  useEffect(() => {
    if (open && consultation) {
      form.reset({
        scheduled_at: consultation.scheduled_at
          ? new Date(consultation.scheduled_at)
          : undefined,
        status_id: consultation.consultation_status_id || "",
        notes: consultation.notes || "",
        method: consultation.method || "phone",
        duration_minutes: consultation.duration_minutes || undefined,
      });
    } else if (!open) {
      form.reset();
    }
  }, [open, consultation, form]);

  const onSubmit = async (data: EditConsultationFormValues) => {
    if (!consultation) return;

    // Only send fields that have values (partial update)
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
  };

  const isSubmitting = updateMutation.isPending;

  if (!consultation) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Sửa Ghi Nhận Tư Vấn</DialogTitle>
          <DialogDescription>
            Cập nhật thông tin ghi nhận tư vấn
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="method"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Phương thức</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                  >
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
                      <SelectItem value="online">Online</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="status_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Trạng thái</FormLabel>
                  <FormControl>
                    <SmartConsultationStatusSelector
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Chọn trạng thái"
                      allowedStatusIds={statuses?.map(s => s.id)}
                      disabled={statusesLoading}
                      variant="select"
                      showOutcomeType
                    />
                  </FormControl>
                  <FormDescription>
                    Trạng thái tư vấn hiện tại
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ghi chú</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Thêm ghi chú về cuộc tư vấn..."
                      className="resize-none"
                      rows={4}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="scheduled_at"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Lịch hẹn tiếp theo</FormLabel>
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
                    Thời gian hẹn tư vấn tiếp theo (nếu có)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                      onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : undefined)}
                      value={field.value || ""}
                    />
                  </FormControl>
                  <FormDescription>
                    Thời lượng cuộc tư vấn
                  </FormDescription>
                  <FormMessage />
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
                Cập Nhật
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
