// src/components/leads/command-center/LeadDetailPanel.tsx
"use client";

import React, { useRef, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Edit,
  Trash2,
  UserPlus,
  Phone,
  Mail,
  MapPin,
  GraduationCap,
  Building,
  Calendar,
  User,
  Zap,
  History,
  ExternalLink,
  RefreshCcw,
} from "lucide-react";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import { ReassignLeadDialog } from "@/components/leads/ReassignLeadDialog";
import { CopyableCell } from "@/components/common/CopyableCell";
import { STAGE_COLORS } from "@/types/pipeline.types";
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
      return "bg-yellow-100 text-yellow-700 border-yellow-200";
    case "assigned":
      return "bg-green-100 text-green-700 border-green-200";
    case "failed":
      return "bg-red-100 text-red-700 border-red-200";
    case "reassign_pending":
      return "bg-orange-100 text-orange-700 border-orange-200";
    default:
      return "bg-gray-100 text-gray-700 border-gray-200";
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

// ✅ TECHNICAL DEBT FIX: Score display color helper
const getScoreColor = (score: number) => {
  if (score >= 80) return "text-red-600 bg-red-50 border-red-200";
  if (score >= 50) return "text-yellow-600 bg-yellow-50 border-yellow-200";
  return "text-gray-600 bg-gray-50 border-gray-200";
};

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

const getEducationLevelLabel = (level: string) => {
  const labels: Record<string, string> = {
    high_school: "Trung học phổ thông",
    diploma: "Cao đẳng",
    bachelor: "Cử nhân",
    master: "Thạc sĩ",
    phd: "Tiến sĩ",
    other: "Khác",
  };
  return labels[level] || level;
};

export function LeadDetailPanel({ leadId, onEdit, onDelete, onAssign }: LeadDetailPanelProps) {
  const { data: lead, isLoading } = useLead(leadId || 0, !!leadId);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [daysSinceContact, setDaysSinceContact] = useState<number | null>(null);

  // Calculate days since last contact on client side only to avoid hydration mismatch
  useEffect(() => {
    if (lead?.last_consultation_at) {
      const days = Math.floor((Date.now() - new Date(lead.last_consultation_at).getTime()) / (1000 * 60 * 60 * 24));
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDaysSinceContact(days);
    } else {
       
      setDaysSinceContact(null);
    }
  }, [lead?.last_consultation_at]);

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
            <p className="text-muted-foreground/70 text-sm">Click vào lead trong danh sách</p>
          </div>
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
      {/* Header */}
      <div className="bg-background shrink-0 border-b p-4">
        <div className="flex items-start gap-4">
          <Avatar className="h-14 w-14">
            <AvatarFallback className="bg-primary/10 text-primary text-base font-semibold">
              {getInitials(lead.full_name)}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 space-y-1">
            <h2 className="truncate text-lg font-semibold">{lead.full_name}</h2>
            <div className="flex flex-wrap items-center gap-1.5">
              {/* Pipeline Stage Badge */}
              {lead.pipeline_stage &&
                (() => {
                  const stageColor =
                    sanitizeColorCode(lead.pipeline_stage.color_code) || STAGE_COLORS[lead.pipeline_stage.id];
                  return (
                    <Badge
                      variant="outline"
                      className={cn("border-0 font-medium", stageColor && "text-white")}
                      style={{
                        backgroundColor: stageColor || undefined,
                      }}
                    >
                      {lead.pipeline_stage.name}
                    </Badge>
                  );
                })()}

              {/* Consultation Status Badge - Current status within the stage */}
              {lead.consultation_status && (
                <Badge
                  variant="outline"
                  className="text-xs font-medium gap-1"
                  style={{
                    borderColor: lead.consultation_status.color_code || "#6b7280",
                    color: lead.consultation_status.color_code || "#6b7280",
                  }}
                >
                  <div
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: lead.consultation_status.color_code || "#6b7280" }}
                  />
                  {lead.consultation_status.name}
                </Badge>
              )}

              {/* ✅ TECHNICAL DEBT FIX: Assignment Status Badge */}
              {lead.assignment_status && (
                <Badge
                  variant="outline"
                  className={cn("text-xs", getAssignmentStatusColor(lead.assignment_status))}
                >
                  {getAssignmentStatusLabel(lead.assignment_status)}
                </Badge>
              )}
              
              {/* ✅ TECHNICAL DEBT FIX: Overdue Indicator */}
              {lead.is_overdue && (
                <Badge variant="destructive" className="text-xs">
                  Quá hạn
                </Badge>
              )}
            </div>
          </div>

          {/* Action Buttons with Tooltips */}
          <TooltipProvider delayDuration={200}>
            <div className="flex shrink-0 items-center gap-1">
              {/* Link: Xem đầy đủ */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" asChild className="h-8 w-8">
                    <Link href={`/leads/${lead.id}`}>
                      <ExternalLink className="h-4 w-4" />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Xem đầy đủ</TooltipContent>
              </Tooltip>

              {/* Action: Sửa */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" onClick={() => onEdit(lead)} className="h-8 w-8">
                    <Edit className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Chỉnh sửa lead</TooltipContent>
              </Tooltip>

              {/* Action: Gán (chỉ hiển thị khi chưa được gán) */}
              {!lead.assigned_officer && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" onClick={() => onAssign(lead)} className="h-8 w-8">
                      <UserPlus className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Gán cho cán bộ</TooltipContent>
                </Tooltip>
              )}

              {/* Action: Phân công lại (chỉ hiển thị khi đã được gán) */}
              {lead.assigned_officer && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button 
                      variant="ghost" 
                      size="icon"
                      onClick={() => setReassignOpen(true)} 
                      className="h-8 w-8"
                    >
                      <RefreshCcw className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Yêu cầu phân công lại</TooltipContent>
                </Tooltip>
              )}

              {/* Destructive Action: Xóa */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onDelete(lead)}
                    className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="bg-destructive text-destructive-foreground">Xóa lead</TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>
        </div>
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="flex-1" ref={scrollAreaRef}>
        <div className="space-y-4 p-4">
          {/* ================================================== */}
          {/* SECTION 1: Thông tin học viên (Combined) */}
          {/* ================================================== */}
          <Card>
            <CardHeader className="px-4 py-2.5">
              <CardTitle className="flex items-center justify-between text-sm font-medium">
                <span className="flex items-center gap-2">
                  <User className="h-4 w-4 text-primary" />
                  Thông tin học viên
                </span>
                {/* Quick Action Buttons in Header */}
                <div className="flex items-center gap-1">
                  {lead.is_hot_lead && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5 bg-orange-50 text-orange-600 border-orange-200">
                      🔥 Hot
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[10px] text-blue-600 hover:bg-blue-50"
                    onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
                  >
                    <Phone className="h-3 w-3 mr-1" />
                    Gọi
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[10px] text-blue-600 hover:bg-blue-50"
                    onClick={() => window.open(`https://zalo.me/${lead.phone?.replace(/\D/g, '')}`, "_blank")}
                  >
                    <span className="font-bold mr-1">Z</span>
                    Zalo
                  </Button>
                  {lead.email && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[10px] text-blue-600 hover:bg-blue-50"
                      onClick={() => window.open(`mailto:${lead.email}`, "_blank")}
                    >
                      <Mail className="h-3 w-3 mr-1" />
                      Email
                    </Button>
                  )}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 px-4 pt-0 pb-4">
              {/* Score Indicators */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Điểm Lead</span>
                    <span className="font-bold">{lead.lead_score}</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        lead.lead_score >= 70 ? "bg-emerald-500" : lead.lead_score >= 40 ? "bg-blue-500" : "bg-slate-400"
                      )}
                      style={{ width: `${Math.min(lead.lead_score, 100)}%` }}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Độ khẩn cấp</span>
                    <span className={cn("font-bold", lead.cached_urgency_score >= 70 && "text-red-600")}>
                      {lead.cached_urgency_score}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        lead.cached_urgency_score >= 70 ? "bg-red-500" : lead.cached_urgency_score >= 40 ? "bg-amber-400" : "bg-green-500"
                      )}
                      style={{ width: `${Math.min(lead.cached_urgency_score, 100)}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Action Suggestions - Softer design */}
              {(lead.is_hot_lead || lead.cached_urgency_score >= 60 || lead.is_overdue) && (
                <div className="rounded-md px-3 py-2 text-xs bg-amber-50/80 border border-amber-200/60 dark:bg-amber-950/30 dark:border-amber-800/50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-300">
                      <Zap className="h-3.5 w-3.5" />
                      {lead.is_overdue ? "Quá hạn liên hệ!" : lead.is_hot_lead ? "Lead nóng cần chú ý" : "Ưu tiên liên hệ sớm"}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-5 px-2 text-[10px] border-amber-300 text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:text-amber-300"
                      onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
                    >
                      Gọi ngay
                    </Button>
                  </div>
                </div>
              )}

              {/* 2-Column Info Layout */}
              <div className="flex gap-4 pt-2 border-t text-xs">
                {/* Left Column: Contact & Personal Info */}
                <div className="flex-1 space-y-1.5">
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
                <div className="flex-1 space-y-1.5">
                  {/* Consultation Count */}
                  <div className="flex items-center justify-between h-5">
                    <span className="text-muted-foreground">Số lần tư vấn:</span>
                    <span className="font-semibold">{lead.consultation_count}</span>
                  </div>

                  {/* Days in Stage */}
                  <div className="flex items-center justify-between h-5">
                    <span className="text-muted-foreground">Ngày trong stage:</span>
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
              <div className="flex items-center justify-between pt-2 border-t">
                <div className="flex items-center gap-2 text-xs">
                  <UserPlus className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="text-muted-foreground">Phụ trách:</span>
                  <span className="font-medium">
                    {lead.assigned_officer?.full_name || "Chưa phân công"}
                  </span>
                </div>
                <OfficerRatingInput
                  key={`rating-${lead.id}`}
                  leadId={lead.id}
                  currentRating={lead.officer_rating ?? null}
                  currentLeadScore={lead.lead_score}
                  compact
                />
              </div>
            </CardContent>
          </Card>

          {/* ================================================== */}
          {/* SECTION 2: Ghi nhận tư vấn (Keep as-is) */}
          {/* ================================================== */}
          <Card className="border-slate-200 bg-slate-50">
            <CardHeader className="px-4 py-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Zap className="h-4 w-4 text-amber-500" />
                Ghi nhận tư vấn
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pt-0 pb-4">
              <QuickConsultationSection leadId={lead.id} />
            </CardContent>
          </Card>

          {/* ================================================== */}
          {/* SECTION 3: Lịch sử tư vấn (with maxItems) */}
          {/* ================================================== */}
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <History className="text-muted-foreground h-4 w-4" />
                Lịch sử tư vấn
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pt-0 pb-4">
              <LeadTimelineTab leadId={lead.id} maxItems={3} />
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
      
      {/* Reassign Dialog */}
      <ReassignLeadDialog
        open={reassignOpen}
        onOpenChange={setReassignOpen}
        lead={lead}
      />
    </div>
  );
}

export default LeadDetailPanel;
