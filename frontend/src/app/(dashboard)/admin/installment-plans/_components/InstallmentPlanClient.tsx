// src/app/(dashboard)/admin/installment-plans/_components/InstallmentPlanClient.tsx
"use client";

import { useState, useEffect } from "react";
import { useForm, useFieldArray, type UseFormReturn } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  CreditCard,
  Loader2,
  MoreVertical,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import {
  BaseCard,
  CardHeader as BaseCardHeader,
  CardBody,
  CardField,
  CardMeta,
  CardActions,
} from "@/components/ui/base-card";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";

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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { TableEmptyState } from "@/components/common/EmptyState";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import {
  useAdminInstallmentPlans,
  useCreateInstallmentPlan,
  useUpdateInstallmentPlan,
  useDeleteInstallmentPlan,
  getPenaltyDescription,
} from "@/hooks/finance/useInstallmentPlans";
import type { InstallmentPlan } from "@/types/finance.types";

// =============================================================================
// FORM SCHEMA
// =============================================================================

const scheduleItemSchema = z.object({
  installment_no: z.number().int().min(1).max(12),
  percent: z.number().min(0).max(100),
  due_days_offset: z.number().int().min(0).max(365),
});

const planFormSchema = z
  .object({
    code: z
      .string()
      .min(1, "Mã phương án là bắt buộc")
      .max(50, "Mã không quá 50 ký tự")
      .regex(/^[A-Z0-9_]+$/, "Chỉ chữ in hoa, số và dấu gạch dưới"),
    name: z.string().min(1, "Tên phương án là bắt buộc").max(200),
    description: z.string().max(500).optional().nullable(),
    installment_count: z.number().int().min(1, "Tối thiểu 1 đợt").max(12, "Tối đa 12 đợt"),
    schedule: z.array(scheduleItemSchema).min(1, "Phải có ít nhất 1 đợt"),
    penalty_type: z.enum(["percentage", "fixed"]),
    penalty_rate: z.number().min(0).max(100),
    grace_period_days: z.number().int().min(0).max(365),
    is_active: z.boolean(),
  })
  .refine(
    (data) => data.schedule.length === data.installment_count,
    { message: "Số đợt trong lịch phải bằng số đợt đã chọn", path: ["schedule"] }
  )
  .refine(
    (data) => {
      const total = data.schedule.reduce((sum, item) => sum + item.percent, 0);
      return Math.abs(total - 100) < 0.01;
    },
    { message: "Tổng phần trăm các đợt phải bằng 100%", path: ["schedule"] }
  );

type PlanFormValues = z.infer<typeof planFormSchema>;

// =============================================================================
// MOBILE PLAN CARD COMPONENT
// =============================================================================

interface MobilePlanCardProps {
  plan: InstallmentPlan;
  onEdit: (plan: InstallmentPlan) => void;
  onDelete: (plan: InstallmentPlan) => void;
}

function MobilePlanCard({ plan, onEdit, onDelete }: MobilePlanCardProps) {
  const [actionSheetOpen, setActionSheetOpen] = useState(false);

  return (
    <BaseCard showCheckbox={false}>
      <BaseCardHeader
        title={plan.name}
        subtitle={
          <code className="bg-muted rounded px-1.5 py-0.5 text-xs">{plan.code}</code>
        }
        badge={
          plan.is_active ? (
            <Badge variant="default">Hoạt động</Badge>
          ) : (
            <Badge variant="secondary">Tạm dừng</Badge>
          )
        }
      />
      <CardBody>
        <CardField label="Số đợt" value={`${plan.installment_count} đợt`} />
        <CardField label="Phí trễ hạn" value={getPenaltyDescription(plan)} />
        {plan.description && (
          <CardField label="Mô tả" value={plan.description} />
        )}
      </CardBody>
      <CardMeta>
        <Badge variant="outline">
          <CreditCard className="mr-1 h-3 w-3" aria-hidden="true" />
          {plan.installment_count} đợt
        </Badge>
      </CardMeta>
      <CardActions>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setActionSheetOpen(true)}
          aria-label="Thao tác"
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </CardActions>

      <MobileActionSheet
        open={actionSheetOpen}
        onOpenChange={setActionSheetOpen}
        title={plan.name}
      >
        <MobileActionSheet.Item
          icon={Pencil}
          onClick={() => {
            setActionSheetOpen(false);
            onEdit(plan);
          }}
        >
          Chỉnh sửa
        </MobileActionSheet.Item>
        <MobileActionSheet.Item
          icon={Trash2}
          variant="destructive"
          onClick={() => {
            setActionSheetOpen(false);
            onDelete(plan);
          }}
        >
          Xóa
        </MobileActionSheet.Item>
      </MobileActionSheet>
    </BaseCard>
  );
}

// =============================================================================
// SCHEDULE EDITOR COMPONENT
// =============================================================================

interface ScheduleEditorProps {
  form: UseFormReturn<PlanFormValues>;
  installmentCount: number;
}

function ScheduleEditor({ form, installmentCount }: ScheduleEditorProps) {
  const { fields, replace } = useFieldArray({
    control: form.control,
    name: "schedule",
  });

  // Sync schedule array with installment_count
  useEffect(() => {
    const currentLength = fields.length;
    if (currentLength !== installmentCount) {
      const currentValues = form.getValues("schedule") || [];
      const newSchedule = Array.from({ length: installmentCount }, (_, i) => {
        if (i < currentValues.length) {
          return {
            installment_no: i + 1,
            percent: currentValues[i].percent,
            due_days_offset: currentValues[i].due_days_offset,
          };
        }
        return {
          installment_no: i + 1,
          percent: 0,
          due_days_offset: i * 30,
        };
      });
      // Distribute evenly if creating from scratch
      if (currentValues.length === 0 || currentValues.length !== installmentCount) {
        const even = Math.floor(100 / installmentCount);
        const remainder = 100 - even * installmentCount;
        newSchedule.forEach((item, i) => {
          item.installment_no = i + 1;
          item.percent = even + (i === installmentCount - 1 ? remainder : 0);
        });
      }
      replace(newSchedule);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [installmentCount]);

  const watchSchedule = form.watch("schedule") as Array<{ percent: number }>;
  const totalPercent = watchSchedule?.reduce((sum: number, item: { percent: number }) => sum + (item?.percent || 0), 0) ?? 0;
  const isValid = Math.abs(totalPercent - 100) < 0.01;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <FormLabel>Lịch trả góp</FormLabel>
        <Badge variant={isValid ? "default" : "destructive"}>
          Tổng: {totalPercent.toFixed(0)}%
        </Badge>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">Đợt</TableHead>
              <TableHead>Tỷ lệ (%)</TableHead>
              <TableHead>Ngày offset</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fields.map((field, index) => (
              <TableRow key={field.id}>
                <TableCell className="font-medium">Đợt {index + 1}</TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`schedule.${index}.percent`}
                    render={({ field: f }) => (
                      <FormItem className="mb-0">
                        <FormControl>
                          <Input
                            type="number"
                            min={0}
                            max={100}
                            step={0.01}
                            className="w-24"
                            {...f}
                            onChange={(e) => f.onChange(parseFloat(e.target.value) || 0)}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </TableCell>
                <TableCell>
                  <FormField
                    control={form.control}
                    name={`schedule.${index}.due_days_offset`}
                    render={({ field: f }) => (
                      <FormItem className="mb-0">
                        <FormControl>
                          <Input
                            type="number"
                            min={0}
                            max={365}
                            className="w-24"
                            {...f}
                            onChange={(e) => f.onChange(parseInt(e.target.value) || 0)}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {!isValid && (
        <p className="text-destructive text-sm">
          Tổng phần trăm phải bằng 100% (hiện tại: {totalPercent.toFixed(0)}%)
        </p>
      )}
    </div>
  );
}

// =============================================================================
// CLIENT COMPONENT
// =============================================================================

export function InstallmentPlanClient() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editPlan, setEditPlan] = useState<InstallmentPlan | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [planToDelete, setPlanToDelete] = useState<InstallmentPlan | null>(null);

  const { data: plans, isLoading } = useAdminInstallmentPlans();
  const createMutation = useCreateInstallmentPlan();
  const updateMutation = useUpdateInstallmentPlan();
  const deleteMutation = useDeleteInstallmentPlan();

  const form = useForm<PlanFormValues>({
    resolver: zodResolver(planFormSchema),
    defaultValues: {
      code: "",
      name: "",
      description: "",
      installment_count: 1,
      schedule: [{ installment_no: 1, percent: 100, due_days_offset: 0 }],
      penalty_type: "percentage",
      penalty_rate: 0,
      grace_period_days: 7,
      is_active: true,
    },
  });

  const isEditMode = !!editPlan;
  const watchInstallmentCount = form.watch("installment_count");

  const openCreateDialog = () => {
    setEditPlan(null);
    form.reset({
      code: "",
      name: "",
      description: "",
      installment_count: 1,
      schedule: [{ installment_no: 1, percent: 100, due_days_offset: 0 }],
      penalty_type: "percentage",
      penalty_rate: 0,
      grace_period_days: 7,
      is_active: true,
    });
    setDialogOpen(true);
  };

  const openEditDialog = (plan: InstallmentPlan) => {
    setEditPlan(plan);
    form.reset({
      code: plan.code,
      name: plan.name,
      description: plan.description || "",
      installment_count: plan.installment_count,
      schedule: plan.schedule.map((item) => ({
        installment_no: item.installment_no,
        percent: item.percent,
        due_days_offset: item.due_days_offset,
      })),
      penalty_type: plan.penalty_type as "percentage" | "fixed",
      penalty_rate: parseFloat(plan.penalty_rate),
      grace_period_days: plan.grace_period_days,
      is_active: plan.is_active,
    });
    setDialogOpen(true);
  };

  const onSubmit = async (values: PlanFormValues) => {
    const payload = {
      code: values.code,
      name: values.name,
      description: values.description || null,
      installment_count: values.installment_count,
      schedule: values.schedule.map((item) => ({
        installment_no: item.installment_no,
        percent: item.percent,
        due_days_offset: item.due_days_offset,
      })),
      penalty_type: values.penalty_type,
      penalty_rate: String(values.penalty_rate),
      grace_period_days: values.grace_period_days,
      is_active: values.is_active,
    };

    try {
      if (isEditMode && editPlan) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars -- destructure-to-omit pattern
        const { code: _code, ...updateData } = payload;
        await updateMutation.mutateAsync({
          id: editPlan.id,
          data: updateData,
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
    if (!planToDelete) return;
    try {
      await deleteMutation.mutateAsync({ id: planToDelete.id });
      setDeleteDialogOpen(false);
      setPlanToDelete(null);
    } catch {
      // Error handled in hook
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <PageContainer>
      <PageHeader
        title="Quản lý phương án trả góp"
        description="Thiết lập các phương án thanh toán theo đợt cho học phí"
        icon={<CreditCard className="h-8 w-8" />}
        actions={
          <Button onClick={openCreateDialog}>
            <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
            Thêm phương án
          </Button>
        }
      />

      <Card>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !plans || plans.length === 0 ? (
            <div className="text-center py-8">
              <TableEmptyState
                title="Chưa có phương án trả góp"
                description="Tạo phương án trả góp đầu tiên để bắt đầu"
              />
              <Button onClick={openCreateDialog} className="mt-4">
                <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
                Thêm phương án
              </Button>
            </div>
          ) : (
            <>
              {/* Desktop Table */}
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Mã</TableHead>
                      <TableHead>Tên</TableHead>
                      <TableHead className="text-center">Số đợt</TableHead>
                      <TableHead>Phạt trễ</TableHead>
                      <TableHead className="text-center">Trạng thái</TableHead>
                      <TableHead className="text-right">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {plans.map((plan) => (
                      <TableRow key={plan.id}>
                        <TableCell>
                          <code className="bg-muted rounded px-1.5 py-0.5 text-xs">
                            {plan.code}
                          </code>
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="font-medium">{plan.name}</p>
                            {plan.description && (
                              <p className="text-muted-foreground text-sm line-clamp-1">
                                {plan.description}
                              </p>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant="outline">{plan.installment_count} đợt</Badge>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm">{getPenaltyDescription(plan)}</span>
                        </TableCell>
                        <TableCell className="text-center">
                          {plan.is_active ? (
                            <Badge variant="default">Hoạt động</Badge>
                          ) : (
                            <Badge variant="secondary">Tạm dừng</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => openEditDialog(plan)}
                              aria-label={`Chỉnh sửa ${plan.name}`}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="text-destructive h-8 w-8"
                              onClick={() => {
                                setPlanToDelete(plan);
                                setDeleteDialogOpen(true);
                              }}
                              aria-label={`Xóa ${plan.name}`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Mobile Cards */}
              <div className="space-y-3 md:hidden">
                {plans.map((plan) => (
                  <MobilePlanCard
                    key={plan.id}
                    plan={plan}
                    onEdit={openEditDialog}
                    onDelete={(p) => {
                      setPlanToDelete(p);
                      setDeleteDialogOpen(true);
                    }}
                  />
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {isEditMode ? "Chỉnh sửa phương án trả góp" : "Thêm phương án trả góp"}
            </DialogTitle>
            <DialogDescription>
              {isEditMode
                ? "Cập nhật thông tin phương án trả góp"
                : "Tạo phương án thanh toán theo đợt mới"}
            </DialogDescription>
          </DialogHeader>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              {/* Code + Name */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="code"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Mã phương án</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="VD: MONTHLY_3"
                          disabled={isEditMode}
                          autoComplete="off"
                          {...field}
                          onChange={(e) => field.onChange(e.target.value.toUpperCase())}
                        />
                      </FormControl>
                      <FormDescription>Chỉ chữ in hoa, số, gạch dưới</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tên phương án</FormLabel>
                      <FormControl>
                        <Input placeholder="VD: Trả góp 3 tháng" autoComplete="off" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Description */}
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mô tả</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="Mô tả chi tiết phương án (tùy chọn)"
                        className="resize-none"
                        rows={2}
                        {...field}
                        value={field.value || ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Installment Count */}
              <FormField
                control={form.control}
                name="installment_count"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số đợt thanh toán</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        max={12}
                        {...field}
                        onChange={(e) => field.onChange(parseInt(e.target.value) || 1)}
                      />
                    </FormControl>
                    <FormDescription>Từ 1 đến 12 đợt</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Schedule Editor */}
              <ScheduleEditor form={form} installmentCount={watchInstallmentCount} />

              {/* Penalty Configuration */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <FormField
                  control={form.control}
                  name="penalty_type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Loại phạt</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn loại" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="percentage">Phần trăm (%)</SelectItem>
                          <SelectItem value="fixed">Cố định (VND)</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="penalty_rate"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Mức phạt</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={0}
                          step={0.01}
                          {...field}
                          onChange={(e) => field.onChange(parseFloat(e.target.value) || 0)}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="grace_period_days"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Ngày ân hạn</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={0}
                          max={365}
                          {...field}
                          onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
                        />
                      </FormControl>
                      <FormDescription>Số ngày trước khi tính phạt</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Active Switch */}
              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex items-center justify-between rounded-lg border p-3">
                    <div className="space-y-0.5">
                      <FormLabel>Trạng thái hoạt động</FormLabel>
                      <FormDescription>
                        Phương án có hiển thị khi tạo phí không
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />

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
                  {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                  {isEditMode ? "Cập nhật" : "Tạo mới"}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa phương án trả góp</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa phương án &quot;{planToDelete?.name}&quot;?
              Phương án sẽ được đánh dấu là không hoạt động (soft delete).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              )}
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
