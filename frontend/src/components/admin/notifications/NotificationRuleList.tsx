// src/components/admin/notifications/NotificationRuleList.tsx
/**
 * ✅ PHASE 2.4: Notification Rules List Component
 *
 * Admin page to manage notification rules visually.
 * Features:
 * - List all rules with pagination
 * - Filter by event and enabled status
 * - Toggle enable/disable
 * - Delete rules with confirmation
 * - View rule details
 */
"use client";

import { useState } from "react";
import {
  AlertCircle,
  Bell,
  Check,
  Edit,
  Loader2,
  Plus,
  Power,
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

import {
  useNotificationRules,
  useToggleNotificationRule,
  useDeleteNotificationRule,
} from "@/hooks/useNotificationRules";
import type { NotificationRule } from "@/types/api.types";
import { NotificationRuleForm } from "./NotificationRuleForm";

export function NotificationRuleList() {
  const [page, setPage] = useState(1);
  const [deleteRuleId, setDeleteRuleId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<number | undefined>(undefined);

  // Fetch rules
  const { data, isLoading, error } = useNotificationRules({
    page,
    page_size: 50,
  });

  // Toggle mutation
  const toggleMutation = useToggleNotificationRule();

  // Delete mutation
  const deleteMutation = useDeleteNotificationRule();

  const handleToggle = async (rule: NotificationRule) => {
    try {
      await toggleMutation.mutateAsync(rule.id);
      toast.success(
        rule.enabled
          ? `Rule "${rule.event}" disabled`
          : `Rule "${rule.event}" enabled`
      );
    } catch (error: unknown) {
      toast.error("Failed to toggle rule");
    }
  };

  const handleDelete = async () => {
    if (!deleteRuleId) return;

    try {
      await deleteMutation.mutateAsync(deleteRuleId);
      toast.success("Rule deleted successfully");
      setDeleteRuleId(null);
    } catch (error: unknown) {
      toast.error("Failed to delete rule");
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

  const getResolverTypeName = (config: Record<string, unknown>) => {
    const type = config.resolver_type as string;
    return type
      ? type.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")
      : "Unknown";
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Notification Rules</h1>
          <p className="text-muted-foreground">
            Manage notification configurations and delivery rules
          </p>
        </div>
        <Button onClick={handleCreateClick}>
          <Plus className="mr-2 h-4 w-4" />
          Create Rule
        </Button>
      </div>

      {/* Main Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            All Notification Rules
          </CardTitle>
          <CardDescription>
            {data
              ? `${data.total_count} total rules configured`
              : "Loading rules..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Loading State */}
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Error State */}
          {error && (
            <div className="flex flex-col items-center justify-center gap-2 py-12">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <p className="text-sm text-muted-foreground">
                Failed to load notification rules
              </p>
            </div>
          )}

          {/* Table */}
          {data && data.rules.length > 0 && (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40px]">Enabled</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Title Template</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Channels</TableHead>
                    <TableHead>Resolver</TableHead>
                    <TableHead className="w-[100px] text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rules.map((rule) => (
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
                      <TableCell className="max-w-[300px] truncate">
                        {rule.title_template}
                      </TableCell>

                      {/* Notification Type */}
                      <TableCell>
                        <Badge className={getTypeColor(rule.notification_type)} variant="secondary">
                          {rule.notification_type}
                        </Badge>
                      </TableCell>

                      {/* Channels */}
                      <TableCell>
                        <div className="flex gap-1">
                          {rule.channels.map((channel) => (
                            <Badge
                              key={channel}
                              variant="outline"
                              className="text-xs"
                            >
                              {channel}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>

                      {/* Resolver Type */}
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
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setDeleteRuleId(rule.id)}
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
            </div>
          )}

          {/* Empty State */}
          {data && data.rules.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 py-12">
              <Bell className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                No notification rules configured
              </p>
            </div>
          )}

          {/* Pagination */}
          {data && data.total_count > 50 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * 50 + 1} to{" "}
                {Math.min(page * 50, data.total_count)} of {data.total_count}{" "}
                rules
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page * 50 >= data.total_count}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={deleteRuleId !== null}
        onOpenChange={(open) => !open && setDeleteRuleId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Notification Rule?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this notification rule. This action
              cannot be undone.
              <br />
              <br />
              Consider disabling the rule instead if you might need it later.
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
                  Deleting...
                </>
              ) : (
                "Delete Rule"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Create/Edit Form Dialog */}
      <NotificationRuleForm
        ruleId={editingRuleId}
        open={formOpen}
        onOpenChange={handleFormClose}
      />
    </div>
  );
}
