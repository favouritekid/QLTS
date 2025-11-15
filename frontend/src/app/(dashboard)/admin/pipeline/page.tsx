// src/app/(dashboard)/admin/pipeline/page.tsx
"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Plus, ArrowLeft, Pencil, Trash2, Workflow } from "lucide-react"; // ✅ Thêm icon Workflow
import Link from "next/link";
import {
  usePipelineStages,
  useConsultationStatuses,
  useDeletePipelineStage,
  useDeleteConsultationStatus,
} from "@/hooks/usePipeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { PipelineStageDialog } from "@/components/admin/PipelineStageDialog";
import { ConsultationStatusDialog } from "@/components/admin/ConsultationStatusDialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { PipelineStage, ConsultationStatus } from "@/types/pipeline.types";

// ✅ Import Component mới
import { TransitionMatrix } from "@/components/admin/pipeline/TransitionMatrix";

export default function AdminPipelinePage() {
  // ... [GIỮ NGUYÊN CODE HOOKS VÀ STATE CŨ] ...
  const { data: stages, isLoading: stagesLoading } = usePipelineStages();
  const { data: statuses, isLoading: statusesLoading } = useConsultationStatuses();

  const [stageDialogOpen, setStageDialogOpen] = useState(false);
  const [editingStage, setEditingStage] = useState<PipelineStage | null>(null);
  const [deletingStageId, setDeletingStageId] = useState<string | null>(null);

  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [editingStatus, setEditingStatus] = useState<ConsultationStatus | null>(null);
  const [deletingStatusId, setDeletingStatusId] = useState<string | null>(null);

  const deleteStage = useDeletePipelineStage();
  const deleteStatus = useDeleteConsultationStatus();

  // ... [GIỮ NGUYÊN CÁC HANDLER FUNCTION CŨ] ...
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

  const maxOrder = stages?.reduce((max, stage) => Math.max(max, stage.order), 0) || 0;

  return (
    <div className="container mx-auto space-y-6 py-6">
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
              Manage pipeline stages, consultation statuses, and workflow rules.
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="stages" className="space-y-6">
        <TabsList>
          <TabsTrigger value="stages">Pipeline Stages</TabsTrigger>
          <TabsTrigger value="statuses">Consultation Statuses</TabsTrigger>
          {/* ✅ Thêm Tab Trigger mới */}
          <TabsTrigger value="workflow" className="gap-2">
            <Workflow className="h-4 w-4" />
            Workflow Rules
          </TabsTrigger>
        </TabsList>

        {/* Pipeline Stages Tab (Giữ nguyên) */}
        <TabsContent value="stages" className="space-y-4">
          {/* ... Nội dung tab stages ... */}
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">Manage the stages in your lead pipeline</p>
            <Button onClick={handleCreateStage}>
              <Plus className="mr-2 h-4 w-4" /> Add Stage
            </Button>
          </div>
          {stagesLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <div className="grid gap-4">
              {stages?.map((stage) => (
                <Card key={stage.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{stage.order}</Badge>
                        <CardTitle className="text-lg">{stage.name}</CardTitle>
                        {stage.is_final_stage && (
                          <Badge variant="destructive">Final Stage</Badge>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => handleEditStage(stage)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDeletingStageId(stage.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <CardDescription>ID: {stage.id}</CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Consultation Statuses Tab (Giữ nguyên) */}
        <TabsContent value="statuses" className="space-y-4">
          {/* ... Nội dung tab statuses ... */}
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">Manage consultation status options</p>
            <Button onClick={handleCreateStatus}>
              <Plus className="mr-2 h-4 w-4" /> Add Status
            </Button>
          </div>
          {statusesLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <div className="grid gap-4">
              {statuses?.map((status) => (
                <Card key={status.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div
                          className="h-4 w-4 rounded-full"
                          style={{ backgroundColor: status.color_code }}
                        />
                        <CardTitle className="text-lg">{status.name}</CardTitle>

                        {/* Outcome Type Badge */}
                        <Badge
                          variant={
                            status.outcome_type === "positive"
                              ? "default"
                              : status.outcome_type === "negative"
                              ? "destructive"
                              : "secondary"
                          }
                          className={
                            status.outcome_type === "positive"
                              ? "bg-green-500 hover:bg-green-600"
                              : ""
                          }
                        >
                          {status.outcome_type}
                        </Badge>

                        {/* Final Status Badge */}
                        {status.is_final_status && (
                          <Badge variant="outline">Final</Badge>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleEditStatus(status)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDeletingStatusId(status.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <CardDescription>
                      ID: {status.id} | Stage: {status.stage_id}
                    </CardDescription>
                  </CardHeader>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ✅ Thêm Tab Content cho Workflow */}
        <TabsContent value="workflow" className="h-[calc(100vh-250px)] space-y-4">
          <TransitionMatrix />
        </TabsContent>
      </Tabs>

      {/* Dialogs (Giữ nguyên) */}
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
        title="Delete Stage"
        description="Are you sure?"
        confirmText="Delete"
        variant="destructive"
        isLoading={deleteStage.isPending}
      />
      <ConfirmDialog
        open={!!deletingStatusId}
        onOpenChange={(open) => !open && setDeletingStatusId(null)}
        onConfirm={handleDeleteStatus}
        title="Delete Status"
        description="Are you sure?"
        confirmText="Delete"
        variant="destructive"
        isLoading={deleteStatus.isPending}
      />
    </div>
  );
}
