// src/app/(dashboard)/leads/[id]/_components/LeadSidebar.tsx
/**
 * LeadSidebar - Complete lead information sidebar
 * 
 * Shows ALL lead fields with N/A for empty values
 * Officers can see what info is missing to ask the lead
 */

"use client";

import { 
  Phone, 
  Mail, 
  MapPin, 
  GraduationCap, 
  Building, 
  UserPlus, 
  Calendar, 
  TrendingUp, 
  Clock, 
  History,
  Briefcase,
  User,
  Hash,
  Globe,
  Target,
  Star,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import { CopyableCell } from "@/components/common/CopyableCell";
import type { Lead, TimelineItem } from "@/types/lead.types";

interface LeadSidebarProps {
  lead: Lead;
  timeline?: TimelineItem[];
  onAssign?: () => void;
  hideHeader?: boolean; // Hide name/score header when shown in top bar
  compact?: boolean; // Compact mode for grid layout (no fixed height, card-style)
}

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

const getEducationLevelLabel = (level: string | null | undefined) => {
  if (!level) return null;
  const labels: Record<string, string> = {
    high_school: "THPT",
    diploma: "Trung cấp/Cao đẳng",
    bachelor: "Đại học",
    master: "Thạc sĩ",
    phd: "Tiến sĩ",
    other: "Khác",
  };
  return labels[level] || level;
};

const getSourceLabel = (source: string | null | undefined) => {
  if (!source) return null;
  return LEAD_SOURCE_OPTIONS.find((o) => o.value === source)?.label || source;
};

const getScoreColor = (score: number) => {
  if (score >= 70) return "bg-success-100 text-success-700 border-success-200";
  if (score >= 50) return "bg-info-100 text-info-700 border-info-200";
  if (score >= 30) return "bg-warning-100 text-warning-700 border-warning-200";
  return "bg-muted text-muted-foreground border-border";
};

const getScoreLabel = (score: number) => {
  if (score >= 70) return "Tiềm năng cao";
  if (score >= 50) return "Trung bình";
  if (score >= 30) return "Thấp";
  return "Rất thấp";
};

const getLocationProximityLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return null;
  const labels: Record<number, string> = {
    0: "Xa",
    1: "Lân cận",
    2: "Gần",
  };
  return labels[value] || null;
};

const getOccupationRelevanceLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return null;
  const labels: Record<number, string> = {
    0: "Không liên quan",
    1: "Gián tiếp",
    2: "Trực tiếp",
  };
  return labels[value] || null;
};

const getAcademicPerformanceLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return null;
  const labels: Record<number, string> = {
    0: "Yếu",
    1: "Trung bình",
    2: "Khá",
    3: "Giỏi",
  };
  return labels[value] || null;
};

// Info row component with N/A support
function InfoRow({ 
  icon: Icon, 
  label, 
  value, 
  isLink,
  href,
  action,
}: { 
  icon: React.ElementType; 
  label: string; 
  value: string | number | null | undefined;
  isLink?: boolean;
  href?: string;
  action?: React.ReactNode;
}) {
  const displayValue = value ?? "N/A";
  const isEmpty = value === null || value === undefined || value === "";
  
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <Icon className={cn("h-3.5 w-3.5 shrink-0", isEmpty ? "text-muted-foreground/50" : "text-muted-foreground")} />
        <span className="text-xs text-muted-foreground shrink-0">{label}:</span>
        {isLink && href && !isEmpty ? (
          <a href={href} className="text-sm text-info-600 hover:underline truncate">
            {displayValue}
          </a>
        ) : (
          <span className={cn("text-sm truncate", isEmpty && "text-muted-foreground/50 italic")}>
            {displayValue}
          </span>
        )}
      </div>
      {action && !isEmpty && action}
    </div>
  );
}

export function LeadSidebar({ lead, timeline, onAssign, hideHeader, compact }: LeadSidebarProps) {
  const stageColor = lead.pipeline_stage?.color_code || STAGE_COLORS[lead.pipeline_stage?.id || 0];
  const daysInPipeline = Math.floor(
    (new Date().getTime() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24)
  );

  return (
    <div className={cn(
      "flex flex-col bg-muted/30",
      compact ? "rounded-lg border" : "h-full border-r overflow-y-auto"
    )}>
      {/* Lead Identity - Hidden when shown in top bar */}
      {!hideHeader && (
        <>
          <div className="p-4 space-y-3">
            <div className="flex items-center gap-3">
              <Avatar className="h-12 w-12 border-2 border-background shadow-sm">
                <AvatarFallback className="bg-primary/10 text-primary text-base font-semibold">
                  {getInitials(lead.full_name)}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold font-display text-base truncate">{lead.full_name}</h2>
                <p className="text-xs text-muted-foreground">Lead #{lead.id}</p>
              </div>
            </div>

            {/* Score Badge */}
            <div className={cn(
              "flex items-center justify-between rounded-lg border p-2.5",
              getScoreColor(lead.lead_score)
            )}>
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                <span className="font-medium text-sm">Điểm</span>
              </div>
              <div className="text-right">
                <div className="font-bold text-lg">{lead.lead_score}</div>
                <div className="text-xs opacity-80">{getScoreLabel(lead.lead_score)}</div>
              </div>
            </div>

            {/* Pipeline Stage */}
            {lead.pipeline_stage && (
              <Badge
                variant="outline"
                className={cn("w-full justify-center py-1.5 border-0 font-medium", stageColor && "text-white")}
                style={{ backgroundColor: stageColor || undefined }}
              >
                {lead.pipeline_stage.name}
              </Badge>
            )}

            {/* Consultation Status - Current status within the stage */}
            {lead.consultation_status && (
              <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-background border">
                <div
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ backgroundColor: lead.consultation_status.color_code || "#6b7280" }}
                />
                <span className="text-xs text-muted-foreground">Trạng thái:</span>
                <span className="text-sm font-medium truncate">
                  {lead.consultation_status.name}
                </span>
              </div>
            )}
          </div>

          <Separator />
        </>
      )}

      {/* Contact Info */}
      <div className="px-4 py-3 space-y-0.5">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Liên hệ</h4>
        
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-sm">
            <Phone className="text-muted-foreground h-4 w-4 shrink-0" />
            <CopyableCell
              value={lead.phone}
              label="số điện thoại"
              className="font-mono text-sm"
            />
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-info-600 hover:bg-info-50"
            onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
          >
            Gọi
          </Button>
        </div>
        
        {lead.phone2 && (
          <div className="flex items-center gap-3 text-sm">
            <Phone className="text-muted-foreground h-4 w-4 shrink-0" />
            <CopyableCell
              value={lead.phone2}
              label="số điện thoại phụ"
              className="font-mono text-sm text-muted-foreground"
            />
          </div>
        )}
        
        {lead.email && (
          <div className="flex items-center gap-3 text-sm">
            <Mail className="text-muted-foreground h-4 w-4 shrink-0" />
            <CopyableCell
              value={lead.email}
              label="email"
              displayValue={
                <a
                  href={`mailto:${lead.email}`}
                  className="text-info-600 hover:underline truncate"
                >
                  {lead.email}
                </a>
              }
            />
          </div>
        )}
        
        <InfoRow icon={MapPin} label="Địa chỉ" value={lead.location} />
      </div>

      <Separator />

      {/* Personal Info */}
      <div className="px-4 py-3 space-y-0.5">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Thông tin cá nhân</h4>
        
        <InfoRow icon={Calendar} label="Năm sinh" value={lead.birth_year} />
        <InfoRow icon={Target} label="Vị trí địa lý" value={getLocationProximityLabel(lead.location_proximity)} />
        <InfoRow icon={Briefcase} label="Liên quan nghề" value={getOccupationRelevanceLabel(lead.occupation_relevance)} />
      </div>

      <Separator />

      {/* Education Info */}
      <div className="px-4 py-3 space-y-0.5">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Học vấn</h4>
        
        <InfoRow icon={GraduationCap} label="Trình độ" value={getEducationLevelLabel(lead.education_level)} />
        <InfoRow icon={Star} label="Học lực" value={getAcademicPerformanceLabel(lead.academic_performance)} />
        <InfoRow icon={Hash} label="GPA" value={lead.gpa} />
      </div>

      <Separator />

      {/* Program & Assignment */}
      <div className="px-4 py-3 space-y-0.5">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Đăng ký</h4>
        
        <InfoRow icon={Globe} label="Nguồn" value={getSourceLabel(lead.source)} />
        <InfoRow 
          icon={Building} 
          label="Ngành" 
          value={lead.offering?.program?.name || lead.offering?.offering_type || null} 
        />
        {lead.assigned_officer ? (
          <InfoRow icon={User} label="Tư vấn viên" value={lead.assigned_officer.full_name} />
        ) : (
          <div className="pt-2">
            <Button 
              variant="outline" 
              size="sm" 
              className="w-full h-8"
              onClick={onAssign}
            >
              <UserPlus className="mr-1.5 h-3.5 w-3.5" />
              Phân công ngay
            </Button>
          </div>
        )}
      </div>

      <Separator />

      {/* Quick Stats */}
      <div className="px-4 py-3 space-y-2">
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Thống kê</h4>
        
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-background rounded-md p-2 border">
            <div className="flex items-center gap-1 text-muted-foreground mb-0.5">
              <Clock className="h-3 w-3" />
              <span className="text-[10px]">Trong pipeline</span>
            </div>
            <div className="font-semibold text-sm">{daysInPipeline} ngày</div>
          </div>
          <div className="bg-background rounded-md p-2 border">
            <div className="flex items-center gap-1 text-muted-foreground mb-0.5">
              <History className="h-3 w-3" />
              <span className="text-[10px]">Số lần tư vấn</span>
            </div>
            <div className="font-semibold text-sm">{lead.consultation_count}</div>
          </div>
        </div>

        <div className="text-[10px] text-muted-foreground flex items-center gap-1 pt-1">
          <Calendar className="h-3 w-3" />
          Ngày tạo: {new Date(lead.created_at).toLocaleDateString("vi-VN")}
        </div>
      </div>
    </div>
  );
}

export default LeadSidebar;
