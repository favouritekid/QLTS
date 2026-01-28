// src/components/admin/ConsultationStatusDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
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
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import {
  useCreateConsultationStatus,
  useUpdateConsultationStatus,
  usePipelineStages,
} from "@/hooks/usePipeline";
import type {
  ConsultationStatus,
  ConsultationStatusCreate,
  ConsultationStatusUpdate,
  OutcomeType,
  StatusType,
  SelectableMode,
} from "@/types/pipeline.types";
import { Checkbox as ShadcnCheckbox } from "@/components/ui/checkbox";
import {
  LEGACY_STATUS_OPTIONS,
  PRESET_COLORS,
  DEFAULT_STATUS_COLOR,
} from "@/constants";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const statusFormSchema = z.object({
  id: z
    .string()
    .min(1, "Mã trạng thái là bắt buộc")
    .regex(
      /^[a-z0-9_]+$/,
      "Mã trạng thái chỉ được chứa chữ thường, số và gạch dưới"
    )
    .max(50, "Mã trạng thái không vượt quá 50 ký tự"),
  name: z
    .string()
    .min(1, "Tên trạng thái là bắt buộc")
    .min(2, "Tên trạng thái phải có ít nhất 2 ký tự")
    .max(100, "Tên trạng thái không vượt quá 100 ký tự"),
  color_code: z
    .string()
    .min(1, "Màu sắc là bắt buộc")
    .regex(/^#[0-9A-Fa-f]{6}$/, "Màu phải là mã hex hợp lệ (VD: #FF5733)"),
  // ✅ FSM v3.0: stage_id is optional (NULL for universal statuses)
  stage_id: z.string().nullable().optional(),
  outcome_type: z.enum(["positive", "neutral", "negative"]),
  // ✅ FSM v3.0: is_final replaces is_final_status
  is_final: z.boolean(),
  legacy_status: z.string().nullable().optional(),
  // ✅ Universal status support
  is_universal: z.boolean(),
  updates_pipeline: z.boolean(),
  // ✅ FSM v3.0: counts_for_funnel replaces counts_for_kpi
  counts_for_funnel: z.boolean(),
  // ✅ FSM v3.0: New fields
  code: z.string().nullable().optional(),
  status_type: z.enum(["transition", "activity", "system"]),
  selectable_mode: z.enum(["user", "role", "system"]),
  phase: z.string().min(1, "Phase là bắt buộc"),
  description: z.string().nullable().optional(),
  display_order: z.number().min(0),
});

type StatusFormValues = z.infer<typeof statusFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface ConsultationStatusDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status?: ConsultationStatus | null; // null = create mode, non-null = edit mode
}

// Using centralized PRESET_COLORS and LEGACY_STATUS_OPTIONS from @/constants

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function ConsultationStatusDialog({
  open,
  onOpenChange,
  status,
}: ConsultationStatusDialogProps) {
  const isEditMode = !!status;

  // Queries
  const { data: stages = [], isLoading: stagesLoading } = usePipelineStages();

  // Mutations
  const createMutation = useCreateConsultationStatus();
  const updateMutation = useUpdateConsultationStatus();

  // Form
  const form = useForm<StatusFormValues>({
    resolver: zodResolver(statusFormSchema),
    defaultValues: {
      id: "",
      name: "",
      color_code: DEFAULT_STATUS_COLOR,
      stage_id: null,
      outcome_type: "neutral",
      // ✅ FSM v3.0: is_final replaces is_final_status
      is_final: false,
      legacy_status: null,
      // ✅ Universal status defaults
      is_universal: false,
      updates_pipeline: true,
      // ✅ FSM v3.0: counts_for_funnel replaces counts_for_kpi
      counts_for_funnel: true,
      // ✅ FSM v3.0: New field defaults
      code: null,
      status_type: "transition",
      selectable_mode: "user",
      phase: "consultation",
      description: null,
      display_order: 0,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && status) {
        form.reset({
          id: status.id,
          name: status.name,
          color_code: status.color_code,
          stage_id: status.stage_id || null,
          outcome_type: status.outcome_type || "neutral",
          // ✅ FSM v3.0: is_final with fallback to is_final_status
          is_final: status.is_final ?? status.is_final_status ?? false,
          legacy_status: status.legacy_status || null,
          // ✅ Universal status fields
          is_universal: status.is_universal ?? false,
          updates_pipeline: status.updates_pipeline ?? true,
          // ✅ FSM v3.0: counts_for_funnel with fallback to counts_for_kpi
          counts_for_funnel: status.counts_for_funnel ?? status.counts_for_kpi ?? true,
          // ✅ FSM v3.0: New fields
          code: status.code || null,
          status_type: status.status_type || "transition",
          selectable_mode: status.selectable_mode || "user",
          phase: status.phase || "consultation",
          description: status.description || null,
          display_order: status.display_order ?? 0,
        });
      } else {
        form.reset({
          id: "",
          name: "",
          color_code: DEFAULT_STATUS_COLOR,
          stage_id: null,
          outcome_type: "neutral",
          // ✅ FSM v3.0 defaults for create mode
          is_final: false,
          legacy_status: null,
          is_universal: false,
          updates_pipeline: true,
          counts_for_funnel: true,
          code: null,
          status_type: "transition",
          selectable_mode: "user",
          phase: "consultation",
          description: null,
          display_order: 0,
        });
      }
    }
  }, [open, isEditMode, status, form]);

  // Handle form submission
  const onSubmit = async (values: StatusFormValues) => {
    try {
      // ✅ FSM v3.0: Build payload with all fields
      const payload = {
        name: values.name,
        color_code: values.color_code,
        stage_id: values.is_universal ? null : (values.stage_id || null),
        outcome_type: values.outcome_type as OutcomeType,
        // ✅ FSM v3.0: New field names
        is_final: values.is_final,
        legacy_status: values.legacy_status || null,
        is_universal: values.is_universal,
        updates_pipeline: values.updates_pipeline,
        counts_for_funnel: values.counts_for_funnel,
        // ✅ FSM v3.0: New fields
        code: values.code || null,
        status_type: values.status_type as StatusType,
        selectable_mode: values.selectable_mode as SelectableMode,
        phase: values.is_universal ? "universal" : values.phase,
        description: values.description || null,
        display_order: values.display_order,
      };

      if (isEditMode && status) {
        await updateMutation.mutateAsync({
          id: status.id,
          data: payload as ConsultationStatusUpdate,
        });
      } else {
        await createMutation.mutateAsync({
          id: values.id,
          ...payload,
        } as ConsultationStatusCreate);
      }

      // Close dialog on success
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error handling is done in mutation hooks (toast)
      console.error("Form submission error:", error);
    }
  };

  // Check if mutation is in progress
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Sửa Trạng thái Tư vấn" : "Tạo Trạng thái Tư vấn Mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật thông tin trạng thái tư vấn"
              : "Nhập thông tin để tạo trạng thái tư vấn mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* ID Field - Only for create mode */}
            {!isEditMode && (
              <FormField
                control={form.control}
                name="id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Mã trạng thái <span className="text-error-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input placeholder="VD: hen_lai" {...field} disabled={isSubmitting} />
                    </FormControl>
                    <FormDescription>
                      Mã định danh duy nhất (chữ thường, số, gạch dưới)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên trạng thái <span className="text-error-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input placeholder="VD: Hẹn lại" {...field} disabled={isSubmitting} />
                  </FormControl>
                  <FormDescription>Tên hiển thị của trạng thái này</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Stage Field - Hidden when Universal */}
            {!form.watch("is_universal") && (
              <FormField
                control={form.control}
                name="stage_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Giai đoạn Pipeline <span className="text-error-500">*</span>
                    </FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value || ""}
                      disabled={isSubmitting || stagesLoading}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn giai đoạn" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {stagesLoading ? (
                          <SelectItem value="loading" disabled>
                            Đang tải...
                          </SelectItem>
                        ) : stages.length === 0 ? (
                          <SelectItem value="empty" disabled>
                            Không có giai đoạn nào
                          </SelectItem>
                        ) : (
                          stages.map((stage) => (
                            <SelectItem key={stage.id} value={stage.id}>
                              {stage.name}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    <FormDescription>Trạng thái này thuộc giai đoạn pipeline nào</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Color Field */}
            <FormField
              control={form.control}
              name="color_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Màu sắc <span className="text-error-500">*</span>
                  </FormLabel>
                  <div className="flex gap-2">
                    <FormControl>
                      <Input
                        placeholder="#3B82F6"
                        {...field}
                        disabled={isSubmitting}
                        className="flex-1"
                      />
                    </FormControl>
                    <div
                      className="h-10 w-10 rounded border"
                      style={{ backgroundColor: field.value }}
                    />
                  </div>
                  <FormDescription>Mã màu hex cho trạng thái này</FormDescription>
                  {/* Color Presets */}
                  <div className="mt-2 flex gap-2">
                    {PRESET_COLORS.map((color) => (
                      <button
                        key={color.value}
                        type="button"
                        className="h-6 w-6 rounded border-2 transition-transform hover:scale-110"
                        style={{
                          backgroundColor: color.value,
                          borderColor: field.value === color.value ? "#000" : "transparent",
                        }}
                        onClick={() => field.onChange(color.value)}
                        title={color.name}
                      />
                    ))}
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Outcome Type Field */}
            <FormField
              control={form.control}
              name="outcome_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Loại kết quả <span className="text-error-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn loại kết quả" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="positive">
                        <span className="flex items-center gap-2">
                          <span className="text-success-500">●</span> Tích cực
                        </span>
                      </SelectItem>
                      <SelectItem value="neutral">
                        <span className="flex items-center gap-2">
                          <span className="text-muted-foreground">●</span> Trung lập
                        </span>
                      </SelectItem>
                      <SelectItem value="negative">
                        <span className="flex items-center gap-2">
                          <span className="text-error-500">●</span> Tiêu cực
                        </span>
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Phân loại kết quả của trạng thái (dùng cho báo cáo và phân tích)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Is Final Field (FSM v3.0) */}
            <FormField
              control={form.control}
              name="is_final"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-y-0 space-x-3 rounded-md border p-4">
                  <FormControl>
                    <ShadcnCheckbox checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Trạng thái cuối</FormLabel>
                    <FormDescription>
                      Đánh dấu là kết thúc vòng đời lead (VD: &apos;Đã ghi danh&apos;,
                      &apos;Từ chối&apos;). Lead có trạng thái cuối sẽ không được tính trong
                      pipeline đang hoạt động.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            {/* ✅ Universal Status Field */}
            <FormField
              control={form.control}
              name="is_universal"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-y-0 space-x-3 rounded-md border p-4 bg-amber-50 border-amber-200">
                  <FormControl>
                    <ShadcnCheckbox checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Universal Status</FormLabel>
                    <FormDescription>
                      Status có thể dùng ở mọi pipeline stage (VD: &quot;Không nghe máy&quot;,
                      &quot;Thuê bao&quot;). Universal statuses luôn xuất hiện trong danh sách cho
                      phép chuyển đổi bất kể stage hiện tại của lead.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            {/* ✅ Updates Pipeline Field */}
            <FormField
              control={form.control}
              name="updates_pipeline"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-y-0 space-x-3 rounded-md border p-4 bg-info-50 border-info-200">
                  <FormControl>
                    <ShadcnCheckbox checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Cập nhật Pipeline Progression</FormLabel>
                    <FormDescription>
                      Bỏ tích nếu status chỉ ghi nhận activity mà KHÔNG thay đổi pipeline progression
                      của lead. Thường dùng cho universal retry statuses (VD: &quot;Không nghe
                      máy&quot;) để ghi nhận cuộc gọi nhưng giữ nguyên trạng thái lead.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            {/* ✅ FSM v3.0: Counts for Funnel Field */}
            <FormField
              control={form.control}
              name="counts_for_funnel"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-y-0 space-x-3 rounded-md border p-4 bg-success-50 border-success-200">
                  <FormControl>
                    <ShadcnCheckbox checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Đếm vào Funnel Analytics</FormLabel>
                    <FormDescription>
                      Bỏ tích nếu status KHÔNG được đếm vào funnel analytics (VD: &quot;Đã rút
                      lại học phí&quot; - thí sinh đã hoàn tiền nên không tính là nhập học).
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            {/* Legacy Status Field - For backward compatibility */}
            <FormField
              control={form.control}
              name="legacy_status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Legacy Status (Tùy chọn)</FormLabel>
                  <Select
                    onValueChange={(value) => field.onChange(value === "_none_" ? null : value)}
                    value={field.value || "_none_"}
                    disabled={isSubmitting}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Tự động từ giai đoạn/kết quả" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="_none_">
                        <span className="text-muted-foreground">Tự động (khuyến nghị)</span>
                      </SelectItem>
                      {LEGACY_STATUS_OPTIONS.map((status) => (
                        <SelectItem key={status.value} value={status.value}>
                          {status.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Ánh xạ sang lead.status để tương thích ngược. Để trống để tự động
                    xác định từ giai đoạn và loại kết quả.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* ============================================================= */}
            {/* FSM v3.0 FIELDS */}
            {/* ============================================================= */}

            <div className="border-t pt-4 mt-4">
              <h4 className="font-medium text-sm text-muted-foreground mb-4">
                FSM v3.0 Configuration
              </h4>

              {/* Code Field */}
              <FormField
                control={form.control}
                name="code"
                render={({ field }) => (
                  <FormItem className="mb-4">
                    <FormLabel>Code (Machine-readable)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="VD: NOT_CONTACTED, ENROLLED"
                        {...field}
                        value={field.value || ""}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Mã máy đọc được cho status (uppercase, underscore). Dùng trong FSM engine.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Phase Field - Hidden when Universal */}
              {!form.watch("is_universal") && (
                <FormField
                  control={form.control}
                  name="phase"
                  render={({ field }) => (
                    <FormItem className="mb-4">
                      <FormLabel>
                        Phase <span className="text-error-500">*</span>
                      </FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value}
                        disabled={isSubmitting}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn phase" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="consultation">Consultation (Tư vấn)</SelectItem>
                          <SelectItem value="admission">Admission (Hồ sơ)</SelectItem>
                          <SelectItem value="fee">Fee (Học phí)</SelectItem>
                          <SelectItem value="enrolled">Enrolled (Nhập học)</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        Phase trong workflow. Lead phải có admission_profile phù hợp để chuyển phase.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              {/* Status Type Field */}
              <FormField
                control={form.control}
                name="status_type"
                render={({ field }) => (
                  <FormItem className="mb-4">
                    <FormLabel>
                      Status Type <span className="text-error-500">*</span>
                    </FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={isSubmitting}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn loại status" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="transition">
                          Transition - Status workflow thường
                        </SelectItem>
                        <SelectItem value="activity">
                          Activity - Ghi nhận hoạt động, không ảnh hưởng workflow
                        </SelectItem>
                        <SelectItem value="system">
                          System - Chỉ hệ thống thay đổi, không hiển thị cho user
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Loại status: transition (workflow), activity (ghi nhận), system (tự động)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Selectable Mode Field */}
              <FormField
                control={form.control}
                name="selectable_mode"
                render={({ field }) => (
                  <FormItem className="mb-4">
                    <FormLabel>
                      Selectable Mode <span className="text-error-500">*</span>
                    </FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                      disabled={isSubmitting}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn quyền chọn" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="user">User - Mọi user có thể chọn</SelectItem>
                        <SelectItem value="role">Role - Chỉ Manager/Admin chọn được</SelectItem>
                        <SelectItem value="system">System - Không hiển thị trong UI</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Ai có thể chọn status này trong UI
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Display Order Field */}
              <FormField
                control={form.control}
                name="display_order"
                render={({ field }) => (
                  <FormItem className="mb-4">
                    <FormLabel>Display Order</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={0}
                        placeholder="0"
                        {...field}
                        value={field.value}
                        onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Thứ tự hiển thị trong danh sách (số nhỏ hơn hiển thị trước)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Description Field */}
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Mô tả chi tiết về status này..."
                        {...field}
                        value={field.value || ""}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormDescription>
                      Mô tả chi tiết về ý nghĩa và cách sử dụng status
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

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
                {isEditMode ? "Cập nhật" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
