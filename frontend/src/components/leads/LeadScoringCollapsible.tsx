// src/components/leads/LeadScoringCollapsible.tsx
/**
 * LeadScoringCollapsible - Collapsible scoring cards display
 *
 * Shows lead scores (overall, engagement, fit, urgency) in a compact,
 * collapsible format to save vertical space while keeping info accessible.
 */
"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  TrendingUp,
  Heart,
  Target,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getLeadScoreTextColor } from "@/constants";
import type { Lead, LeadInsights } from "@/types/lead.types";

interface LeadScoringCollapsibleProps {
  lead: Lead;
  insights?: LeadInsights | null;
  defaultExpanded?: boolean;
  className?: string;
}

const getScoreLabel = (score: number) => {
  if (score >= 70) return "Cao";
  if (score >= 50) return "TB";
  if (score >= 30) return "Thấp";
  return "Yếu";
};

// Mini score badge component
function ScoreBadge({
  icon: Icon,
  label,
  value,
  className,
}: {
  icon: React.ElementType;
  label: string;
  value: number | null;
  className?: string;
}) {
  const isNull = value === null;
  const colorClass = isNull ? "text-muted-foreground bg-muted" : getLeadScoreTextColor(value);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className={cn("p-1.5 rounded-md", colorClass)}>
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">
          {label}
        </p>
        <p className={cn("text-sm font-bold", isNull ? "text-muted-foreground" : colorClass.split(" ")[0])}>
          {isNull ? "—" : value}
        </p>
      </div>
    </div>
  );
}

export function LeadScoringCollapsible({
  lead,
  insights,
  defaultExpanded = false,
  className,
}: LeadScoringCollapsibleProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const overallScore = lead.lead_score;
  const engagementScore = insights?.engagement_score ?? null;
  const fitScore = insights?.fit_score ?? null;
  const urgencyScore = lead.cached_urgency_score;

  return (
    <div className={cn("border rounded-lg bg-card", className)}>
      {/* Header - Always visible */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-medium">Điểm đánh giá</span>
        </div>

        {/* Summary when collapsed */}
        {!isExpanded && (
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold",
                getLeadScoreTextColor(overallScore)
              )}
            >
              <TrendingUp className="h-3 w-3" />
              {overallScore}
              <span className="text-[10px] font-normal opacity-80">
                ({getScoreLabel(overallScore)})
              </span>
            </div>
          </div>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 pb-3 pt-1 border-t">
          {/* Main Score */}
          <div
            className={cn(
              "flex items-center justify-between p-3 rounded-lg mb-3",
              getLeadScoreTextColor(overallScore)
            )}
          >
            <div className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              <div>
                <p className="text-xs opacity-80">Điểm tổng hợp</p>
                <p className="text-2xl font-bold">{overallScore}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-sm font-medium">{getScoreLabel(overallScore)}</p>
              <p className="text-xs opacity-70">
                {lead.is_hot_lead ? "Hot Lead" : "Lead thường"}
              </p>
            </div>
          </div>

          {/* Detail Scores Grid */}
          <div className="grid grid-cols-3 gap-2">
            <ScoreBadge
              icon={Heart}
              label="Engagement"
              value={engagementScore}
            />
            <ScoreBadge
              icon={Target}
              label="Phù hợp"
              value={fitScore}
            />
            <ScoreBadge
              icon={Zap}
              label="Khẩn cấp"
              value={urgencyScore}
            />
          </div>

          {/* Officer Rating if available */}
          {insights?.officer_rating && (
            <div className="mt-3 pt-3 border-t">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Đánh giá tư vấn viên</span>
                <div className="flex items-center gap-1">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <span
                      key={i}
                      className={cn(
                        "text-sm",
                        i < (insights.officer_rating ?? 0)
                          ? "text-warning-500"
                          : "text-border"
                      )}
                    >
                      ★
                    </span>
                  ))}
                </div>
              </div>
              {insights.officer_summary && (
                <p className="mt-1 text-xs text-muted-foreground italic">
                  &quot;{insights.officer_summary}&quot;
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default LeadScoringCollapsible;
