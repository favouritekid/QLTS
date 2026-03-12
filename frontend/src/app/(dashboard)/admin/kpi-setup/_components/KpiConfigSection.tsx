"use client";

import { useMemo, useState } from "react";
import { Building2, Globe, Pencil, Plus, Trash2, User } from "lucide-react";

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
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import {
  useKpiConfigs,
  useCreateKpiConfig,
  useUpdateKpiConfig,
  useDeleteKpiConfig,
} from "@/hooks/useKpiSetup";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import type { KpiConfigItem } from "@/types/kpi-setup.types";
import { KPI_CODES, PERIOD_TYPES } from "@/types/kpi-setup.types";
import type { OrganizationUnit } from "@/types/organization.types";

interface Props {
  fiscalYear: number;
  isAdmin?: boolean;
}

function flattenUnits(nodes: OrganizationUnit[] = []): OrganizationUnit[] {
  let flat: OrganizationUnit[] = [];
  nodes.forEach((node) => {
    flat.push(node);
    if (node.children) {
      flat = [...flat, ...flattenUnits(node.children)];
    }
  });
  return flat;
}

function ScopeIcon({ item }: { item: KpiConfigItem }) {
  if (item.officer_id) return <User aria-hidden="true" className="h-3.5 w-3.5" />;
  if (item.unit_id) return <Building2 aria-hidden="true" className="h-3.5 w-3.5" />;
  return <Globe aria-hidden="true" className="h-3.5 w-3.5" />;
}

export function KpiConfigSection({ fiscalYear: _fiscalYear, isAdmin = true }: Props) {
  void _fiscalYear; // reserved for future temporal filtering
  const { data: configs = [], isLoading } = useKpiConfigs();
  const createMut = useCreateKpiConfig();
  const updateMut = useUpdateKpiConfig();
  const deleteMut = useDeleteKpiConfig();

  const { data: unitsTree } = useOrganizationUnits();
  const units = useMemo(() => flattenUnits(unitsTree || []), [unitsTree]);

  // Broad list for table display — resolve officer names
  const { data: allOfficersPage } = useAdminUsersList({
    role: "officer",
    status: "active",
    page_size: 500,
  });
  const allOfficers = allOfficersPage?.users || [];

  // Dialog state
  const [showCreate, setShowCreate] = useState(false);
  const [editingConfig, setEditingConfig] = useState<KpiConfigItem | null>(null);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  // Create form state
  const [kpiCode, setKpiCode] = useState("");
  const [periodType, setPeriodType] = useState("daily");
  const [targetValue, setTargetValue] = useState(10);
  const [scope, setScope] = useState<"global" | "unit" | "officer">("global");
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [selectedOfficerId, setSelectedOfficerId] = useState<number | null>(null);

  // Edit form state
  const [editTargetValue, setEditTargetValue] = useState(0);
  const [editIsActive, setEditIsActive] = useState(true);

  // Filtered officer list for create form (by selected unit)
  const { data: filteredOfficersPage } = useAdminUsersList(
    selectedUnitId
      ? { unit_id: selectedUnitId, role: "officer", status: "active", page_size: 200 }
      : { role: "officer", status: "active", page_size: 200 },
  );
  const filteredOfficers = filteredOfficersPage?.users || [];

  function resetCreateForm() {
    setKpiCode("");
    setPeriodType("daily");
    setTargetValue(10);
    setScope("global");
    setSelectedUnitId(null);
    setSelectedOfficerId(null);
  }

  function openCreate() {
    resetCreateForm();
    setShowCreate(true);
  }

  function openEdit(config: KpiConfigItem) {
    setEditingConfig(config);
    setEditTargetValue(config.target_value);
    setEditIsActive(config.is_active);
  }

  const isScopeValid =
    scope === "global" ||
    (scope === "unit" && selectedUnitId != null) ||
    (scope === "officer" && selectedUnitId != null && selectedOfficerId != null);

  function handleCreate() {
    if (!isScopeValid) return;
    createMut.mutate(
      {
        kpi_code: kpiCode,
        target_value: targetValue,
        period_type: periodType,
        unit_id: scope === "unit" || scope === "officer" ? selectedUnitId : null,
        officer_id: scope === "officer" ? selectedOfficerId : null,
      },
      {
        onSuccess: () => {
          setShowCreate(false);
          resetCreateForm();
        },
      },
    );
  }

  function handleUpdate() {
    if (!editingConfig) return;
    updateMut.mutate(
      { id: editingConfig.id, data: { target_value: editTargetValue, is_active: editIsActive } },
      { onSuccess: () => setEditingConfig(null) },
    );
  }

  function handleDelete() {
    if (deleteId == null) return;
    deleteMut.mutate(deleteId, { onSuccess: () => setDeleteId(null) });
  }

  function getScopeLabel(item: KpiConfigItem): string {
    if (item.officer_id) {
      const officer = allOfficers.find((o) => o.id === item.officer_id);
      return officer?.full_name || `Cán bộ #${item.officer_id}`;
    }
    if (item.unit_id) {
      const unit = units.find((u) => u.id === item.unit_id);
      return unit ? unit.name : `Đơn vị #${item.unit_id}`;
    }
    return "Toàn trường";
  }

  function getKpiLabel(code: string): string {
    return KPI_CODES.find((k) => k.value === code)?.label ?? code;
  }

  function getPeriodLabel(type: string): string {
    return PERIOD_TYPES.find((p) => p.value === type)?.label ?? type;
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <CardTitle className="text-base">Cấu hình KPI</CardTitle>
          {isAdmin && (
            <Button type="button" size="sm" onClick={openCreate}>
              <Plus aria-hidden="true" className="h-4 w-4" />
              Thêm mới
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Đang tải…</p>
          ) : configs.length === 0 ? (
            <p className="text-sm text-muted-foreground">Chưa có cấu hình KPI nào.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>KPI</TableHead>
                  <TableHead>Chu kỳ</TableHead>
                  <TableHead>Phạm vi</TableHead>
                  <TableHead className="text-right">Giá trị</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  {isAdmin && <TableHead className="text-right">Thao tác</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {configs.map((config) => (
                  <TableRow key={config.id}>
                    <TableCell className="font-medium">{getKpiLabel(config.kpi_code)}</TableCell>
                    <TableCell>{getPeriodLabel(config.period_type)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <ScopeIcon item={config} />
                        <span className="text-sm">{getScopeLabel(config)}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{config.target_value}</TableCell>
                    <TableCell>
                      <Badge variant={config.is_active ? "default" : "secondary"} className="text-xs">
                        {config.is_active ? "Hoạt động" : "Tắt"}
                      </Badge>
                    </TableCell>
                    {isAdmin && (
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button type="button" variant="ghost" size="sm" onClick={() => openEdit(config)}>
                            <Pencil aria-hidden="true" className="h-4 w-4" />
                            Sửa
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:text-destructive"
                            onClick={() => setDeleteId(config.id)}
                          >
                            <Trash2 aria-hidden="true" className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={(open) => !open && setShowCreate(false)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Thêm cấu hình KPI</DialogTitle>
            <DialogDescription>Tạo quy tắc KPI mới cho toàn trường, đơn vị hoặc cán bộ.</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Mã KPI</Label>
              <Select value={kpiCode} onValueChange={setKpiCode}>
                <SelectTrigger><SelectValue placeholder="Chọn KPI" /></SelectTrigger>
                <SelectContent>
                  {KPI_CODES.map((k) => (
                    <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Chu kỳ</Label>
              <Select value={periodType} onValueChange={setPeriodType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PERIOD_TYPES.map((p) => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Phạm vi</Label>
              <Select
                value={scope}
                onValueChange={(v: "global" | "unit" | "officer") => {
                  setScope(v);
                  if (v === "global") { setSelectedUnitId(null); setSelectedOfficerId(null); }
                  if (v === "unit") { setSelectedOfficerId(null); }
                }}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Toàn trường</SelectItem>
                  <SelectItem value="unit">Đơn vị</SelectItem>
                  <SelectItem value="officer">Cán bộ</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {(scope === "unit" || scope === "officer") && (
              <div className="space-y-2">
                <Label>Đơn vị</Label>
                <Select
                  value={selectedUnitId != null ? String(selectedUnitId) : ""}
                  onValueChange={(v) => {
                    setSelectedUnitId(Number(v));
                    setSelectedOfficerId(null);
                  }}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn đơn vị" /></SelectTrigger>
                  <SelectContent>
                    {units.map((u) => (
                      <SelectItem key={u.id} value={String(u.id)}>{u.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {scope === "officer" && (
              <div className="space-y-2">
                <Label>Cán bộ</Label>
                <Select
                  value={selectedOfficerId != null ? String(selectedOfficerId) : ""}
                  onValueChange={(v) => setSelectedOfficerId(Number(v))}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn cán bộ" /></SelectTrigger>
                  <SelectContent>
                    {filteredOfficers.map((o) => (
                      <SelectItem key={o.id} value={String(o.id)}>{o.full_name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="config-target-value">Giá trị mục tiêu</Label>
              <Input
                id="config-target-value"
                type="number"
                min={0}
                step={0.1}
                value={targetValue || ""}
                onChange={(e) => setTargetValue(Number(e.target.value))}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>Hủy</Button>
            <Button
              type="button"
              onClick={handleCreate}
              disabled={createMut.isPending || !kpiCode || targetValue <= 0 || !isScopeValid}
            >
              {createMut.isPending ? "Đang lưu…" : "Tạo"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={editingConfig != null} onOpenChange={(open) => !open && setEditingConfig(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sửa cấu hình KPI</DialogTitle>
            <DialogDescription>
              {editingConfig ? getKpiLabel(editingConfig.kpi_code) : ""}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="edit-target-value">Giá trị mục tiêu</Label>
              <Input
                id="edit-target-value"
                type="number"
                min={0}
                step={0.1}
                value={editTargetValue || ""}
                onChange={(e) => setEditTargetValue(Number(e.target.value))}
              />
            </div>
            <div className="flex items-center gap-3">
              <Switch
                id="edit-is-active"
                checked={editIsActive}
                onCheckedChange={setEditIsActive}
              />
              <Label htmlFor="edit-is-active">Hoạt động</Label>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditingConfig(null)}>Hủy</Button>
            <Button
              type="button"
              onClick={handleUpdate}
              disabled={updateMut.isPending || editTargetValue <= 0}
            >
              {updateMut.isPending ? "Đang lưu…" : "Cập nhật"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <AlertDialog open={deleteId != null} onOpenChange={(open) => !open && setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa cấu hình KPI?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này không thể hoàn tác. Cấu hình sẽ bị xóa vĩnh viễn.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMut.isPending ? "Đang xóa…" : "Xóa"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
