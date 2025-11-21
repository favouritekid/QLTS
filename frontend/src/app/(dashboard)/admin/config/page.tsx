// src/app/(dashboard)/admin/config/page.tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  GraduationCap,
  Layers,
  FileText,
  Plus,
  Pencil,
  Trash2,
  Loader2,
} from "lucide-react";

// ============================================
// TYPES
// ============================================

interface ConfigItem {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  order: number;
  is_active: boolean;
}

interface ConfigItemCreate {
  code: string;
  name: string;
  description?: string;
  order?: number;
}

interface ConfigItemUpdate {
  name?: string;
  description?: string;
  order?: number;
  is_active?: boolean;
}

// ============================================
// CONFIG TABLE COMPONENT
// ============================================

interface ConfigTableProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  endpoint: string;
  queryKey: string;
}

function ConfigTable({ title, description, icon, endpoint, queryKey }: ConfigTableProps) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editItem, setEditItem] = useState<ConfigItem | null>(null);
  const [formData, setFormData] = useState<ConfigItemCreate>({
    code: "",
    name: "",
    description: "",
    order: 1,
  });

  // Fetch items
  const { data: items = [], isLoading } = useQuery<ConfigItem[]>({
    queryKey: ["config", queryKey],
    queryFn: async () => {
      const response = await api.get(`/api/admin/${endpoint}?active_only=false`);
      return response.data;
    },
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: async (data: ConfigItemCreate) => {
      const response = await api.post(`/api/admin/${endpoint}`, data);
      return response.data;
    },
    onSuccess: () => {
      toast.success(`${title} created successfully!`);
      queryClient.invalidateQueries({ queryKey: ["config", queryKey] });
      handleCloseDialog();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail || `Failed to create ${title}`);
    },
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: ConfigItemUpdate }) => {
      const response = await api.put(`/api/admin/${endpoint}/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      toast.success(`${title} updated successfully!`);
      queryClient.invalidateQueries({ queryKey: ["config", queryKey] });
      handleCloseDialog();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail || `Failed to update ${title}`);
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/admin/${endpoint}/${id}`);
    },
    onSuccess: () => {
      toast.success(`${title} deleted successfully!`);
      queryClient.invalidateQueries({ queryKey: ["config", queryKey] });
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail || `Failed to delete ${title}`);
    },
  });

  const handleOpenCreate = () => {
    setEditItem(null);
    setFormData({ code: "", name: "", description: "", order: items.length + 1 });
    setDialogOpen(true);
  };

  const handleOpenEdit = (item: ConfigItem) => {
    setEditItem(item);
    setFormData({
      code: item.code,
      name: item.name,
      description: item.description || "",
      order: item.order,
    });
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditItem(null);
    setFormData({ code: "", name: "", description: "", order: 1 });
  };

  const handleSubmit = () => {
    if (editItem) {
      updateMutation.mutate({
        id: editItem.id,
        data: {
          name: formData.name,
          description: formData.description,
          order: formData.order,
        },
      });
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this item?")) {
      deleteMutation.mutate(id);
    }
  };

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {icon}
            <div>
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <Button onClick={handleOpenCreate}>
            <Plus className="h-4 w-4 mr-2" />
            Add New
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No items configured. Click &quot;Add New&quot; to create one.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">Code</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-[80px]">Order</TableHead>
                <TableHead className="w-[100px]">Status</TableHead>
                <TableHead className="w-[120px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <code className="bg-muted px-2 py-1 rounded text-xs">
                      {item.code}
                    </code>
                  </TableCell>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {item.description || "—"}
                  </TableCell>
                  <TableCell>{item.order}</TableCell>
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
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(item.id)}
                        disabled={deleteMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editItem ? `Edit ${title}` : `Create New ${title}`}
            </DialogTitle>
            <DialogDescription>
              {editItem
                ? "Update the configuration item details"
                : "Enter details for the new configuration item"}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {!editItem && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  Code <span className="text-destructive">*</span>
                </label>
                <Input
                  placeholder="e.g., dai_hoc"
                  value={formData.code}
                  onChange={(e) =>
                    setFormData({ ...formData, code: e.target.value })
                  }
                  disabled={isSubmitting}
                />
                <p className="text-xs text-muted-foreground">
                  Unique identifier (lowercase, underscores)
                </p>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">
                Name <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="e.g., Degree Level Name"
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                disabled={isSubmitting}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                placeholder="Optional description..."
                value={formData.description}
                onChange={(e) =>
                  setFormData({ ...formData, description: e.target.value })
                }
                disabled={isSubmitting}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Display Order</label>
              <Input
                type="number"
                min={1}
                value={formData.order}
                onChange={(e) =>
                  setFormData({ ...formData, order: parseInt(e.target.value) || 1 })
                }
                disabled={isSubmitting}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={handleCloseDialog}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={isSubmitting || !formData.code || !formData.name}
            >
              {isSubmitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {editItem ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ============================================
// MAIN PAGE COMPONENT
// ============================================

export default function SystemConfigPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-3xl font-bold tracking-tight">System Configuration</h1>
        <p className="text-muted-foreground">
          Manage system-wide configuration options for degree levels, offering types, and document types.
        </p>
      </header>

      {/* Tabs */}
      <Tabs defaultValue="degree-levels" className="space-y-4">
        <TabsList>
          <TabsTrigger value="degree-levels" className="gap-2">
            <GraduationCap className="h-4 w-4" />
            Degree Levels
          </TabsTrigger>
          <TabsTrigger value="offering-types" className="gap-2">
            <Layers className="h-4 w-4" />
            Offering Types
          </TabsTrigger>
          <TabsTrigger value="document-types" className="gap-2">
            <FileText className="h-4 w-4" />
            Document Types
          </TabsTrigger>
        </TabsList>

        <TabsContent value="degree-levels">
          <ConfigTable
            title="Degree Level"
            description="Configure available degree levels for academic programs (e.g., Bachelor's, Master's, PhD)"
            icon={<GraduationCap className="h-8 w-8 text-primary" />}
            endpoint="degree-levels"
            queryKey="degree-levels"
          />
        </TabsContent>

        <TabsContent value="offering-types">
          <ConfigTable
            title="Offering Type"
            description="Configure program offering types (e.g., Full-time, Part-time, Online)"
            icon={<Layers className="h-8 w-8 text-primary" />}
            endpoint="offering-types"
            queryKey="offering-types"
          />
        </TabsContent>

        <TabsContent value="document-types">
          <ConfigTable
            title="Document Type"
            description="Configure required document types for applications (e.g., ID Card, Transcript, Photo)"
            icon={<FileText className="h-8 w-8 text-primary" />}
            endpoint="document-types"
            queryKey="document-types"
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
