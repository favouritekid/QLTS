// src/app/(dashboard)/admin/organization-tree/_components/OrganizationTreeClient.tsx
"use client";

import { useState } from "react";
import { OrganizationTreeView } from "@/components/admin/organization/OrganizationTreeView";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { OrganizationTreeNodeWithAggregation } from "@/types/organization.types";

interface OrganizationTreeClientProps {
  initialData?: OrganizationTreeNodeWithAggregation[];
}

/**
 * Organization Tree View Client Component
 *
 * Displays organization units in a tree structure with:
 * - Majors listed under each unit
 * - Aggregated statistics (total majors, admission quota, tuition fees)
 * - Expand/collapse functionality
 * - Filtering by academic year
 */
export function OrganizationTreeClient({ initialData }: OrganizationTreeClientProps) {
  const [academicYear, setAcademicYear] = useState<number>(new Date().getFullYear());
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selectedNode, setSelectedNode] = useState<OrganizationTreeNodeWithAggregation | null>(null);

  const handleNodeClick = (node: OrganizationTreeNodeWithAggregation) => {
    setSelectedNode(node);
  };

  // Only use initialData when filters match default state
  const shouldUseInitialData =
    academicYear === new Date().getFullYear() && !includeInactive;

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-bold">Cây Đơn Vị Tổ Chức</h1>
        <p className="text-muted-foreground mt-2">
          Hiển thị cấu trúc tổ chức với thông tin ngành học và thống kê tổng hợp
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Bộ lọc</CardTitle>
          <CardDescription>Tùy chỉnh hiển thị dữ liệu</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Academic Year Filter */}
            <div className="space-y-2">
              <Label htmlFor="academicYear">Năm học</Label>
              <Input
                id="academicYear"
                type="number"
                value={academicYear}
                onChange={(e) => setAcademicYear(parseInt(e.target.value) || new Date().getFullYear())}
                min={2000}
                max={2100}
              />
            </div>

            {/* Include Inactive Toggle */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="includeInactive">Hiển thị đơn vị không hoạt động</Label>
                <Switch
                  id="includeInactive"
                  checked={includeInactive}
                  onCheckedChange={setIncludeInactive}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Bao gồm các đơn vị đã bị vô hiệu hóa trong cây tổ chức
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tree View */}
      <OrganizationTreeView
        academicYear={academicYear}
        includeInactive={includeInactive}
        onNodeClick={handleNodeClick}
        initialData={shouldUseInitialData ? initialData : undefined}
      />

      {/* Selected Node Details (Optional) */}
      {selectedNode && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Chi tiết đơn vị được chọn</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="font-medium">Tên:</div>
                <div>{selectedNode.name}</div>

                <div className="font-medium">Loại:</div>
                <div>{selectedNode.type}</div>

                <div className="font-medium">ID:</div>
                <div>{selectedNode.id}</div>

                {selectedNode.description && (
                  <>
                    <div className="font-medium">Mô tả:</div>
                    <div>{selectedNode.description}</div>
                  </>
                )}

                <div className="font-medium">Số chương trình trực thuộc:</div>
                <div>{selectedNode.stats.direct_programs}</div>

                <div className="font-medium">Tổng số chương trình (bao gồm con):</div>
                <div>{selectedNode.stats.total_programs}</div>

                {selectedNode.stats.total_admission_quota && (
                  <>
                    <div className="font-medium">Tổng chỉ tiêu:</div>
                    <div>{selectedNode.stats.total_admission_quota}</div>
                  </>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
