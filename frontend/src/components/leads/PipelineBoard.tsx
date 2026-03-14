// src/components/leads/PipelineBoard.tsx
"use client";

import { useMemo } from "react";
import { DndContext } from "@dnd-kit/core";

import { PipelineColumn } from "./PipelineColumn";
import type { FullPipeline } from "@/types/pipeline.types";

interface PipelineBoardProps {
  pipeline: FullPipeline;
}

export function PipelineBoard({ pipeline }: PipelineBoardProps) {
  // Sort stages by order — memoized to prevent PipelineColumn re-renders
  const sortedStages = useMemo(
    () => [...pipeline.stages].sort((a, b) => a.order - b.order),
    [pipeline.stages]
  );

  return (
    // DndContext with no sensors — required as ancestor for useDroppable/useSortable
    // in child components, but drag cannot start without sensors.
    <DndContext>
      <div className="flex gap-4 overflow-x-auto pb-4 snap-x snap-mandatory lg:snap-none -mx-4 px-4 lg:mx-0 lg:px-0">
        {sortedStages.map((stage) => (
          <PipelineColumn
            key={stage.id}
            stage={stage}
            leads={stage.leads || []}
          />
        ))}
      </div>
    </DndContext>
  );
}
