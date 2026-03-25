// src/components/admin/notifications/NotificationRuleForm.tsx
/**
 * ✅ PHASE 2.4 + 3.2: Notification Rule Form Component
 *
 * Form for creating and editing notification rules.
 * Features:
 * - All rule fields with validation
 * - Visual resolver builder
 * - ✅ PHASE 3.2: Advanced visual condition builder with nested AND/OR groups
 * - Create and edit modes
 */
"use client";

import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import * as z from "zod";
import {
  Loader2,
  Save,
} from "lucide-react";

import { ConditionBuilder, type Condition } from "./ConditionBuilder";

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
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

import {
  useCreateNotificationRule,
  useUpdateNotificationRule,
  useNotificationRule,
} from "@/hooks/useNotificationRules";

// ============================================
// FORM SCHEMA & VALIDATION
// ============================================

const formSchema = z.object({
  event: z.string().min(1, "Event is required"),
  title_template: z.string().min(1, "Title template is required"),
  message_template: z.string().min(1, "Message template is required"),
  notification_type: z.enum(["info", "success", "warning", "error", "reminder", "admin_update", "system"]),
  link_template: z.string().optional(),
  channels: z.array(z.string()).min(1, "At least one channel is required"),
  recipient_config: z.record(z.string(), z.unknown()),
  condition: z.record(z.string(), z.unknown()).nullable(),
  enabled: z.boolean(),
});

type FormValues = z.infer<typeof formSchema>;

// ============================================
// CONSTANTS
// ============================================

const SYSTEM_EVENTS = [
  // Lead Events
  { value: "lead_assigned", label: "Lead Assigned" },
  { value: "lead_assignment_failed", label: "Lead Assignment Failed" },
  { value: "lead_reassigned", label: "Lead Reassigned" },
  { value: "lead_status_changed", label: "Lead Status Changed" },
  { value: "lead_created", label: "Lead Created" },
  { value: "lead_deleted", label: "Lead Deleted" },

  // Consultation Events
  { value: "consultation_created", label: "Consultation Created" },
  { value: "consultation_updated", label: "Consultation Updated" },
  { value: "consultation_deleted", label: "Consultation Deleted" },
  { value: "consultation_reminder", label: "Consultation Reminder" },

  // Application Events
  { value: "application_created", label: "Application Created" },
  { value: "application_status_changed", label: "Application Status Changed" },
  { value: "application_deleted", label: "Application Deleted" },

  // Finance Events
  { value: "dorm_fee_created", label: "Dorm Fee Created" },
  { value: "payment_received", label: "Payment Received" },
  { value: "payment_overdue", label: "Payment Overdue" },

  // Dorm Events
  { value: "dorm_room_assigned", label: "Dorm Room Assigned" },
  { value: "dorm_maintenance_request", label: "Dorm Maintenance Request" },

  // Asset Events
  { value: "asset_maintenance_alert", label: "Asset Maintenance Alert" },
  { value: "asset_checked_out", label: "Asset Checked Out" },

  // System Events
  { value: "system_alert", label: "System Alert" },
  { value: "system_announcement", label: "System Announcement" },
  { value: "user_role_changed", label: "User Role Changed" },
  { value: "user_deactivated", label: "User Deactivated" },
  { value: "pipeline_config_updated", label: "Pipeline Config Updated" },
  { value: "officer_availability_changed", label: "Officer Availability Changed" },
];

const NOTIFICATION_TYPES = [
  { value: "info", label: "Info", color: "bg-info-100 text-info-800 dark:bg-info-900/50 dark:text-info-300" },
  { value: "success", label: "Success", color: "bg-success-100 text-success-800 dark:bg-success-900/50 dark:text-success-300" },
  { value: "warning", label: "Warning", color: "bg-warning-100 text-warning-800 dark:bg-warning-900/50 dark:text-warning-300" },
  { value: "error", label: "Error", color: "bg-error-100 text-error-800 dark:bg-error-900/50 dark:text-error-300" },
  { value: "reminder", label: "Reminder", color: "bg-purple-100 text-purple-800 dark:bg-purple-900/50 dark:text-purple-300" },
  { value: "admin_update", label: "Admin Update", color: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-300" },
  { value: "system", label: "System", color: "bg-muted text-muted-foreground" },
];

const CHANNELS = [
  { value: "browser", label: "Browser", status: "live" as const },
  { value: "email", label: "Email", status: "live" as const },
  { value: "sms", label: "SMS", status: "planned" as const },
  { value: "zalo", label: "Zalo", status: "planned" as const },
];

const RESOLVER_TYPES = [
  { value: "lead_owner", label: "Lead Owner" },
  { value: "unit_staff", label: "Unit Staff" },
  { value: "unit_managers", label: "Unit Managers" },
  { value: "all_admins", label: "All Admins" },
  { value: "all_users", label: "All Users" },
  { value: "specific_users", label: "Specific Users" },
  { value: "dorm_residents", label: "Dorm Residents" },
  { value: "dorm_staff", label: "Dorm Staff" },
  { value: "actor_excluded", label: "Actor Excluded (Wrapper)" },
  { value: "composite", label: "Composite (Multiple)" },
];

// ============================================
// COMPONENT PROPS
// ============================================

interface NotificationRuleFormProps {
  ruleId?: number; // If provided, edit mode. Otherwise, create mode
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

// ============================================
// MAIN COMPONENT
// ============================================

export function NotificationRuleForm({
  ruleId,
  open,
  onOpenChange,
  onSuccess,
}: NotificationRuleFormProps) {
  const isEditMode = !!ruleId;

  // Fetch existing rule if in edit mode
  const { data: existingRule, isLoading: loadingRule } = useNotificationRule(ruleId);

  // Mutations
  const createMutation = useCreateNotificationRule();
  const updateMutation = useUpdateNotificationRule();

  // Resolver builder state
  const [resolverType, setResolverType] = useState<string>("lead_owner");

  // Form
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      event: "",
      title_template: "",
      message_template: "",
      notification_type: "info",
      link_template: "",
      channels: ["browser"],
      recipient_config: { resolver_type: "lead_owner", params: {} },
      condition: null,
      enabled: true,
    },
  });

  // Load existing rule data into form
  useEffect(() => {
    if (existingRule && isEditMode) {
      const newResolverType = existingRule.recipient_config.resolver_type as string || "lead_owner";

      form.reset({
        event: existingRule.event,
        title_template: existingRule.title_template,
        message_template: existingRule.message_template,
        notification_type: existingRule.notification_type as "info" | "success" | "warning" | "error",
        link_template: existingRule.link_template || "",
        channels: existingRule.channels,
        recipient_config: existingRule.recipient_config,
        condition: existingRule.condition,
        enabled: existingRule.enabled,
      });

      // Defer setState to avoid synchronous updates in effect
      queueMicrotask(() => {
        setResolverType(newResolverType);
      });
    }
  }, [existingRule, isEditMode, form]);

  // Update recipient_config when resolver type changes
  useEffect(() => {
    form.setValue("recipient_config", {
      resolver_type: resolverType,
      params: {},
    });
  }, [resolverType, form]);

  const onSubmit = async (data: FormValues) => {
    try {
      if (isEditMode && ruleId) {
        await updateMutation.mutateAsync({
          ruleId,
          data,
        });
        toast.success("Notification rule updated successfully");
      } else {
        await createMutation.mutateAsync(data);
        toast.success("Notification rule created successfully");
      }
      onOpenChange(false);
      form.reset();
      onSuccess?.();
    } catch {
      toast.error(
        isEditMode
          ? "Failed to update notification rule"
          : "Failed to create notification rule"
      );
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Edit Notification Rule" : "Create Notification Rule"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Update the notification rule configuration."
              : "Create a new notification rule to manage system notifications."}
          </DialogDescription>
        </DialogHeader>

        {loadingRule && isEditMode ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              {/* Event */}
              <FormField
                control={form.control}
                name="event"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Event</FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={isEditMode} // Can't change event in edit mode
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select an event" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {SYSTEM_EVENTS.map((event) => (
                          <SelectItem key={event.value} value={event.value}>
                            {event.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      The system event that triggers this notification
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Title Template */}
              <FormField
                control={form.control}
                name="title_template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Title Template</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., Lead Assigned: $lead_name"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Use $field_name for variables (e.g., $lead_name, $officer_id)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Message Template */}
              <FormField
                control={form.control}
                name="message_template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Message Template</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="e.g., Lead $lead_name has been assigned to you."
                        rows={3}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Use $field_name for variables from the event payload
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Notification Type */}
              <FormField
                control={form.control}
                name="notification_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Notification Type</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {NOTIFICATION_TYPES.map((type) => (
                          <SelectItem key={type.value} value={type.value}>
                            <div className="flex items-center gap-2">
                              <Badge className={type.color} variant="secondary">
                                {type.label}
                              </Badge>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Severity level of the notification
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Link Template (Optional) */}
              <FormField
                control={form.control}
                name="link_template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Link Template (Optional)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., /leads/$lead_id"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Optional link to navigate when notification is clicked
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Channels */}
              <FormField
                control={form.control}
                name="channels"
                render={() => (
                  <FormItem>
                    <FormLabel>Channels</FormLabel>
                    <FormDescription>
                      Select delivery channels for this notification
                    </FormDescription>
                    <div className="space-y-2">
                      {CHANNELS.map((channel) => (
                        <FormField
                          key={channel.value}
                          control={form.control}
                          name="channels"
                          render={({ field }) => (
                            <FormItem className="flex items-center space-x-2 space-y-0">
                              <FormControl>
                                <Checkbox
                                  checked={field.value?.includes(channel.value)}
                                  disabled={channel.status === "planned"}
                                  onCheckedChange={(checked) => {
                                    const current = field.value || [];
                                    if (checked) {
                                      field.onChange([...current, channel.value]);
                                    } else {
                                      field.onChange(
                                        current.filter((v) => v !== channel.value)
                                      );
                                    }
                                  }}
                                />
                              </FormControl>
                              <FormLabel className={`text-sm font-normal ${channel.status === "planned" ? "text-muted-foreground" : "cursor-pointer"}`}>
                                {channel.label}
                                {channel.status === "planned" && (
                                  <span className="ml-2 inline-flex items-center rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                                    Planned
                                  </span>
                                )}
                              </FormLabel>
                            </FormItem>
                          )}
                        />
                      ))}
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Resolver Type */}
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  Recipient Resolver
                </label>
                <Select value={resolverType} onValueChange={setResolverType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RESOLVER_TYPES.map((resolver) => (
                      <SelectItem key={resolver.value} value={resolver.value}>
                        {resolver.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-sm text-muted-foreground">
                  Strategy for determining who receives this notification
                </p>
              </div>

              {/* ✅ PHASE 3.2: Visual Condition Builder */}
              <FormField
                control={form.control}
                name="condition"
                render={({ field }) => (
                  <FormItem className="border-t pt-4">
                    <ConditionBuilder
                      value={field.value as Condition}
                      onChange={field.onChange}
                      eventType={form.watch("event")}
                    />
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Enabled */}
              <FormField
                control={form.control}
                name="enabled"
                render={({ field }) => (
                  <FormItem className="flex items-center justify-between rounded-lg border p-4">
                    <div className="space-y-0.5">
                      <FormLabel className="text-base">Enabled</FormLabel>
                      <FormDescription>
                        Activate this notification rule immediately
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />

              {/* Footer */}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                  disabled={isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {isEditMode ? "Updating..." : "Creating..."}
                    </>
                  ) : (
                    <>
                      <Save className="mr-2 h-4 w-4" />
                      {isEditMode ? "Update Rule" : "Create Rule"}
                    </>
                  )}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
