// src/components/admin/notifications/TemplateList.tsx
/**
 * ✅ PHASE 3.1: Template List Component
 *
 * Admin UI for managing reusable notification templates.
 * Features:
 * - List all templates with pagination
 * - Filter by category and system flag
 * - Search by name or description
 * - Create, edit, delete templates
 * - View template usage count
 * - Protection for system templates
 */
"use client";

import { useState } from "react";
import {
  AlertCircle,
  Edit,
  FileText,
  Loader2,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { toast } from "sonner";

import { Pagination } from "@/components/common/table/Pagination";

import {
  useNotificationTemplates,
  useDeleteNotificationTemplate,
} from "@/hooks/useNotificationTemplates";
import type { NotificationTemplate } from "@/types/api.types";
import { TemplateForm } from "./TemplateForm";

const CATEGORIES = [
  { value: "all", label: "All Categories" },
  { value: "lead", label: "Lead" },
  { value: "consultation", label: "Consultation" },
  { value: "application", label: "Application" },
  { value: "finance", label: "Finance" },
  { value: "dorm", label: "Dorm" },
  { value: "system", label: "System" },
];

interface TemplateListProps {
  initialData?: import("@/types/api.types").NotificationTemplatesPage; // ✅ PHASE 1 - WEEK 2: Accept initialData from server
}

export function TemplateList({ initialData }: TemplateListProps) {
  const [page, setPage] = useState(1); // ✅ TECHNICAL DEBT FIX: Implement pagination
  const [pageSize, setPageSize] = useState(10);
  const [category, setCategory] = useState<string>("all");
  const [isSystem, setIsSystem] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [deleteTemplateId, setDeleteTemplateId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingTemplateId, setEditingTemplateId] = useState<number | undefined>(undefined);

  // Fetch templates (with initialData from server)
  const { data, isLoading, error } = useNotificationTemplates(
    {
      page,
      page_size: pageSize,
      category: category === "all" ? undefined : category,
      is_system: isSystem === "all" ? undefined : isSystem === "true",
      search: search || undefined,
    },
    {
      // ✅ Use initialData only when no filters applied
      initialData:
        page === 1 && category === "all" && isSystem === "all" && !search
          ? initialData
          : undefined,
    }
  );

  // Delete mutation
  const deleteMutation = useDeleteNotificationTemplate();

  const handleDelete = async () => {
    if (!deleteTemplateId) return;

    try {
      await deleteMutation.mutateAsync(deleteTemplateId);
      toast.success("Template deleted successfully");
      setDeleteTemplateId(null);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to delete template");
    }
  };

  const handleCreateClick = () => {
    setEditingTemplateId(undefined);
    setFormOpen(true);
  };

  const handleEditClick = (templateId: number) => {
    setEditingTemplateId(templateId);
    setFormOpen(true);
  };

  const handleFormClose = () => {
    setFormOpen(false);
    setEditingTemplateId(undefined);
  };

  const getCategoryColor = (cat: string | null) => {
    switch (cat) {
      case "lead":
        return "bg-info-100 text-info-800 dark:bg-info-900/50 dark:text-info-300";
      case "consultation":
        return "bg-purple-100 text-purple-800 dark:bg-purple-900/50 dark:text-purple-300";
      case "application":
        return "bg-success-100 text-success-800 dark:bg-success-900/50 dark:text-success-300";
      case "finance":
        return "bg-warning-100 text-warning-800 dark:bg-warning-900/50 dark:text-warning-300";
      case "dorm":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/50 dark:text-orange-300";
      case "system":
        return "bg-muted text-muted-foreground";
      default:
        return "bg-muted text-muted-foreground";
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold font-display tracking-tight flex items-center gap-2">
            <FileText className="h-8 w-8" />
            Notification Templates
          </h1>
          <p className="text-muted-foreground">
            Manage reusable templates for notification rules
          </p>
        </div>
        <Button onClick={handleCreateClick}>
          <Plus className="mr-2 h-4 w-4" />
          Create Template
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Search */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Search</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search by name or description..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2"
                  >
                    <X className="h-4 w-4 text-muted-foreground" />
                  </button>
                )}
              </div>
            </div>

            {/* Category Filter */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Category</label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((cat) => (
                    <SelectItem key={cat.value} value={cat.value}>
                      {cat.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* System Filter */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Type</label>
              <Select value={isSystem} onValueChange={setIsSystem}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Templates</SelectItem>
                  <SelectItem value="false">Custom Templates</SelectItem>
                  <SelectItem value="true">System Templates</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Main Card */}
      <Card>
        <CardHeader>
          <CardTitle>Templates ({data?.total_count || 0})</CardTitle>
          <CardDescription>
            Reusable templates that can be shared across multiple notification rules
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-destructive py-4">
              <AlertCircle className="h-5 w-5" />
              <span>Failed to load templates: {error.message}</span>
            </div>
          )}

          {!isLoading && !error && data && data.templates.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No templates found</p>
              <p className="text-sm">Try adjusting your filters or create a new template</p>
            </div>
          )}

          {!isLoading && !error && data && data.templates.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[200px]">Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-[120px]">Category</TableHead>
                  <TableHead className="w-[100px] text-center">Usage</TableHead>
                  <TableHead className="w-[100px] text-center">Type</TableHead>
                  <TableHead className="w-[120px] text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.templates.map((template: NotificationTemplate) => (
                  <TableRow key={template.id}>
                    {/* Name */}
                    <TableCell className="font-medium">
                      {template.name}
                    </TableCell>

                    {/* Description */}
                    <TableCell className="text-sm text-muted-foreground">
                      {template.description || "-"}
                    </TableCell>

                    {/* Category */}
                    <TableCell>
                      <Badge className={getCategoryColor(template.category)} variant="secondary">
                        {template.category || "None"}
                      </Badge>
                    </TableCell>

                    {/* Usage Count */}
                    <TableCell className="text-center">
                      <Badge variant="outline">
                        {template.usage_count} rule{template.usage_count !== 1 ? "s" : ""}
                      </Badge>
                    </TableCell>

                    {/* System Flag */}
                    <TableCell className="text-center">
                      {template.is_system ? (
                        <Badge variant="secondary">System</Badge>
                      ) : (
                        <Badge variant="outline">Custom</Badge>
                      )}
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEditClick(template.id)}
                          disabled={deleteMutation.isPending}
                          aria-label="Chỉnh sửa"
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeleteTemplateId(template.id)}
                          disabled={
                            template.is_system ||
                            template.usage_count > 0 ||
                            deleteMutation.isPending
                          }
                          aria-label="Xóa"
                          title={
                            template.is_system
                              ? "Cannot delete system template"
                              : template.usage_count > 0
                              ? "Cannot delete template in use"
                              : "Delete template"
                          }
                        >
                          <Trash2
                            className={`h-4 w-4 ${
                              template.is_system || template.usage_count > 0
                                ? "text-muted-foreground"
                                : "text-destructive"
                            }`}
                          />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {/* Pagination */}
          {!isLoading && !error && data && data.total_count > 0 && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={data.total_count}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              showPageSizeSelector={true}
              pageSizeOptions={[10, 20, 50]}
              isLoading={isLoading}
            />
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={deleteTemplateId !== null}
        onOpenChange={(open) => !open && setDeleteTemplateId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Template?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this notification template. This action
              cannot be undone.
              <br />
              <br />
              <strong>Note:</strong> System templates and templates currently in use
              cannot be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Deleting…
                </>
              ) : (
                "Delete Template"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Create/Edit Form Dialog */}
      <TemplateForm
        templateId={editingTemplateId}
        open={formOpen}
        onOpenChange={handleFormClose}
      />
    </div>
  );
}
