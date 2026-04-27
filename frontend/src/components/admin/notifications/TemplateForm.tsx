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
  { value: "asset", label: "Tài sản" },
  { value: "security", label: "Bảo mật" },
  { value: "pipeline", label: "Pipeline" },
  { value: "operational", label: "Vận hành" },
];

const formSchema = z.object({
  name: z.string().min(1, "Tên template là bắt buộc").max(100, "Tên template tối đa 100 ký tự"),
  template_code: z.string().min(1, "Mã template là bắt buộc").max(100, "Mã template tối đa 100 ký tự"),
  description: z.string().optional(),
  title_template: z.string().min(1, "Title template is required").max(255),
  message_template: z.string().min(1, "Message template is required"),
  link_template: z.string().optional(),
  variables: z.array(z.string()).optional(),
  category: z.string().optional(),
  supported_channels: z.array(z.string()),
  template_type: z.string(),
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
      template_code: "",
      description: "",
      title_template: "",
      message_template: "",
      link_template: "",
      variables: [],
      category: undefined,
      supported_channels: ["browser"],
      template_type: "system",
      is_system: false,
    },
  });

  // Reset form when template data loads or dialog opens
  useEffect(() => {
    if (open && existingTemplate && isEditMode) {
      form.reset({
        name: existingTemplate.name,
        template_code: existingTemplate.template_code || "",
        description: existingTemplate.description || "",
        title_template: existingTemplate.title_template,
        message_template: existingTemplate.message_template,
        link_template: existingTemplate.link_template || "",
        variables: existingTemplate.variables || [],
        category: existingTemplate.category || undefined,
        supported_channels: existingTemplate.supported_channels || ["browser"],
        template_type: (existingTemplate.template_type as "system" | "zalo_zns" | "email_html" | "sms") || "system",
        is_system: existingTemplate.is_system,
      });
    } else if (open && !isEditMode) {
      form.reset({
        name: "",
        template_code: "",
        description: "",
        title_template: "",
        message_template: "",
        link_template: "",
        variables: [],
        category: undefined,
        supported_channels: ["browser"],
        template_type: "system",
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
          template_code: data.template_code,
          description: data.description || null,
          title_template: data.title_template,
          message_template: data.message_template,
          link_template: data.link_template || null,
          variables: data.variables,
          category: data.category || null,
          supported_channels: data.supported_channels,
          template_type: data.template_type,
        };
        await updateMutation.mutateAsync({ templateId, data: updateData });
        toast.success("Đã cập nhật template");
      } else {
        // Create new template
        const createData: NotificationTemplateCreate = {
          name: data.name,
          template_code: data.template_code,
          description: data.description || null,
          title_template: data.title_template,
          message_template: data.message_template,
          link_template: data.link_template || null,
          variables: data.variables,
          category: data.category || null,
          supported_channels: data.supported_channels,
          template_type: data.template_type,
          is_system: data.is_system,
        };
        await createMutation.mutateAsync(createData);
        toast.success("Đã tạo template mới");
      }
      onOpenChange(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || (isEditMode ? "Không thể cập nhật template" : "Không thể tạo template"));
    }
  };

  const handleAddVariable = () => {
    const trimmed = variableInput.trim();
    if (!trimmed) return;

    const currentVariables = form.getValues("variables") || [];
    if (currentVariables.includes(trimmed)) {
      toast.warning(`Biến "${trimmed}" đã tồn tại`);
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
            {isEditMode ? "Chỉnh sửa template" : "Tạo template mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật template thông báo. Thay đổi sẽ áp dụng cho tất cả rule đang dùng template này."
              : "Tạo template tái sử dụng để dùng chung cho nhiều rule thông báo."}
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
                    <FormLabel>Tên template *</FormLabel>
                    <FormControl>
                      <Input placeholder="VD: Lead được phân công" {...field} />
                    </FormControl>
                    <FormDescription>
                      Tên dễ đọc cho admin (dùng trong danh sách)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Template Code */}
              <FormField
                control={form.control}
                name="template_code"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mã template *</FormLabel>
                    <FormControl>
                      <Input placeholder="VD: TPL_LEAD_ASSIGN" {...field} />
                    </FormControl>
                    <FormDescription>
                      Mã định danh duy nhất cho template (VD: TPL_LEAD_ASSIGN)
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
                    <FormLabel>Mô tả</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Mô tả ngắn gọn để admin dễ tra cứu"
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
                    <FormLabel>Danh mục</FormLabel>
                    {/* `key` forces remount when value changes from undefined→string
                        post-mount (form.reset after async template fetch). Without
                        it Radix Select stays stuck on the placeholder. */}
                    <Select key={field.value ?? "__empty__"} value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn danh mục..." />
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
                      Phân loại template theo nhóm sự kiện (Lead, Tư vấn, ...)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Supported Channels */}
              <FormField
                control={form.control}
                name="supported_channels"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Kênh hỗ trợ</FormLabel>
                    <div className="flex flex-wrap gap-3">
                      {["browser", "email", "zalo", "sms"].map((ch) => (
                        <label key={ch} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={field.value?.includes(ch)}
                            onChange={(e) => {
                              const current = field.value || [];
                              field.onChange(
                                e.target.checked
                                  ? [...current, ch]
                                  : current.filter((c: string) => c !== ch)
                              );
                            }}
                          />
                          {ch}
                        </label>
                      ))}
                    </div>
                    <FormDescription>Kênh mà template này hỗ trợ</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Template Type */}
              <FormField
                control={form.control}
                name="template_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Loại template</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="system">System</SelectItem>
                        <SelectItem value="email_html">Email HTML</SelectItem>
                        <SelectItem value="zalo_zns">Zalo ZNS</SelectItem>
                        <SelectItem value="sms">SMS</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>Loại template cho kênh gửi</FormDescription>
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
                    <FormLabel>Template tiêu đề *</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="VD: Lead được phân công: $lead_name"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Dùng $tên_biến để chèn placeholder (VD: $lead_name)
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
                    <FormLabel>Template nội dung *</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="VD: Bạn đã được phân công lead $lead_name (SĐT: $lead_phone)"
                        rows={4}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Dùng $tên_biến để chèn placeholder
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
                    <FormLabel>Template đường dẫn</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="VD: /leads/$lead_id"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Đường dẫn điều hướng (tuỳ chọn) — có thể chứa placeholder
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
                    <FormLabel>Biến của template</FormLabel>
                    <div className="space-y-2">
                      {/* Variable input */}
                      <div className="flex gap-2">
                        <Input
                          placeholder="VD: lead_name, officer_id"
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
                      Danh sách biến có thể dùng trong template (dùng làm tài liệu)
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
                      <FormLabel>Template hệ thống</FormLabel>
                      <FormDescription>
                        {isEditMode
                          ? "Cờ template hệ thống không thể đổi sau khi tạo"
                          : "Template hệ thống không bị xoá để tránh mất dữ liệu ngoài ý muốn"}
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
                  Hủy
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditMode
                    ? (isPending ? "Đang cập nhật..." : "Cập nhật template")
                    : (isPending ? "Đang tạo..." : "Tạo template")}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
