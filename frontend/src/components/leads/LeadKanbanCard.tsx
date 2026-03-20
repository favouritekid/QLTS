// src/components/leads/LeadKanbanCard.tsx
"use client";

import React from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Link from "next/link";
import { Mail, Phone, TrendingUp, User, Eye } from "lucide-react";

import { useClientNow } from "@/hooks/useClientNow";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Lead, LeadSource } from "@/types/lead.types";
import { getLeadSourceLabel, getLeadScoreColor } from "@/constants";

interface LeadKanbanCardProps {
  lead: Lead;
  isDragging?: boolean;
}

// Helper to get source badge color
const getSourceColor = (source: string) => {
  const colors: Record<string, string> = {
    website: "bg-info-100 text-info-800",
    referral: "bg-success-100 text-success-800",
    social_media: "bg-purple-100 text-purple-800",
    walk_in: "bg-orange-100 text-orange-800",
    email: "bg-cyan-100 text-cyan-800",
    phone: "bg-pink-100 text-pink-800",
    event: "bg-warning-100 text-warning-800",
    other: "bg-muted text-muted-foreground",
  };
  return colors[source] || colors.other;
};

export function LeadKanbanCard({ lead, isDragging = false }: LeadKanbanCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSortableDragging,
  } = useSortable({
    id: lead.id,
    // ✅ T2 FIX: Attach metadata so handleDragEnd can resolve target stage from card drops
    data: { type: "card", stageId: lead.pipeline_stage?.id },
  });

  // Hydration-safe: useClientNow() returns null on server, Date.now() after hydration
  const now = useClientNow();
  const daysInPipeline = now && lead.created_at
    ? Math.floor((now - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : null;

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isSortableDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style}>
      <Card
        className="hover:shadow-md transition-shadow"
      >
        <CardContent className="p-3 space-y-2">
          {/* Header */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 flex-1 min-w-0">
              <div className="flex-1 min-w-0">
                <Link
                  href={`/leads/${lead.id}`}
                  className="font-medium text-sm hover:underline line-clamp-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {lead.full_name}
                </Link>
                <p className="text-xs text-muted-foreground">#{lead.id}</p>
              </div>
            </div>
            <Badge
              className={`text-xs font-semibold border ${getLeadScoreColor(lead.lead_score)}`}
            >
              <TrendingUp className="h-3 w-3 mr-1" />
              {lead.lead_score}
            </Badge>
          </div>

          {/* Contact Info */}
          <div className="space-y-1">
            {lead.email && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Mail className="h-3 w-3 flex-shrink-0" />
                <span className="truncate">{lead.email}</span>
              </div>
            )}
            {lead.phone && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Phone className="h-3 w-3 flex-shrink-0" />
                <span className="truncate">{lead.phone}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-2 border-t">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={`text-xs ${getSourceColor(lead.source)}`}>
                {getLeadSourceLabel(lead.source as LeadSource)}
              </Badge>
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <User className="h-3 w-3" />
                <span>
                  {lead.assigned_officer?.full_name
                    ? lead.assigned_officer.full_name
                    : lead.assigned_officer_id
                      ? `#${lead.assigned_officer_id}`
                      : "Chưa phân công"}
                </span>
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              asChild
              onClick={(e) => e.stopPropagation()}
              aria-label="Xem chi tiết lead"
            >
              <Link href={`/leads/${lead.id}`}>
                <Eye className="h-3 w-3" />
              </Link>
            </Button>
          </div>

          {/* Time indicator - hydration safe */}
          {daysInPipeline !== null && (
            <div className="text-xs text-muted-foreground">
              {daysInPipeline} ngày trong pipeline
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
