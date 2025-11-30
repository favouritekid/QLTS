// src/components/admin/notifications/NotificationRuleList.tsx
/**
 * ✅ PHASE 2.4: Notification Rules List Component (Improved)
 *
 * Trang quản lý quy tắc thông báo với giao diện được cải thiện:
 * - Nhóm theo loại sự kiện (Lead, Application, Consultation, etc.)
 * - Các section có thể thu gọn
 * - Tìm kiếm và lọc
 * - Bảng được đơn giản hóa
 * - Giao diện tiếng Việt
 */
"use client";

import { useState, useMemo } from "react";
import {
  AlertCircle,
  Bell,
  ChevronDown,
  ChevronRight,
  Edit,
  Filter,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
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
import { toast } from "sonner";
import { cn } from "@/lib/utils";

import {
  useNotificationRules,
  useToggleNotificationRule,
  useDeleteNotificationRule,
} from "@/hooks/useNotificationRules";
import type { NotificationRule } from "@/types/api.types";
import { NotificationRuleWizard } from "./NotificationRuleWizard";

// Event category configuration
const EVENT_CATEGORIES = {
  lead: {
    label: "Sự kiện Lead",
    icon: "👤",
    description: "Thông báo liên quan đến lead và tiếp nhận",
  },
  application: {
    label: "Sự kiện Hồ sơ",
    icon: "📝",
    description: "Thông báo về trạng thái hồ sơ ứng tuyển",
  },
  consultation: {
    label: "Sự kiện Tư vấn",
    icon: "💬",
    description: "Thông báo về lịch hẹn và tư vấn",
  },
  assignment: {
    label: "Sự kiện Phân công",
    icon: "👥",
    description: "Thông báo về phân công công việc",
  },
  other: {
    label: "Sự kiện khác",
    icon: "🔔",
    description: "Các thông báo khác",
  },
} as const;

type CategoryKey = keyof typeof EVENT_CATEGORIES;

function getCategoryFromEvent(event: string): CategoryKey {
  const prefix = event.toLowerCase().split("_")[0];
  if (prefix in EVENT_CATEGORIES) {
    return prefix as CategoryKey;
  }
  return "other";
}

interface RuleGroup {
  category: CategoryKey;
  rules: NotificationRule[];
}

export function NotificationRuleList() {
  const [deleteRuleId, setDeleteRuleId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<number | undefined>(undefined);

  // Filters
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "enabled" | "disabled">("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "success" | "warning" | "error" | "info">("all");

  // Collapsed sections state
  const [collapsedSections, setCollapsedSections] = useState<Set<CategoryKey>>(new Set());

  // Fetch rules (fetch all at once, filter client-side)
  const { data, isLoading, error } = useNotificationRules({
    page: 1,
    page_size: 100, // Fetch all rules
  });

  // Toggle mutation
  const toggleMutation = useToggleNotificationRule();

  // Delete mutation
  const deleteMutation = useDeleteNotificationRule();

  // Group and filter rules
  const groupedRules = useMemo<RuleGroup[]>(() => {
    if (!data?.rules) return [];

    // Filter rules based on search and filters
    let filtered = data.rules;

    // Search filter
    if (search) {
      const searchLower = search.toLowerCase();
      filtered = filtered.filter(
        (rule) =>
          rule.event.toLowerCase().includes(searchLower) ||
          rule.title_template.toLowerCase().includes(searchLower)
      );
    }

    // Status filter
    if (statusFilter !== "all") {
      filtered = filtered.filter((rule) =>
        statusFilter === "enabled" ? rule.enabled : !rule.enabled
      );
    }

    // Type filter
    if (typeFilter !== "all") {
      filtered = filtered.filter((rule) => rule.notification_type === typeFilter);
    }

    // Group by category
    const groups = new Map<CategoryKey, NotificationRule[]>();

    for (const rule of filtered) {
      const category = getCategoryFromEvent(rule.event);
      if (!groups.has(category)) {
        groups.set(category, []);
      }
      groups.get(category)!.push(rule);
    }

    // Convert to array and sort by category order
    const categoryOrder: CategoryKey[] = ["lead", "application", "consultation", "assignment", "other"];
    return categoryOrder
      .filter((cat) => groups.has(cat))
      .map((cat) => ({
        category: cat,
        rules: groups.get(cat)!,
      }));
  }, [data, search, statusFilter, typeFilter]);

  const handleToggle = async (rule: NotificationRule) => {
    try {
      await toggleMutation.mutateAsync(rule.id);
      toast.success(
        rule.enabled
          ? `Đã tắt quy tắc "${rule.event}"`
          : `Đã bật quy tắc "${rule.event}"`
      );
    } catch {
      toast.error("Không thể thay đổi trạng thái quy tắc");
    }
  };

  const handleDelete = async () => {
    if (!deleteRuleId) return;

    try {
      await deleteMutation.mutateAsync(deleteRuleId);
      toast.success("Đã xóa quy tắc thành công");
      setDeleteRuleId(null);
    } catch {
      toast.error("Không thể xóa quy tắc");
    }
  };

  const handleCreateClick = () => {
    setEditingRuleId(undefined);
    setFormOpen(true);
  };

  const handleEditClick = (ruleId: number) => {
    setEditingRuleId(ruleId);
    setFormOpen(true);
  };

  const handleFormClose = () => {
    setFormOpen(false);
    setEditingRuleId(undefined);
  };

  const toggleSection = (category: CategoryKey) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const getResolverTypeName = (config: Record<string, unknown>) => {
    const type = config.resolver_type as string;
    if (!type) return "Chưa xác định";

    // Map resolver types to Vietnamese
    const resolverMap: Record<string, string> = {
      "assigned_officer": "Cán bộ phụ trách",
      "lead_owner": "Người sở hữu lead",
      "specific_user": "Người dùng cụ thể",
      "specific_role": "Vai trò cụ thể",
      "unit_members": "Thành viên đơn vị",
      "all_users": "Tất cả người dùng",
      "applicant": "Người nộp hồ sơ",
      "consultation_officer": "Cán bộ tư vấn",
    };

    return resolverMap[type] || type.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "success":
        return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
      case "warning":
        return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200";
      case "error":
        return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
      default:
        return "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200";
    }
  };

  const totalRules = data?.total_count || 0;
  const enabledRules = data?.rules.filter((r) => r.enabled).length || 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Quy tắc thông báo</h1>
          <p className="text-muted-foreground">
            Quản lý cấu hình và quy tắc gửi thông báo
          </p>
        </div>
        <Button onClick={handleCreateClick}>
          <Plus className="mr-2 h-4 w-4" />
          Tạo quy tắc mới
        </Button>
      </div>

      {/* Stats Card */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Tổng quy tắc</CardTitle>
            <Bell className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalRules}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Đang hoạt động</CardTitle>
            <div className="h-2 w-2 rounded-full bg-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{enabledRules}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Đã tắt</CardTitle>
            <div className="h-2 w-2 rounded-full bg-gray-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalRules - enabledRules}</div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-5 w-5" />
            Tìm kiếm và lọc
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row">
            {/* Search */}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Tìm theo tên sự kiện..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10"
              />
            </div>

            {/* Status Filter */}
            <Select value={statusFilter} onValueChange={(value: any) => setStatusFilter(value)}>
              <SelectTrigger className="w-full sm:w-[180px]">
                <SelectValue placeholder="Trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả trạng thái</SelectItem>
                <SelectItem value="enabled">Đang hoạt động</SelectItem>
                <SelectItem value="disabled">Đã tắt</SelectItem>
              </SelectContent>
            </Select>

            {/* Type Filter */}
            <Select value={typeFilter} onValueChange={(value: any) => setTypeFilter(value)}>
              <SelectTrigger className="w-full sm:w-[180px]">
                <SelectValue placeholder="Loại thông báo" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả loại</SelectItem>
                <SelectItem value="success">Thành công</SelectItem>
                <SelectItem value="info">Thông tin</SelectItem>
                <SelectItem value="warning">Cảnh báo</SelectItem>
                <SelectItem value="error">Lỗi</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Error State */}
      {error && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-12">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="text-sm text-muted-foreground">
              Không thể tải danh sách quy tắc thông báo
            </p>
          </CardContent>
        </Card>
      )}

      {/* Grouped Rules */}
      {!isLoading && !error && (
        <div className="space-y-4">
          {groupedRules.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center gap-2 py-12">
                <Bell className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  {search || statusFilter !== "all" || typeFilter !== "all"
                    ? "Không tìm thấy quy tắc phù hợp"
                    : "Chưa có quy tắc thông báo nào"}
                </p>
              </CardContent>
            </Card>
          ) : (
            groupedRules.map((group) => {
              const categoryInfo = EVENT_CATEGORIES[group.category];
              const isCollapsed = collapsedSections.has(group.category);

              return (
                <Card key={group.category}>
                  {/* Category Header - Clickable */}
                  <CardHeader
                    className="cursor-pointer hover:bg-muted/50 transition-colors"
                    onClick={() => toggleSection(group.category)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-2xl">{categoryInfo.icon}</span>
                        <div>
                          <CardTitle className="flex items-center gap-2">
                            {categoryInfo.label}
                            <Badge variant="secondary">{group.rules.length}</Badge>
                          </CardTitle>
                          <CardDescription>{categoryInfo.description}</CardDescription>
                        </div>
                      </div>
                      <Button variant="ghost" size="icon">
                        {isCollapsed ? (
                          <ChevronRight className="h-5 w-5" />
                        ) : (
                          <ChevronDown className="h-5 w-5" />
                        )}
                      </Button>
                    </div>
                  </CardHeader>

                  {/* Category Content - Collapsible */}
                  {!isCollapsed && (
                    <CardContent>
                      <div className="rounded-md border">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-[60px]">Trạng thái</TableHead>
                              <TableHead>Sự kiện</TableHead>
                              <TableHead>Tiêu đề</TableHead>
                              <TableHead className="w-[100px]">Loại</TableHead>
                              <TableHead className="w-[150px]">Người nhận</TableHead>
                              <TableHead className="w-[120px] text-right">
                                Thao tác
                              </TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {group.rules.map((rule) => (
                              <TableRow key={rule.id}>
                                {/* Enabled Toggle */}
                                <TableCell>
                                  <Switch
                                    checked={rule.enabled}
                                    onCheckedChange={() => handleToggle(rule)}
                                    disabled={toggleMutation.isPending}
                                  />
                                </TableCell>

                                {/* Event */}
                                <TableCell className="font-mono text-sm">
                                  {rule.event}
                                </TableCell>

                                {/* Title Template */}
                                <TableCell className="max-w-[400px]">
                                  <div className="truncate" title={rule.title_template}>
                                    {rule.title_template}
                                  </div>
                                  <div className="flex gap-1 mt-1">
                                    {rule.channels.map((channel) => (
                                      <Badge
                                        key={channel}
                                        variant="outline"
                                        className="text-xs"
                                      >
                                        {channel === "email" ? "📧" : "🔔"} {channel}
                                      </Badge>
                                    ))}
                                  </div>
                                </TableCell>

                                {/* Notification Type */}
                                <TableCell>
                                  <Badge
                                    className={getTypeColor(rule.notification_type)}
                                    variant="secondary"
                                  >
                                    {rule.notification_type === "success" && "Thành công"}
                                    {rule.notification_type === "info" && "Thông tin"}
                                    {rule.notification_type === "warning" && "Cảnh báo"}
                                    {rule.notification_type === "error" && "Lỗi"}
                                  </Badge>
                                </TableCell>

                                {/* Resolver/Recipient */}
                                <TableCell className="text-sm text-muted-foreground">
                                  {getResolverTypeName(rule.recipient_config)}
                                </TableCell>

                                {/* Actions */}
                                <TableCell className="text-right">
                                  <div className="flex items-center justify-end gap-1">
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      onClick={() => handleEditClick(rule.id)}
                                      disabled={deleteMutation.isPending}
                                      title="Chỉnh sửa"
                                    >
                                      <Edit className="h-4 w-4" />
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      onClick={() => setDeleteRuleId(rule.id)}
                                      disabled={deleteMutation.isPending}
                                      title="Xóa"
                                    >
                                      <Trash2 className="h-4 w-4 text-destructive" />
                                    </Button>
                                  </div>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </CardContent>
                  )}
                </Card>
              );
            })
          )}
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={deleteRuleId !== null}
        onOpenChange={(open) => !open && setDeleteRuleId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa quy tắc thông báo?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này sẽ xóa vĩnh viễn quy tắc thông báo này và không thể hoàn tác.
              <br />
              <br />
              Bạn nên cân nhắc tắt quy tắc thay vì xóa nếu có thể cần dùng lại sau này.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang xóa...
                </>
              ) : (
                "Xóa quy tắc"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Create/Edit Wizard Dialog */}
      <NotificationRuleWizard
        ruleId={editingRuleId}
        open={formOpen}
        onOpenChange={handleFormClose}
      />
    </div>
  );
}
