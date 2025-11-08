// src/components/admin/policies/TemplatesTab.tsx
"use client";

import { useState } from "react";
import { FileText, Sparkles } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";

import { useTemplates, useApplyTemplate } from "@/hooks/usePolicies";
import type { TemplateInfo } from "@/types/policy.types";

export function TemplatesTab() {
  const { toast } = useToast();
  const { data, isLoading } = useTemplates();
  const applyTemplateMutation = useApplyTemplate();

  const [applyDialogOpen, setApplyDialogOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateInfo | null>(null);
  const [targetRole, setTargetRole] = useState("");

  const handleApplyTemplate = async () => {
    if (!selectedTemplate || !targetRole) {
      toast({
        title: "Validation Error",
        description: "Please enter a role name",
        variant: "destructive",
      });
      return;
    }

    try {
      const result = await applyTemplateMutation.mutateAsync({
        template_id: selectedTemplate.id,
        role: targetRole.startsWith("role:") ? targetRole : `role:${targetRole}`,
        validate: true,
      });

      toast({
        title: "Success",
        description: `Applied ${result.added} policies to ${targetRole}`,
      });
      setApplyDialogOpen(false);
      setTargetRole("");
    } catch (error: any) {
      toast({
        title: "Error",
        description: error.response?.data?.detail || "Failed to apply template",
        variant: "destructive",
      });
    }
  };

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    );
  }

  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {data?.templates.map((template) => (
          <Card key={template.id}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  {template.display_name}
                </CardTitle>
                <Badge variant={template.category === "core" ? "default" : "secondary"}>
                  {template.category}
                </Badge>
              </div>
              <CardDescription>{template.description}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="text-sm font-medium">Policies ({template.policies.length})</div>
                <div className="mt-2 max-h-32 space-y-1 overflow-y-auto rounded bg-muted p-2 text-xs">
                  {template.policies.slice(0, 5).map((policy, idx) => (
                    <div key={idx} className="font-mono">
                      {policy.object} → {policy.action}
                    </div>
                  ))}
                  {template.policies.length > 5 && (
                    <div className="text-muted-foreground">
                      +{template.policies.length - 5} more...
                    </div>
                  )}
                </div>
              </div>
              <Button
                className="w-full"
                onClick={() => {
                  setSelectedTemplate(template);
                  setApplyDialogOpen(true);
                }}
              >
                <Sparkles className="mr-2 h-4 w-4" />
                Apply Template
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Apply Template Dialog */}
      <Dialog open={applyDialogOpen} onOpenChange={setApplyDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply Template: {selectedTemplate?.display_name}</DialogTitle>
            <DialogDescription>
              This will add {selectedTemplate?.policies.length} policies to the specified role.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="role">Target Role</Label>
              <Input
                id="role"
                placeholder="role:custom_role or custom_role"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Enter role name (role: prefix optional)
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApplyDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleApplyTemplate} disabled={applyTemplateMutation.isPending}>
              {applyTemplateMutation.isPending ? "Applying..." : "Apply"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
