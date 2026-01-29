// src/components/leads/command-center/MobileLeadCard.tsx
/**
 * MobileLeadCard - Card-based lead display for mobile devices
 *
 * Provides a touch-friendly interface for viewing and interacting with leads
 * on mobile devices. Shows key information at a glance with swipe actions.
 */
"use client";

import React from "react";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import { Phone, MoreVertical, ChevronRight, Zap } from "lucide-react";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DynamicColorBadge } from "@/components/ui/dynamic-color-badge";
import { UrgencyBadge } from "@/components/common/UrgencyBadge";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import { Edit, Trash2, UserPlus, ArrowRightLeft } from "lucide-react";
import type { Lead } from "@/types/lead.types";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import { STAGE_COLORS } from "@/types/pipeline.types";

interface MobileLeadCardProps {
  lead: Lead;
  isSelected?: boolean;
  isChecked?: boolean;
  onSelect: (lead: Lead) => void;
  onCheck?: (checked: boolean) => void;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign?: (lead: Lead) => void;
  onChangeStage?: (lead: Lead) => void;
  showCheckbox?: boolean;
}

const getSourceLabel = (value: string) =>
  LEAD_SOURCE_OPTIONS.find((o) => o.value === value)?.label || value;

export function MobileLeadCard({
  lead,
  isSelected,
  isChecked,
  onSelect,
  onCheck,
  onEdit,
  onDelete,
  onAssign,
  onChangeStage,
  showCheckbox = false,
}: MobileLeadCardProps) {
  const [actionSheetOpen, setActionSheetOpen] = React.useState(false);

  // Get stage color
  const stageColor = sanitizeColorCode(lead.pipeline_stage?.color_code) ||
    STAGE_COLORS[lead.pipeline_stage?.id || ""] ||
    "#6B7280";

  // Format last activity
  const lastActivity = lead.last_consultation_at
    ? format(new Date(lead.last_consultation_at), "dd/MM", { locale: vi })
    : null;

  return (
    <div
      className={cn(
        "relative flex items-start gap-3 rounded-lg border bg-card p-3",
        "transition-all duration-150 active:bg-muted/50",
        isSelected && "border-primary bg-primary/5 ring-1 ring-primary/20"
      )}
    >
      {/* Checkbox (optional) */}
      {showCheckbox && (
        <div className="pt-0.5">
          <Checkbox
            checked={isChecked}
            onCheckedChange={(checked) => onCheck?.(!!checked)}
            aria-label={`Chọn ${lead.full_name}`}
            className="h-5 w-5"
          />
        </div>
      )}

      {/* Main content - Tappable area */}
      <button
        type="button"
        className="flex-1 min-w-0 text-left"
        onClick={() => onSelect(lead)}
      >
        {/* Top row: Name + Urgency */}
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-sm truncate flex-1">
            {lead.full_name}
          </span>
          {lead.cached_urgency_score !== undefined && lead.cached_urgency_score > 0 && (
            <UrgencyBadge score={lead.cached_urgency_score} compact />
          )}
        </div>

        {/* Phone number */}
        <div className="flex items-center gap-1.5 text-muted-foreground text-xs mb-2">
          <Phone className="h-3 w-3" />
          <span>{lead.phone || "Chưa có SĐT"}</span>
        </div>

        {/* Bottom row: Stage + Source + Score */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Stage badge */}
          {lead.pipeline_stage && (
            <DynamicColorBadge
              color={stageColor}
              className="text-[10px] h-5 px-1.5"
            >
              {lead.pipeline_stage.name}
            </DynamicColorBadge>
          )}

          {/* Source */}
          <Badge variant="outline" className="text-[10px] h-5 px-1.5">
            {getSourceLabel(lead.source)}
          </Badge>

          {/* Lead score (if high) */}
          {lead.lead_score > 70 && (
            <Badge
              variant="secondary"
              className="text-[10px] h-5 px-1.5 bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
            >
              <Zap className="h-2.5 w-2.5 mr-0.5" />
              {lead.lead_score}
            </Badge>
          )}

          {/* Last activity */}
          {lastActivity && (
            <span className="text-[10px] text-muted-foreground ml-auto">
              {lastActivity}
            </span>
          )}
        </div>
      </button>

      {/* Actions */}
      <div className="flex items-center gap-1">
        {/* More actions button */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            setActionSheetOpen(true);
          }}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>

        {/* Chevron indicator */}
        <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
      </div>

      {/* Action Sheet */}
      <MobileActionSheet
        open={actionSheetOpen}
        onOpenChange={setActionSheetOpen}
        title={lead.full_name}
      >
        <MobileActionSheet.Item
          icon={Edit}
          onClick={() => {
            setActionSheetOpen(false);
            onEdit(lead);
          }}
        >
          Chỉnh sửa
        </MobileActionSheet.Item>
        {onAssign && (
          <MobileActionSheet.Item
            icon={UserPlus}
            onClick={() => {
              setActionSheetOpen(false);
              onAssign(lead);
            }}
          >
            Gán cán bộ
          </MobileActionSheet.Item>
        )}
        {onChangeStage && (
          <MobileActionSheet.Item
            icon={ArrowRightLeft}
            onClick={() => {
              setActionSheetOpen(false);
              onChangeStage(lead);
            }}
          >
            Đổi giai đoạn
          </MobileActionSheet.Item>
        )}
        <MobileActionSheet.Item
          icon={Trash2}
          variant="destructive"
          onClick={() => {
            setActionSheetOpen(false);
            onDelete(lead);
          }}
        >
          Xóa lead
        </MobileActionSheet.Item>
      </MobileActionSheet>
    </div>
  );
}

// =============================================================================
// MOBILE LEAD LIST - Container for card list with bulk selection
// =============================================================================

interface MobileLeadListProps {
  leads: Lead[];
  selectedLeadId: number | null;
  onSelectLead: (lead: Lead) => void;
  onEditLead: (lead: Lead) => void;
  onDeleteLead: (lead: Lead) => void;
  onAssignLead?: (lead: Lead) => void;
  onChangeStage?: (lead: Lead) => void;
  // Bulk selection
  selectedLeads?: Lead[];
  onSelectionChange?: (leads: Lead[]) => void;
  showBulkSelect?: boolean;
}

export function MobileLeadList({
  leads,
  selectedLeadId,
  onSelectLead,
  onEditLead,
  onDeleteLead,
  onAssignLead,
  onChangeStage,
  selectedLeads = [],
  onSelectionChange,
  showBulkSelect = false,
}: MobileLeadListProps) {
  const selectedIds = new Set(selectedLeads.map((l) => l.id));

  const handleCheck = (lead: Lead, checked: boolean) => {
    if (!onSelectionChange) return;

    if (checked) {
      onSelectionChange([...selectedLeads, lead]);
    } else {
      onSelectionChange(selectedLeads.filter((l) => l.id !== lead.id));
    }
  };

  if (leads.length === 0) {
    return null; // Empty state handled by parent
  }

  return (
    <div className="space-y-2 p-3">
      {leads.map((lead) => (
        <MobileLeadCard
          key={lead.id}
          lead={lead}
          isSelected={selectedLeadId === lead.id}
          isChecked={selectedIds.has(lead.id)}
          onSelect={onSelectLead}
          onCheck={(checked) => handleCheck(lead, checked)}
          onEdit={onEditLead}
          onDelete={onDeleteLead}
          onAssign={onAssignLead}
          onChangeStage={onChangeStage}
          showCheckbox={showBulkSelect}
        />
      ))}
    </div>
  );
}

export default MobileLeadCard;
