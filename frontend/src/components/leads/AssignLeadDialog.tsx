// src/components/leads/AssignLeadDialog.tsx
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { useAssignLead, useBulkAssignLeads } from "@/hooks/useLeads";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import type { Lead } from "@/types/lead.types";

// Validation schema
const assignSchema = z.object({
  officer_id: z.number({ message: "Please select an officer" }),
  reason: z
    .string()
    .max(500, "Reason must be less than 500 characters")
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

  // Fetch officers (users with role "officer" or "admin")
  const { data: usersData, isLoading: usersLoading } = useAdminUsersList({
    page: 1,
    page_size: 100,
    status: "active",
  });

  const isBulk = !!leadIds && leadIds.length > 0;
  const isSingle = !!lead && !isBulk;

  const form = useForm<AssignFormValues>({
    resolver: zodResolver(assignSchema),
    defaultValues: {
      officer_id: undefined,
      reason: "",
    },
  });

  // Reset form when dialog opens
  useEffect(() => {
    if (!open) {
      form.reset();
    }
  }, [open, form]);

  const onSubmit = async (data: AssignFormValues) => {
    if (isSingle && lead) {
      assignMutation.mutate(
        {
          leadId: lead.id,
          data: {
            officer_id: data.officer_id,
            reason: data.reason,
          },
        },
        {
          onSuccess: () => {
            onOpenChange(false);
            onSuccess?.();
          },
        }
      );
    } else if (isBulk && leadIds) {
      bulkAssignMutation.mutate(
        {
          lead_ids: leadIds,
          officer_id: data.officer_id,
          reason: data.reason,
        },
        {
          onSuccess: () => {
            onOpenChange(false);
            onSuccess?.();
          },
        }
      );
    }
  };

  const isSubmitting = assignMutation.isPending || bulkAssignMutation.isPending;

  // Filter users to get only officers/admins
  const officers = usersData?.users?.filter(
    (user) => user.role === "officer" || user.role === "admin"
  ) || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isBulk
              ? `Assign ${leadIds?.length} Leads`
              : `Assign Lead: ${lead?.full_name}`}
          </DialogTitle>
          <DialogDescription>
            {isBulk
              ? `Assign ${leadIds?.length} selected leads to an officer.`
              : "Assign this lead to an officer for follow-up."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="officer_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Assign to Officer *</FormLabel>
                  <Select
                    onValueChange={(value) => field.onChange(Number(value))}
                    value={field.value?.toString()}
                    disabled={usersLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select an officer" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {officers.length === 0 ? (
                        <div className="p-2 text-sm text-muted-foreground">
                          No officers available
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
                    Select the officer who will handle {isBulk ? "these leads" : "this lead"}
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
                  <FormLabel>Reason (Optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="e.g., Has expertise in this field, available capacity, etc."
                      className="resize-none"
                      rows={3}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Provide a reason for this assignment (optional)
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
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting || officers.length === 0}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isBulk ? `Assign ${leadIds?.length} Leads` : "Assign Lead"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
