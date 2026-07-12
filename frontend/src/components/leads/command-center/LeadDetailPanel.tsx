// src/components/leads/command-center/LeadDetailPanel.tsx
"use client";

import React, { useRef, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { isLeadOverdue } from "@/lib/leads/overdue";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Edit,
  Trash2,
  UserPlus,
  Phone,
  Mail,
  MapPin,
  GraduationCap,
  User,
  Zap,
  History,
  ExternalLink,
  RefreshCcw,
  MoreVertical,
  FileText,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import { DynamicColorBadge } from "@/components/ui/dynamic-color-badge";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSectionV2 } from "@/components/leads/QuickConsultationSectionV2";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ReassignLeadDialog } from "@/components/leads/ReassignLeadDialog";
import { CopyableCell } from "@/components/common/CopyableCell";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { getEducationLevelLabel } from "@/constants";
import { getStatusConfig, getStatusDotColor } from "@/lib/status-config";
import { OfficerRatingInput } from "@/components/leads/OfficerRatingInput";
import type { Lead } from "@/types/lead.types";

interface LeadDetailPanelProps {
  leadId: number | null;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign: (lead: Lead) => void;
}

// ✅ TECHNICAL DEBT FIX: Status badge color helper
const getAssignmentStatusColor = (status: string) => {
  switch (status) {
    case "pending":
      return "bg-warning-100 text-warning-700 border-warning-200";
    case "assigned":
      return "bg-success-100 text-success-700 border-success-200";
    case "failed":
      return "bg-error-100 text-error-700 border-error-200";
    case "reassign_pending":
      return "bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-900/50 dark:text-orange-300 dark:border-orange-800";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
};

const getAssignmentStatusLabel = (status: string) => {
  switch (status) {
    case "pending":
      return "Chờ phân công";
    case "assigned":
      return "Đã phân công";
    case "failed":
      return "Phân công thất bại";
    case "reassign_pending":
      return "Chờ phân công lại";
    default:
      return status;
  }
};

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export function LeadDetailPanel({ leadId, onEdit, onDelete, onAssign }: LeadDetailPanelProps) {
  const { data: lead, isLoading, isError, refetch } = useLead(leadId || 0, !!leadId);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const isMobile = useIsMobile();

  // ✅ FIX: Calculate days since contact in useEffect to avoid impure Date.now() in render
  // Also prevents hydration mismatch (useState defaults to null, matching SSR)
  const [daysSinceContact, setDaysSinceContact] = useState<number | null>(null);
  useEffect(() => {
    // Intentional setState: synchronizing display value with system time
    // This is a valid use case per React docs for external system synchronization
    /* eslint-disable react-hooks/set-state-in-effect */
    if (!lead?.last_consultation_at) {
      setDaysSinceContact(null);
      return;
    }
    const days = Math.floor(
      (Date.now() - new Date(lead.last_consultation_at).getTime()) / (1000 * 60 * 60 * 24)
    );
    setDaysSinceContact(days);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [lead?.last_consultation_at]);

  // ✅ Tính is_overdue ở client (theo next_activity_at) thay vì tin field cache
  // lead.is_overdue — cache đó chỉ refresh ở mutation/nightly nên có thể "tàng
  // hình" tới ~14h. useState(false) khớp SSR (tránh hydration mismatch); effect
  // đồng bộ theo system time, chạy lại khi mốc hẹn đổi.
  const [isOverdue, setIsOverdue] = useState(false);
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setIsOverdue(isLeadOverdue({ next_activity_at: lead?.next_activity_at ?? null }));
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [lead?.next_activity_at]);

  // Auto-scroll to top when leadId changes
  useEffect(() => {
    if (leadId && scrollAreaRef.current) {
      scrollAreaRef.current.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [leadId]);

  // Empty state
  if (!leadId) {
    return (
      <div className="bg-muted/20 flex h-full items-center justify-center">
        <div className="space-y-3 text-center">
          <div className="bg-muted mx-auto flex h-12 w-12 items-center justify-center rounded-full">
            <User className="text-muted-foreground h-6 w-6" />
          </div>
          <div>
            <p className="text-muted-foreground font-medium">Chọn lead để xem chi tiết</p>
            <p className="text-muted-foreground/70 text-sm">Chọn lead trong danh sách</p>
          </div>
        </div>
      </div>
    );
  }

  // Error state — fetch lỗi (network/403/404). Tránh kẹt skeleton vĩnh viễn:
  // báo rõ + cho thử lại (mẫu như trang /leads/[id]).
  if (isError) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <div className="max-w-xs space-y-3 text-center">
          <div className="bg-error-50 dark:bg-error-950/40 mx-auto flex h-12 w-12 items-center justify-center rounded-full">
            <AlertCircle className="text-error-500 h-6 w-6" />
          </div>
          <div>
            <p className="text-foreground font-medium">Không tải được thông tin lead</p>
            <p className="text-muted-foreground text-sm">
              Có thể do mất mạng hoặc bạn không có quyền xem lead này.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
            Thử lại
          </Button>
        </div>
      </div>
    );
  }

  // Loading state
  if (isLoading || !lead) {
    return (
      <div className="h-full space-y-4 p-4">
        <div className="flex items-center gap-4">
          <Skeleton className="h-16 w-16 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div
      key={leadId}
      className="flex h-full flex-col"
    >
      {/* Header - Mobile Optimized, Full Width Rows */}
      {/* Note: pr-10 to avoid Sheet close button overlap */}
      <div className="bg-background shrink-0 border-b p-3 pr-10 space-y-2">
        {/* Row 1: Avatar + Name + Assignment Status */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Avatar className="h-9 w-9 shrink-0">
              <AvatarFallback className="bg-primary/10 text-primary text-xs font-semibold">
                {getInitials(lead.full_name)}
              </AvatarFallback>
            </Avatar>
            <h2 className="truncate text-base font-semibold font-display">
              {lead.full_name}
            </h2>
          </div>
          {lead.assignment_status && (
            <Badge
              variant="outline"
              className={cn("text-xs shrink-0", getAssignmentStatusColor(lead.assignment_status))}
            >
              {getAssignmentStatusLabel(lead.assignment_status)}
            </Badge>
          )}
        </div>

        {/* Row 2: Status Badges - space between */}
        <div className="flex items-center justify-between gap-2">
          {/* Pipeline Stage Badge */}
          {lead.pipeline_stage ? (() => {
            const stageColor =
              sanitizeColorCode(lead.pipeline_stage.color_code) || STAGE_COLORS[lead.pipeline_stage.id];
            return (
              <Badge
                variant="outline"
                className={cn("border-0 font-medium text-xs", stageColor && "text-white")}
                style={{ backgroundColor: stageColor || undefined }}
              >
                {lead.pipeline_stage.name}
              </Badge>
            );
          })() : <span />}

          {/* Consultation Status Badge */}
          {lead.consultation_status ? (
            <DynamicColorBadge
              color={lead.consultation_status.color_code}
              variant="subtle"
              size="sm"
            >
              {lead.consultation_status.name}
            </DynamicColorBadge>
          ) : <span />}
        </div>

        {/* Row 3: Action Buttons - space between */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" className="h-11 sm:h-7 px-2 text-xs" asChild>
              <Link href={`/leads/${lead.id}`}>
                <ExternalLink className="h-3.5 w-3.5 mr-1" />
                Xem
              </Link>
            </Button>
            <Button variant="outline" size="sm" className="h-11 sm:h-7 px-2 text-xs" asChild>
              <a href={`tel:${lead.phone}`}>
                <Phone className="h-3.5 w-3.5 mr-1" />
                Gọi
              </a>
            </Button>
            <Button variant="outline" size="sm" className="h-11 sm:h-7 px-2 text-xs" asChild>
              <a
                href={`https://zalo.me/${lead.phone?.replace(/\D/g, '')}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className="font-bold mr-1">Z</span>
                Zalo
              </a>
            </Button>
          </div>

          {/* More Actions - Mobile: ActionSheet, Desktop: Dropdown */}
          {isMobile ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="h-11 w-11 sm:h-7 sm:w-7 p-0"
                onClick={() => setActionSheetOpen(true)}
                aria-label="Mở menu thao tác"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
              <MobileActionSheet
                open={actionSheetOpen}
                onOpenChange={setActionSheetOpen}
                title="Thao tác"
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
                {!lead.assigned_officer && (
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
                {lead.assigned_officer && lead.permissions.can_transfer_lead && (
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
                {lead.assigned_officer && lead.permissions.can_request_reassign && (
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
                <Button variant="ghost" size="sm" className="h-11 w-11 sm:h-7 sm:w-7 p-0" aria-label="Mở menu thao tác">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
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
                {!lead.assigned_officer && (
                  <DropdownMenuItem onClick={() => onAssign(lead)}>
                    <UserPlus className="mr-2 h-4 w-4" />
                    Gán cho cán bộ
                  </DropdownMenuItem>
                )}
                {lead.assigned_officer && lead.permissions.can_transfer_lead && (
                  <DropdownMenuItem onClick={() => setAssignOpen(true)}>
                    <UserPlus className="mr-2 h-4 w-4" />
                    Chuyển giao lead
                  </DropdownMenuItem>
                )}
                {lead.assigned_officer && lead.permissions.can_request_reassign && (
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
        </div>
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="flex-1" ref={scrollAreaRef}>
        <div className="space-y-3 p-3 sm:space-y-4 sm:p-4">
          {/* ================================================== */}
          {/* CỬA VÀO HỒ SƠ — 1 chạm sang /admissions khi đã có hồ sơ */}
          {/* Đặt trên cùng: khi lead đã có hồ sơ thì hồ sơ là ưu tiên. */}
          {/* Thin-client: label/màu lấy từ getStatusConfig('admission'). */}
          {/* ================================================== */}
          {(() => {
            const profile = lead.admission_profiles?.[0];
            if (!profile) return null;
            const cfg = getStatusConfig(profile.status, "admission");
            const extraCount = (lead.admission_profiles?.length ?? 1) - 1;
            return (
              <Link
                href={`/admissions/${profile.id}`}
                aria-label={`Xem hồ sơ tuyển sinh #${profile.id} — ${cfg.label}`}
                className="group relative flex min-h-14 items-center gap-3 overflow-hidden rounded-xl border bg-card p-2.5 pl-3 shadow-sm transition-colors hover:border-primary/40 active:scale-[0.995]"
              >
                {/* Vạch màu trạng thái (viền-trái) */}
                <span className={cn("absolute inset-y-0 left-0 w-1", getStatusDotColor(profile.status))} />
                {/* Chip nhận diện hồ sơ, tô theo trạng thái */}
                <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", cfg.badgeColor)}>
                  <FileText className="h-[18px] w-[18px]" />
                </span>
                {/* Nội dung: eyebrow + trạng thái + mã SV */}
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Hồ sơ tuyển sinh
                    <span className="font-mono font-semibold tracking-tight text-muted-foreground/80">#{profile.id}</span>
                    {extraCount > 0 && (
                      <span className="font-sans font-medium normal-case text-muted-foreground/70">· +{extraCount} hồ sơ</span>
                    )}
                  </span>
                  <span className="mt-0.5 flex items-baseline gap-1.5 truncate text-[15px] font-semibold leading-tight text-foreground">
                    {cfg.label}
                    {profile.student_code && (
                      <span className="truncate font-mono text-[11px] font-medium tracking-tight text-muted-foreground">
                        · Mã SV {profile.student_code}
                      </span>
                    )}
                  </span>
                </span>
                {/* Lối vào — chevron trỏ sang module tuyển sinh */}
                <span className="flex shrink-0 items-center gap-1 pr-0.5 text-xs font-semibold text-muted-foreground transition-colors group-hover:text-primary">
                  Xem
                  <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none" />
                </span>
              </Link>
            );
          })()}

          {/* ================================================== */}
          {/* SECTION 1: Thông tin học viên (Combined) */}
          {/* ================================================== */}
          <Card>
            <CardHeader className="px-3 py-2 sm:px-4 sm:py-2.5">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <User className="h-4 w-4 text-primary shrink-0" />
                <span>Thông tin</span>
                {lead.is_hot_lead && (
                  <Badge variant="outline" className="text-xs px-1.5 py-0 h-5 bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-950/50 dark:text-orange-400 dark:border-orange-800">
                    🔥 Hot
                  </Badge>
                )}
                {isOverdue && (
                  <Badge variant="destructive" className="text-xs px-1.5 py-0 h-5">
                    Quá hạn
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 px-3 pt-0 pb-3 sm:px-4 sm:pb-4">
              {/* Score Indicators */}
              <div className="grid grid-cols-2 gap-2 sm:gap-3">
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Điểm Lead</span>
                    <span className="font-bold">{lead.lead_score}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-[width] duration-500",
                        lead.lead_score >= 70 ? "bg-success-500" : lead.lead_score >= 50 ? "bg-info-500" : lead.lead_score >= 30 ? "bg-warning-500" : "bg-muted-foreground/50"
                      )}
                      style={{ width: `${Math.min(lead.lead_score, 100)}%` }}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Độ khẩn cấp</span>
                    <span className={cn("font-bold", lead.cached_urgency_score >= 70 && "text-error-600")}>
                      {lead.cached_urgency_score}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-[width] duration-500",
                        lead.cached_urgency_score >= 70 ? "bg-error-500" : lead.cached_urgency_score >= 40 ? "bg-warning-400" : "bg-success-500"
                      )}
                      style={{ width: `${Math.min(lead.cached_urgency_score, 100)}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Action Suggestions - Softer design */}
              {(lead.is_hot_lead || lead.cached_urgency_score >= 60 || isOverdue) && (
                <div className="rounded-md px-3 py-2 text-xs bg-amber-50/80 border border-amber-200/60 dark:bg-amber-950/30 dark:border-amber-800/50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-300">
                      <Zap className="h-3.5 w-3.5" />
                      {isOverdue ? "Quá hạn liên hệ!" : lead.is_hot_lead ? "Lead nóng cần chú ý" : "Ưu tiên liên hệ sớm"}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-11 sm:h-5 px-2 text-xs sm:text-[10px] border-amber-300 text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:text-amber-300"
                      asChild
                    >
                      <a href={`tel:${lead.phone}`}>Gọi ngay</a>
                    </Button>
                  </div>
                </div>
              )}

              {/* 2-Column Info Layout - Stack on mobile */}
              <div className="flex flex-col gap-3 pt-2 border-t text-xs sm:flex-row sm:gap-4">
                {/* Left Column: Contact & Personal Info */}
                <div className="flex-1 space-y-1.5 min-w-0">
                  {/* Phone - Always Visible */}
                  <div className="flex items-center gap-2 h-5">
                    <Phone className="text-muted-foreground h-3 w-3 shrink-0" />
                    <CopyableCell value={lead.phone} label="SĐT" className="font-mono text-xs" />
                    {lead.phone2 && (
                      <>
                        <span className="text-muted-foreground">/</span>
                        <CopyableCell value={lead.phone2} label="SĐT2" className="font-mono text-xs" />
                      </>
                    )}
                  </div>

                  {/* Email - Hide if empty */}
                  {lead.email && (
                    <div className="flex items-center gap-2 h-5">
                      <Mail className="text-muted-foreground h-3 w-3 shrink-0" />
                      <CopyableCell value={lead.email} label="Email" className="text-xs" />
                    </div>
                  )}

                  {/* Location - Hide if empty */}
                  {lead.location && (
                    <div className="flex items-center gap-2 h-5">
                      <MapPin className="text-muted-foreground h-3 w-3 shrink-0" />
                      <span className="truncate">{lead.location}</span>
                    </div>
                  )}

                  {/* Education - Hide if empty */}
                  {lead.education_level && (
                    <div className="flex items-center gap-2 h-5">
                      <GraduationCap className="text-muted-foreground h-3 w-3 shrink-0" />
                      <span className="truncate">
                        {getEducationLevelLabel(lead.education_level)}
                        {lead.gpa && <span className="text-muted-foreground"> ({lead.gpa})</span>}
                      </span>
                    </div>
                  )}
                </div>

                {/* Right Column: Stats & Program */}
                <div className="flex-1 space-y-1.5 min-w-0">
                  {/* Consultation Count */}
                  <div className="flex items-center justify-between h-5">
                    <span className="text-muted-foreground">Số lần tư vấn:</span>
                    <span className="font-semibold">{lead.consultation_count}</span>
                  </div>

                  {/* Days in Stage */}
                  <div className="flex items-center justify-between h-5">
                    <span className="text-muted-foreground">Ngày trong giai đoạn:</span>
                    <span className="font-semibold">{lead.days_in_stage ?? 0}</span>
                  </div>

                  {/* Last Contact */}
                  <div className="flex items-center justify-between h-5">
                    <span className="text-muted-foreground">Liên hệ cuối:</span>
                    <span className="font-semibold">
                      {daysSinceContact !== null 
                        ? `${daysSinceContact} ngày`
                        : "Chưa có"
                      }
                    </span>
                  </div>

                  {/* Program - Hide if empty */}
                  {(lead.offering?.program?.name || lead.offering?.offering_type) && (
                    <div className="flex items-center justify-between h-5">
                      <span className="text-muted-foreground">Ngành:</span>
                      <span className="font-semibold text-right" title={lead.offering?.program?.name || lead.offering?.offering_type}>
                        {lead.offering?.program?.name || lead.offering?.offering_type}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Footer: Phụ trách + Rating (Merged) */}
              <div className="flex flex-col gap-2 pt-2 border-t sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2 text-xs min-w-0">
                  <UserPlus className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="text-muted-foreground shrink-0">Phụ trách:</span>
                  <span className="font-medium truncate">
                    {lead.assigned_officer?.full_name || "Chưa phân công"}
                  </span>
                </div>
                <OfficerRatingInput
                  key={`rating-${lead.id}`}
                  leadId={lead.id}
                  currentRating={lead.officer_rating ?? null}
                  currentLeadScore={lead.lead_score}
                  version={lead.version}
                  compact
                />
              </div>
            </CardContent>
          </Card>

          {/* ================================================== */}
          {/* SECTION 2: Ghi nhận tư vấn (Keep as-is) */}
          {/* ================================================== */}
          <Card>
            <CardHeader className="px-3 py-2.5 sm:px-4 sm:py-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Zap className="h-4 w-4 text-amber-500 shrink-0" />
                Ghi nhận tư vấn
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3 pt-0 pb-3 sm:px-4 sm:pb-4">
              <QuickConsultationSectionV2 leadId={lead.id} />
            </CardContent>
          </Card>

          {/* ================================================== */}
          {/* SECTION 3: Lịch sử tư vấn (with maxItems) */}
          {/* ================================================== */}
          <Card>
            <CardHeader className="px-3 py-2.5 sm:px-4 sm:py-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <History className="text-muted-foreground h-4 w-4 shrink-0" />
                Lịch sử tư vấn
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3 pt-0 pb-3 sm:px-4 sm:pb-4">
              <LeadTimelineTab leadId={lead.id} maxItems={3} />
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
      
      {/* Assign Dialog (Manager/Admin: direct reassign) */}
      <AssignLeadDialog
        open={assignOpen}
        onOpenChange={setAssignOpen}
        lead={lead}
      />
      {/* Reassign Dialog (Officer: request reassign) */}
      <ReassignLeadDialog
        open={reassignOpen}
        onOpenChange={setReassignOpen}
        lead={lead}
      />
    </div>
  );
}

export default LeadDetailPanel;
