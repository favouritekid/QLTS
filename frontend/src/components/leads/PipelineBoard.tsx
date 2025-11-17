// src/components/leads/PipelineBoard.tsx
"use client";

import { useState } from "react";
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { SortableContext, horizontalListSortingStrategy } from "@dnd-kit/sortable";

import { PipelineColumn } from "./PipelineColumn";
import { LeadKanbanCard } from "./LeadKanbanCard";
import { useMoveLeadToStage } from "@/hooks/usePipeline";
import type { FullPipeline } from "@/types/pipeline.types";
import type { Lead } from "@/types/lead.types";

interface PipelineBoardProps {
  pipeline: FullPipeline;
}

export function PipelineBoard({ pipeline }: PipelineBoardProps) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const [activeLead, setActiveLead] = useState<Lead | null>(null);
  const [activeStageId, setActiveStageId] = useState<string | null>(null);

  const moveLead = useMoveLeadToStage();

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // 8px movement required before drag starts
      },
    })
  );

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    const leadId = active.id as number;

    setActiveId(leadId);

    // Find the lead and its current stage
    for (const stage of pipeline.stages) {
      const lead = stage.leads?.find((l) => l.id === leadId);
      if (lead) {
        setActiveLead(lead);
        setActiveStageId(stage.id);
        break;
      }
    }
  };

  const handleDragOver = (event: DragOverEvent) => {
    const { over } = event;
    if (!over) return;

    // Update active stage for visual feedback
    const newStageId = over.id as string;
    if (newStageId !== activeStageId) {
      setActiveStageId(newStageId);
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || !activeLead) {
      setActiveId(null);
      setActiveLead(null);
      setActiveStageId(null);
      return;
    }

    const leadId = active.id as number;
    const targetStageId = over.id as string;

    // Find source stage
    let sourceStageId: string | null = null;
    for (const stage of pipeline.stages) {
      if (stage.leads?.some((l) => l.id === leadId)) {
        sourceStageId = stage.id;
        break;
      }
    }

    // Only move if dropped on a different stage
    if (sourceStageId && sourceStageId !== targetStageId) {
      moveLead.mutate({
        lead_id: leadId,
        from_stage_id: sourceStageId,
        to_stage_id: targetStageId,
        reason: `Moved from ${sourceStageId} to ${targetStageId}`,
      });
    }

    setActiveId(null);
    setActiveLead(null);
    setActiveStageId(null);
  };

  const handleDragCancel = () => {
    setActiveId(null);
    setActiveLead(null);
    setActiveStageId(null);
  };

  // Sort stages by order
  const sortedStages = [...pipeline.stages].sort((a, b) => a.order - b.order);

  // Get stage IDs for sortable context
  const stageIds = sortedStages.map((stage) => stage.id);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="flex gap-4 overflow-x-auto pb-4">
        <SortableContext items={stageIds} strategy={horizontalListSortingStrategy}>
          {sortedStages.map((stage) => (
            <PipelineColumn
              key={stage.id}
              stage={stage}
              leads={stage.leads || []}
              isActiveDropZone={activeStageId === stage.id && activeId !== null}
            />
          ))}
        </SortableContext>
      </div>

      {/* Drag Overlay */}
      <DragOverlay>
        {activeId && activeLead ? (
          <div className="opacity-60 rotate-3 cursor-grabbing">
            <LeadKanbanCard lead={activeLead} isDragging />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
