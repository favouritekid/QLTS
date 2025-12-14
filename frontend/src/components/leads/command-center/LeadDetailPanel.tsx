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
import { cn } from "@/lib/utils";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import { ReassignLeadDialog } from "@/components/leads/ReassignLeadDialog";
import { CopyableCell } from "@/components/common/CopyableCell";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { LeadInsightsCard } from "@/components/leads/LeadInsightsCard";
import type { Lead } from "@/types/lead.types";

interface LeadDetailPanelProps {
  leadId: number | null;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign: (lead: Lead) => void;
}

// TODO: Use when implementing status badges
// const getStatusColor = (status: LeadStatus) => {
//   switch (status) {
//     case "new":
//       return "bg-blue-500";
//     case "assigned":
//       return "bg-purple-500";
//     case "contacted":
//       return "bg-cyan-500";
//     case "qualified":
//       return "bg-emerald-500";
//     case "unqualified":
//       return "bg-gray-500";
//     case "converted":
//       return "bg-green-500";
//     case "rejected":
//       return "bg-red-500";
//     default:
//       return "bg-gray-500";
//   }
// };

// TODO: Use when implementing score display
// const getScoreColor = (score: number) => {
//   if (score >= 80) return "text-red-600 bg-red-50 border-red-200";
//   if (score >= 50) return "text-yellow-600 bg-yellow-50 border-yellow-200";
//   return "text-gray-600 bg-gray-50 border-gray-200";
// };

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
    <AnimatePresence mode="wait">
      <motion.div
        key={leadId}
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        transition={{ duration: 0.15, ease: "easeOut" }}
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
            {lead.pipeline_stage &&
              (() => {
                const stageColor =
                  lead.pipeline_stage.color_code || STAGE_COLORS[lead.pipeline_stage.id];
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
          {/* Thông tin liên hệ */}
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="text-sm font-medium">Thông tin liên hệ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5 px-4 pt-0 pb-4">
              {/* Phone with Copy + Call */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-sm">
                  <Phone className="text-muted-foreground h-4 w-4 shrink-0" />
                  <CopyableCell
                    value={lead.phone}
                    label="số điện thoại"
                    className="font-mono"
                  />
                  {lead.phone2 && (
                    <>
                      <span className="text-muted-foreground">/</span>
                      <CopyableCell
                        value={lead.phone2}
                        label="số điện thoại phụ"
                        className="font-mono"
                      />
                    </>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs text-blue-600 hover:bg-blue-50 hover:text-blue-700"
                  onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
                >
                  <Phone className="mr-1 h-3 w-3" />
                  Gọi
                </Button>
              </div>

              {/* Email with Copy */}
              {lead.email && (
                <div className="flex items-center gap-3 text-sm">
                  <Mail className="text-muted-foreground h-4 w-4 shrink-0" />
                  <CopyableCell
                    value={lead.email}
                    label="email"
                    displayValue={
                      <a
                        href={`mailto:${lead.email}`}
                        className="text-blue-600 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {lead.email}
                      </a>
                    }
                  />
                </div>
              )}

              {/* Location */}
              {lead.location && (
                <div className="flex items-center gap-3 text-sm">
                  <MapPin className="text-muted-foreground h-4 w-4 shrink-0" />
                  <span className="truncate">{lead.location}</span>
                </div>
              )}

              {/* Trình độ học vấn */}
              {lead.education_level && (
                <div className="flex items-center gap-3 text-sm">
                  <GraduationCap className="text-muted-foreground h-4 w-4 shrink-0" />
                  <span className="truncate">
                    {getEducationLevelLabel(lead.education_level)}
                    {lead.gpa && ` (GPA: ${lead.gpa})`}
                  </span>
                </div>
              )}

              {/* Chương trình */}
              {lead.offering && (
                <div className="flex items-center gap-3 text-sm">
                  <Building className="text-muted-foreground h-4 w-4 shrink-0" />
                  <span className="truncate">
                    {lead.offering.program?.degree_level &&
                      `${lead.offering.program.degree_level} `}
                    {lead.offering.program?.name || lead.offering.offering_type}
                    {lead.offering.offering_type && ` (${lead.offering.offering_type})`}
                  </span>
                </div>
              )}

              {/* Tư vấn viên phụ trách */}
              {lead.assigned_officer && (
                <div className="flex items-center gap-3 text-sm">
                  <UserPlus className="text-muted-foreground h-4 w-4 shrink-0" />
                  <span className="truncate">
                    <strong>{lead.assigned_officer.full_name}</strong>
                  </span>
                </div>
              )}

              {/* Ngày tạo */}
              <div className="text-muted-foreground flex items-center gap-3 text-sm">
                <Calendar className="h-4 w-4 shrink-0" />
                <span>Ngày tạo: {new Date(lead.created_at).toLocaleDateString("vi-VN")}</span>
              </div>
            </CardContent>
          </Card>

          {/* ✅ Combined Lead Insights + Action Suggestions */}
          <LeadInsightsCard
            lead={lead}
            onContact={() => window.open(`tel:${lead.phone}`, "_blank")}
          />

          {/* Ghi nhận tư vấn nhanh */}
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

          {/* Dòng thời gian */}
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <History className="text-muted-foreground h-4 w-4" />
                Dòng thời gian
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pt-0 pb-4">
              <LeadTimelineTab leadId={lead.id} />
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
      </motion.div>
    </AnimatePresence>
  );
}

export default LeadDetailPanel;
