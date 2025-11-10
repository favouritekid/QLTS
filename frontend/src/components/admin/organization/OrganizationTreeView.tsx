// src/components/admin/organization/OrganizationTreeView.tsx
import React, { useState, useMemo } from "react";
import {
  ChevronRight,
  ChevronDown,
  Building2,
  GraduationCap,
  Users,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useOrganizationTreeWithAggregation } from "@/hooks/useOrganization";
import type { OrganizationTreeNodeWithAggregation } from "@/types/organization.types";

interface OrganizationTreeViewProps {
  academicYear?: number;
  includeInactive?: boolean;
  onNodeClick?: (node: OrganizationTreeNodeWithAggregation) => void;
}

/**
 * Format currency in VND
 */
function formatCurrency(amount: number | null | undefined): string {
  if (!amount) return "N/A";
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    minimumFractionDigits: 0,
  }).format(amount);
}

/**
 * Tree node component with expand/collapse functionality
 */
interface TreeNodeProps {
  node: OrganizationTreeNodeWithAggregation;
  level: number;
  onNodeClick?: (node: OrganizationTreeNodeWithAggregation) => void;
}

function TreeNode({ node, level, onNodeClick }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(level === 0); // Root nodes expanded by default
  const hasChildren = node.children && node.children.length > 0;
  const hasMajors = node.majors && node.majors.length > 0;

  // Determine the type icon
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "Khoa":
        return <Building2 className="h-4 w-4" />;
      case "Bộ môn":
        return <GraduationCap className="h-4 w-4" />;
      default:
        return <Building2 className="h-4 w-4" />;
    }
  };

  // Get type color
  const getTypeColor = (type: string) => {
    switch (type) {
      case "Khoa":
        return "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200";
      case "Bộ môn":
        return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
      case "Phòng ban":
        return "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200";
      case "Trung tâm":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200";
      default:
        return "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200";
    }
  };

  return (
    <div className="w-full">
      <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
        <div
          className={cn(
            "flex items-center gap-2 py-2 px-3 rounded-md hover:bg-accent transition-colors",
            !node.is_active && "opacity-50"
          )}
          style={{ paddingLeft: `${level * 24 + 12}px` }}
        >
          {/* Expand/Collapse Button */}
          {hasChildren ? (
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="icon" className="h-6 w-6 p-0">
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
          ) : (
            <div className="h-6 w-6" />
          )}

          {/* Type Icon */}
          <div className="flex-shrink-0">{getTypeIcon(node.type)}</div>

          {/* Node Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => onNodeClick?.(node)}
                className="font-medium text-sm hover:underline text-left"
              >
                {node.name}
              </button>
              <Badge variant="outline" className={cn("text-xs", getTypeColor(node.type))}>
                {node.type}
              </Badge>
              {!node.is_active && (
                <Badge variant="secondary" className="text-xs">
                  Không hoạt động
                </Badge>
              )}
            </div>

            {/* Statistics */}
            <div className="flex items-center gap-4 mt-1 text-xs text-muted-foreground flex-wrap">
              {/* Direct Majors */}
              {node.stats.direct_majors > 0 && (
                <div className="flex items-center gap-1">
                  <GraduationCap className="h-3 w-3" />
                  <span>{node.stats.direct_majors} ngành</span>
                </div>
              )}

              {/* Total Majors (including descendants) */}
              {node.stats.total_majors > node.stats.direct_majors && (
                <div className="flex items-center gap-1">
                  <GraduationCap className="h-3 w-3" />
                  <span className="font-medium">
                    {node.stats.total_majors} ngành (tổng)
                  </span>
                </div>
              )}

              {/* Total Admission Quota */}
              {node.stats.total_admission_quota && (
                <div className="flex items-center gap-1">
                  <Users className="h-3 w-3" />
                  <span>{node.stats.total_admission_quota} chỉ tiêu</span>
                </div>
              )}

              {/* Average Tuition Fee */}
              {node.stats.avg_tuition_fee && (
                <div className="flex items-center gap-1">
                  <DollarSign className="h-3 w-3" />
                  <span>TB: {formatCurrency(Number(node.stats.avg_tuition_fee))}</span>
                </div>
              )}
            </div>

            {/* Major List (if direct majors exist) */}
            {hasMajors && isExpanded && (
              <div className="mt-2 space-y-1">
                {node.majors.map((major) => (
                  <div
                    key={major.id}
                    className="flex items-center gap-2 p-2 rounded bg-muted/50 text-xs"
                  >
                    <GraduationCap className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{major.name}</div>
                      <div className="text-muted-foreground">Mã: {major.code}</div>
                    </div>
                    {major.total_admission_quota && (
                      <Badge variant="secondary" className="text-xs flex-shrink-0">
                        {major.total_admission_quota} chỉ tiêu
                      </Badge>
                    )}
                    {major.tuition_fee && (
                      <div className="text-muted-foreground flex-shrink-0">
                        {formatCurrency(Number(major.tuition_fee))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Children */}
        {hasChildren && (
          <CollapsibleContent>
            <div className="space-y-0.5">
              {node.children.map((child) => (
                <TreeNode
                  key={child.id}
                  node={child}
                  level={level + 1}
                  onNodeClick={onNodeClick}
                />
              ))}
            </div>
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  );
}

/**
 * Organization Tree View Component
 * Displays organization units in a tree structure with majors and aggregated statistics
 */
export function OrganizationTreeView({
  academicYear,
  includeInactive = false,
  onNodeClick,
}: OrganizationTreeViewProps) {
  const { data: treeData, isLoading, error } = useOrganizationTreeWithAggregation(
    academicYear,
    includeInactive
  );

  // Calculate overall statistics
  const overallStats = useMemo(() => {
    if (!treeData || treeData.length === 0) return null;

    let totalUnits = 0;
    let totalMajors = 0;
    let totalQuota = 0;
    const allTuitionFees: number[] = [];

    const countNode = (node: OrganizationTreeNodeWithAggregation) => {
      totalUnits++;
      totalMajors += node.stats.direct_majors;
      if (node.stats.total_admission_quota) {
        totalQuota += node.stats.total_admission_quota;
      }

      // Collect tuition fees from direct majors
      node.majors.forEach((major) => {
        if (major.tuition_fee) {
          allTuitionFees.push(Number(major.tuition_fee));
        }
      });

      node.children.forEach(countNode);
    };

    treeData.forEach(countNode);

    const avgTuition =
      allTuitionFees.length > 0
        ? allTuitionFees.reduce((sum, fee) => sum + fee, 0) / allTuitionFees.length
        : null;
    const minTuition = allTuitionFees.length > 0 ? Math.min(...allTuitionFees) : null;
    const maxTuition = allTuitionFees.length > 0 ? Math.max(...allTuitionFees) : null;

    return {
      totalUnits,
      totalMajors,
      totalQuota,
      avgTuition,
      minTuition,
      maxTuition,
    };
  }, [treeData]);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8">
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-8">
          <div className="text-center text-destructive">
            Lỗi khi tải dữ liệu: {error.message}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!treeData || treeData.length === 0) {
    return (
      <Card>
        <CardContent className="py-8">
          <div className="text-center text-muted-foreground">
            Không có dữ liệu đơn vị tổ chức
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Overall Statistics */}
      {overallStats && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Thống kê tổng quan</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Tổng đơn vị</div>
                <div className="text-2xl font-bold">{overallStats.totalUnits}</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Tổng ngành học</div>
                <div className="text-2xl font-bold">{overallStats.totalMajors}</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Tổng chỉ tiêu</div>
                <div className="text-2xl font-bold">{overallStats.totalQuota}</div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Học phí TB</div>
                <div className="text-sm font-semibold">
                  {formatCurrency(overallStats.avgTuition)}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Học phí thấp nhất</div>
                <div className="text-sm font-semibold text-green-600">
                  {formatCurrency(overallStats.minTuition)}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Học phí cao nhất</div>
                <div className="text-sm font-semibold text-red-600">
                  {formatCurrency(overallStats.maxTuition)}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tree View */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Cây đơn vị tổ chức</CardTitle>
          {academicYear && (
            <div className="text-sm text-muted-foreground">Năm học: {academicYear}</div>
          )}
        </CardHeader>
        <CardContent>
          <div className="space-y-0.5">
            {treeData.map((node) => (
              <TreeNode key={node.id} node={node} level={0} onNodeClick={onNodeClick} />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
