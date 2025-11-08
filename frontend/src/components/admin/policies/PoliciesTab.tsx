// src/components/admin/policies/PoliciesTab.tsx
"use client";

import { useState } from "react";
import { Plus, Trash2, AlertTriangle } from "lucide-react";
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
import { toast } from "sonner";

import { usePolicies, useAddPolicy, useDeletePolicy, useValidatePolicy } from "@/hooks/usePolicies";
import type { PolicyRule } from "@/types/policy.types";

export function PoliciesTab() {
  const { data: policies, isLoading } = usePolicies();
  const addPolicyMutation = useAddPolicy();
  const deletePolicyMutation = useDeletePolicy();
  const validatePolicyMutation = useValidatePolicy();

  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [policyToDelete, setPolicyToDelete] = useState<PolicyRule | null>(null);
  const [validationWarning, setValidationWarning] = useState<string[]>([]);

  const [newPolicy, setNewPolicy] = useState({
    subject: "",
    object: "",
    action: "",
  });

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
    } catch (error: any) {
      toast.error(error.response?.data?.detail || "Failed to add policy");
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
    } catch (error) {
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
    } catch (error: any) {
      toast.error(error.response?.data?.detail || "Failed to delete policy");
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
                  {policies && policies.length > 0 ? (
                    policies.map((policy, index) => (
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
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={4} className="h-24 text-center">
                        No policies found
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
              <Input
                id="subject"
                placeholder="role:manager"
                value={newPolicy.subject}
                onChange={(e) => setNewPolicy({ ...newPolicy, subject: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="object">Object / Resource (e.g., /api/leads/*)</Label>
              <Input
                id="object"
                placeholder="/api/leads/*"
                value={newPolicy.object}
                onChange={(e) => setNewPolicy({ ...newPolicy, object: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="action">Action (e.g., GET, POST, .*)</Label>
              <Input
                id="action"
                placeholder="GET"
                value={newPolicy.action}
                onChange={(e) => setNewPolicy({ ...newPolicy, action: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddPolicy} disabled={addPolicyMutation.isPending}>
              {addPolicyMutation.isPending ? "Adding..." : "Add Policy"}
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
              {deletePolicyMutation.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
