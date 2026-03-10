"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, CalendarPlus, Plus, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import {
  useCreateHoliday,
  useDeleteHoliday,
  useHolidays,
  useHolidayStatus,
  useSeedHolidays,
  useUpdateHoliday,
} from "@/hooks/useKpiPlanning";
import type { Holiday } from "@/types/kpi-planning.types";

const currentYear = new Date().getFullYear();

export default function HolidayManagementPage() {
  const router = useRouter();
  const [yearFilter, setYearFilter] = useState(currentYear);
  const [showCreate, setShowCreate] = useState(false);
  const [editHoliday, setEditHoliday] = useState<Holiday | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Holiday | null>(null);
  const seedYear = currentYear + 1;

  // Form state
  const [formDate, setFormDate] = useState("");
  const [formName, setFormName] = useState("");
  const [formRecurring, setFormRecurring] = useState(false);

  // Queries
  const { data: statusCurrent } = useHolidayStatus(currentYear);
  const { data: statusNext } = useHolidayStatus(currentYear + 1);
  const { data: holidays, isLoading, isError, error: holidaysError } = useHolidays(yearFilter);

  // Mutations
  const createMut = useCreateHoliday();
  const updateMut = useUpdateHoliday();
  const deleteMut = useDeleteHoliday();
  const seedMut = useSeedHolidays();

  const openCreate = () => {
    setFormDate("");
    setFormName("");
    setFormRecurring(false);
    setShowCreate(true);
  };

  const openEdit = (h: Holiday) => {
    setFormDate(h.date);
    setFormName(h.name);
    setFormRecurring(h.is_recurring);
    setEditHoliday(h);
  };

  return (
    <PageContainer maxWidth="full">
      <div className="mb-4 flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/admin/kpi-planning")}
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          Quay lại
        </Button>
      </div>

      <PageHeader
        title="Quản lý ngày lễ"
        description="Cấu hình lịch ngày lễ để tính working days chính xác cho KPI Planning"
      />

      {/* Status Banners */}
      {statusCurrent && !statusCurrent.is_complete && (
        <Alert variant="destructive" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Năm {currentYear} chưa đầy đủ</AlertTitle>
          <AlertDescription>{statusCurrent.warning}</AlertDescription>
        </Alert>
      )}
      {statusNext && !statusNext.is_complete && (
        <Alert className="mb-4 border-yellow-500">
          <AlertTriangle className="h-4 w-4 text-yellow-600" />
          <AlertTitle>Năm {currentYear + 1} chưa cấu hình</AlertTitle>
          <AlertDescription>
            {statusNext.warning}
            <Button
              size="sm"
              variant="outline"
              className="ml-3"
              onClick={() => seedMut.mutate(currentYear + 1)}
              disabled={seedMut.isPending}
            >
              <CalendarPlus className="mr-1 h-3.5 w-3.5" />
              Seed ngày lễ {currentYear + 1}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          value={String(yearFilter)}
          onValueChange={(v) => setYearFilter(Number(v))}
        >
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[currentYear - 1, currentYear, currentYear + 1, currentYear + 2].map(
              (y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ),
            )}
          </SelectContent>
        </Select>

        <Button size="sm" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          Thêm ngày lễ
        </Button>

        <Button
          size="sm"
          variant="outline"
          onClick={() => seedMut.mutate(seedYear)}
          disabled={seedMut.isPending}
        >
          <CalendarPlus className="mr-1 h-3.5 w-3.5" />
          Seed recurring → {seedYear}
        </Button>
      </div>

      {/* Holiday List */}
      <Card>
        <CardHeader>
          <CardTitle>
            Danh sách ngày lễ — {yearFilter} ({holidays?.total ?? 0} ngày)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : isError ? (
            <p className="py-8 text-center text-destructive">
              {holidaysError?.response?.data?.detail || "Không thể tải danh sách ngày lễ"}
            </p>
          ) : !holidays?.items?.length ? (
            <p className="py-8 text-center text-muted-foreground">
              Chưa có ngày lễ cho năm {yearFilter}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ngày</TableHead>
                  <TableHead>Tên</TableHead>
                  <TableHead className="text-center">Recurring</TableHead>
                  <TableHead className="text-right">Hành động</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {holidays.items.map((h) => (
                  <TableRow key={h.id}>
                    <TableCell className="font-mono">{h.date}</TableCell>
                    <TableCell>{h.name}</TableCell>
                    <TableCell className="text-center">
                      {h.is_recurring ? (
                        <Badge>Hàng năm</Badge>
                      ) : (
                        <Badge variant="outline">Riêng năm</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => openEdit(h)}
                        >
                          Sửa
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive"
                          onClick={() => setDeleteTarget(h)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Thêm ngày lễ</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Ngày</label>
              <Input
                type="date"
                value={formDate}
                onChange={(e) => setFormDate(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Tên ngày lễ</label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="VD: Tết Nguyên Đán (Mùng 1)"
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={formRecurring}
                onCheckedChange={setFormRecurring}
              />
              <label className="text-sm">
                Lặp hàng năm (1/1, 30/4, 1/5, 2/9)
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={async () => {
                await createMut.mutateAsync({
                  date: formDate,
                  name: formName,
                  is_recurring: formRecurring,
                });
                setShowCreate(false);
              }}
              disabled={createMut.isPending || !formDate || !formName}
            >
              Thêm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={!!editHoliday} onOpenChange={() => setEditHoliday(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa ngày lễ</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Ngày</label>
              <Input
                type="date"
                value={formDate}
                onChange={(e) => setFormDate(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Tên ngày lễ</label>
              <Input
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={formRecurring}
                onCheckedChange={setFormRecurring}
              />
              <label className="text-sm">Lặp hàng năm</label>
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={async () => {
                if (!editHoliday) return;
                await updateMut.mutateAsync({
                  id: editHoliday.id,
                  data: {
                    date: formDate,
                    name: formName,
                    is_recurring: formRecurring,
                  },
                });
                setEditHoliday(null);
              }}
              disabled={updateMut.isPending}
            >
              Cập nhật
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa ngày lễ?</AlertDialogTitle>
            <AlertDialogDescription>
              Xóa &quot;{deleteTarget?.name}&quot; ({deleteTarget?.date})?
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground"
              onClick={async () => {
                if (deleteTarget) {
                  await deleteMut.mutateAsync(deleteTarget.id);
                  setDeleteTarget(null);
                }
              }}
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}


