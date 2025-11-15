// src/app/(dashboard)/admin/pipeline/page.tsx
"use client";

import { useState, useMemo } from "react"; // ✅ Thêm useMemo
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Plus, ArrowLeft, Pencil, Trash2, Workflow, FolderGit2 } from "lucide-react";
import Link from "next/link";
import {
  usePipelineStages,
  useConsultationStatuses,
  useDeletePipelineStage,
  useDeleteConsultationStatus,
} from "@/hooks/usePipeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator"; // ✅ Thêm Separator để phân cách nhóm
import { PipelineStageDialog } from "@/components/admin/PipelineStageDialog";
import { ConsultationStatusDialog } from "@/components/admin/ConsultationStatusDialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { PipelineStage, ConsultationStatus } from "@/types/pipeline.types";
import { TransitionMatrix } from "@/components/admin/pipeline/TransitionMatrix";

export default function AdminPipelinePage() {
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

  // ✅ Sắp xếp Stages theo order để hiển thị đúng thứ tự quy trình
  const sortedStages = useMemo(() => {
    return [...(stages || [])].sort((a, b) => a.order - b.order);
  }, [stages]);

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
          <TabsTrigger value="workflow" className="gap-2">
            <Workflow className="h-4 w-4" />
            Workflow Rules
          </TabsTrigger>
        </TabsList>

        {/* Pipeline Stages Tab */}
        <TabsContent value="stages" className="space-y-4">
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
              {sortedStages.map((stage) => (
                <Card key={stage.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{stage.order}</Badge>
                        <CardTitle className="text-lg">{stage.name}</CardTitle>
                        {stage.is_final_stage && <Badge variant="destructive">Final Stage</Badge>}
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

        {/* ✅ Consultation Statuses Tab (Đã nhóm theo Stage) */}
        <TabsContent value="statuses" className="space-y-6">
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              Manage consultation status options grouped by stage
            </p>
            <Button onClick={handleCreateStatus}>
              <Plus className="mr-2 h-4 w-4" /> Add Status
            </Button>
          </div>

          {statusesLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-8 w-48" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-8 w-48" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : (
            <div className="space-y-8">
              {sortedStages.map((stage) => {
                // Lọc status thuộc stage này
                const stageStatuses = statuses?.filter((s) => s.stage_id === stage.id) || [];

                return (
                  <div key={stage.id} className="space-y-3">
                    {/* Header của nhóm (Stage Name) */}
                    <div className="flex items-center gap-3">
                      <div className="bg-muted flex h-8 w-8 items-center justify-center rounded-full border text-sm font-bold">
                        {stage.order}
                      </div>
                      <h3 className="flex items-center gap-2 text-lg font-semibold">
                        {stage.name}
                        <Badge
                          variant="outline"
                          className="text-muted-foreground text-xs font-normal"
                        >
                          ID: {stage.id}
                        </Badge>
                      </h3>
                      <div className="bg-border/60 ml-2 h-px flex-1"></div>
                    </div>

                    {/* Grid Statuses của Stage này */}
                    {stageStatuses.length === 0 ? (
                      <div className="bg-muted/10 text-muted-foreground flex h-24 items-center justify-center rounded-lg border border-dashed text-sm">
                        No statuses defined for this stage
                      </div>
                    ) : (
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                        {stageStatuses.map((status) => (
                          <Card key={status.id} className="transition-shadow hover:shadow-sm">
                            <CardHeader className="p-4 pb-2">
                              <div className="flex items-start justify-between">
                                <div className="flex items-center gap-2">
                                  <div
                                    className="ring-border h-3 w-3 rounded-full ring-1 ring-offset-1"
                                    style={{ backgroundColor: status.color_code }}
                                  />
                                  <span className="font-semibold">{status.name}</span>
                                </div>
                                <div className="flex gap-1">
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7"
                                    onClick={() => handleEditStatus(status)}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="text-destructive hover:text-destructive h-7 w-7"
                                    onClick={() => setDeletingStatusId(status.id)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>
                              </div>
                            </CardHeader>
                            <CardContent className="p-4 pt-2">
                              <div className="mb-2 flex flex-wrap gap-2">
                                {/* Outcome Type Badge */}
                                <Badge
                                  variant={
                                    status.outcome_type === "positive"
                                      ? "default"
                                      : status.outcome_type === "negative"
                                        ? "destructive"
                                        : "secondary"
                                  }
                                  className={`h-5 px-1.5 text-[10px] ${
                                    status.outcome_type === "positive"
                                      ? "bg-green-600 hover:bg-green-700"
                                      : ""
                                  }`}
                                >
                                  {status.outcome_type}
                                </Badge>

                                {/* Final Status Badge */}
                                {status.is_final_status && (
                                  <Badge
                                    variant="outline"
                                    className="border-primary text-primary h-5 px-1.5 text-[10px]"
                                  >
                                    Final
                                  </Badge>
                                )}
                              </div>
                              <p className="text-muted-foreground font-mono text-xs">
                                ID: {status.id}
                              </p>
                            </CardContent>
                          </Card>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Hiển thị các Status mồ côi (nếu có - trường hợp xóa stage nhưng chưa xóa status) */}
              {statuses?.filter((s) => !stages?.find((st) => st.id === s.stage_id)).length ? (
                <div className="mt-8 space-y-3 opacity-70">
                  <div className="flex items-center gap-3">
                    <div className="bg-destructive/10 text-destructive border-destructive/20 flex h-8 w-8 items-center justify-center rounded-full border text-sm font-bold">
                      !
                    </div>
                    <h3 className="text-destructive text-lg font-semibold">
                      Orphaned Statuses (Missing Stage)
                    </h3>
                    <div className="bg-destructive/20 ml-2 h-px flex-1"></div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {statuses
                      .filter((s) => !stages?.find((st) => st.id === s.stage_id))
                      .map((status) => (
                        <Card key={status.id} className="border-destructive/30 bg-destructive/5">
                          <CardHeader className="p-4">
                            <div className="flex justify-between">
                              <span className="font-semibold">{status.name}</span>
                              <div className="flex gap-1">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="h-7 w-7"
                                  onClick={() => handleEditStatus(status)}
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="text-destructive h-7 w-7"
                                  onClick={() => setDeletingStatusId(status.id)}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </div>
                            <p className="text-destructive text-xs">
                              Stage ID: {status.stage_id} (Not found)
                            </p>
                          </CardHeader>
                        </Card>
                      ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </TabsContent>

        {/* Workflow Rules Tab */}
        <TabsContent value="workflow" className="h-[calc(100vh-250px)] space-y-4">
          <TransitionMatrix />
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
