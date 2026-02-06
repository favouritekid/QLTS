// src/components/admin/notifications/TemplateForm.tsx
/**
 * ✅ PHASE 3.1: Template Form Component
 *
 * Dialog form for creating and editing notification templates.
 * Features:
 * - Create new templates or edit existing ones
 * - Form validation with zod schema
 * - Variable tags input for template placeholders
 * - Category selection
 * - System template flag (admin-only)
 * - Template preview
 */
"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, Plus, X } from "lucide-react";

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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

import {
  useNotificationTemplate,
  useCreateNotificationTemplate,
  useUpdateNotificationTemplate,
} from "@/hooks/useNotificationTemplates";
import type { NotificationTemplateCreate, NotificationTemplateUpdate } from "@/types/api.types";

const CATEGORIES = [
  { value: "lead", label: "Lead" },
  { value: "consultation", label: "Consultation" },
  { value: "application", label: "Application" },
  { value: "finance", label: "Finance" },
  { value: "dorm", label: "Dorm" },
  { value: "system", label: "System" },
];

const formSchema = z.object({
  name: z.string().min(1, "Name is required").max(100, "Name must be under 100 characters"),
  description: z.string().optional(),
  title_template: z.string().min(1, "Title template is required").max(255),
  message_template: z.string().min(1, "Message template is required"),
  link_template: z.string().optional(),
  variables: z.array(z.string()).optional(),
  category: z.string().optional(),
  is_system: z.boolean(),
});

type FormValues = z.infer<typeof formSchema>;

interface TemplateFormProps {
  templateId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function TemplateForm({ templateId, open, onOpenChange }: TemplateFormProps) {
  const [variableInput, setVariableInput] = useState("");

  // Determine if this is edit mode
  const isEditMode = templateId !== undefined;

  // Fetch template data if editing
  const { data: existingTemplate, isLoading: isLoadingTemplate } = useNotificationTemplate(
    templateId!,
    { enabled: isEditMode && open }
  );

  // Mutations
  const createMutation = useCreateNotificationTemplate();
  const updateMutation = useUpdateNotificationTemplate();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: "",
      description: "",
      title_template: "",
      message_template: "",
      link_template: "",
      variables: [],
      category: undefined,
      is_system: false,
    },
  });

  // Reset form when template data loads or dialog opens
  useEffect(() => {
    if (open && existingTemplate && isEditMode) {
      form.reset({
        name: existingTemplate.name,
        description: existingTemplate.description || "",
        title_template: existingTemplate.title_template,
        message_template: existingTemplate.message_template,
        link_template: existingTemplate.link_template || "",
        variables: existingTemplate.variables || [],
        category: existingTemplate.category || undefined,
        is_system: existingTemplate.is_system,
      });
    } else if (open && !isEditMode) {
      form.reset({
        name: "",
        description: "",
        title_template: "",
        message_template: "",
        link_template: "",
        variables: [],
        category: undefined,
        is_system: false,
      });
    }
  }, [existingTemplate, form, isEditMode, open]);

  const onSubmit = async (data: FormValues) => {
    try {
      if (isEditMode && templateId) {
        // Update existing template
        // Note: is_system flag cannot be changed after creation
        const updateData: NotificationTemplateUpdate = {
          name: data.name,
          description: data.description || null,
          title_template: data.title_template,
          message_template: data.message_template,
          link_template: data.link_template || null,
          variables: data.variables,
          category: data.category || null,
        };
        await updateMutation.mutateAsync({ templateId, data: updateData });
        toast.success("Template updated successfully");
      } else {
        // Create new template
        const createData: NotificationTemplateCreate = {
          name: data.name,
          description: data.description || null,
          title_template: data.title_template,
          message_template: data.message_template,
          link_template: data.link_template || null,
          variables: data.variables,
          category: data.category || null,
          is_system: data.is_system,
        };
        await createMutation.mutateAsync(createData);
        toast.success("Template created successfully");
      }
      onOpenChange(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || `Failed to ${isEditMode ? "update" : "create"} template`);
    }
  };

  const handleAddVariable = () => {
    const trimmed = variableInput.trim();
    if (!trimmed) return;

    const currentVariables = form.getValues("variables") || [];
    if (currentVariables.includes(trimmed)) {
      toast.warning(`Variable "${trimmed}" already exists`);
      return;
    }

    form.setValue("variables", [...currentVariables, trimmed]);
    setVariableInput("");
  };

  const handleRemoveVariable = (variable: string) => {
    const currentVariables = form.getValues("variables") || [];
    form.setValue(
      "variables",
      currentVariables.filter((v) => v !== variable)
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddVariable();
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Edit Template" : "Create Template"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Update the notification template. Changes will affect all rules using this template."
              : "Create a reusable notification template that can be shared across multiple rules."}
          </DialogDescription>
        </DialogHeader>

        {isLoadingTemplate && isEditMode ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              {/* Name */}
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name *</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g., lead_assignment" {...field} />
                    </FormControl>
                    <FormDescription>
                      Unique identifier for this template (used internally)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Description */}
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Human-readable description for administrators"
                        rows={2}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Category */}
              <FormField
                control={form.control}
                name="category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Category</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select a category" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {CATEGORIES.map((cat) => (
                          <SelectItem key={cat.value} value={cat.value}>
                            {cat.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Organize templates by category (e.g., lead, consultation)
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
                    <FormLabel>Title Template *</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., Lead assigned: {lead_name}"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Use {"{variable_name}"} for placeholders (e.g., {"{lead_name}"})
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
                    <FormLabel>Message Template *</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="e.g., You have been assigned to lead {lead_name} (Phone: {lead_phone})"
                        rows={4}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Use {"{variable_name}"} for placeholders
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Link Template */}
              <FormField
                control={form.control}
                name="link_template"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Link Template</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., /leads/{lead_id}"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Optional navigation link with placeholders
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Variables */}
              <FormField
                control={form.control}
                name="variables"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Template Variables</FormLabel>
                    <div className="space-y-2">
                      {/* Variable input */}
                      <div className="flex gap-2">
                        <Input
                          placeholder="e.g., lead_name, officer_id"
                          value={variableInput}
                          onChange={(e) => setVariableInput(e.target.value)}
                          onKeyDown={handleKeyDown}
                        />
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleAddVariable}
                          aria-label="Thêm biến"
                        >
                          <Plus className="h-4 w-4" />
                        </Button>
                      </div>

                      {/* Variable tags */}
                      {field.value && field.value.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {field.value.map((variable) => (
                            <Badge key={variable} variant="secondary">
                              {variable}
                              <button
                                type="button"
                                onClick={() => handleRemoveVariable(variable)}
                                className="ml-1 hover:text-destructive"
                                aria-label="Xóa biến"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <FormDescription>
                      List of variables available in this template (for documentation)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* System Flag */}
              <FormField
                control={form.control}
                name="is_system"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={isEditMode}
                      />
                    </FormControl>
                    <div className="space-y-1 leading-none">
                      <FormLabel>System Template</FormLabel>
                      <FormDescription>
                        {isEditMode
                          ? "System flag cannot be changed after template creation"
                          : "System templates cannot be deleted and are protected from accidental removal"}
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
                  disabled={isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditMode ? "Update Template" : "Create Template"}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
