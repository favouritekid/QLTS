// src/components/leads/command-center/MobileLeadCard.tsx
/**
 * MobileLeadCard - Card-based lead display for mobile devices
 *
 * Uses BaseCard System for consistent layout.
 * Provides a touch-friendly interface for viewing and interacting with leads.
 */
"use client";

import React from "react";
import { Phone, MoreVertical, Zap, Edit, Trash2, UserPlus, ArrowRightLeft } from "lucide-react";
import { sanitizeColorCode } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DynamicColorBadge } from "@/components/ui/dynamic-color-badge";
import { UrgencyBadge } from "@/components/common/UrgencyBadge";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import {
  BaseCard,
  CardHeader,
  CardBody,
  CardField,
  CardMeta,
  CardTime,
  CardActions,
} from "@/components/ui/base-card";
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

  // Handle card click - only trigger if action sheet is closed
  const handleCardClick = () => {
    if (!actionSheetOpen) {
      onSelect(lead);
    }
  };

  return (
    <BaseCard
      selected={isSelected || isChecked}
      onSelect={(checked) => onCheck?.(checked)}
      showCheckbox={showCheckbox}
      onClick={handleCardClick}
      className="active:bg-muted/50"
    >
      {/* Header: Name + Urgency Badge */}
      <CardHeader
        title={lead.full_name}
        badge={
          lead.cached_urgency_score !== undefined && lead.cached_urgency_score > 0 ? (
            <UrgencyBadge score={lead.cached_urgency_score} compact />
          ) : undefined
        }
      />

      {/* Body: Phone number */}
      <CardBody>
        <CardField
          icon={<Phone className="h-3 w-3" />}
          label="SĐT"
          value={lead.phone || "Chưa có"}
        />
      </CardBody>

      {/* Meta: Stage + Source + Score + Last activity */}
      <CardMeta>
        {/* Stage badge */}
        {lead.pipeline_stage && (
          <DynamicColorBadge color={stageColor}>
            {lead.pipeline_stage.name}
          </DynamicColorBadge>
        )}

        {/* Source */}
        <Badge variant="outline">
          {getSourceLabel(lead.source)}
        </Badge>

        {/* Lead score (if high) */}
        {lead.lead_score > 70 && (
          <Badge
            variant="secondary"
            className="bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
          >
            <Zap className="h-2.5 w-2.5 mr-0.5" />
            {lead.lead_score}
          </Badge>
        )}

        {/* Last activity */}
        {lead.last_consultation_at && (
          <CardTime date={lead.last_consultation_at} format="date" className="ml-auto" />
        )}
      </CardMeta>

      {/* Actions */}
      <CardActions>
        <Button
          variant="ghost"
          size="icon"
          className="h-10 w-10"
          onClick={() => setActionSheetOpen(true)}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </CardActions>

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
    </BaseCard>
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
