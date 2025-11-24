// src/components/leads/ConsultationDialog.tsx
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
import { Textarea } from "@/components/ui/textarea";
import { DateTimePicker } from "@/components/common/form";

import { useAddConsultation } from "@/hooks/useLeads";
import { SmartConsultationStatusSelector } from "@/components/common/selectors";

// Validation schema - using Date object for scheduled_at
const consultationSchema = z.object({
  scheduled_at: z.date({
    message: "Vui lòng chọn ngày giờ",
  }),
  status_id: z.string().min(1, "Vui lòng chọn trạng thái"),
  notes: z
    .string()
    .max(1000, "Ghi chú không được quá 1000 ký tự")
    .optional(),
});

type ConsultationFormValues = z.infer<typeof consultationSchema>;

interface ConsultationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leadId: number;
}

export function ConsultationDialog({
  open,
  onOpenChange,
  leadId,
}: ConsultationDialogProps) {
  const addMutation = useAddConsultation();

  const form = useForm<ConsultationFormValues>({
    resolver: zodResolver(consultationSchema),
    defaultValues: {
      scheduled_at: undefined,
      status_id: "",
      notes: "",
    },
  });

  // Reset form when dialog opens
  useEffect(() => {
    if (!open) {
      form.reset();
    }
  }, [open, form]);

  const onSubmit = async (data: ConsultationFormValues) => {
    addMutation.mutate(
      {
        leadId,
        data: {
          scheduled_at: data.scheduled_at ? data.scheduled_at.toISOString() : null,
          status_id: data.status_id,
          notes: data.notes,
          method: "phone",
        },
      },
      {
        onSuccess: () => {
          onOpenChange(false);
        },
      }
    );
  };

  const isSubmitting = addMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Lên lịch tư vấn</DialogTitle>
          <DialogDescription>
            Tạo lịch hẹn tư vấn mới cho lead này
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="scheduled_at"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ngày giờ hẹn *</FormLabel>
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
                    Thời gian dự kiến tư vấn
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="status_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Trạng thái *</FormLabel>
                  <FormControl>
                    <SmartConsultationStatusSelector
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Chọn trạng thái"
                      variant="select"
                      showOutcomeType
                    />
                  </FormControl>
                  <FormDescription>
                    Trạng thái hiện tại của lịch hẹn
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
                  <FormLabel>Ghi chú (Tùy chọn)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Thêm ghi chú về buổi tư vấn..."
                      className="resize-none"
                      rows={4}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Thông tin thêm hoặc nội dung tư vấn
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
                Lưu lịch hẹn
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
