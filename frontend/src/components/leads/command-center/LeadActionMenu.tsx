// src/components/leads/command-center/LeadActionMenu.tsx
"use client";

/**
 * LeadActionMenu — menu thao tác lead DÙNG CHUNG cho panel chi tiết, hàng bảng
 * desktop (RowActions) và card mobile. Một nguồn duy nhất → 3 nơi luôn khớp
 * (trước đây card/hàng chỉ có Sửa/Xóa còn panel đủ Email/Gán/Chuyển giao → lệch).
 *
 * `variant`: caller quyết định "sheet" (MobileActionSheet) vs "dropdown"
 * (DropdownMenu) — card list dùng "sheet", panel tự tính qua useIsMobile. Tránh
 * gọi useIsMobile trong CHÍNH component (list N hàng ⇒ N subscription matchMedia)
 * và khớp đúng breakpoint layout (card hiện ở <1024 nhưng useIsMobile là ≤767).
 *
 * Thin-client: Gán/Chuyển giao/Yêu cầu đổi hiển thị theo cờ
 * lead.permissions?.can_assign_lead / can_transfer_lead / can_request_reassign do
 * backend cấp (list = LeadListItem, chi tiết = LeadDetail) — KHÔNG đọc user.role FE.
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
  /**
   * Kiểu hiển thị menu. "sheet" = MobileActionSheet (card mobile), "dropdown" =
   * DropdownMenu (desktop). Panel truyền theo useIsMobile của chính nó.
   */
  variant: "sheet" | "dropdown";
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
   * card/row, tắt cho panel (không có cha click-able). Áp cho CẢ click của
   * trigger LẪN của item menu trong portal (React bubble theo cây React).
   */
  stopPropagation?: boolean;
}

export function LeadActionMenu({
  lead,
  onEdit,
  onDelete,
  onAssign,
  variant,
  triggerClassName,
  triggerLabel = "Mở menu thao tác",
  sheetTitle = "Thao tác",
  align = "end",
  stopPropagation = false,
}: LeadActionMenuProps) {
  const [assignOpen, setAssignOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  // Latch: giữ dialog mounted SAU lần mở đầu tiên (để Radix chạy animation ĐÓNG),
  // nhưng card chưa từng mở thì KHÔNG mount → list N hàng không tốn N cặp dialog.
  const [assignSeen, setAssignSeen] = useState(false);
  const [reassignSeen, setReassignSeen] = useState(false);

  const openAssign = () => {
    setAssignSeen(true);
    setAssignOpen(true);
  };
  const openReassign = () => {
    setReassignSeen(true);
    setReassignOpen(true);
  };

  // Thin-client: đọc THẲNG cờ backend (không && lại với hasOfficer — backend đã
  // gate can_transfer/reassign kèm điều kiện lead đã gán rồi).
  const hasOfficer = !!lead.assigned_officer;
  const canAssign = !hasOfficer && !!lead.permissions?.can_assign_lead;
  const canTransfer = !!lead.permissions?.can_transfer_lead;
  const canReassign = !!lead.permissions?.can_request_reassign;
  // Nhóm giữa (gán/chuyển giao/xin đổi) có mục nào không → có thì mới thêm
  // divider dưới (tránh 2 divider liền khi nhóm rỗng).
  const hasAssignGroup = canAssign || canTransfer || canReassign;

  const triggerBtnClass = cn("h-11 w-11 sm:h-7 sm:w-7 p-0", triggerClassName);

  const menu =
    variant === "sheet" ? (
      <>
        <Button
          variant="ghost"
          size="sm"
          className={triggerBtnClass}
          onClick={() => setActionSheetOpen(true)}
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
          {canAssign && (
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
                openAssign();
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
                openReassign();
              }}
            >
              Yêu cầu đổi người phụ trách
            </MobileActionSheet.Item>
          )}
          {hasAssignGroup && <MobileActionSheet.Divider />}
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
          {canAssign && (
            <DropdownMenuItem onClick={() => onAssign(lead)}>
              <UserPlus className="mr-2 h-4 w-4" />
              Gán cho cán bộ
            </DropdownMenuItem>
          )}
          {canTransfer && (
            <DropdownMenuItem onClick={openAssign}>
              <UserPlus className="mr-2 h-4 w-4" />
              Chuyển giao lead
            </DropdownMenuItem>
          )}
          {canReassign && (
            <DropdownMenuItem onClick={openReassign}>
              <RefreshCcw className="mr-2 h-4 w-4" />
              Yêu cầu đổi người phụ trách
            </DropdownMenuItem>
          )}
          {hasAssignGroup && <DropdownMenuSeparator />}
          <DropdownMenuItem
            onClick={() => onDelete(lead)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Xóa lead
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );

  // `display:contents` → span không tạo box (giữ nguyên layout flex của card),
  // nhưng vẫn là node DOM nhận sự kiện. Click từ trigger/menu-item (kể cả nội
  // dung portal của sheet/dropdown/dialog — React bubble theo cây React, không
  // theo DOM) nổi tới đây → stopPropagation, KHÔNG chạm onClick của card/hàng.
  return (
    <span
      style={{ display: "contents" }}
      onClick={stopPropagation ? (e) => e.stopPropagation() : undefined}
    >
      {menu}
      {assignSeen && (
        // Chuyển giao (manager/admin) — đổi trực tiếp người phụ trách
        <AssignLeadDialog open={assignOpen} onOpenChange={setAssignOpen} lead={lead} />
      )}
      {reassignSeen && (
        // Xin đổi phụ trách (officer được giao) — chờ manager/admin duyệt
        <ReassignLeadDialog
          open={reassignOpen}
          onOpenChange={setReassignOpen}
          lead={lead}
        />
      )}
    </span>
  );
}

export default LeadActionMenu;
