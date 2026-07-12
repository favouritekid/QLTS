// src/components/leads/command-center/MobileLeadCard.tsx
/**
 * MobileLeadCard — thẻ lead mobile, 3 tầng gọn:
 *   1. Tên lead (đầy chiều rộng → đỡ bị cắt) + menu ⋮
 *   2. 🎓 Trình độ · Ngành học · Thời gian · Nguồn
 *   3. ● Trạng thái · Người tư vấn
 * Tầng 2 & 3 CÙNG cỡ chữ (text-xs). Màu consultation_status dồn vào CHẤM ●
 * (chữ để foreground vì nhiều color_code sáng như #FACC15 khó đọc). Giữ
 * SwipeToCall + LeadActionMenu + chạm mở panel. (SĐT bỏ khỏi mặt card — vẫn gọi
 * được qua vuốt-để-gọi / menu / chi tiết.)
 */
"use client";

import React from "react";
import { GraduationCap, User, UserPlus } from "lucide-react";
import { formatDistanceToNowStrict } from "date-fns";
import { vi } from "date-fns/locale";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { Checkbox } from "@/components/ui/checkbox";
import { LeadActionMenu } from "./LeadActionMenu";
import { SwipeToCall } from "@/components/common/SwipeToCall";
import { isLeadOverdue } from "@/lib/leads/overdue";
import type { Lead } from "@/types/lead.types";
import { getLeadSourceLabel, getEducationLevelLabel } from "@/constants";

interface MobileLeadCardProps {
  lead: Lead;
  isSelected?: boolean;
  isChecked?: boolean;
  onSelect: (lead: Lead) => void;
  onCheck?: (checked: boolean) => void;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  /** "Gán cho cán bộ" khi lead chưa phân công (mở dialog gán ở parent). */
  onAssign: (lead: Lead) => void;
  showCheckbox?: boolean;
}

export function MobileLeadCard({
  lead,
  isSelected,
  isChecked,
  onSelect,
  onCheck,
  onEdit,
  onDelete,
  onAssign,
  showCheckbox = false,
}: MobileLeadCardProps) {
  // Bấm card → mở panel chi tiết. LeadActionMenu/checkbox tự stopPropagation
  // nên không kích hoạt onSelect khi thao tác chúng.
  const handleCardClick = () => onSelect(lead);

  // Màu trạng thái tư vấn dồn vào CHẤM ● (chữ để foreground cho dễ đọc — nhiều
  // color_code rất sáng như #FACC15/#FBBF24 sẽ không đọc được nếu làm màu chữ).
  // fallback "" (KHÔNG mặc định #6B7280) để nhánh dot trung tính theo-theme sống.
  const statusColor = sanitizeColorCode(lead.consultation_status?.color_code, "");
  const statusName = lead.consultation_status?.name ?? "Chưa tư vấn";
  const owner = lead.assigned_officer?.full_name;
  const major =
    lead.offering?.program?.name || lead.offering?.offering_type || null;
  // "Trình độ Ngành học" = trình độ học vấn của LEAD (education_level, có nhãn VN)
  // + ngành đăng ký. Ghép phần có sẵn; rỗng cả hai → "Chưa chọn ngành".
  const eduLabel = getEducationLevelLabel(lead.education_level);
  const eduMajor = [eduLabel, major].filter(Boolean).join(" · ") || "Chưa chọn ngành";
  // Overdue tính client theo next_activity_at (cache is_overdue có thể trễ ~14h).
  const overdue = isLeadOverdue({ next_activity_at: lead.next_activity_at ?? null });
  const selected = isSelected || isChecked;

  return (
    <SwipeToCall phone={lead.phone} label={lead.full_name}>
      <div
        onClick={handleCardClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          // Chỉ act khi CHÍNH card được focus — không nuốt Enter/Space của nút
          // menu ⋮ / checkbox con (chúng bubble lên đây; guard target tránh
          // preventDefault chặn kích hoạt của chúng).
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect(lead);
          }
        }}
        className={cn(
          "virtual-card relative flex gap-2.5 rounded-xl border bg-card p-3 shadow-sm",
          "cursor-pointer touch-manipulation transition-colors active:bg-muted/50",
          selected
            ? "border-primary/50 ring-1 ring-primary/20"
            : "hover:border-border hover:bg-accent/40"
        )}
      >
        {/* Checkbox bulk-select (hiếm khi bật trên mobile) */}
        {showCheckbox && (
          <div className="shrink-0 pt-0.5" onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={isChecked}
              onCheckedChange={(c) => onCheck?.(c === true)}
              aria-label="Chọn lead"
            />
          </div>
        )}

        <div className="min-w-0 flex-1 space-y-1.5">
          {/* Tầng 1: tên lead (đầy chiều rộng) + menu */}
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-[15px] font-semibold leading-tight">
              {lead.full_name}
            </span>
            <LeadActionMenu
              lead={lead}
              onEdit={onEdit}
              onDelete={onDelete}
              onAssign={onAssign}
              variant="sheet"
              sheetTitle={lead.full_name}
              triggerClassName="h-11 w-11 sm:h-11 sm:w-11 -my-2 -mr-2"
              stopPropagation
            />
          </div>

          {/* Tầng 2: 🎓 Trình độ · Ngành học · Thời gian · Nguồn */}
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="inline-flex min-w-0 flex-1 items-center gap-1.5">
              <GraduationCap className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
              <span className="truncate text-foreground/90">{eduMajor}</span>
            </span>
            <span className="text-muted-foreground/40">·</span>
            {overdue ? (
              <span
                className="shrink-0 font-medium text-error-600 dark:text-error-500"
                suppressHydrationWarning
              >
                Quá hạn
              </span>
            ) : lead.last_consultation_at ? (
              <span className="shrink-0 tabular-nums" suppressHydrationWarning>
                {formatDistanceToNowStrict(new Date(lead.last_consultation_at), {
                  addSuffix: true,
                  locale: vi,
                })}
              </span>
            ) : (
              <span className="shrink-0 text-muted-foreground/60">Chưa liên hệ</span>
            )}
            <span className="text-muted-foreground/40">·</span>
            <span className="shrink-0 text-muted-foreground/80">
              {getLeadSourceLabel(lead.source)}
            </span>
          </div>

          {/* Tầng 3: ● Trạng thái · Người tư vấn (cùng cỡ chữ tầng 2) */}
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span
                className={cn(
                  "h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-inset ring-black/10 dark:ring-white/15",
                  !statusColor && "bg-muted-foreground/40"
                )}
                style={statusColor ? { backgroundColor: statusColor } : undefined}
              />
              <span className="truncate font-medium text-foreground/90">{statusName}</span>
            </span>
            <span className="shrink-0 text-muted-foreground/40">·</span>
            {owner ? (
              <span className="inline-flex min-w-0 flex-1 items-center gap-1">
                <User className="h-3 w-3 shrink-0 opacity-70" />
                <span className="truncate">{owner}</span>
              </span>
            ) : (
              <span className="inline-flex shrink-0 items-center gap-1 font-medium text-amber-600 dark:text-amber-500">
                <UserPlus className="h-3 w-3" />
                Chưa phân công
              </span>
            )}
          </div>
        </div>
      </div>
    </SwipeToCall>
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
  onAssignLead: (lead: Lead) => void;
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
          showCheckbox={showBulkSelect}
        />
      ))}
    </div>
  );
}

export default MobileLeadCard;
