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
import { toast } from "sonner";

import { PipelineColumn } from "./PipelineColumn";
import { LeadKanbanCard } from "./LeadKanbanCard";
import type { FullPipeline } from "@/types/pipeline.types";
import type { Lead } from "@/types/lead.types";

interface PipelineBoardProps {
  pipeline: FullPipeline;
}

export function PipelineBoard({ pipeline }: PipelineBoardProps) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const [activeLead, setActiveLead] = useState<Lead | null>(null);
  const [activeStageId, setActiveStageId] = useState<string | null>(null);

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

  // ✅ T2 FIX: Helper to resolve target stage ID from any droppable/sortable element
  // When dropping on a column, over.id is the stage ID directly.
  // When dropping on a card, over.data.current has { type: "card", stageId }.
  const resolveTargetStageId = (over: DragOverEvent["over"] | DragEndEvent["over"]): string | null => {
    if (!over) return null;
    const data = over.data?.current;
    if (data?.type === "column") return data.stageId as string;
    if (data?.type === "card") return data.stageId as string;
    // Fallback: check if over.id matches a known stage
    const asString = String(over.id);
    if (pipeline.stages.some((s) => s.id === asString)) return asString;
    return null;
  };

  const handleDragOver = (event: DragOverEvent) => {
    const { over } = event;
    if (!over) return;

    // ✅ T2 FIX: Resolve stage from metadata instead of assuming over.id is stageId
    const newStageId = resolveTargetStageId(over);
    if (newStageId && newStageId !== activeStageId) {
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

    // ✅ T2 FIX: Resolve target stage from metadata — works for both column and card drops
    const targetStageId = resolveTargetStageId(over);

    if (!targetStageId) {
      setActiveId(null);
      setActiveLead(null);
      setActiveStageId(null);
      return;
    }

    // Find source stage
    let sourceStageId: string | null = null;
    for (const stage of pipeline.stages) {
      if (stage.leads?.some((l) => l.id === active.id)) {
        sourceStageId = stage.id;
        break;
      }
    }

    // Drag-drop cannot directly move leads between pipeline stages.
    // Pipeline stage changes are derived from consultation status transitions
    // (each stage has multiple statuses with different business meanings).
    // User must open the lead and create a consultation to change status.
    if (sourceStageId && sourceStageId !== targetStageId) {
      toast.info("Vui lòng mở lead để chuyển trạng thái", {
        description: "Di chuyển pipeline phải qua bước tư vấn (consultation) để đảm bảo đúng nghiệp vụ.",
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
