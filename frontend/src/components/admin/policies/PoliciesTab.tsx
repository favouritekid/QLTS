// src/components/admin/policies/PoliciesTab.tsx
"use client";

import { useState, useMemo } from "react";
import { Plus, Trash2, AlertTriangle, Filter, X } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Combobox } from "@/components/ui/combobox";
import { toast } from "sonner";

import { usePolicies, useAddPolicy, useDeletePolicy, useValidatePolicy } from "@/hooks/usePolicies";
import { usePolicySuggestions } from "@/hooks/usePolicySuggestions";
import type { PolicyRule } from "@/types/policy.types";

// Helper to extract error message from API errors
function getErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    return response?.data?.detail || fallback;
  }
  return fallback;
}

export function PoliciesTab() {
  const { data: policies, isLoading } = usePolicies();
  const { data: suggestions } = usePolicySuggestions();
  const addPolicyMutation = useAddPolicy();
  const deletePolicyMutation = useDeletePolicy();
  const validatePolicyMutation = useValidatePolicy();

  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [policyToDelete, setPolicyToDelete] = useState<PolicyRule | null>(null);
  const [validationWarning, setValidationWarning] = useState<string[]>([]);

  // Filter states
  const [subjectFilter, setSubjectFilter] = useState("");
  const [objectFilter, setObjectFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  const [newPolicy, setNewPolicy] = useState({
    subject: "",
    object: "",
    action: "",
  });

  // Filtered policies with useMemo
  const filteredPolicies = useMemo(() => {
    if (!policies) return [];

    return policies.filter((policy) => {
      const matchSubject = !subjectFilter ||
        policy.subject.toLowerCase().includes(subjectFilter.toLowerCase());
      const matchObject = !objectFilter ||
        policy.object.toLowerCase().includes(objectFilter.toLowerCase());
      const matchAction = !actionFilter ||
        policy.action.toLowerCase().includes(actionFilter.toLowerCase());

      return matchSubject && matchObject && matchAction;
    });
  }, [policies, subjectFilter, objectFilter, actionFilter]);

  // Check if any filter is active
  const hasActiveFilters = subjectFilter || objectFilter || actionFilter;

  // Clear all filters
  const clearFilters = () => {
    setSubjectFilter("");
    setObjectFilter("");
    setActionFilter("");
  };

  const handleAddPolicy = async () => {
    if (!newPolicy.subject || !newPolicy.object || !newPolicy.action) {
      toast.error("All fields are required");
      return;
    }

    try {
      await addPolicyMutation.mutateAsync(newPolicy);
      toast.success("Policy added successfully");
      setAddDialogOpen(false);
      setNewPolicy({ subject: "", object: "", action: "" });
    } catch (error) {
      toast.error(getErrorMessage(error, "Failed to add policy"));
    }
  };

  const handleDeleteClick = async (policy: PolicyRule) => {
    // Validate before delete
    try {
      const validation = await validatePolicyMutation.mutateAsync({
        ...policy,
        operation: "remove",
      });

      if (!validation.is_safe) {
        setValidationWarning(validation.warnings);
        return; // Block deletion
      }

      if (validation.warnings.length > 0) {
        setValidationWarning(validation.warnings);
      }

      setPolicyToDelete(policy);
      setDeleteDialogOpen(true);
    } catch {
      toast.error("Failed to validate policy deletion");
    }
  };

  const handleDeleteConfirm = async () => {
    if (!policyToDelete) return;

    try {
      await deletePolicyMutation.mutateAsync(policyToDelete);
      toast.success("Policy deleted successfully");
      setDeleteDialogOpen(false);
      setPolicyToDelete(null);
      setValidationWarning([]);
    } catch (error) {
      toast.error(getErrorMessage(error, "Failed to delete policy"));
    }
  };

  const getRoleBadgeVariant = (subject: string) => {
    if (subject.includes("admin")) return "default";
    if (subject.includes("manager")) return "secondary";
    return "outline";
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Policy Rules</CardTitle>
              <CardDescription>
                Manage Casbin policy rules (Subject → Object → Action)
              </CardDescription>
            </div>
            <Button onClick={() => setAddDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Add Policy
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {validationWarning.length > 0 && (
            <Alert variant="destructive" className="mb-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                <strong>Safety Warning:</strong>
                <ul className="mt-2 list-disc pl-4">
                  {validationWarning.map((warning, i) => (
                    <li key={i}>{warning}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {/* Filter Section */}
          <div className="mb-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Filter className="h-4 w-4" />
                <span>Filter Policies</span>
              </div>
              {hasActiveFilters && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearFilters}
                  className="h-8"
                >
                  <X className="mr-1 h-3 w-3" />
                  Clear Filters
                </Button>
              )}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-1">
                <Label htmlFor="filter-subject" className="text-xs text-muted-foreground">
                  Subject
                </Label>
                <Input
                  id="filter-subject"
                  placeholder="e.g., role:admin"
                  value={subjectFilter}
                  onChange={(e) => setSubjectFilter(e.target.value)}
                  className="h-9"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="filter-object" className="text-xs text-muted-foreground">
                  Object / Resource
                </Label>
                <Input
                  id="filter-object"
                  placeholder="e.g., /api/leads"
                  value={objectFilter}
                  onChange={(e) => setObjectFilter(e.target.value)}
                  className="h-9"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="filter-action" className="text-xs text-muted-foreground">
                  Action
                </Label>
                <Input
                  id="filter-action"
                  placeholder="e.g., GET"
                  value={actionFilter}
                  onChange={(e) => setActionFilter(e.target.value)}
                  className="h-9"
                />
              </div>
            </div>
            {hasActiveFilters && (
              <div className="text-sm text-muted-foreground">
                Showing {filteredPolicies.length} of {policies?.length || 0} policies
              </div>
            )}
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Subject</TableHead>
                    <TableHead>Object (Resource)</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredPolicies.length > 0 ? (
                    filteredPolicies.map((policy, index) => (
                      <TableRow key={index}>
                        <TableCell>
                          <Badge variant={getRoleBadgeVariant(policy.subject)}>
                            {policy.subject}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-sm">{policy.object}</TableCell>
                        <TableCell>
                          <code className="rounded bg-muted px-2 py-1 text-sm">{policy.action}</code>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteClick(policy)}
                            disabled={deletePolicyMutation.isPending}
                            aria-label="Xóa policy"
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={4} className="h-24 text-center">
                        {hasActiveFilters ? (
                          <div className="flex flex-col items-center gap-2">
                            <p className="text-muted-foreground">No policies match your filter</p>
                            <Button variant="link" size="sm" onClick={clearFilters}>
                              Clear filters
                            </Button>
                          </div>
                        ) : (
                          <p className="text-muted-foreground">No policies found</p>
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Policy Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Policy</DialogTitle>
            <DialogDescription>
              Create a new Casbin policy rule. Use role:name format for subjects.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="subject">Subject (e.g., role:manager)</Label>
              <Combobox
                value={newPolicy.subject}
                onChange={(value) => setNewPolicy({ ...newPolicy, subject: value })}
                suggestions={suggestions?.subjects || []}
                placeholder="Select or type subject..."
                searchPlaceholder="Search subjects..."
                emptyText="No subjects found. Type to create new."
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="object">Object / Resource (e.g., /api/leads/*)</Label>
              <Combobox
                value={newPolicy.object}
                onChange={(value) => setNewPolicy({ ...newPolicy, object: value })}
                suggestions={suggestions?.objects || []}
                placeholder="Select or type resource path..."
                searchPlaceholder="Search resources..."
                emptyText="No resources found. Type to create new."
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="action">Action (e.g., GET, POST, .*)</Label>
              <Combobox
                value={newPolicy.action}
                onChange={(value) => setNewPolicy({ ...newPolicy, action: value })}
                suggestions={suggestions?.actions || []}
                placeholder="Select or type action..."
                searchPlaceholder="Search actions..."
                emptyText="No actions found. Type to create new."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddPolicy} disabled={addPolicyMutation.isPending}>
              {addPolicyMutation.isPending ? "Adding…" : "Add Policy"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Policy?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this policy?
              <div className="mt-2 rounded bg-muted p-2 font-mono text-sm">
                {policyToDelete?.subject} → {policyToDelete?.object} → {policyToDelete?.action}
              </div>
              {validationWarning.length > 0 && (
                <Alert variant="destructive" className="mt-4">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>
                    {validationWarning.map((w, i) => (
                      <div key={i}>{w}</div>
                    ))}
                  </AlertDescription>
                </Alert>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deletePolicyMutation.isPending}
            >
              {deletePolicyMutation.isPending ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
