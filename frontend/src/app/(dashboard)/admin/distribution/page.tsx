"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { Plus, Pencil, Trash2, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
// Import Dialog Component (Sẽ tạo ở Bước 2)
import { DistributionRuleDialog } from "@/components/admin/distribution/DistributionRuleDialog";

// Định nghĩa kiểu dữ liệu nhận về từ API Distribution Rule
interface DistributionRule {
  id: number;
  offering_id: number;
  unit_id: number;
  weight: number;
  priority: number;
  is_active: boolean;
  offering_name?: string;
  unit_name?: string;
}

export default function DistributionRulesPage() {
  const queryClient = useQueryClient();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DistributionRule | null>(null);

  // 1. Fetch Rules List
  const { data: rules, isLoading } = useQuery({
    queryKey: ["admin", "distribution-rules"],
    queryFn: async () => {
      const res = await api.get<DistributionRule[]>("/api/admin/distribution-rules");
      return res.data;
    },
  });

  // 2. Toggle Active Mutation
  const toggleMutation = useMutation({
    mutationFn: async ({ id, isActive }: { id: number; isActive: boolean }) => {
      return api.put(`/api/admin/distribution-rules/${id}`, { is_active: isActive });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success("Đã cập nhật trạng thái thành công");
    },
    onError: () => toast.error("Không thể cập nhật trạng thái"),
  });

  // 3. Delete Mutation (Optional)
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      return api.delete(`/api/admin/distribution-rules/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success("Đã xóa luật phân phối");
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-12 w-48" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-bold">
            <Share2 className="h-8 w-8" /> Phân Phối Tuyển Sinh
          </h1>
          <p className="text-muted-foreground mt-1">
            Cấu hình tỷ lệ chia Lead (Weighted Round Robin) giữa các đơn vị.
          </p>
        </div>
        <Button
          onClick={() => {
            setEditingRule(null);
            setIsDialogOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" /> Thêm Luật Mới
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách Luật Phân Phối</CardTitle>
          <CardDescription>Quản lý các quy tắc tự động định tuyến hồ sơ.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Chương trình (Offering)</TableHead>
                <TableHead>Đơn vị tiếp nhận (Unit)</TableHead>
                <TableHead className="text-center">Trọng số (Weight)</TableHead>
                <TableHead className="text-center">Ưu tiên</TableHead>
                <TableHead className="text-center">Trạng thái</TableHead>
                <TableHead className="text-right">Hành động</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground h-24 text-center">
                    Chưa có luật nào được cấu hình.
                  </TableCell>
                </TableRow>
              )}
              {rules?.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell className="font-medium">
                    {rule.offering_name || `ID: ${rule.offering_id}`}
                  </TableCell>
                  <TableCell>{rule.unit_name || `ID: ${rule.unit_id}`}</TableCell>
                  <TableCell className="text-center">
                    <Badge variant="secondary" className="px-3 py-1 text-sm">
                      {rule.weight}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-center font-mono text-xs">{rule.priority}</TableCell>
                  <TableCell className="text-center">
                    <div className="flex justify-center">
                      <Switch
                        checked={rule.is_active}
                        onCheckedChange={(checked) =>
                          toggleMutation.mutate({ id: rule.id, isActive: checked })
                        }
                      />
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => {
                          setEditingRule(rule);
                          setIsDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive hover:bg-destructive/10"
                        onClick={() => {
                          if (confirm("Bạn chắc chắn muốn xóa luật này?"))
                            deleteMutation.mutate(rule.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <DistributionRuleDialog
        open={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        rule={editingRule}
      />
    </div>
  );
}
