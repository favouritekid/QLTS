// src/app/(dashboard)/admin/pipeline/page.tsx
"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Plus, ArrowLeft, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePipelineStages, useConsultationStatuses, useDeletePipelineStage, useDeleteConsultationStatus } from "@/hooks/usePipeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { PipelineStageDialog } from "@/components/admin/PipelineStageDialog";
import { ConsultationStatusDialog } from "@/components/admin/ConsultationStatusDialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { PipelineStage, ConsultationStatus } from "@/types/pipeline.types";

export default function AdminPipelinePage() {
  const { data: stages, isLoading: stagesLoading } = usePipelineStages();
  const { data: statuses, isLoading: statusesLoading } = useConsultationStatuses();

  // Dialog state for Pipeline Stages
  const [stageDialogOpen, setStageDialogOpen] = useState(false);
  const [editingStage, setEditingStage] = useState<PipelineStage | null>(null);
  const [deletingStageId, setDeletingStageId] = useState<string | null>(null);

  // Dialog state for Consultation Statuses
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [editingStatus, setEditingStatus] = useState<ConsultationStatus | null>(null);
  const [deletingStatusId, setDeletingStatusId] = useState<string | null>(null);

  // Delete mutations
  const deleteStage = useDeletePipelineStage();
  const deleteStatus = useDeleteConsultationStatus();

  // Handlers for Pipeline Stages
  const handleCreateStage = () => {
    setEditingStage(null);
    setStageDialogOpen(true);
  };

  const handleEditStage = (stage: PipelineStage) => {
    setEditingStage(stage);
    setStageDialogOpen(true);
  };

  const handleDeleteStage = async () => {
    if (deletingStageId) {
      await deleteStage.mutateAsync(deletingStageId);
      setDeletingStageId(null);
    }
  };

  // Handlers for Consultation Statuses
  const handleCreateStatus = () => {
    setEditingStatus(null);
    setStatusDialogOpen(true);
  };

  const handleEditStatus = (status: ConsultationStatus) => {
    setEditingStatus(status);
    setStatusDialogOpen(true);
  };

  const handleDeleteStatus = async () => {
    if (deletingStatusId) {
      await deleteStatus.mutateAsync(deletingStatusId);
      setDeletingStatusId(null);
    }
  };

  // Get max order for new stages
  const maxOrder = stages?.reduce((max, stage) => Math.max(max, stage.order), 0) || 0;

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/admin">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div>
            <h1 className="text-3xl font-bold">Pipeline Settings</h1>
            <p className="text-muted-foreground">
              Manage pipeline stages and consultation statuses
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="stages" className="space-y-6">
        <TabsList>
          <TabsTrigger value="stages">Pipeline Stages</TabsTrigger>
          <TabsTrigger value="statuses">Consultation Statuses</TabsTrigger>
        </TabsList>

        {/* Pipeline Stages Tab */}
        <TabsContent value="stages" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Manage the stages in your lead pipeline
            </p>
            <Button onClick={handleCreateStage}>
              <Plus className="h-4 w-4 mr-2" />
              Add Stage
            </Button>
          </div>

          {stagesLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4">
              {stages?.map((stage) => (
                <Card key={stage.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Badge variant="outline" className="text-sm">
                          Order: {stage.order}
                        </Badge>
                        <CardTitle className="text-lg">{stage.name}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm" onClick={() => handleEditStage(stage)}>
                          <Pencil className="h-4 w-4 mr-2" />
                          Edit
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setDeletingStageId(stage.id)}>
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </Button>
                      </div>
                    </div>
                    <CardDescription>Stage ID: {stage.id}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-6 text-sm">
                      <div>
                        <span className="text-muted-foreground">Total Leads:</span>
                        <span className="ml-2 font-medium">{stage.lead_count || 0}</span>
                      </div>
                      {stage.conversion_rate !== undefined && (
                        <div>
                          <span className="text-muted-foreground">Conversion Rate:</span>
                          <span className="ml-2 font-medium">
                            {(stage.conversion_rate * 100).toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Consultation Statuses Tab */}
        <TabsContent value="statuses" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Manage consultation status options
            </p>
            <Button onClick={handleCreateStatus}>
              <Plus className="h-4 w-4 mr-2" />
              Add Status
            </Button>
          </div>

          {statusesLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4">
              {statuses?.map((status) => (
                <Card key={status.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: status.color_code }}
                        />
                        <CardTitle className="text-lg">{status.name}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm" onClick={() => handleEditStatus(status)}>
                          <Pencil className="h-4 w-4 mr-2" />
                          Edit
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setDeletingStatusId(status.id)}>
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </Button>
                      </div>
                    </div>
                    <CardDescription>Status ID: {status.id}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">Stage:</span>
                        <span className="ml-2 font-medium">{status.stage_id}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Color:</span>
                        <span className="ml-2 font-medium">{status.color_code}</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <PipelineStageDialog
        open={stageDialogOpen}
        onOpenChange={setStageDialogOpen}
        stage={editingStage}
        maxOrder={maxOrder}
      />

      <ConsultationStatusDialog
        open={statusDialogOpen}
        onOpenChange={setStatusDialogOpen}
        status={editingStatus}
      />

      <ConfirmDialog
        open={!!deletingStageId}
        onOpenChange={(open) => !open && setDeletingStageId(null)}
        onConfirm={handleDeleteStage}
        title="Delete Pipeline Stage"
        description="Are you sure you want to delete this pipeline stage? This action cannot be undone. All leads in this stage will need to be reassigned."
        confirmText="Delete"
        variant="destructive"
        isLoading={deleteStage.isPending}
      />

      <ConfirmDialog
        open={!!deletingStatusId}
        onOpenChange={(open) => !open && setDeletingStatusId(null)}
        onConfirm={handleDeleteStatus}
        title="Delete Consultation Status"
        description="Are you sure you want to delete this consultation status? This action cannot be undone."
        confirmText="Delete"
        variant="destructive"
        isLoading={deleteStatus.isPending}
      />
    </div>
  );
}
