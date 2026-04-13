// src/components/leads/AssignLeadDialog.tsx
"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { AlertCircle, Loader2, RefreshCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  ResponsiveDialog,
  ResponsiveDialogContent,
  ResponsiveDialogDescription,
  ResponsiveDialogFooter,
  ResponsiveDialogHeader,
  ResponsiveDialogTitle,
} from "@/components/ui/responsive-dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { useAssignLead, useBulkAssignLeads, usePerformLeadAction } from "@/hooks/useLeads";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import type { Lead } from "@/types/lead.types";

// Validation schema
const assignSchema = z.object({
  officer_id: z.string().min(1, "Vui lòng chọn tư vấn viên"),
  reason: z
    .string()
    .max(500, "Lý do không được quá 500 ký tự")
    .optional(),
});

type AssignFormValues = z.infer<typeof assignSchema>;

interface AssignLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead?: Lead | null;
  leadIds?: number[];
  onSuccess?: () => void;
}

export function AssignLeadDialog({
  open,
  onOpenChange,
  lead,
  leadIds,
  onSuccess,
}: AssignLeadDialogProps) {
  const assignMutation = useAssignLead();
  const bulkAssignMutation = useBulkAssignLeads();
  const performAction = usePerformLeadAction();
  const [showFallback, setShowFallback] = useState(false);

  // Fetch officers — server-filtered by role to avoid client-side truncation
  const { data: usersData, isLoading: usersLoading } = useAdminUsersList({
    page: 1,
    page_size: 100,
    status: "active",
    role: "officer",
  });

  const isBulk = !!leadIds && leadIds.length > 0;
  const isSingle = !!lead && !isBulk;

  const form = useForm<AssignFormValues>({
    resolver: zodResolver(assignSchema),
    defaultValues: {
      officer_id: "",
      reason: "",
    },
  });

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      form.reset();
      setShowFallback(false);
    }
    onOpenChange(nextOpen);
  };

  const onSubmit = async (data: AssignFormValues) => {
    const officerId = parseInt(data.officer_id, 10);

    if (isSingle && lead) {
      assignMutation.mutate(
        {
          leadId: lead.id,
          data: {
            officer_id: officerId,
            reason: data.reason,
          },
        },
        {
          onSuccess: () => {
            handleOpenChange(false);
            onSuccess?.();
          },
          onError: (error) => {
            const status = error.response?.status;
            // Officer inactive/not found → offer auto-reassign fallback
            if (status === 404 || status === 403) {
              setShowFallback(true);
            }
          },
        }
      );
    } else if (isBulk && leadIds) {
      bulkAssignMutation.mutate(
        {
          lead_ids: leadIds,
          officer_id: officerId,
          reason: data.reason,
        },
        {
          onSuccess: () => {
            handleOpenChange(false);
            onSuccess?.();
          },
        }
      );
    }
  };

  const isSubmitting = assignMutation.isPending || bulkAssignMutation.isPending;

  // Officers already server-filtered by role param
  const officers = usersData?.users || [];

  return (
    <ResponsiveDialog open={open} onOpenChange={handleOpenChange}>
      <ResponsiveDialogContent className="sm:max-w-[500px]">
        <ResponsiveDialogHeader>
          <ResponsiveDialogTitle>
            {isBulk
              ? `Phân công ${leadIds?.length} Lead`
              : `Phân công Lead: ${lead?.full_name}`}
          </ResponsiveDialogTitle>
          <ResponsiveDialogDescription>
            {isBulk
              ? `Phân công ${leadIds?.length} lead đã chọn cho tư vấn viên.`
              : "Phân công lead này cho tư vấn viên để theo dõi."}
          </ResponsiveDialogDescription>
        </ResponsiveDialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="officer_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Phân công cho *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={usersLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn tư vấn viên" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {officers.length === 0 ? (
                        <div className="p-2 text-sm text-muted-foreground">
                          Không có tư vấn viên nào
                        </div>
                      ) : (
                        officers.map((officer) => (
                          <SelectItem key={officer.id} value={officer.id.toString()}>
                            <div className="flex flex-col">
                              <span className="font-medium">{officer.full_name || officer.username}</span>
                              <span className="text-xs text-muted-foreground">
                                {officer.email}
                              </span>
                            </div>
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Chọn tư vấn viên sẽ xử lý {isBulk ? "các lead này" : "lead này"}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Lý do (Tùy chọn)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="VD: Có chuyên môn trong lĩnh vực này, có thời gian sẵn, ..."
                      className="resize-none"
                      rows={3}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Cung cấp lý do cho việc phân công này (tùy chọn)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {showFallback && isSingle && lead && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription className="flex items-center justify-between">
                  <span>Phân công thất bại. Bạn có thể thử phân công tự động.</span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={performAction.isPending}
                    onClick={() => {
                      performAction.mutate(
                        {
                          leadId: lead.id,
                          data: {
                            action: "reassign",
                            reason: "Phân công thủ công thất bại — tự động phân lại",
                          },
                        },
                        {
                          onSuccess: () => {
                            handleOpenChange(false);
                            onSuccess?.();
                          },
                        },
                      );
                    }}
                  >
                    {performAction.isPending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCcw className="mr-1 h-3 w-3" />
                    )}
                    Tự động phân lại
                  </Button>
                </AlertDescription>
              </Alert>
            )}

            <ResponsiveDialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={isSubmitting}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isSubmitting || officers.length === 0}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isBulk ? `Phân công ${leadIds?.length} Lead` : "Phân công Lead"}
              </Button>
            </ResponsiveDialogFooter>
          </form>
        </Form>
      </ResponsiveDialogContent>
    </ResponsiveDialog>
  );
}
