/**
 * CRUDTable - Reusable CRUD Table Component
 *
 * Extracted from admin/config/ConfigClient.tsx pattern
 * Provides full CRUD operations for any entity type
 */

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Plus, Pencil, Trash2 } from "lucide-react";
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
import { CRUDDialog } from "./CRUDDialog";
import type { BaseEntity, CRUDTableColumn } from "./types";

// ============================================
// TYPES
// ============================================

// Minimal interface required for CRUD operations
interface CRUDEntity {
  id: number;
  name?: string; // Optional since not all entities have a name field
  is_active: boolean;
}

interface CRUDTableProps<T extends CRUDEntity, TFormValues> {
  title: string;
  description: string;
  icon?: React.ReactNode;
  columns: CRUDTableColumn<T>[];
  data: T[];
  isLoading: boolean;
  mapItemToFormData: (item: T) => TFormValues;
  createMutation?: unknown;
  updateMutation?: unknown;
  deleteMutation?: unknown;
  onCreate?: (data: TFormValues) => Promise<void>;
  onUpdate?: (id: number, data: TFormValues) => Promise<void>;
  onDelete?: (id: number, name?: string) => Promise<void>;
  renderForm: (
    item: T | null,
    formData: TFormValues,
    setFormData: (data: TFormValues) => void,
    isEdit: boolean
  ) => React.ReactNode;
  initialFormData: () => TFormValues;
  // Fallback defaults if not provided (legacy support removed)
  emptyMessage?: string;
  showActions?: boolean;
  allowCreate?: boolean;
  allowEdit?: boolean;
  allowDelete?: boolean;
}

// ============================================
// COMPONENT
// ============================================

export function CRUDTable<T extends CRUDEntity, TFormValues>({
  title,
  description,
  icon,
  columns,
  data,
  isLoading,
  createMutation,
  updateMutation,
  deleteMutation,
  onCreate,
  onUpdate,
  onDelete,
  renderForm,
  initialFormData,
  mapItemToFormData,
  emptyMessage = "Chưa có dữ liệu. Nhấn \"Thêm mới\" để tạo.",
  showActions = true,
  allowCreate = true,
  allowEdit = true,
  allowDelete = true,
}: CRUDTableProps<T, TFormValues>) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<T | null>(null);
  const [formData, setFormData] = useState<TFormValues>(initialFormData());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: number; label: string } | null>(null);

  // ============================================
  // HANDLERS
  // ============================================

  const handleOpenCreate = () => {
    setEditItem(null);
    setFormData(initialFormData());
    setDialogOpen(true);
  };

  const handleOpenEdit = (item: T) => {
    setEditItem(item);
    setFormData(mapItemToFormData(item));
    setDialogOpen(true);
  };

  const handleDelete = (id: number, name?: string) => {
    const itemLabel = name || `item #${id}`;
    setPendingDelete({ id, label: itemLabel });
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (pendingDelete) {
      try {
        if (onDelete) await onDelete(pendingDelete.id, pendingDelete.label);
      } catch (error) {
        console.error("Delete failed:", error);
      }
    }
    setDeleteConfirmOpen(false);
    setPendingDelete(null);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditItem(null);
    setFormData(initialFormData());
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      if (editItem) {
        if (onUpdate) await onUpdate(editItem.id, formData);
      } else {
        if (onCreate) await onCreate(formData);
      }
      handleCloseDialog();
    } catch (error) {
      // Error handling is done in parent via toast
      console.error("CRUD operation failed:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  // ============================================
  // RENDER COLUMN VALUE
  // ============================================

  const renderColumnValue = (item: T, column: CRUDTableColumn<T>) => {
    if (column.render) {
      return column.render(item);
    }

    const value = item[column.key as keyof T];

    // Handle special cases
    if (column.key === 'code') {
      return (
        <code className="bg-muted rounded px-2 py-1 text-xs font-mono">
          {String(value)}
        </code>
      );
    }

    if (column.key === 'is_active' || column.key === 'status') {
      const isActive = value === true || value === 'active';
      return (
        <Badge variant={isActive ? "default" : "secondary"}>
          {isActive ? "Hoạt động" : "Ngưng hoạt động"}
        </Badge>
      );
    }

    if (value === null || value === undefined) {
      return <span className="text-muted-foreground">—</span>;
    }

    return String(value);
  };

  // ============================================
  // RENDER
  // ============================================

  return (
    <>
      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {icon}
            <div>
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="text-sm text-muted-foreground">{description}</p>
            </div>
          </div>
          {allowCreate && (
            <Button onClick={handleOpenCreate}>
              <Plus className="mr-2 h-4 w-4" />
              Thêm mới
            </Button>
          )}
        </div>

        {/* Table */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : data.length === 0 ? (
          <div className="text-muted-foreground py-8 text-center border rounded-lg">
            {emptyMessage}
          </div>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  {columns.map((column) => (
                    <TableHead key={String(column.key)} style={{ width: column.width }}>
                      {column.header}
                    </TableHead>
                  ))}
                  {showActions && (allowEdit || allowDelete) && (
                    <TableHead className="w-[120px] text-right">Thao tác</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((item) => {
                  const isGroupHeader = (item as unknown as { isGroupHeader?: boolean }).isGroupHeader;

                  return (
                    <TableRow key={item.id} className={isGroupHeader ? "bg-muted/30" : ""}>
                      {columns.map((column) => (
                        <TableCell key={String(column.key)}>
                          {renderColumnValue(item, column)}
                        </TableCell>
                      ))}
                      {showActions && (allowEdit || allowDelete) && (
                        <TableCell className="text-right">
                          {!isGroupHeader && (
                            <div className="flex justify-end gap-2">
                              {allowEdit && (
                                <Button
                                  key="edit"
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => handleOpenEdit(item)}
                                  aria-label="Chỉnh sửa"
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                              )}
                              {allowDelete && (
                                <Button
                                  key="delete"
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => handleDelete(item.id, item.name)}
                                  aria-label="Xóa"
                                >
                                  <Trash2 className="h-4 w-4 text-destructive" />
                                </Button>
                              )}
                            </div>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Dialog */}
      <CRUDDialog
        open={dialogOpen}
        onClose={handleCloseDialog}
        title={editItem ? `Edit ${title}` : `Create ${title}`}
        isEdit={!!editItem}
        onSubmit={handleSubmit}
        isSubmitting={isSubmitting}
      >
        {renderForm(editItem, formData, setFormData, !!editItem)}
      </CRUDDialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa &quot;{pendingDelete?.label}&quot;?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleConfirmDelete}
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
