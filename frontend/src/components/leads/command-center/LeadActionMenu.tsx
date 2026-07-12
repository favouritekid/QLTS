// src/components/leads/command-center/LeadActionMenu.tsx
"use client";

/**
 * LeadActionMenu — menu thao tác lead DÙNG CHUNG cho panel chi tiết, hàng bảng
 * desktop (RowActions) và card mobile. Một nguồn duy nhất → 3 nơi luôn khớp
 * (trước đây card/hàng chỉ có Sửa/Xóa còn panel đủ Email/Gán/Chuyển giao → lệch).
 *
 * Mobile → MobileActionSheet, desktop → DropdownMenu (giống panel). Tự sở hữu
 * AssignLeadDialog (chuyển giao) + ReassignLeadDialog (xin đổi phụ trách).
 *
 * Thin-client: hiển thị "Chuyển giao lead" / "Yêu cầu đổi người phụ trách" theo
 * cờ lead.permissions?.can_transfer_lead / can_request_reassign do backend cấp
 * (list = LeadListItem, chi tiết = LeadDetail) — KHÔNG đọc user.role ở FE.
 */

import React, { useState } from "react";
import {
  Edit,
  Trash2,
  UserPlus,
  Mail,
  RefreshCcw,
  MoreVertical,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ReassignLeadDialog } from "@/components/leads/ReassignLeadDialog";
import type { Lead } from "@/types/lead.types";

interface LeadActionMenuProps {
  lead: Lead;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  /** "Gán cho cán bộ" khi lead CHƯA có người phụ trách (parent mở dialog gán). */
  onAssign: (lead: Lead) => void;
  /** className nút trigger. Mặc định responsive (44px touch mobile / 28px desktop). */
  triggerClassName?: string;
  /** aria-label nút trigger. */
  triggerLabel?: string;
  /** Tiêu đề action sheet mobile. */
  sheetTitle?: string;
  /** Căn dropdown desktop. */
  align?: "start" | "end" | "center";
  /**
   * Chặn click nổi lên phần tử cha (card/hàng có onClick mở panel). Bật cho
   * card/row, tắt cho panel (không có cha click-able).
   */
  stopPropagation?: boolean;
}

export function LeadActionMenu({
  lead,
  onEdit,
  onDelete,
  onAssign,
  triggerClassName,
  triggerLabel = "Mở menu thao tác",
  sheetTitle = "Thao tác",
  align = "end",
  stopPropagation = false,
}: LeadActionMenuProps) {
  const isMobile = useIsMobile();
  const [assignOpen, setAssignOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [actionSheetOpen, setActionSheetOpen] = useState(false);

  const hasOfficer = !!lead.assigned_officer;
  const canTransfer = hasOfficer && !!lead.permissions?.can_transfer_lead;
  const canReassign = hasOfficer && !!lead.permissions?.can_request_reassign;

  const triggerBtnClass = cn("h-11 w-11 sm:h-7 sm:w-7 p-0", triggerClassName);

  const handleTriggerClick = (e: React.MouseEvent) => {
    if (stopPropagation) e.stopPropagation();
  };

  return (
    <>
      {isMobile ? (
        <>
          <Button
            variant="ghost"
            size="sm"
            className={triggerBtnClass}
            onClick={(e) => {
              handleTriggerClick(e);
              setActionSheetOpen(true);
            }}
            aria-label={triggerLabel}
          >
            <MoreVertical className="h-4 w-4" />
          </Button>
          <MobileActionSheet
            open={actionSheetOpen}
            onOpenChange={setActionSheetOpen}
            title={sheetTitle}
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
            {lead.email && (
              <MobileActionSheet.Item
                icon={Mail}
                href={`mailto:${lead.email}`}
                onClick={() => setActionSheetOpen(false)}
              >
                Gửi email
              </MobileActionSheet.Item>
            )}
            <MobileActionSheet.Divider />
            {!hasOfficer && (
              <MobileActionSheet.Item
                icon={UserPlus}
                onClick={() => {
                  setActionSheetOpen(false);
                  onAssign(lead);
                }}
              >
                Gán cho cán bộ
              </MobileActionSheet.Item>
            )}
            {canTransfer && (
              <MobileActionSheet.Item
                icon={UserPlus}
                onClick={() => {
                  setActionSheetOpen(false);
                  setAssignOpen(true);
                }}
              >
                Chuyển giao lead
              </MobileActionSheet.Item>
            )}
            {canReassign && (
              <MobileActionSheet.Item
                icon={RefreshCcw}
                onClick={() => {
                  setActionSheetOpen(false);
                  setReassignOpen(true);
                }}
              >
                Yêu cầu đổi người phụ trách
              </MobileActionSheet.Item>
            )}
            <MobileActionSheet.Divider />
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
            <MobileActionSheet.Cancel onClick={() => setActionSheetOpen(false)} />
          </MobileActionSheet>
        </>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={triggerBtnClass}
              onClick={handleTriggerClick}
              aria-label={triggerLabel}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align={align} className="w-48">
            <DropdownMenuItem onClick={() => onEdit(lead)}>
              <Edit className="mr-2 h-4 w-4" />
              Chỉnh sửa
            </DropdownMenuItem>
            {lead.email && (
              <DropdownMenuItem asChild>
                <a href={`mailto:${lead.email}`}>
                  <Mail className="mr-2 h-4 w-4" />
                  Gửi email
                </a>
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            {!hasOfficer && (
              <DropdownMenuItem onClick={() => onAssign(lead)}>
                <UserPlus className="mr-2 h-4 w-4" />
                Gán cho cán bộ
              </DropdownMenuItem>
            )}
            {canTransfer && (
              <DropdownMenuItem onClick={() => setAssignOpen(true)}>
                <UserPlus className="mr-2 h-4 w-4" />
                Chuyển giao lead
              </DropdownMenuItem>
            )}
            {canReassign && (
              <DropdownMenuItem onClick={() => setReassignOpen(true)}>
                <RefreshCcw className="mr-2 h-4 w-4" />
                Yêu cầu đổi người phụ trách
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => onDelete(lead)}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Xóa lead
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Lazy-mount: chỉ dựng dialog khi thực sự mở → list N hàng KHÔNG mount N
          cặp dialog (mỗi cái gọi hook/query). Đóng dialog rồi unmount luôn. */}
      {assignOpen && (
        // Chuyển giao (manager/admin) — đổi trực tiếp người phụ trách
        <AssignLeadDialog
          open={assignOpen}
          onOpenChange={setAssignOpen}
          lead={lead}
        />
      )}
      {reassignOpen && (
        // Xin đổi phụ trách (officer được giao) — chờ manager/admin duyệt
        <ReassignLeadDialog
          open={reassignOpen}
          onOpenChange={setReassignOpen}
          lead={lead}
        />
      )}
    </>
  );
}

export default LeadActionMenu;
