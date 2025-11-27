// src/components/admin/notifications/NotificationRuleForm.tsx
/**
 * ✅ PHASE 2.4: Notification Rule Form Component
 *
 * Form for creating and editing notification rules.
 * Features:
 * - All rule fields with validation
 * - Visual resolver builder
 * - Visual condition builder
 * - Create and edit modes
 */
"use client";

import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import * as z from "zod";
import {
  AlertCircle,
  Check,
  Loader2,
  Plus,
  Save,
  X,
} from "lucide-react";

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
import type { NotificationRule } from "@/types/api.types";

// ============================================
// FORM SCHEMA & VALIDATION
// ============================================

const formSchema = z.object({
  event: z.string().min(1, "Event is required"),
  title_template: z.string().min(1, "Title template is required"),
  message_template: z.string().min(1, "Message template is required"),
  notification_type: z.enum(["info", "success", "warning", "error"]),
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
  { value: "application_documents_updated", label: "Application Documents Updated" },
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
  { value: "info", label: "Info", color: "bg-blue-100 text-blue-800" },
  { value: "success", label: "Success", color: "bg-green-100 text-green-800" },
  { value: "warning", label: "Warning", color: "bg-yellow-100 text-yellow-800" },
  { value: "error", label: "Error", color: "bg-red-100 text-red-800" },
];

const CHANNELS = [
  { value: "browser", label: "Browser" },
  { value: "email", label: "Email" },
  { value: "sms", label: "SMS" },
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

const CONDITION_OPERATORS = [
  { value: "eq", label: "Equal (=)" },
  { value: "ne", label: "Not Equal (≠)" },
  { value: "gt", label: "Greater Than (>)" },
  { value: "gte", label: "Greater or Equal (≥)" },
  { value: "lt", label: "Less Than (<)" },
  { value: "lte", label: "Less or Equal (≤)" },
  { value: "in", label: "In List" },
  { value: "not_in", label: "Not In List" },
  { value: "contains", label: "Contains" },
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

  // Condition builder state
  const [conditionEnabled, setConditionEnabled] = useState(false);
  const [conditionField, setConditionField] = useState("");
  const [conditionOperator, setConditionOperator] = useState("eq");
  const [conditionValue, setConditionValue] = useState("");

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

      // Set resolver type
      setResolverType(existingRule.recipient_config.resolver_type as string || "lead_owner");

      // Set condition state
      if (existingRule.condition) {
        setConditionEnabled(true);
        setConditionField(existingRule.condition.field as string || "");
        setConditionOperator(existingRule.condition.operator as string || "eq");
        setConditionValue(String(existingRule.condition.value || ""));
      }
    }
  }, [existingRule, isEditMode, form]);

  // Update recipient_config when resolver type changes
  useEffect(() => {
    form.setValue("recipient_config", {
      resolver_type: resolverType,
      params: {},
    });
  }, [resolverType, form]);

  // Update condition when builder state changes
  useEffect(() => {
    if (conditionEnabled && conditionField && conditionOperator && conditionValue) {
      form.setValue("condition", {
        field: conditionField,
        operator: conditionOperator,
        value: conditionValue,
      });
    } else {
      form.setValue("condition", null);
    }
  }, [conditionEnabled, conditionField, conditionOperator, conditionValue, form]);

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
    } catch (error: unknown) {
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
                              <FormLabel className="text-sm font-normal cursor-pointer">
                                {channel.label}
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
                <FormLabel>Recipient Resolver</FormLabel>
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

              {/* Condition Builder */}
              <div className="space-y-4 border-t pt-4">
                <div className="flex items-center space-x-2">
                  <Switch
                    checked={conditionEnabled}
                    onCheckedChange={setConditionEnabled}
                  />
                  <FormLabel>Enable Activation Condition</FormLabel>
                </div>

                {conditionEnabled && (
                  <div className="space-y-3 pl-4 border-l-2 border-muted">
                    <div className="grid grid-cols-3 gap-2">
                      {/* Field */}
                      <div className="space-y-1">
                        <FormLabel className="text-xs">Field</FormLabel>
                        <Input
                          placeholder="e.g., status"
                          value={conditionField}
                          onChange={(e) => setConditionField(e.target.value)}
                        />
                      </div>

                      {/* Operator */}
                      <div className="space-y-1">
                        <FormLabel className="text-xs">Operator</FormLabel>
                        <Select
                          value={conditionOperator}
                          onValueChange={setConditionOperator}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {CONDITION_OPERATORS.map((op) => (
                              <SelectItem key={op.value} value={op.value}>
                                {op.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {/* Value */}
                      <div className="space-y-1">
                        <FormLabel className="text-xs">Value</FormLabel>
                        <Input
                          placeholder="e.g., active"
                          value={conditionValue}
                          onChange={(e) => setConditionValue(e.target.value)}
                        />
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Notification will only trigger if condition is met
                    </p>
                  </div>
                )}
              </div>

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
