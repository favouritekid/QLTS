// src/components/leads/PipelineBoard.tsx
"use client";

import { useState, useMemo } from "react";
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  TouchSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
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

  // Touch-optimized sensor configuration
  // - TouchSensor: 250ms delay to distinguish from scroll, 5px tolerance
  // - PointerSensor: 8px distance for mouse/trackpad
  // - KeyboardSensor: Accessibility support
  const sensors = useSensors(
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 250, // Hold 250ms before drag starts (prevents accidental drags while scrolling)
        tolerance: 5, // Allow 5px movement during delay
      },
    }),
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // 8px movement required before drag starts (for mouse/trackpad)
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
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

  // Sort stages by order — memoized to prevent PipelineColumn re-renders
  const sortedStages = useMemo(
    () => [...pipeline.stages].sort((a, b) => a.order - b.order),
    [pipeline.stages]
  );

  // Get stage IDs for sortable context
  const stageIds = useMemo(
    () => sortedStages.map((stage) => stage.id),
    [sortedStages]
  );

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="flex gap-4 overflow-x-auto pb-4 snap-x snap-mandatory lg:snap-none -mx-4 px-4 lg:mx-0 lg:px-0">
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
