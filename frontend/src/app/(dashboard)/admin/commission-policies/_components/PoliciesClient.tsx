"use client"

import { useState, useCallback, useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Plus, Edit } from "lucide-react"
import { todayVN } from "@/lib/utils/vn-date"
import { PageContainer } from "@/components/layouts/PageContainer"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  useCommissionPolicies,
  useCreateCommissionPolicy,
  useUpdateCommissionPolicy,
} from "@/hooks/useCommissions"
import { commissionPolicyCreateSchema, type CommissionPolicyCreateFormData } from "@/lib/zod/commission"
import type { CommissionPolicy } from "@/types/commission.types"

// =============================================================================
// CONSTANTS
// =============================================================================

const PAGE_SIZE = 10

function formatCurrency(amount: number | null): string {
  if (amount == null) return "-"
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(amount)
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function PoliciesClient() {
  const [page, setPage] = useState(1)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<CommissionPolicy | null>(null)

  const { data, isLoading, isError, error } = useCommissionPolicies({
    skip: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  })

  const totalPages = data ? Math.ceil(data.total_count / PAGE_SIZE) : 0

  const handleCreate = useCallback(() => {
    setEditTarget(null)
    setDialogOpen(true)
  }, [])

  const handleEdit = useCallback((policy: CommissionPolicy) => {
    setEditTarget(policy)
    setDialogOpen(true)
  }, [])

  if (isError) {
    return (
      <PageContainer maxWidth="xl">
        <h1 className="text-2xl font-bold tracking-tight">Chính sách Hoa hồng</h1>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi tải dữ liệu: {error?.message}</p>
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer maxWidth="xl">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Chính sách Hoa hồng</h1>
          <p className="text-muted-foreground">Quản lý các chính sách tính hoa hồng cho CTV.</p>
        </div>
        <Button size="sm" onClick={handleCreate}>
          <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
          Thêm chính sách
        </Button>
      </header>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[900px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Tên</TableHead>
                    <TableHead>Trigger Status</TableHead>
                    <TableHead>Loại tính</TableHead>
                    <TableHead className="text-right">Giá trị</TableHead>
                    <TableHead>Đơn vị</TableHead>
                    <TableHead>Hiệu lực</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead>Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.policies?.length ? (
                    data.policies.map((policy) => (
                      <TableRow key={policy.id}>
                        <TableCell>
                          <p className="font-medium text-sm">{policy.name}</p>
                          {policy.description && (
                            <p className="text-muted-foreground text-xs truncate max-w-[200px]">{policy.description}</p>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="font-mono text-xs">
                            {policy.trigger_status_id}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">
                            {policy.calculation_type === "fixed" ? "Cố định" : "Phần trăm"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          {policy.calculation_type === "fixed"
                            ? formatCurrency(policy.fixed_amount)
                            : `${policy.percentage}%`}
                        </TableCell>
                        <TableCell className="text-sm">
                          {policy.unit?.name ?? "Toàn hệ thống"}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {policy.effective_from}
                          {policy.effective_to ? ` - ${policy.effective_to}` : " - Vô hạn"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={policy.is_active ? "default" : "outline"}>
                            {policy.is_active ? "Hoạt động" : "Tắt"}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon" onClick={() => handleEdit(policy)} aria-label="Sửa">
                            <Edit className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                        Chưa có chính sách nào. Thêm chính sách mới để bắt đầu.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {data && data.total_count > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-sm">
            Hiển thị {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, data.total_count)} / {data.total_count}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
              Trước
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
              Sau
            </Button>
          </div>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <PolicyDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        policy={editTarget}
      />
    </PageContainer>
  )
}

// =============================================================================
// POLICY DIALOG
// =============================================================================

interface PolicyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  policy: CommissionPolicy | null
}

function PolicyDialog({ open, onOpenChange, policy }: PolicyDialogProps) {
  const isEdit = !!policy
  const createMutation = useCreateCommissionPolicy()
  const updateMutation = useUpdateCommissionPolicy()

  const form = useForm({
    resolver: zodResolver(commissionPolicyCreateSchema),
    defaultValues: {
      name: "",
      description: "",
      trigger_status_id: "",
      calculation_type: "fixed",
      fixed_amount: undefined,
      percentage: undefined,
      unit_id: undefined,
      offering_id: undefined,
      effective_from: todayVN(),
      effective_to: "",
      is_active: true,
    },
  })

  const calcType = form.watch("calculation_type")

  // C13: Clear opposing field when switching calculation_type
  useEffect(() => {
    if (calcType === "fixed") {
      form.setValue("percentage", undefined)
    } else if (calcType === "percentage") {
      form.setValue("fixed_amount", undefined)
    }
  }, [calcType, form])

  // Reset/pre-fill form when dialog opens or policy changes
  useEffect(() => {
    if (open && policy) {
      form.reset({
        name: policy.name,
        description: policy.description ?? "",
        trigger_status_id: policy.trigger_status_id,
        calculation_type: policy.calculation_type as "fixed" | "percentage",
        fixed_amount: policy.fixed_amount ?? undefined,
        percentage: policy.percentage ?? undefined,
        unit_id: policy.unit_id ?? undefined,
        offering_id: policy.offering_id ?? undefined,
        effective_from: policy.effective_from,
        effective_to: policy.effective_to ?? "",
        is_active: policy.is_active,
      })
    } else if (open) {
      form.reset({
        name: "",
        description: "",
        trigger_status_id: "",
        calculation_type: "fixed",
        fixed_amount: undefined,
        percentage: undefined,
        effective_from: todayVN(),
        effective_to: "",
        is_active: true,
      })
    }
  }, [open, policy, form])

  async function onSubmit(data: CommissionPolicyCreateFormData) {
    try {
      if (isEdit && policy) {
        await updateMutation.mutateAsync({ id: policy.id, data })
      } else {
        await createMutation.mutateAsync(data)
      }
      onOpenChange(false)
    } catch {
      // Errors handled by mutation hook
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Sửa chính sách" : "Thêm chính sách mới"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Cập nhật thông tin chính sách hoa hồng." : "Tạo chính sách hoa hồng mới cho CTV."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tên chính sách <span className="text-destructive">*</span></FormLabel>
                  <FormControl>
                    <Input placeholder="VD: Hoa hồng tuyển sinh K50" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mô tả</FormLabel>
                  <FormControl>
                    <Textarea placeholder="Mô tả chính sách..." rows={2} {...field} value={field.value ?? ""} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="trigger_status_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Trigger Status ID <span className="text-destructive">*</span></FormLabel>
                  <FormControl>
                    <Input placeholder="VD: sts11" className="font-mono" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="calculation_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Loại tính <span className="text-destructive">*</span></FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="fixed">Cố định (VND)</SelectItem>
                      <SelectItem value="percentage">Phần trăm (%)</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {calcType === "fixed" && (
              <FormField
                control={form.control}
                name="fixed_amount"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số tiền cố định (VND) <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="500000"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : undefined)}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {calcType === "percentage" && (
              <FormField
                control={form.control}
                name="percentage"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phần trăm (%) <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        step="0.01"
                        min="0"
                        max="100"
                        placeholder="5.00"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : undefined)}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="effective_from"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Ngày bắt đầu <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input type="date" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="effective_to"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Ngày kết thúc</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex items-center gap-2">
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <Label>Kích hoạt</Label>
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Đang lưu…" : isEdit ? "Cập nhật" : "Tạo"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
