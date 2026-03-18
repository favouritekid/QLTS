"use client";

/**
 * Admin KPI Configuration Page
 * Phase 5: Allows admins to configure KPI targets for officers and units.
 */

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Plus,
  Pencil,
  Trash2,
  Target,
  Building2,
  User,
  Globe,
  RefreshCw,
  RotateCcw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

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
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Info } from "lucide-react";

import { api } from "@/lib/api/client";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { OrganizationUnit } from "@/types/organization.types";
import { cn } from "@/lib/utils";
import { PageContainer } from "@/components/layouts/PageContainer";
import { TableEmptyState } from "@/components/common/EmptyState";
import { KpiWorkflowStepper } from "./_components/KpiWorkflowStepper";
import { KpiCatalogOverview } from "./_components/KpiCatalogOverview";
import { ConfigConflictWarnings } from "./_components/ConfigConflictWarnings";

// =============================================================================
// TYPES
// =============================================================================

interface KpiConfig {
  id: number;
  kpi_code: string;
  target_value: number;
  period_type: string;
  unit_id: number | null;
  officer_id: number | null;
  source_plan_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface KpiTarget {
  id: number;
  kpi_code: string;
  annual_target: number;
  fiscal_year: number;
  unit_id: number | null;
  officer_id: number | null;
  achieved_ytd: number;
  is_active: boolean;
  last_sync_at: string | null;
  created_at: string;
}

// =============================================================================
// KPI CODE OPTIONS
// =============================================================================

// KPI codes sourced from canonical catalog (single source of truth)
import { useKpiCatalog } from "@/lib/hooks/use-kpi-catalog";

const PERIOD_TYPES = [
  { value: "daily", label: "Hàng ngày" },
  { value: "monthly", label: "Hàng tháng" },
  { value: "annual", label: "Hàng năm" },
];

// =============================================================================
// API FUNCTIONS
// =============================================================================

async function fetchKpiConfigs(isActive: boolean = true): Promise<KpiConfig[]> {
  const res = await api.get(`/api/admin/kpi-config/configs?is_active=${isActive}`);
  return res.data;
}

async function fetchKpiTargets(isActive: boolean = true, fiscalYear?: number): Promise<KpiTarget[]> {
  let params = `?is_active=${isActive}`;
  if (fiscalYear) params += `&fiscal_year=${fiscalYear}`;
  const res = await api.get(`/api/admin/kpi-config/targets${params}`);
  return res.data;
}

async function createKpiConfig(data: Partial<KpiConfig>): Promise<KpiConfig> {
  const res = await api.post("/api/admin/kpi-config/configs", data);
  return res.data;
}

async function updateKpiConfig(
  id: number,
  data: Partial<KpiConfig>
): Promise<KpiConfig> {
  const res = await api.put(`/api/admin/kpi-config/configs/${id}`, data);
  return res.data;
}

async function deleteKpiConfig(id: number): Promise<void> {
  await api.delete(`/api/admin/kpi-config/configs/${id}`);
}

async function createKpiTarget(data: Partial<KpiTarget>): Promise<KpiTarget> {
  const res = await api.post("/api/admin/kpi-config/targets", data);
  return res.data;
}

async function updateKpiTarget(
  id: number,
  data: Partial<KpiTarget>
): Promise<KpiTarget> {
  const res = await api.put(`/api/admin/kpi-config/targets/${id}`, data);
  return res.data;
}

async function deleteKpiTarget(id: number): Promise<void> {
  await api.delete(`/api/admin/kpi-config/targets/${id}`);
}

interface SyncYTDResponse {
  target_id: number;
  officer_id: number;
  kpi_code: string;
  fiscal_year: number;
  achieved_ytd: number;
  message: string;
}

async function syncKpiTarget(id: number): Promise<SyncYTDResponse> {
  const res = await api.post(`/api/admin/kpi-config/targets/${id}/sync`);
  return res.data;
}

// =============================================================================
// COMPONENT
// =============================================================================

export default function KpiConfigPage() {
  const queryClient = useQueryClient();
  const { getKpiOptions, catalogMap, catalog } = useKpiCatalog();
  const KPI_CODES = getKpiOptions();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isTargetDialogOpen, setIsTargetDialogOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<KpiConfig | null>(null);
  const [editingTarget, setEditingTarget] = useState<KpiTarget | null>(null);
  const [deleteConfigId, setDeleteConfigId] = useState<number | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [showInactiveTargets, setShowInactiveTargets] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    kpi_code: "",
    target_value: 10,
    period_type: "daily",
    unit_id: null as number | null,
    officer_id: null as number | null,
    scope: "global", // 'global' | 'unit' | 'officer'
  });

  const [targetFormData, setTargetFormData] = useState({
    kpi_code: "enrollments_annual",
    annual_target: 100,
    fiscal_year: new Date().getFullYear(),
    unit_id: null as number | null,
    officer_id: null as number | null,
    scope: "global",
  });

  // Fetch Data for Selectors
  const { data: usersPage } = useAdminUsersList({ page_size: 100 });
  const officers = usersPage?.users || [];

  const { data: unitsTree } = useOrganizationUnits();
  
  // Flatten units tree for dropdown
  const flattenUnits = (nodes: OrganizationUnit[] = []): OrganizationUnit[] => {
    let flat: OrganizationUnit[] = [];
    nodes.forEach((node) => {
      flat.push(node);
      if (node.children) {
        flat = [...flat, ...flattenUnits(node.children)];
      }
    });
    return flat;
  };
  const units = flattenUnits(unitsTree || []);

  // Queries
  const { data: configs, isLoading: loadingConfigs } = useQuery({
    queryKey: ["kpi-configs", showInactive],
    queryFn: () => fetchKpiConfigs(!showInactive),
  });

  // P6: Check if any configs come from KPI Planning
  const hasPlanningConfigs = useMemo(
    () => configs?.some((c) => c.source_plan_id != null) ?? false,
    [configs],
  );

  const { data: targets, isLoading: loadingTargets } = useQuery({
    queryKey: ["kpi-targets", showInactiveTargets],
    queryFn: () => fetchKpiTargets(!showInactiveTargets),
  });

  // Mutations
  const createMutation = useMutation({
    mutationFn: createKpiConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-configs"] });
      toast.success("Đã tạo cấu hình KPI thành công");
      setIsDialogOpen(false);
      resetForm();
    },
    onError: (err: Error) => {
      toast.error(err.message || "Tạo cấu hình thất bại");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<KpiConfig> }) =>
      updateKpiConfig(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-configs"] });
      toast.success("Đã cập nhật KPI");
      setIsDialogOpen(false);
      setEditingConfig(null);
      resetForm();
    },
    onError: (err: Error) => {
      toast.error(err.message || "Cập nhật thất bại");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteKpiConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-configs"] });
      toast.success("Đã vô hiệu hóa cấu hình KPI");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Xóa cấu hình thất bại");
    },
  });

  const createTargetMutation = useMutation({
    mutationFn: createKpiTarget,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-targets"] });
      toast.success("Đã tạo mục tiêu năm");
      setIsTargetDialogOpen(false);
      // Reset form after success
      setTargetFormData({
        kpi_code: "enrollments_annual",
        annual_target: 100,
        fiscal_year: new Date().getFullYear(),
        unit_id: null,
        officer_id: null,
        scope: "global",
      });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Tạo mục tiêu thất bại");
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (id: number) => updateKpiConfig(id, { is_active: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-configs"] });
      toast.success("Đã khôi phục cấu hình KPI");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Khôi phục thất bại");
    },
  });

  const updateTargetMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<KpiTarget> }) =>
      updateKpiTarget(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-targets"] });
      toast.success("Đã cập nhật mục tiêu năm");
      setIsTargetDialogOpen(false);
      setEditingTarget(null);
    },
    onError: (err: Error) => {
      toast.error(err.message || "Cập nhật thất bại");
    },
  });

  const deleteTargetMutation = useMutation({
    mutationFn: deleteKpiTarget,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-targets"] });
      toast.success("Đã vô hiệu hóa mục tiêu năm");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Xóa mục tiêu thất bại");
    },
  });

  const restoreTargetMutation = useMutation({
    mutationFn: (id: number) => updateKpiTarget(id, { is_active: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kpi-targets"] });
      toast.success("Đã khôi phục mục tiêu năm");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Khôi phục thất bại");
    },
  });

  const syncTargetMutation = useMutation({
    mutationFn: syncKpiTarget,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["kpi-targets"] });
      toast.success(data.message);
    },
    onError: (err: Error) => {
      toast.error(err.message || "Đồng bộ thất bại");
    },
  });

  // Helpers
  function resetForm() {
    setFormData({
      kpi_code: "",
      target_value: 10,
      period_type: "daily",
      unit_id: null,
      officer_id: null,
      scope: "global",
    });
    // Also reset target form defaults if needed, though usually on open
    setTargetFormData({
      kpi_code: "enrollments_annual",
      annual_target: 100,
      fiscal_year: new Date().getFullYear(),
      unit_id: null,
      officer_id: null,
      scope: "global",
    });
  }

  function handleEdit(config: KpiConfig) {
    setEditingConfig(config);
    let scope = "global";
    if (config.officer_id) scope = "officer";
    else if (config.unit_id) scope = "unit";

    setFormData({
      kpi_code: config.kpi_code,
      target_value: config.target_value,
      period_type: config.period_type,
      unit_id: config.unit_id,
      officer_id: config.officer_id,
      scope,
    });
    setIsDialogOpen(true);
  }

  function handleSubmit() {
    if (editingConfig) {
      updateMutation.mutate({
        id: editingConfig.id,
        data: { target_value: formData.target_value },
      });
    } else {
      createMutation.mutate(formData);
    }
  }

  function handleEditTarget(target: KpiTarget) {
    setEditingTarget(target);
    let scope = "global";
    if (target.officer_id) scope = "officer";
    else if (target.unit_id) scope = "unit";

    setTargetFormData({
      kpi_code: target.kpi_code,
      annual_target: target.annual_target,
      fiscal_year: target.fiscal_year,
      unit_id: target.unit_id,
      officer_id: target.officer_id,
      scope,
    });
    setIsTargetDialogOpen(true);
  }

  function handleTargetSubmit() {
    if (editingTarget) {
      updateTargetMutation.mutate({
        id: editingTarget.id,
        data: { annual_target: targetFormData.annual_target },
      });
    } else {
      createTargetMutation.mutate(targetFormData);
    }
  }

  function getScopeIcon(item: { officer_id: number | null; unit_id: number | null }) {
    if (item.officer_id) return <User className="h-4 w-4" />;
    if (item.unit_id) return <Building2 className="h-4 w-4" />;
    return <Globe className="h-4 w-4" />;
  }

  function getScopeLabel(item: { officer_id: number | null; unit_id: number | null }) {
    if (item.officer_id) {
      const officer = officers.find((o) => o.id === item.officer_id);
      return officer ? `Cán bộ: ${officer.full_name || officer.email}` : `Cán bộ #${item.officer_id}`;
    }
    if (item.unit_id) {
      const unit = units.find((u) => u.id === item.unit_id);
      return unit ? `Đơn vị: ${unit.name}` : `Đơn vị #${item.unit_id}`;
    }
    return "Toàn cục";
  }

  return (
    <PageContainer maxWidth="full">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
            <h1 className="text-2xl font-bold font-display flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            Cấu hình KPI
          </h1>
          <p className="text-muted-foreground mt-1">
            Cấu hình mục tiêu hàng ngày/tháng và mục tiêu năm cho cán bộ
          </p>
        </div>
      </div>

      <KpiWorkflowStepper />

      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Nguyên tắc Thừa kế chỉ tiêu</AlertTitle>
        <AlertDescription>
          Hệ thống sẽ áp dụng chỉ tiêu theo thứ tự ưu tiên: 
          <strong> Cán bộ (Cá nhân)</strong> &gt; 
          <strong> Đơn vị (Team)</strong> &gt; 
          <strong> Toàn cục (Global)</strong>. 
          <br/>
          Ví dụ: Nếu Cán bộ A có chỉ tiêu riêng, hệ thống sẽ dùng chỉ tiêu đó. Nếu không, sẽ tìm chỉ tiêu của Đơn vị mà cán bộ thuộc về. Nếu vẫn không có, sẽ dùng chỉ tiêu Toàn cục.
        </AlertDescription>
      </Alert>

      {hasPlanningConfigs && (
        <Alert className="border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/20">
          <Info className="h-4 w-4" />
          <AlertTitle>KPI Planning đang quản lý một số mục tiêu</AlertTitle>
          <AlertDescription>
            Các mục tiêu có nhãn &quot;Planning&quot; được quản lý tự động qua module KPI Planning
            và không thể chỉnh sửa ở đây.{" "}
            <Link href="/admin/kpi-planning" className="font-medium underline hover:text-amber-900 dark:hover:text-amber-200">
              Quản lý tại KPI Planning →
            </Link>
          </AlertDescription>
        </Alert>
      )}

      <KpiCatalogOverview catalog={catalog} catalogMap={catalogMap} />

      {/* Daily/Monthly Configs */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle>Mục tiêu Ngày/Tháng</CardTitle>
              <CardDescription>
                Cấu hình mục tiêu KPI định kỳ (kế thừa: Cán bộ → Đơn vị → Toàn cục)
              </CardDescription>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center space-x-2">
                <Switch
                  id="show-inactive"
                  checked={showInactive}
                  onCheckedChange={setShowInactive}
                />
                <Label htmlFor="show-inactive">Hiển thị đã xóa</Label>
              </div>
              <Button onClick={() => { resetForm(); setIsDialogOpen(true); }}>
                <Plus className="mr-2 h-4 w-4" />
                Thêm Cấu hình
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingConfigs ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mã KPI</TableHead>
                  <TableHead>Mục tiêu</TableHead>
                  <TableHead>Chu kỳ</TableHead>
                  <TableHead>Phạm vi</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead className="text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {configs?.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-32">
                      <TableEmptyState
                        title="Chưa có cấu hình KPI"
                        description="Hãy thêm cấu hình KPI đầu tiên để theo dõi hiệu suất"
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  configs?.map((config) => (
                    <TableRow key={config.id}>
                      <TableCell className="font-medium">
                        {KPI_CODES.find((k) => k.value === config.kpi_code)?.label ||
                          config.kpi_code}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums">
                        {config.target_value}
                      </TableCell>
                      <TableCell className="capitalize">{config.period_type}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {getScopeIcon(config)}
                          <span className="text-sm">{getScopeLabel(config)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={config.is_active ? "default" : "secondary"}>
                          {config.is_active ? "Hoạt động" : "Ngừng"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {config.source_plan_id != null ? (
                          <Badge variant="outline" className="border-amber-300 text-amber-700 dark:text-amber-400">
                            Planning
                          </Badge>
                        ) : showInactive ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => restoreMutation.mutate(config.id)}
                            aria-label="Khôi phục"
                          >
                            <RefreshCw className="h-4 w-4 text-success-600" />
                          </Button>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleEdit(config)}
                              aria-label="Chỉnh sửa"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setDeleteConfigId(config.id)}
                              aria-label="Xóa"
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Annual Targets */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <div>
              <CardTitle>Mục tiêu Năm</CardTitle>
              <CardDescription>
                Các mục tiêu hàng năm với theo dõi tiến độ YTD (đồng bộ hàng ngày lúc 1:00 AM)
              </CardDescription>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center space-x-2">
                <Switch
                  id="show-inactive-targets"
                  checked={showInactiveTargets}
                  onCheckedChange={setShowInactiveTargets}
                />
                <Label htmlFor="show-inactive-targets">Hiển thị đã xóa</Label>
              </div>
              <Button variant="outline" onClick={() => { setEditingTarget(null); setTargetFormData({ kpi_code: 'enrollments_annual', annual_target: 100, fiscal_year: new Date().getFullYear(), unit_id: null, officer_id: null, scope: 'global' }); setIsTargetDialogOpen(true); }}>
                <Target className="mr-2 h-4 w-4" />
                Thêm Mục tiêu Năm
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingTargets ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mã KPI</TableHead>
                  <TableHead>Năm</TableHead>
                  <TableHead>Phạm vi</TableHead>
                  <TableHead>Mục tiêu Năm</TableHead>
                  <TableHead>Đạt được (YTD)</TableHead>
                  <TableHead>Tiến độ</TableHead>
                  <TableHead>Đồng bộ cuối</TableHead>
                  <TableHead className="text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets?.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="h-32">
                      <TableEmptyState
                        title="Chưa có mục tiêu năm"
                        description="Hãy thêm mục tiêu để theo dõi tiến độ YTD"
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  targets?.map((target) => {
                    const progress =
                      target.annual_target > 0
                        ? Math.round((target.achieved_ytd / target.annual_target) * 100)
                        : 0;
                    return (
                      <TableRow key={target.id}>
                        <TableCell className="font-medium">
                          {KPI_CODES.find((k) => k.value === target.kpi_code)?.label ||
                            target.kpi_code}
                        </TableCell>
                        <TableCell>{target.fiscal_year}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {getScopeIcon(target)}
                            <span className="text-sm">{getScopeLabel(target)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">
                          {target.annual_target.toLocaleString()}
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">
                          {target.achieved_ytd.toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="flex-1 bg-muted rounded-full h-2 max-w-24">
                              <div
                                className="bg-primary h-2 rounded-full transition-[width]"
                                style={{ width: `${Math.min(progress, 100)}%` }}
                              />
                            </div>
                            <span className="text-sm font-medium tabular-nums">{progress}%</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {target.last_sync_at
                            ? new Date(target.last_sync_at).toLocaleDateString("vi-VN")
                            : "Chưa bao giờ"}
                        </TableCell>
                        <TableCell className="text-right">
                          {showInactiveTargets ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => restoreTargetMutation.mutate(target.id)}
                              disabled={restoreTargetMutation.isPending}
                            >
                              <RotateCcw className="mr-1 h-4 w-4" />
                              Khôi phục
                            </Button>
                          ) : (
                            <>
                              {/* Sync button only for officer-level targets */}
                              {target.officer_id && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => syncTargetMutation.mutate(target.id)}
                                  disabled={syncTargetMutation.isPending}
                                  aria-label="Đồng bộ YTD"
                                >
                                  <RefreshCw className={cn("h-4 w-4", syncTargetMutation.isPending && "animate-spin")} />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleEditTarget(target)}
                                aria-label="Chỉnh sửa"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setDeleteTargetId(target.id)}
                                aria-label="Xóa"
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <AlertDialog open={!!deleteConfigId} onOpenChange={(open) => !open && setDeleteConfigId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Vô hiệu hóa cấu hình này?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này sẽ vô hiệu hóa cấu hình KPI. Bạn có thể kích hoạt lại sau nếu cần.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteConfigId) deleteMutation.mutate(deleteConfigId);
                setDeleteConfigId(null);
              }}
            >
              Vô hiệu hóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Target Delete AlertDialog */}
      <AlertDialog open={!!deleteTargetId} onOpenChange={(open) => !open && setDeleteTargetId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Vô hiệu hóa mục tiêu này?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này sẽ vô hiệu hóa mục tiêu năm. Bạn có thể kích hoạt lại sau nếu cần.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteTargetId) deleteTargetMutation.mutate(deleteTargetId);
                setDeleteTargetId(null);
              }}
            >
              Vô hiệu hóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Config Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={(open) => {
        setIsDialogOpen(open);
        if (!open) {
          setEditingConfig(null);
          resetForm();
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingConfig ? "Sửa Cấu hình KPI" : "Tạo Cấu hình KPI"}
            </DialogTitle>
            <DialogDescription>
              Cấu hình giá trị mục tiêu cho các KPI cụ thể
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label>Mã KPI</Label>
              <Select
                value={formData.kpi_code}
                onValueChange={(v) => {
                  const entry = catalogMap.get(v);
                  setFormData({
                    ...formData,
                    kpi_code: v,
                    ...(entry ? { period_type: entry.period_type } : {}),
                  });
                }}
                disabled={!!editingConfig}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Chọn KPI..." />
                </SelectTrigger>
                <SelectContent>
                  {KPI_CODES.map((k) => (
                    <SelectItem key={k.value} value={k.value}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Giá trị Mục tiêu</Label>
              <Input
                type="number"
                value={formData.target_value}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    target_value: parseFloat(e.target.value) || 0,
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Loại Chu kỳ</Label>
              <Select
                value={formData.period_type}
                onValueChange={(v) =>
                  setFormData({ ...formData, period_type: v })
                }
                disabled={!!editingConfig || !!catalogMap.get(formData.kpi_code)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERIOD_TYPES.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Scope Selection for Config */}
            <div className="space-y-2">
              <Label>Phạm vi áp dụng</Label>
              <Select
                value={formData.scope}
                onValueChange={(v) => {
                  setFormData({
                    ...formData,
                    scope: v,
                    unit_id: null,
                    officer_id: null,
                  });
                }}
                disabled={!!editingConfig}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Toàn cục (Mặc định)</SelectItem>
                  <SelectItem value="unit">Đơn vị (Team)</SelectItem>
                  <SelectItem value="officer">Cán bộ (Cá nhân)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground">
                Ưu tiên: Cán bộ &gt; Đơn vị &gt; Toàn cục
              </p>
            </div>

            {formData.scope === "unit" && (
              <div className="space-y-2">
                <Label>Chọn Đơn vị</Label>
                <Select
                  value={formData.unit_id?.toString() || ""}
                  onValueChange={(v) =>
                    setFormData({ ...formData, unit_id: parseInt(v) })
                  }
                  disabled={!!editingConfig}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn đơn vị..." /></SelectTrigger>
                  <SelectContent>
                    {units.map((u) => (
                      <SelectItem key={u.id} value={u.id.toString()}>
                        {u.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {formData.scope === "officer" && (
              <div className="space-y-2">
                <Label>Chọn Cán bộ</Label>
                <Select
                  value={formData.officer_id?.toString() || ""}
                  onValueChange={(v) => {
                    const oid = parseInt(v);
                    const officer = officers.find((o) => o.id === oid);
                    setFormData({
                      ...formData,
                      officer_id: oid,
                      unit_id: officer?.unit_id ?? null,
                    });
                  }}
                  disabled={!!editingConfig}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn cán bộ..." /></SelectTrigger>
                  <SelectContent>
                    {officers.map((u) => (
                      <SelectItem key={u.id} value={u.id.toString()}>
                        {u.full_name || u.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <ConfigConflictWarnings
              formData={formData}
              isEditing={!!editingConfig}
              catalogMap={catalogMap}
            />
          </div>
          <DialogFooter>
            <Button
              onClick={handleSubmit}
              disabled={
                createMutation.isPending ||
                updateMutation.isPending ||
                !formData.kpi_code ||
                (!editingConfig && formData.scope === "unit" && !formData.unit_id) ||
                (!editingConfig && formData.scope === "officer" && !formData.officer_id)
              }
            >
              {editingConfig ? "Cập nhật" : "Tạo mới"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Target Dialog */}
      <Dialog open={isTargetDialogOpen} onOpenChange={(open) => {
        setIsTargetDialogOpen(open);
        if (!open) {
          setEditingTarget(null);
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingTarget ? "Sửa Mục tiêu Năm" : "Tạo Mục tiêu Năm"}
            </DialogTitle>
            <DialogDescription>
              Đặt mục tiêu tuyển sinh/chuyển đổi năm để theo dõi tiến độ
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label>Mã KPI</Label>
              <Select
                value={targetFormData.kpi_code}
                onValueChange={(v) =>
                  setTargetFormData({ ...targetFormData, kpi_code: v })
                }
                disabled={!!editingTarget}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KPI_CODES.map((k) => (
                    <SelectItem key={k.value} value={k.value}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Mục tiêu Năm</Label>
              <Input
                type="number"
                value={targetFormData.annual_target}
                onChange={(e) =>
                  setTargetFormData({
                    ...targetFormData,
                    annual_target: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Năm Tài chính</Label>
              <Input
                type="number"
                value={targetFormData.fiscal_year}
                onChange={(e) =>
                  setTargetFormData({
                    ...targetFormData,
                    fiscal_year: parseInt(e.target.value) || new Date().getFullYear(),
                  })
                }
                disabled={!!editingTarget}
              />
            </div>

            {/* Scope Selection for Annual Target */}
            <div className="space-y-2">
              <Label>Phạm vi áp dụng</Label>
              <Select
                value={targetFormData.scope}
                onValueChange={(v) => {
                  setTargetFormData({
                    ...targetFormData,
                    scope: v,
                    unit_id: null,
                    officer_id: null,
                  });
                }}
                disabled={!!editingTarget}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="global">Toàn cục (Mặc định)</SelectItem>
                  <SelectItem value="unit">Đơn vị (Team)</SelectItem>
                  <SelectItem value="officer">Cán bộ (Cá nhân)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {targetFormData.scope === "unit" && (
              <div className="space-y-2">
                <Label>Chọn Đơn vị</Label>
                <Select
                  value={targetFormData.unit_id?.toString() || ""}
                  onValueChange={(v) =>
                    setTargetFormData({ ...targetFormData, unit_id: parseInt(v) })
                  }
                  disabled={!!editingTarget}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn đơn vị..." /></SelectTrigger>
                  <SelectContent>
                    {units.map((u) => (
                      <SelectItem key={u.id} value={u.id.toString()}>
                        {u.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {targetFormData.scope === "officer" && (
              <div className="space-y-2">
                <Label>Chọn Cán bộ</Label>
                <Select
                  value={targetFormData.officer_id?.toString() || ""}
                  onValueChange={(v) => {
                    const oid = parseInt(v);
                    const officer = officers.find((o) => o.id === oid);
                    setTargetFormData({
                      ...targetFormData,
                      officer_id: oid,
                      unit_id: officer?.unit_id ?? null,
                    });
                  }}
                  disabled={!!editingTarget}
                >
                  <SelectTrigger><SelectValue placeholder="Chọn cán bộ..." /></SelectTrigger>
                  <SelectContent>
                    {officers.map((u) => (
                      <SelectItem key={u.id} value={u.id.toString()}>
                        {u.full_name || u.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              onClick={handleTargetSubmit}
              disabled={
                createTargetMutation.isPending ||
                updateTargetMutation.isPending ||
                (!editingTarget && targetFormData.scope === "unit" && !targetFormData.unit_id) ||
                (!editingTarget && targetFormData.scope === "officer" && !targetFormData.officer_id)
              }
            >
              {editingTarget ? "Cập nhật" : "Tạo Mục tiêu"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
