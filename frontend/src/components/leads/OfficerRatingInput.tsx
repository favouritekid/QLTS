// src/components/leads/OfficerRatingInput.tsx
/**
 * OfficerRatingInput - Star rating component for officers to rate leads
 * 
 * Features:
 * - 5-star rating with hover effect
 * - Tooltip explaining each rating level
 * - Auto-save when changed
 * - Shows impact on fit_score
 */
"use client";

import React, { useState } from "react";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useUpdateLead } from "@/hooks/useLeads";

interface OfficerRatingInputProps {
  leadId: number;
  currentRating: number | null;
  currentLeadScore?: number;
  className?: string;
  compact?: boolean;
  version?: number; // Optimistic locking - prevents concurrent update conflicts
}

const RATING_LABELS: Record<number, { label: string; description: string }> = {
  1: { label: "Rất thấp", description: "Không phù hợp, khó chuyển đổi" },
  2: { label: "Thấp", description: "Ít tiềm năng, cần nhiều nỗ lực" },
  3: { label: "Trung bình", description: "Bình thường, có thể chuyển đổi" },
  4: { label: "Cao", description: "Tiềm năng tốt, nên ưu tiên" },
  5: { label: "Rất cao", description: "Rất tiềm năng, ưu tiên cao nhất" },
};

export function OfficerRatingInput({
  leadId,
  currentRating,
  currentLeadScore = 0,
  className,
  compact = false,
  version,
}: OfficerRatingInputProps) {
  const [hoverRating, setHoverRating] = useState<number | null>(null);
  // Local state để UI update ngay lập tức khi click
  const [localRating, setLocalRating] = useState<number | null>(currentRating);
  const updateLead = useUpdateLead();

  // Sync local state when prop changes (e.g., after refetch)
  // BUT only if mutation is not pending - otherwise we'd lose optimistic update
  React.useEffect(() => {
    if (!updateLead.isPending) {
      setLocalRating(currentRating);
    }
  }, [currentRating, updateLead.isPending]);

  const displayRating = hoverRating ?? localRating ?? 0;
  
  // Calculate fit_score impact
  const currentFitScore = currentLeadScore + (localRating ? localRating * 4 : 0);
  const hoverFitScore = hoverRating 
    ? currentLeadScore + hoverRating * 4 
    : currentFitScore;

  const handleRate = (rating: number) => {
    // Update local state immediately for instant UI feedback
    setLocalRating(rating);
    
    updateLead.mutate(
      {
        id: leadId,
        data: { officer_rating: rating, version },
      },
      {
        onSuccess: () => {
          // Local state already updated, toast comes from useUpdateLead
        },
        onError: () => {
          // Rollback local state on error
          setLocalRating(currentRating);
        },
      }
    );
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className={cn("flex flex-col gap-1", className)}>
        {/* Stars Row */}
        <div className="flex items-center gap-0.5">
          {[1, 2, 3, 4, 5].map((star) => (
            <Tooltip key={star}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => handleRate(star)}
                  onMouseEnter={() => setHoverRating(star)}
                  onMouseLeave={() => setHoverRating(null)}
                  disabled={updateLead.isPending}
                  aria-label={`Đánh giá ${star} trên 5`}
                  className={cn(
                    "p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber-400 rounded",
                    updateLead.isPending && "opacity-50 cursor-not-allowed"
                  )}
                >
                  <Star
                    className={cn(
                      "transition-colors",
                      compact ? "h-4 w-4" : "h-5 w-5",
                      star <= displayRating
                        ? "fill-amber-400 text-amber-400"
                        : "fill-transparent text-border hover:text-amber-200"
                    )}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                <div className="font-medium">{RATING_LABELS[star].label}</div>
                <div className="text-muted-foreground">{RATING_LABELS[star].description}</div>
                <div className="text-amber-600 mt-1">
                  +{star * 4} điểm phù hợp
                </div>
              </TooltipContent>
            </Tooltip>
          ))}
          
          {/* Current rating label */}
          {!compact && currentRating && (
            <span className="ml-2 text-xs text-muted-foreground">
              {RATING_LABELS[currentRating]?.label}
            </span>
          )}
        </div>

        {/* Fit Score Impact (shown on hover) */}
        {!compact && hoverRating && hoverRating !== currentRating && (
          <div className="text-[10px] text-amber-600">
            Điểm phù hợp: {currentFitScore} → {Math.min(hoverFitScore, 100)}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

export default OfficerRatingInput;
