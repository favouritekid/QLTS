// src/app/(dashboard)/admin/pipeline/_components/PipelineClient.tsx
"use client";

/**
 * ✅ PHASE 1 - WEEK 2 - DAY 1: Pipeline Client Component
 *
 * Handles all client-side interactions for pipeline management:
 * - Pipeline stages CRUD
 * - Consultation statuses CRUD (grouped by stage)
 * - Workflow rules (transition matrix)
 * - Dialogs and confirmations
 */

import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Plus, Pencil, Trash2, Workflow } from "lucide-react";
import {
  usePipelineStages,
  useConsultationStatuses,
  useDeletePipelineStage,
  useDeleteConsultationStatus,
} from "@/hooks/usePipeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { PipelineStageDialog } from "@/components/admin/PipelineStageDialog";
import { ConsultationStatusDialog } from "@/components/admin/ConsultationStatusDialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { PipelineStage, ConsultationStatus } from "@/types/pipeline.types";
import { TransitionMatrix } from "@/components/admin/pipeline/TransitionMatrix";

interface PipelineClientProps {
  initialData: {
    stages: PipelineStage[];
    statuses: ConsultationStatus[];
  };
}

export function PipelineClient({ initialData }: PipelineClientProps) {
  const { data: stages, isLoading: stagesLoading } = usePipelineStages({
    initialData: initialData.stages,
  });
  const { data: statuses, isLoading: statusesLoading } = useConsultationStatuses({
    initialData: initialData.statuses,
  });

  const [stageDialogOpen, setStageDialogOpen] = useState(false);
  const [editingStage, setEditingStage] = useState<PipelineStage | null>(null);
  const [deletingStageId, setDeletingStageId] = useState<string | null>(null);

  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [editingStatus, setEditingStatus] = useState<ConsultationStatus | null>(null);
  const [deletingStatusId, setDeletingStatusId] = useState<string | null>(null);

  const deleteStage = useDeletePipelineStage();
  const deleteStatus = useDeleteConsultationStatus();

  // Sort stages by order
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
    <PageContainer>
      {/* Header */}
      <PageHeader
        title="Cấu Hình Pipeline"
        description="Quản lý các giai đoạn pipeline, trạng thái tư vấn và quy tắc workflow."
        backButton={{ href: "/admin", label: "Quay lại Admin" }}
      />

      {/* Tabs */}
      <Tabs defaultValue="stages" className="space-y-6">
        <TabsList>
          <TabsTrigger value="stages">Giai Đoạn Pipeline</TabsTrigger>
          <TabsTrigger value="statuses">Trạng Thái Tư Vấn</TabsTrigger>
          <TabsTrigger value="workflow" className="gap-2">
            <Workflow className="h-4 w-4" />
            Quy Tắc Workflow
          </TabsTrigger>
        </TabsList>

        {/* Pipeline Stages Tab */}
        <TabsContent value="stages" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">Quản lý các giai đoạn trong pipeline lead</p>
            <Button onClick={handleCreateStage}>
              <Plus className="mr-2 h-4 w-4" /> Thêm giai đoạn
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
                        {stage.is_final_stage && <Badge variant="destructive">Giai đoạn cuối</Badge>}
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => handleEditStage(stage)} aria-label="Chỉnh sửa giai đoạn">
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDeletingStageId(stage.id)}
                          aria-label="Xóa giai đoạn"
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

        {/* Consultation Statuses Tab (Grouped by Stage) */}
        <TabsContent value="statuses" className="space-y-6">
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              Quản lý các tùy chọn trạng thái tư vấn theo giai đoạn
            </p>
            <Button onClick={handleCreateStatus}>
              <Plus className="mr-2 h-4 w-4" /> Thêm trạng thái
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
                        Chưa có trạng thái cho giai đoạn này
                      </div>
                    ) : (
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                        {stageStatuses.map((status) => (
                          <Card key={status.id} className="transition-shadow hover:shadow-sm">
                            <CardHeader className="p-4 pb-2">
                              <div className="flex items-start justify-between">
                                <div className="flex items-center gap-2">
                                  <ColorDot color={status.color_code} size="md" className="ring-border ring-1 ring-offset-1" />
                                  <span className="font-semibold">{status.name}</span>
                                </div>
                                <div className="flex gap-1">
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7"
                                    onClick={() => handleEditStatus(status)}
                                    aria-label="Chỉnh sửa trạng thái"
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="text-destructive hover:text-destructive h-7 w-7"
                                    onClick={() => setDeletingStatusId(status.id)}
                                    aria-label="Xóa trạng thái"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>
                              </div>
                            </CardHeader>
                            <CardContent className="p-4 pt-2">
                              <div className="mb-2 flex flex-wrap gap-2">
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
                                      ? "bg-success-600 hover:bg-success-700"
                                      : ""
                                  }`}
                                >
                                  {status.outcome_type}
                                </Badge>

                                {status.is_final && (
                                  <Badge
                                    variant="outline"
                                    className="border-primary text-primary h-5 px-1.5 text-[10px]"
                                  >
                                    Cuối
                                  </Badge>
                                )}

                                {status.is_universal && (
                                  <Badge
                                    variant="outline"
                                    className="border-amber-500 text-amber-700 bg-amber-50 h-5 px-1.5 text-[10px]"
                                  >
                                    Toàn cầu
                                  </Badge>
                                )}

                                {!status.updates_pipeline && (
                                  <Badge
                                    variant="outline"
                                    className="border-info-500 text-info-700 bg-info-50 h-5 px-1.5 text-[10px]"
                                  >
                                    Không cập nhật
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

              {/* Orphaned Statuses (Missing Stage) */}
              {statuses?.filter((s) => !stages?.find((st) => st.id === s.stage_id)).length ? (
                <div className="mt-8 space-y-3 opacity-70">
                  <div className="flex items-center gap-3">
                    <div className="bg-destructive/10 text-destructive border-destructive/20 flex h-8 w-8 items-center justify-center rounded-full border text-sm font-bold">
                      !
                    </div>
                    <h3 className="text-destructive text-lg font-semibold">
                      Trạng Thái Mồ Côi (Thiếu Giai Đoạn)
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
                                  aria-label="Chỉnh sửa trạng thái"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="text-destructive h-7 w-7"
                                  onClick={() => setDeletingStatusId(status.id)}
                                  aria-label="Xóa trạng thái"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </div>
                            <p className="text-destructive text-xs">
                              Stage ID: {status.stage_id} (Không tìm thấy)
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
        title="Xoá giai đoạn"
        description="Bạn có chắc?"
        confirmText="Xoá"
        variant="destructive"
        isLoading={deleteStage.isPending}
      />
      <ConfirmDialog
        open={!!deletingStatusId}
        onOpenChange={(open) => !open && setDeletingStatusId(null)}
        onConfirm={handleDeleteStatus}
        title="Xoá trạng thái"
        description="Bạn có chắc?"
        confirmText="Xoá"
        variant="destructive"
        isLoading={deleteStatus.isPending}
      />
    </PageContainer>
  );
}
