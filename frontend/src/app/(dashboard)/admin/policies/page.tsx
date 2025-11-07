"use client";

import { useState } from "react";
import { Plus, Trash2, Shield, Info } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { useCasbinPolicies, useAddPolicy, useDeletePolicy } from "@/hooks/useCasbinPolicies";
import type { PolicyCreate } from "@/types/api.types";

// Validation schema for policy
const policySchema = z.object({
  subject: z.string().min(1, "Subject is required"),
  object: z.string().min(1, "Object is required"),
  action: z.string().min(1, "Action is required"),
});

type PolicyFormValues = z.infer<typeof policySchema>;

export default function CasbinPoliciesPage() {
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [policyToDelete, setPolicyToDelete] = useState<PolicyCreate | null>(null);

  const { data: policies, isLoading, error } = useCasbinPolicies();
  const addPolicyMutation = useAddPolicy();
  const deletePolicyMutation = useDeletePolicy();

  const form = useForm<PolicyFormValues>({
    resolver: zodResolver(policySchema),
    defaultValues: {
      subject: "",
      object: "",
      action: "",
    },
  });

  async function onSubmit(values: PolicyFormValues) {
    try {
      await addPolicyMutation.mutateAsync(values);
      setAddDialogOpen(false);
      form.reset();
    } catch {
      // Error handling is done in the mutation hook
    }
  }

  async function handleDeletePolicy() {
    if (policyToDelete) {
      await deletePolicyMutation.mutateAsync(policyToDelete);
      setPolicyToDelete(null);
    }
  }

  const isPending = addPolicyMutation.isPending || deletePolicyMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Casbin Policy Management</h1>
          <p className="text-muted-foreground">
            Manage access control policies for role-based permissions
          </p>
        </div>
        <Button onClick={() => setAddDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Policy
        </Button>
      </header>

      {/* Info Alert */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>About Casbin Policies</AlertTitle>
        <AlertDescription>
          Policies define what actions a subject (role) can perform on an object (resource). Format:
          [subject, object, action]. Example: [role:admin, /api/admin/*, *] means the admin role can
          perform any action on admin API endpoints.
        </AlertDescription>
      </Alert>

      {/* Policies Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Active Policies
          </CardTitle>
          <CardDescription>
            {policies ? `${policies.length} policies configured` : "Loading policies..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <p className="text-destructive">Error loading policies: {error.message}</p>
          )}

          {isLoading && (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}

          {!isLoading && policies && policies.length === 0 && (
            <div className="text-center py-12">
              <Shield className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground mb-2">No policies found</p>
              <p className="text-sm text-muted-foreground">
                Add your first policy to get started
              </p>
            </div>
          )}

          {!isLoading && policies && policies.length > 0 && (
            <div className="border rounded-lg overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40px]">#</TableHead>
                    <TableHead>Subject (Role)</TableHead>
                    <TableHead>Object (Resource)</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="w-[100px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {policies.map((policy, index) => {
                    const [subject, object, action] = policy;
                    return (
                      <TableRow key={`${subject}-${object}-${action}-${index}`}>
                        <TableCell className="text-muted-foreground">{index + 1}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{subject}</Badge>
                        </TableCell>
                        <TableCell>
                          <code className="text-sm bg-muted px-2 py-1 rounded">{object}</code>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{action}</Badge>
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() =>
                              setPolicyToDelete({
                                subject,
                                object,
                                action,
                              })
                            }
                            disabled={isPending}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Common Policy Examples */}
      <Card>
        <CardHeader>
          <CardTitle>Common Policy Examples</CardTitle>
          <CardDescription>Quick reference for creating policies</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="border-l-4 border-blue-500 bg-muted/50 p-3 rounded">
              <p className="text-sm font-mono">
                <strong>role:admin</strong>, <strong>/api/admin/*</strong>, <strong>*</strong>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Admin role can perform any action on all admin endpoints
              </p>
            </div>
            <div className="border-l-4 border-green-500 bg-muted/50 p-3 rounded">
              <p className="text-sm font-mono">
                <strong>role:manager</strong>, <strong>/api/leads/*</strong>, <strong>GET|POST|PUT</strong>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Manager role can read, create, and update leads
              </p>
            </div>
            <div className="border-l-4 border-yellow-500 bg-muted/50 p-3 rounded">
              <p className="text-sm font-mono">
                <strong>role:user</strong>, <strong>/api/profile</strong>, <strong>GET|PUT</strong>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                User role can view and edit their own profile
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Add Policy Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent className="sm:max-w-[550px]">
          <DialogHeader>
            <DialogTitle>Add New Policy</DialogTitle>
            <DialogDescription>
              Define a new access control policy for your application.
            </DialogDescription>
          </DialogHeader>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              {/* Subject */}
              <FormField
                control={form.control}
                name="subject"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Subject (Role)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., role:admin, role:manager, user:123"
                        {...field}
                        disabled={isPending}
                      />
                    </FormControl>
                    <FormDescription>
                      The subject that this policy applies to (usually a role like role:admin)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Object */}
              <FormField
                control={form.control}
                name="object"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Object (Resource)</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., /api/admin/*, /api/leads, /api/profile"
                        {...field}
                        disabled={isPending}
                      />
                    </FormControl>
                    <FormDescription>
                      The resource or endpoint path (* wildcard supported)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Action */}
              <FormField
                control={form.control}
                name="action"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Action</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., *, GET, POST, PUT, DELETE, GET|POST"
                        {...field}
                        disabled={isPending}
                      />
                    </FormControl>
                    <FormDescription>
                      HTTP method(s) allowed (* for all, | to separate multiple)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setAddDialogOpen(false);
                    form.reset();
                  }}
                  disabled={isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending}>
                  {isPending ? "Adding..." : "Add Policy"}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!policyToDelete} onOpenChange={() => setPolicyToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Policy?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove the following policy:
              <div className="mt-3 p-3 bg-muted rounded-md font-mono text-sm">
                <div><strong>Subject:</strong> {policyToDelete?.subject}</div>
                <div><strong>Object:</strong> {policyToDelete?.object}</div>
                <div><strong>Action:</strong> {policyToDelete?.action}</div>
              </div>
              <p className="mt-2">This action cannot be undone.</p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeletePolicy}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={isPending}
            >
              {isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
