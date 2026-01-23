// src/app/(dashboard)/admin/config/_components/SystemCategoryManager.tsx
"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Plus, Pencil, Trash2, Loader2, List, Upload } from "lucide-react";
import type { AxiosError } from "axios";

// ============================================
// TYPES
// ============================================

interface SystemCategory {
  id: number;
  type: string;
  code: string;
  name: string;
  description?: string | null;
  display_order: number;
  is_active: boolean;
}

interface CategoryFormData {
  code: string;
  name: string;
  description?: string;
}

// Category Types
const CATEGORY_TYPES = [
  { value: "ethnicity", label: "Dân tộc (Ethnicity)" },
  { value: "nationality", label: "Quốc tịch (Nationality)" },
  { value: "religion", label: "Tôn giáo (Religion)" },
  { value: "disability_type", label: "Loại khuyết tật (Disability Type)" },
  { value: "province", label: "Tỉnh thành (Province)" },
];

// ============================================
// MAIN COMPONENT
// ============================================

export function SystemCategoryManager() {
  const queryClient = useQueryClient();
  const [selectedType, setSelectedType] = useState<string>("ethnicity");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<SystemCategory | null>(null);
  const [formData, setFormData] = useState<CategoryFormData>({
    code: "",
    name: "",
    description: "",
  });

  // Fetch categories by type
  const { data: categories = [], isLoading } = useQuery<SystemCategory[]>({
    queryKey: ["config", "categories", selectedType],
    queryFn: async () => {
      const response = await api.get(`/api/config/categories`, {
        params: { type: selectedType },
      });
      return response.data;
    },
    enabled: !!selectedType,
  });

  // Create mutation (Admin only - will use POST /api/config/categories/import with single row)
  const createMutation = useMutation({
    mutationFn: async (data: CategoryFormData) => {
      // Note: Backend expects Excel import, we'll use a workaround
      // Create a simple CSV-like payload
      const formDataObj = new FormData();
      formDataObj.append("type", selectedType);
      
      // Create a simple text file with code,name
      const blob = new Blob([`${data.code},${data.name}\n`], { type: "text/csv" });
      formDataObj.append("file", blob, "category.csv");
      
      const response = await api.post(`/api/config/categories/import`, formDataObj);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Category created successfully!");
      queryClient.invalidateQueries({ queryKey: ["config", "categories", selectedType] });
      handleCloseDialog();
    },
    onError: (error: AxiosError<{ detail: string }>) => {
      toast.error(error.response?.data?.detail || "Failed to create category");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/config/categories/${id}`);
    },
    onSuccess: () => {
      toast.success("Category deleted successfully!");
      queryClient.invalidateQueries({ queryKey: ["config", "categories", selectedType] });
    },
    onError: (error: AxiosError<{ detail: string }>) => {
      toast.error(error.response?.data?.detail || "Failed to delete category");
    },
  });

  const handleOpenCreate = () => {
    setEditItem(null);
    setFormData({ code: "", name: "", description: "" });
    setDialogOpen(true);
  };

  const handleOpenEdit = (item: SystemCategory) => {
    setEditItem(item);
    setFormData({
      code: item.code,
      name: item.name,
      description: item.description || "",
    });
    setDialogOpen(true);
  };

  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this category?")) {
      deleteMutation.mutate(id);
    }
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditItem(null);
    setFormData({ code: "", name: "", description: "" });
  };

  const handleSubmit = () => {
    if (!formData.code || !formData.name) {
      toast.error("Code and Name are required");
      return;
    }

    if (editItem) {
      toast.info("Update functionality not available via API");
    } else {
      createMutation.mutate(formData);
    }
  };

  const currentTypeLabel = useMemo(
    () => CATEGORY_TYPES.find((t) => t.value === selectedType)?.label || selectedType,
    [selectedType]
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <List className="text-primary h-8 w-8" />
            <div>
              <CardTitle>System Categories</CardTitle>
              <CardDescription>
                Manage dynamic dropdown categories for personal information
              </CardDescription>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Category Type Selector */}
        <div className="flex items-center gap-4">
          <label className="text-sm font-medium w-32">Category Type:</label>
          <Select value={selectedType} onValueChange={setSelectedType}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Select category type" />
            </SelectTrigger>
            <SelectContent>
              {CATEGORY_TYPES.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex-1" />
          <Button onClick={handleOpenCreate} size="sm">
            <Plus className="mr-2 h-4 w-4" />
            Add New
          </Button>
        </div>

        {/* Categories Table */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : categories.length === 0 ? (
          <div className="text-muted-foreground border-dashed border-2 rounded-lg py-12 text-center">
            <p className="text-sm">No {currentTypeLabel} categories found.</p>
            <p className="text-xs mt-1">Click &quot;Add New&quot; to create one.</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[120px]">Code</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-[80px]">Order</TableHead>
                <TableHead className="w-[100px]">Status</TableHead>
                <TableHead className="w-[120px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {categories.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <code className="bg-muted rounded px-2 py-1 text-xs">{item.code}</code>
                  </TableCell>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {item.description || "—"}
                  </TableCell>
                  <TableCell>{item.display_order}</TableCell>
                  <TableCell>
                    <Badge variant={item.is_active ? "default" : "secondary"}>
                      {item.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleOpenEdit(item)}
                        disabled
                        title="Edit not supported via API"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(item.id)}
                        title="Delete category"
                      >
                        <Trash2 className="text-destructive h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {/* Info Note */}
        <div className="bg-muted/50 border rounded-lg p-4 text-sm">
          <p className="font-medium mb-1">💡 Note:</p>
          <ul className="text-muted-foreground space-y-1 ml-4 list-disc">
            <li>Categories are seeded from <code className="bg-background px-1 rounded">scripts/seeds/seed_system_categories.py</code></li>
            <li>To add/update categories in bulk, modify the CSV file and re-run the seed script</li>
            <li>✅ Delete function now available for admin users</li>
          </ul>
        </div>
      </CardContent>

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editItem ? `Edit ${currentTypeLabel}` : `Create New ${currentTypeLabel}`}
            </DialogTitle>
            <DialogDescription>
              {editItem
                ? "Update the category details"
                : "Enter details for the new category"}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                Code <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="e.g., KINH"
                value={formData.code}
                onChange={(e) => setFormData({ ...formData, code: e.target.value.toUpperCase() })}
                disabled={!!editItem}
              />
              <p className="text-muted-foreground text-xs">
                Unique identifier (uppercase, max 50 chars)
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">
                Name <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="e.g., Người Kinh"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                placeholder="Optional description..."
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={handleCloseDialog}>
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={createMutation.isPending || !formData.code || !formData.name}
            >
              {createMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editItem ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
