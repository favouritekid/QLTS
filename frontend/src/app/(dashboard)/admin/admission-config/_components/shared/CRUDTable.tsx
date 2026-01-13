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
import { CRUDDialog } from "./CRUDDialog";
import type { BaseEntity, BaseFormData, CRUDTableColumn } from "./types";

// ============================================
// TYPES
// ============================================

interface CRUDTableProps<T extends BaseEntity> {
  title: string;
  description: string;
  icon?: React.ReactNode;
  columns: CRUDTableColumn<T>[];
  data: T[];
  isLoading: boolean;
  onCreate: (data: BaseFormData) => Promise<void>;
  onUpdate: (id: number, data: BaseFormData) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  renderForm: (
    item: T | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => React.ReactNode;
  initialFormData: () => BaseFormData;
  emptyMessage?: string;
  showActions?: boolean;
  allowCreate?: boolean;
  allowEdit?: boolean;
  allowDelete?: boolean;
}

// ============================================
// COMPONENT
// ============================================

export function CRUDTable<T extends BaseEntity>({
  title,
  description,
  icon,
  columns,
  data,
  isLoading,
  onCreate,
  onUpdate,
  onDelete,
  renderForm,
  initialFormData,
  emptyMessage = "No items configured. Click \"Add New\" to create one.",
  showActions = true,
  allowCreate = true,
  allowEdit = true,
  allowDelete = true,
}: CRUDTableProps<T>) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<T | null>(null);
  const [formData, setFormData] = useState<BaseFormData>(initialFormData());
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    setFormData({
      code: item.code,
      name: item.name,
      description: item.description || "",
      display_order: item.display_order,
      is_active: item.is_active,
    });
    setDialogOpen(true);
  };

  const handleDelete = async (id: number, name: string) => {
    if (confirm(`Are you sure you want to delete "${name}"?`)) {
      try {
        await onDelete(id);
      } catch (error) {
        console.error("Delete failed:", error);
      }
    }
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
        await onUpdate(editItem.id, formData);
      } else {
        await onCreate(formData);
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
          {isActive ? "Active" : "Inactive"}
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
              Add New
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
                    <TableHead className="w-[120px] text-right">Actions</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((item) => (
                  <TableRow key={item.id}>
                    {columns.map((column) => (
                      <TableCell key={String(column.key)}>
                        {renderColumnValue(item, column)}
                      </TableCell>
                    ))}
                    {showActions && (allowEdit || allowDelete) && (
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {allowEdit && (
                            <Button
                              key="edit"
                              variant="ghost"
                              size="icon"
                              onClick={() => handleOpenEdit(item)}
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
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
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
    </>
  );
}
