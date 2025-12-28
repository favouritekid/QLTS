"use client";

/**
 * Admin KPI Configuration Page
 * Phase 5: Allows admins to configure KPI targets for officers and units.
 */

import { useState, useEffect } from "react";
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

import { api } from "@/lib/api/client";

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

const KPI_CODES = [
  { value: "consultations_daily", label: "Tư vấn (Ngày)" },
  { value: "consultations_monthly", label: "Tư vấn (Tháng)" },
  { value: "enrollments", label: "Nhập học" },
  { value: "conversion_rate", label: "Tỉ lệ chuyển đổi (%)" },
  { value: "response_time", label: "Thời gian phản hồi (giờ)" },
];

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

async function fetchKpiTargets(fiscalYear?: number): Promise<KpiTarget[]> {
  const params = fiscalYear ? `?fiscal_year=${fiscalYear}` : "";
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

// =============================================================================
// COMPONENT
// =============================================================================

export default function KpiConfigPage() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isTargetDialogOpen, setIsTargetDialogOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<KpiConfig | null>(null);
  const [deleteConfigId, setDeleteConfigId] = useState<number | null>(null);

  // Form state
  const [formData, setFormData] = useState({
    kpi_code: "",
    target_value: 10,
    period_type: "daily",
    unit_id: null as number | null,
    officer_id: null as number | null,
  });

  const [targetFormData, setTargetFormData] = useState({
    kpi_code: "enrollments",
    annual_target: 100,
    fiscal_year: new Date().getFullYear(),
  });

  // Queries
  const { data: configs, isLoading: loadingConfigs } = useQuery({
    queryKey: ["kpi-configs"],
    queryFn: () => fetchKpiConfigs(true),
  });

  const { data: targets, isLoading: loadingTargets } = useQuery({
    queryKey: ["kpi-targets"],
    queryFn: () => fetchKpiTargets(),
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
    },
    onError: (err: Error) => {
      toast.error(err.message || "Tạo mục tiêu thất bại");
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
    });
  }

  function handleEdit(config: KpiConfig) {
    setEditingConfig(config);
    setFormData({
      kpi_code: config.kpi_code,
      target_value: config.target_value,
      period_type: config.period_type,
      unit_id: config.unit_id,
      officer_id: config.officer_id,
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

  function getScopeIcon(config: KpiConfig) {
    if (config.officer_id) return <User className="h-4 w-4" />;
    if (config.unit_id) return <Building2 className="h-4 w-4" />;
    return <Globe className="h-4 w-4" />;
  }

  function getScopeLabel(config: KpiConfig) {
    if (config.officer_id) return `Cán bộ #${config.officer_id}`;
    if (config.unit_id) return `Đơn vị #${config.unit_id}`;
    return "Toàn cục";
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            Cấu hình KPI
          </h1>
          <p className="text-muted-foreground mt-1">
            Cấu hình mục tiêu hàng ngày/tháng và mục tiêu năm cho cán bộ
          </p>
        </div>
        <div className="flex gap-2">
          <Dialog open={isTargetDialogOpen} onOpenChange={setIsTargetDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Target className="mr-2 h-4 w-4" />
                Thêm Mục tiêu Năm
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Tạo Mục tiêu Năm</DialogTitle>
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
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  onClick={() => createTargetMutation.mutate(targetFormData)}
                  disabled={createTargetMutation.isPending}
                >
                  Tạo Mục tiêu
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={isDialogOpen} onOpenChange={(open) => {
            setIsDialogOpen(open);
            if (!open) {
              setEditingConfig(null);
              resetForm();
            }
          }}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Thêm Cấu hình
              </Button>
            </DialogTrigger>
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
                    onValueChange={(v) =>
                      setFormData({ ...formData, kpi_code: v })
                    }
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
                        target_value: parseInt(e.target.value) || 0,
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
                    disabled={!!editingConfig}
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
              </div>
              <DialogFooter>
                <Button
                  onClick={handleSubmit}
                  disabled={createMutation.isPending || updateMutation.isPending}
                >
                  {editingConfig ? "Cập nhật" : "Tạo mới"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Daily/Monthly Configs */}
      <Card>
        <CardHeader>
          <CardTitle>Mục tiêu Ngày/Tháng</CardTitle>
          <CardDescription>
            Cấu hình mục tiêu KPI định kỳ (kế thừa: Cán bộ → Đơn vị → Toàn cục)
          </CardDescription>
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
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      Chưa có cấu hình nào. Hãy thêm cấu hình KPI đầu tiên của bạn.
                    </TableCell>
                  </TableRow>
                ) : (
                  configs?.map((config) => (
                    <TableRow key={config.id}>
                      <TableCell className="font-medium">
                        {KPI_CODES.find((k) => k.value === config.kpi_code)?.label ||
                          config.kpi_code}
                      </TableCell>
                      <TableCell className="font-mono">
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
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(config)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeleteConfigId(config.id)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
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
          <CardTitle>Mục tiêu Năm</CardTitle>
          <CardDescription>
            Các mục tiêu hàng năm với theo dõi tiến độ YTD (đồng bộ hàng ngày lúc 1:00 AM)
          </CardDescription>
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
                  <TableHead>Mục tiêu Năm</TableHead>
                  <TableHead>Đạt được (YTD)</TableHead>
                  <TableHead>Tiến độ</TableHead>
                  <TableHead>Đồng bộ cuối</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets?.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      Chưa có mục tiêu năm. Hãy thêm mục tiêu để theo dõi YTD.
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
                        <TableCell className="font-mono">
                          {target.annual_target.toLocaleString()}
                        </TableCell>
                        <TableCell className="font-mono">
                          {target.achieved_ytd.toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="flex-1 bg-muted rounded-full h-2 max-w-24">
                              <div
                                className="bg-primary h-2 rounded-full transition-all"
                                style={{ width: `${Math.min(progress, 100)}%` }}
                              />
                            </div>
                            <span className="text-sm font-medium">{progress}%</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {target.last_sync_at
                            ? new Date(target.last_sync_at).toLocaleDateString("vi-VN")
                            : "Chưa bao giờ"}
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
    </div>
  );
}
