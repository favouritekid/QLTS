// src/app/(dashboard)/admin/tuition-discount/page.tsx
"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import { CalendarIcon, Loader2, Pencil, Plus, Trash2, Percent, Banknote } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { cn } from "@/lib/utils";

import {
  useTuitionDiscountPolicies,
  useCreateTuitionDiscountPolicy,
  useUpdateTuitionDiscountPolicy,
  useDeleteTuitionDiscountPolicy,
} from "@/hooks/useTuitionDiscount";
import type {
  TuitionDiscountPolicy,
  TuitionDiscountPolicyCreate,
  DiscountType,
} from "@/types/tuition-discount.types";

// =============================================================================
// FORM SCHEMA
// =============================================================================

const policyFormSchema = z.object({
  code: z
    .string()
    .min(1, "Mã chính sách là bắt buộc")
    .max(50, "Mã không quá 50 ký tự")
    .regex(/^[A-Z0-9_]+$/, "Chỉ chữ in hoa, số và dấu gạch dưới"),
  name: z.string().min(1, "Tên chính sách là bắt buộc").max(200),
  description: z.string().max(2000).optional(),
  discount_type: z.enum(["amount", "percentage"]),
  discount_value: z.number().min(0, "Giá trị phải >= 0"),
  valid_from: z.date().optional().nullable(),
  valid_to: z.date().optional().nullable(),
  is_stackable: z.boolean(),
  priority: z.number().int().min(0),
  max_usage: z.number().int().min(0).optional().nullable(),
  is_active: z.boolean(),
  // JSON fields - applicable_scope
  all_programs: z.boolean(),
  is_heavy_only: z.boolean(),
  degree_levels: z.string().optional(), // Comma-separated: "Cao đẳng, Trung cấp"
  major_program_codes: z.string().optional(), // Comma-separated: "6480201, 6510301"
  offering_types: z.string().optional(), // Comma-separated: "Chính quy, Liên thông"
});

type PolicyFormValues = z.infer<typeof policyFormSchema>;

// =============================================================================
// MAIN PAGE COMPONENT
// =============================================================================

export default function TuitionDiscountPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editPolicy, setEditPolicy] = useState<TuitionDiscountPolicy | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [policyToDelete, setPolicyToDelete] = useState<TuitionDiscountPolicy | null>(null);

  // Queries & Mutations
  const { data, isLoading } = useTuitionDiscountPolicies({ includeExpired: true });
  const createMutation = useCreateTuitionDiscountPolicy();
  const updateMutation = useUpdateTuitionDiscountPolicy();
  const deleteMutation = useDeleteTuitionDiscountPolicy();

  const form = useForm<PolicyFormValues>({
    resolver: zodResolver(policyFormSchema),
    defaultValues: {
      code: "",
      name: "",
      description: "",
      discount_type: "percentage",
      discount_value: 0,
      valid_from: null,
      valid_to: null,
      is_stackable: false,
      priority: 0,
      max_usage: null,
      is_active: true,
      all_programs: true,
      is_heavy_only: false,
      degree_levels: "",
      major_program_codes: "",
      offering_types: "",
    },
  });

  const isEditMode = !!editPolicy;

  const openCreateDialog = () => {
    setEditPolicy(null);
    form.reset({
      code: "",
      name: "",
      description: "",
      discount_type: "percentage",
      discount_value: 0,
      valid_from: null,
      valid_to: null,
      is_stackable: false,
      priority: 0,
      max_usage: null,
      is_active: true,
      all_programs: true,
      is_heavy_only: false,
      degree_levels: "",
      major_program_codes: "",
      offering_types: "",
    });
    setDialogOpen(true);
  };

  const openEditDialog = (policy: TuitionDiscountPolicy) => {
    setEditPolicy(policy);
    const scope = policy.applicable_scope || {};
    form.reset({
      code: policy.code,
      name: policy.name,
      description: policy.description || "",
      discount_type: policy.discount_type,
      discount_value: policy.discount_value,
      valid_from: policy.valid_from ? new Date(policy.valid_from) : null,
      valid_to: policy.valid_to ? new Date(policy.valid_to) : null,
      is_stackable: policy.is_stackable,
      priority: policy.priority,
      max_usage: policy.max_usage,
      is_active: policy.is_active,
      all_programs: scope.all_programs || false,
      is_heavy_only: scope.is_heavy_only || false,
      degree_levels: Array.isArray(scope.degree_levels) ? scope.degree_levels.join(", ") : "",
      major_program_codes: Array.isArray(scope.major_program_codes) ? scope.major_program_codes.join(", ") : "",
      offering_types: Array.isArray(scope.offering_types) ? scope.offering_types.join(", ") : "",
    });
    setDialogOpen(true);
  };

  // Helper to parse comma-separated string to array
  const parseCommaSeparated = (value: string | undefined): string[] | undefined => {
    if (!value || value.trim() === "") return undefined;
    return value.split(",").map(s => s.trim()).filter(s => s.length > 0);
  };

  const onSubmit = async (values: PolicyFormValues) => {
    const payload: TuitionDiscountPolicyCreate = {
      code: values.code.toUpperCase(),
      name: values.name,
      description: values.description || null,
      discount_type: values.discount_type as DiscountType,
      discount_value: values.discount_value,
      valid_from: values.valid_from?.toISOString().split("T")[0] || null,
      valid_to: values.valid_to?.toISOString().split("T")[0] || null,
      is_stackable: values.is_stackable,
      priority: values.priority,
      max_usage: values.max_usage || null,
      is_active: values.is_active,
      applicable_scope: {
        all_programs: values.all_programs,
        is_heavy_only: values.is_heavy_only,
        degree_levels: parseCommaSeparated(values.degree_levels),
        major_program_codes: parseCommaSeparated(values.major_program_codes),
        offering_types: parseCommaSeparated(values.offering_types),
      },
      target_criteria: {},
    };

    try {
      if (isEditMode && editPolicy) {
        await updateMutation.mutateAsync({
          id: editPolicy.id,
          data: payload,
        });
      } else {
        await createMutation.mutateAsync(payload);
      }
      setDialogOpen(false);
    } catch {
      // Error handled in hook
    }
  };

  const handleDelete = async () => {
    if (!policyToDelete) return;
    try {
      await deleteMutation.mutateAsync({ id: policyToDelete.id });
      setDeleteDialogOpen(false);
      setPolicyToDelete(null);
    } catch {
      // Error handled in hook
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
      maximumFractionDigits: 0,
    }).format(value);
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <PageContainer>
      <PageHeader
        title="Quản lý chính sách ưu đãi học phí"
        description="Thiết lập và quản lý các chính sách ưu đãi, giảm giá học phí"
        icon={<Percent className="h-8 w-8" />}
        actions={
          <Button onClick={openCreateDialog}>
            <Plus className="mr-2 h-4 w-4" />
            Thêm chính sách
          </Button>
        }
      />

      <Card>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mã</TableHead>
                  <TableHead>Tên chính sách</TableHead>
                  <TableHead>Loại</TableHead>
                  <TableHead>Giá trị</TableHead>
                  <TableHead>Hiệu lực</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead className="text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="text-muted-foreground text-center py-8">
                      Chưa có chính sách nào. Nhấn &quot;Thêm chính sách&quot; để tạo mới.
                    </TableCell>
                  </TableRow>
                )}
                {data?.items.map((policy) => (
                  <TableRow key={policy.id}>
                    <TableCell className="font-mono text-sm">{policy.code}</TableCell>
                    <TableCell>
                      <div className="font-medium">{policy.name}</div>
                      {policy.description && (
                        <div className="text-muted-foreground text-xs truncate max-w-[300px]">
                          {policy.description}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      {policy.discount_type === "percentage" ? (
                        <Badge variant="secondary">
                          <Percent className="mr-1 h-3 w-3" />
                          Phần trăm
                        </Badge>
                      ) : (
                        <Badge variant="outline">
                          <Banknote className="mr-1 h-3 w-3" />
                          Số tiền
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-medium">
                      {policy.discount_type === "percentage"
                        ? `${policy.discount_value}%`
                        : formatCurrency(policy.discount_value)}
                    </TableCell>
                    <TableCell>
                      {policy.valid_from || policy.valid_to ? (
                        <div className="text-xs">
                          {policy.valid_from && (
                            <div>Từ: {format(new Date(policy.valid_from), "dd/MM/yyyy")}</div>
                          )}
                          {policy.valid_to && (
                            <div>Đến: {format(new Date(policy.valid_to), "dd/MM/yyyy")}</div>
                          )}
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-xs">Không giới hạn</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {policy.is_active ? (
                        policy.is_expired ? (
                          <Badge variant="destructive">Hết hạn</Badge>
                        ) : (
                          <Badge variant="default">Hoạt động</Badge>
                        )
                      ) : (
                        <Badge variant="secondary">Tạm dừng</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditDialog(policy)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setPolicyToDelete(policy);
                          setDeleteDialogOpen(true);
                        }}
                      >
                        <Trash2 className="text-destructive h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>
              {isEditMode ? "Chỉnh sửa chính sách" : "Tạo chính sách mới"}
            </DialogTitle>
            <DialogDescription>
              {isEditMode
                ? "Cập nhật thông tin chính sách ưu đãi"
                : "Nhập thông tin để tạo chính sách ưu đãi mới"}
            </DialogDescription>
          </DialogHeader>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                {/* Code */}
                <FormField
                  control={form.control}
                  name="code"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Mã chính sách *</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="VD: EARLY_BIRD_2025"
                          {...field}
                          onChange={(e) => field.onChange(e.target.value.toUpperCase())}
                          disabled={isEditMode || isSubmitting}
                          className="uppercase"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Priority */}
                <FormField
                  control={form.control}
                  name="priority"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Độ ưu tiên</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          placeholder="0"
                          value={field.value}
                          onChange={(e) => field.onChange(e.target.valueAsNumber || 0)}
                          disabled={isSubmitting}
                        />
                      </FormControl>
                      <FormDescription>Cao hơn = áp dụng trước</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Name */}
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tên chính sách *</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="VD: Ưu đãi đăng ký sớm 2025"
                        {...field}
                        disabled={isSubmitting}
                      />
                    </FormControl>
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
                        placeholder="Mô tả chi tiết về chính sách..."
                        className="resize-none"
                        {...field}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-4">
                {/* Discount Type */}
                <FormField
                  control={form.control}
                  name="discount_type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Loại ưu đãi *</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value}
                        disabled={isSubmitting}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="percentage">Phần trăm (%)</SelectItem>
                          <SelectItem value="amount">Số tiền (VNĐ)</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Discount Value */}
                <FormField
                  control={form.control}
                  name="discount_value"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Giá trị ưu đãi *</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          placeholder={
                            form.watch("discount_type") === "percentage" ? "VD: 15" : "VD: 2000000"
                          }
                          value={field.value}
                          onChange={(e) => field.onChange(e.target.valueAsNumber || 0)}
                          disabled={isSubmitting}
                        />
                      </FormControl>
                      <FormDescription>
                        {form.watch("discount_type") === "percentage"
                          ? "Nhập phần trăm (0-100)"
                          : "Nhập số tiền VNĐ"}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Valid From */}
                <FormField
                  control={form.control}
                  name="valid_from"
                  render={({ field }) => (
                    <FormItem className="flex flex-col">
                      <FormLabel>Ngày bắt đầu</FormLabel>
                      <Popover>
                        <PopoverTrigger asChild>
                          <FormControl>
                            <Button
                              variant="outline"
                              className={cn(
                                "pl-3 text-left font-normal",
                                !field.value && "text-muted-foreground"
                              )}
                              disabled={isSubmitting}
                            >
                              {field.value ? (
                                format(field.value, "dd/MM/yyyy", { locale: vi })
                              ) : (
                                <span>Chọn ngày</span>
                              )}
                              <CalendarIcon className="ml-auto h-4 w-4 opacity-50" />
                            </Button>
                          </FormControl>
                        </PopoverTrigger>
                        <PopoverContent className="w-auto p-0" align="start">
                          <Calendar
                            mode="single"
                            selected={field.value || undefined}
                            onSelect={field.onChange}
                            locale={vi}
                          />
                        </PopoverContent>
                      </Popover>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Valid To */}
                <FormField
                  control={form.control}
                  name="valid_to"
                  render={({ field }) => (
                    <FormItem className="flex flex-col">
                      <FormLabel>Ngày kết thúc</FormLabel>
                      <Popover>
                        <PopoverTrigger asChild>
                          <FormControl>
                            <Button
                              variant="outline"
                              className={cn(
                                "pl-3 text-left font-normal",
                                !field.value && "text-muted-foreground"
                              )}
                              disabled={isSubmitting}
                            >
                              {field.value ? (
                                format(field.value, "dd/MM/yyyy", { locale: vi })
                              ) : (
                                <span>Chọn ngày</span>
                              )}
                              <CalendarIcon className="ml-auto h-4 w-4 opacity-50" />
                            </Button>
                          </FormControl>
                        </PopoverTrigger>
                        <PopoverContent className="w-auto p-0" align="start">
                          <Calendar
                            mode="single"
                            selected={field.value || undefined}
                            onSelect={field.onChange}
                            locale={vi}
                          />
                        </PopoverContent>
                      </Popover>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Max Usage */}
              <FormField
                control={form.control}
                name="max_usage"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Giới hạn số lượt sử dụng</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="Để trống = không giới hạn"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : null)}
                        disabled={isSubmitting}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Scope Options */}
              <div className="space-y-3 rounded-lg border p-4">
                <div className="text-sm font-medium">Phạm vi áp dụng</div>

                <FormField
                  control={form.control}
                  name="all_programs"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between">
                      <div>
                        <FormLabel>Áp dụng tất cả ngành</FormLabel>
                        <FormDescription>Chính sách áp dụng cho mọi chương trình</FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={isSubmitting}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="is_heavy_only"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between">
                      <div>
                        <FormLabel>Chỉ ngành nặng nhọc, độc hại</FormLabel>
                        <FormDescription>Chỉ áp dụng cho ngành có is_heavy = true</FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={isSubmitting || form.watch("all_programs")}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                {/* Additional Scope Options - shown when all_programs is false */}
                {!form.watch("all_programs") && (
                  <div className="space-y-3 border-t pt-3">
                    <FormField
                      control={form.control}
                      name="degree_levels"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Trình độ cụ thể</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="VD: Cao đẳng, Trung cấp"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormDescription>Phân cách bằng dấu phẩy</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="major_program_codes"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Mã ngành cụ thể</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="VD: 6480201, 6510301"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormDescription>Phân cách bằng dấu phẩy</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="offering_types"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Loại hình đào tạo</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="VD: Chính quy, Liên thông"
                              {...field}
                              disabled={isSubmitting}
                            />
                          </FormControl>
                          <FormDescription>Phân cách bằng dấu phẩy</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                )}
              </div>

              {/* Status Options */}
              <div className="space-y-3 rounded-lg border p-4">
                <FormField
                  control={form.control}
                  name="is_stackable"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between">
                      <div>
                        <FormLabel>Cho phép cộng dồn</FormLabel>
                        <FormDescription>Có thể kết hợp với ưu đãi khác</FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={isSubmitting}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="is_active"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between">
                      <div>
                        <FormLabel>Trạng thái hoạt động</FormLabel>
                        <FormDescription>Bật/tắt chính sách này</FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={isSubmitting}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </div>

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setDialogOpen(false)}
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

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xác nhận xóa</DialogTitle>
            <DialogDescription>
              Bạn có chắc chắn muốn xóa chính sách &quot;{policyToDelete?.name}&quot;?
              Hành động này không thể hoàn tác.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteMutation.isPending}
            >
              Hủy
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Xóa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
