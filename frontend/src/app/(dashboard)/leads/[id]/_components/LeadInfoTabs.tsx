// src/app/(dashboard)/leads/[id]/_components/LeadInfoTabs.tsx
/**
 * LeadInfoTabs - Tabbed panel for lead information
 *
 * Tabs:
 * - Tổng quan: Contact, Personal, Education, Source info
 * - Lịch sử: Consultation timeline
 * - Hồ sơ: Admission profile status
 */
"use client";

import { useState, useCallback, useMemo } from "react";
import { SwipeableTabs } from "@/components/common/SwipeableContainer";
import {
  Phone,
  Mail,
  MapPin,
  Calendar,
  Globe,
  User,
  GraduationCap,
  AlertCircle,
  FileText,
  PhoneCall,
  UserPlus,
  Video,
  MessageSquare,
  Clock,
  History,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import { CopyableCell } from "@/components/common/CopyableCell";
import { AuditLogTimeline } from "@/components/audit/AuditLogTimeline";
import { LEAD_SOURCE_OPTIONS, getEducationLevelLabel } from "@/constants";
import type { Lead, TimelineItem } from "@/types/lead.types";

interface LeadInfoTabsProps {
  lead: Lead;
  timeline?: TimelineItem[];
  onAssign?: () => void;
  onCreateProfile?: () => void;
  onViewProfile?: () => void;
}

type TabId = "overview" | "history" | "profile" | "audit";

const tabs: { id: TabId; label: string }[] = [
  { id: "overview", label: "Tổng quan" },
  { id: "history", label: "Lịch sử" },
  { id: "profile", label: "Hồ sơ" },
  { id: "audit", label: "Audit Log" },
];

// Helper functions
const getSourceLabel = (source: string | null | undefined) => {
  if (!source) return "N/A";
  return LEAD_SOURCE_OPTIONS.find((o) => o.value === source)?.label || source;
};

const getLocationProximityLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "N/A";
  const labels: Record<number, string> = { 0: "Xa", 1: "Lân cận", 2: "Gần" };
  return labels[value] || "N/A";
};

const getOccupationRelevanceLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "N/A";
  const labels: Record<number, string> = { 0: "Không liên quan", 1: "Gián tiếp", 2: "Trực tiếp" };
  return labels[value] || "N/A";
};

const getAcademicPerformanceLabel = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "N/A";
  const labels: Record<number, string> = { 0: "Yếu", 1: "Trung bình", 2: "Khá", 3: "Giỏi" };
  return labels[value] || "N/A";
};

const isWeakStudent = (lead: Lead) => {
  return lead.academic_performance === 0 || (lead.gpa !== null && lead.gpa !== undefined && lead.gpa < 5.5);
};

// Profile status Vietnamese labels
const PROFILE_STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  submitted: "Đã nộp",
  approved: "Đã duyệt",
  confirmed: "Đã xác nhận",
  enrolled: "Đã nhập học",
  rejected: "Bị từ chối",
  resubmitted: "Nộp lại",
  overridden: "Ngoại lệ",
};

// Profile status color config
const getProfileStatusStyle = (status: string) => {
  switch (status) {
    case "approved":
    case "confirmed":
    case "enrolled":
      return { bg: "bg-success-50", border: "border-success-200", label: "text-success-600", value: "text-success-800", icon: "text-success-600" };
    case "rejected":
      return { bg: "bg-error-50", border: "border-error-200", label: "text-error-600", value: "text-error-800", icon: "text-error-600" };
    case "submitted":
    case "resubmitted":
      return { bg: "bg-info-50", border: "border-info-200", label: "text-info-600", value: "text-info-800", icon: "text-info-600" };
    case "overridden":
      return { bg: "bg-warning-50", border: "border-warning-200", label: "text-warning-600", value: "text-warning-800", icon: "text-warning-600" };
    default: // draft
      return { bg: "bg-muted", border: "border-border", label: "text-muted-foreground", value: "text-foreground", icon: "text-muted-foreground" };
  }
};

// Get method icon and color
const getMethodConfig = (method?: string) => {
  switch (method) {
    case "phone":
      return { icon: Phone, color: "text-success-600", bg: "bg-success-100", label: "Gọi điện" };
    case "email":
      return { icon: Mail, color: "text-info-600", bg: "bg-info-100", label: "Email" };
    case "video_call":
    case "video":
      return { icon: Video, color: "text-purple-600", bg: "bg-purple-100", label: "Video" };
    case "sms":
      return { icon: MessageSquare, color: "text-cyan-600", bg: "bg-cyan-100", label: "SMS" };
    case "in_person":
      return { icon: User, color: "text-amber-600", bg: "bg-amber-100", label: "Gặp mặt" };
    default:
      return { icon: PhoneCall, color: "text-muted-foreground", bg: "bg-muted", label: "Tư vấn" };
  }
};

// Get outcome styles
const getOutcomeStyles = (outcomeType?: string | null) => {
  switch (outcomeType) {
    case "positive":
      return { bg: "bg-success-50", border: "border-success-200", text: "text-success-700" };
    case "negative":
      return { bg: "bg-error-50", border: "border-error-200", text: "text-error-700" };
    default:
      return { bg: "bg-info-50", border: "border-info-200", text: "text-info-700" };
  }
};

// Info row component
function InfoRow({
  label,
  value,
  className,
}: {
  label: string;
  value: string | number | null | undefined;
  className?: string;
}) {
  const displayValue = value ?? "N/A";
  const isEmpty = value === null || value === undefined || value === "";

  return (
    <div className={cn("p-2.5 bg-muted rounded-xl", className)}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("text-sm font-medium", isEmpty ? "text-muted-foreground italic" : "text-foreground")}>
        {displayValue}
      </div>
    </div>
  );
}

export function LeadInfoTabs({
  lead,
  timeline,
  onAssign,
  onCreateProfile,
  onViewProfile,
}: LeadInfoTabsProps) {
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  // Sort by timestamp descending (newest first) before slicing
  const recentTimeline = useMemo(() => timeline
    ? [...timeline].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).slice(0, 5)
    : [], [timeline]);

  // Get current tab index for swipe navigation
  const activeIndex = tabs.findIndex((t) => t.id === activeTab);

  // Handle swipe tab change
  const handleTabChange = useCallback((index: number) => {
    if (index >= 0 && index < tabs.length) {
      setActiveTab(tabs[index].id);
    }
  }, []);

  return (
    <div className="bg-card rounded-2xl border border-border overflow-hidden">
      {/* Tab Headers */}
      <div className="flex border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex-1 px-4 py-3 text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "text-indigo-600 bg-indigo-50 border-b-2 border-indigo-600"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content - Swipeable on mobile */}
      <SwipeableTabs
        activeIndex={activeIndex}
        onTabChange={handleTabChange}
        tabCount={tabs.length}
        className="p-4"
      >
        {/* Overview Tab */}
        {activeTab === "overview" && (
          <div className="space-y-4">
            {/* Contact Info */}
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Liên hệ
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between p-2.5 bg-muted rounded-xl">
                  <div className="flex items-center gap-3">
                    <Phone className="w-4 h-4 text-muted-foreground" />
                    <CopyableCell
                      value={lead.phone}
                      label="số điện thoại"
                      className="text-sm font-medium text-foreground"
                    />
                  </div>
                  <span className="text-xs text-success-600 font-medium">Chính</span>
                </div>

                {lead.phone2 && (
                  <div className="flex items-center justify-between p-2.5 hover:bg-muted rounded-xl transition-colors">
                    <div className="flex items-center gap-3">
                      <Phone className="w-4 h-4 text-muted-foreground" />
                      <CopyableCell
                        value={lead.phone2}
                        label="số điện thoại phụ"
                        className="text-sm text-muted-foreground"
                      />
                    </div>
                    <span className="text-xs text-muted-foreground">Phụ</span>
                  </div>
                )}

                {lead.email && (
                  <div className="flex items-center gap-3 p-2.5 hover:bg-muted rounded-xl transition-colors">
                    <Mail className="w-4 h-4 text-muted-foreground" />
                    <a
                      href={`mailto:${lead.email}`}
                      className="text-sm text-info-600 hover:underline truncate"
                    >
                      {lead.email}
                    </a>
                  </div>
                )}

                <div className="flex items-center gap-3 p-2.5 hover:bg-muted rounded-xl transition-colors">
                  <MapPin className="w-4 h-4 text-muted-foreground" />
                  <span className={cn("text-sm", lead.location ? "text-muted-foreground" : "text-muted-foreground italic")}>
                    {lead.location || "N/A"}
                  </span>
                </div>
              </div>
            </div>

            {/* Personal Info */}
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Thông tin cá nhân
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <InfoRow label="Năm sinh" value={lead.birth_year} />
                <InfoRow label="Vị trí địa lý" value={getLocationProximityLabel(lead.location_proximity)} />
                <InfoRow
                  label="Liên quan nghề"
                  value={getOccupationRelevanceLabel(lead.occupation_relevance)}
                  className="col-span-2"
                />
              </div>
            </div>

            {/* Education - Warning for weak student */}
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Học vấn
              </h3>
              {isWeakStudent(lead) ? (
                <div className="p-3 bg-warning-50 border border-warning-200 rounded-xl">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="w-4 h-4 text-warning-500" />
                    <span className="text-xs font-semibold text-warning-700">Lưu ý khi tư vấn</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <div className="text-xs text-warning-600">Trình độ</div>
                      <div className="text-sm font-semibold text-warning-800">
                        {getEducationLevelLabel(lead.education_level)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-warning-600">Học lực</div>
                      <div className="text-sm font-semibold text-warning-800">
                        {getAcademicPerformanceLabel(lead.academic_performance)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-warning-600">GPA</div>
                      <div className="text-sm font-semibold text-warning-800">
                        {lead.gpa ?? "N/A"}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  <InfoRow label="Trình độ" value={getEducationLevelLabel(lead.education_level)} />
                  <InfoRow label="Học lực" value={getAcademicPerformanceLabel(lead.academic_performance)} />
                  <InfoRow label="GPA" value={lead.gpa} />
                </div>
              )}
            </div>

            {/* Source & Assignment */}
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Nguồn & Phân công
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Nguồn</span>
                  <span className="text-sm font-medium text-foreground flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5" />
                    {getSourceLabel(lead.source)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Tư vấn viên</span>
                  {lead.assigned_officer ? (
                    <span className="text-sm font-medium text-foreground">
                      {lead.assigned_officer.full_name}
                    </span>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={onAssign}
                    >
                      <UserPlus className="mr-1 h-3 w-3" />
                      Phân công
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* History Tab */}
        {activeTab === "history" && (
          <div className="space-y-2">
            {recentTimeline.length > 0 ? (
              recentTimeline.map((item, index) => {
                const isConsultation = item.type === "consultation";
                const consultData = isConsultation ? (item.data as {
                  method?: string;
                  notes?: string;
                  scheduled_at?: string;
                  consultation_status?: { name?: string; color_code?: string; outcome_type?: string };
                  officer?: { full_name?: string };
                }) : null;

                const methodConfig = getMethodConfig(consultData?.method);
                const MethodIcon = methodConfig.icon;
                const statusName = consultData?.consultation_status?.name || item.description;
                const statusColor = consultData?.consultation_status?.color_code;
                const outcomeType = consultData?.consultation_status?.outcome_type;
                const outcomeStyles = getOutcomeStyles(outcomeType);
                const actorName = consultData?.officer?.full_name || item.actor?.full_name;
                const notes = consultData?.notes;
                const scheduledAt = consultData?.scheduled_at;

                return (
                  <div
                    key={`${item.type}-${item.timestamp}-${(item.data as { id?: number })?.id ?? index}`}
                    className={cn(
                      "p-3 rounded-xl border transition-colors",
                      index === 0
                        ? outcomeStyles.bg + " " + outcomeStyles.border
                        : "bg-card border-border hover:bg-muted"
                    )}
                  >
                    {/* Row 1: Icon + Status + Time */}
                    <div className="flex items-start justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-2 min-w-0">
                        {/* Method Icon */}
                        <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0", methodConfig.bg)}>
                          <MethodIcon className={cn("w-3.5 h-3.5", methodConfig.color)} />
                        </div>

                        {/* Status with color */}
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            {statusColor && (
                              <ColorDot color={statusColor} size="sm" />
                            )}
                            <span className={cn("text-sm font-medium truncate", index === 0 ? outcomeStyles.text : "text-foreground")}>
                              {statusName}
                            </span>
                          </div>
                          {/* Actor */}
                          {actorName && (
                            <div className="text-xs text-muted-foreground">{actorName}</div>
                          )}
                        </div>
                      </div>

                      {/* Timestamp */}
                      <div className="text-right flex-shrink-0">
                        <div className="text-xs font-medium text-muted-foreground" suppressHydrationWarning>
                          {new Date(item.timestamp).toLocaleTimeString("vi-VN", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                        <div className="text-xs text-muted-foreground/70" suppressHydrationWarning>
                          {new Date(item.timestamp).toLocaleDateString("vi-VN", {
                            day: "2-digit",
                            month: "2-digit",
                          })}
                        </div>
                      </div>
                    </div>

                    {/* Row 2: Notes (if any, not auto-generated) */}
                    {notes && !notes.startsWith("Ghi nhận:") && !notes.startsWith("Ghi nhận nhanh:") && (
                      <p className="text-xs text-muted-foreground italic pl-9 truncate">&quot;{notes}&quot;</p>
                    )}

                    {/* Row 3: Scheduled follow-up */}
                    {scheduledAt && (
                      <div className="flex items-center gap-1 text-xs text-info-600 pl-9 mt-1">
                        <Clock className="w-3 h-3" />
                        <span suppressHydrationWarning>Hẹn: {new Date(scheduledAt).toLocaleString("vi-VN", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}</span>
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="text-center py-8">
                <div className="w-12 h-12 bg-muted rounded-2xl flex items-center justify-center mx-auto mb-3">
                  <Calendar className="w-6 h-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground">Chưa có lịch sử tư vấn</p>
              </div>
            )}
          </div>
        )}

        {/* Profile Tab */}
        {activeTab === "profile" && (
          <div>
            {lead.admission_profile ? (
              <div className="space-y-4">
                {(() => {
                  const profileStyle = getProfileStatusStyle(lead.admission_profile.status);
                  return (
                    <div className={cn("p-4 border rounded-xl", profileStyle.bg, profileStyle.border)}>
                      <div className="flex items-center gap-2 mb-2">
                        <FileText className={cn("w-4 h-4", profileStyle.icon)} />
                        <span className={cn("text-sm font-semibold", profileStyle.value)}>
                          Hồ sơ tuyển sinh #{lead.admission_profile.id}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <span className={profileStyle.label}>Trạng thái:</span>{" "}
                          <span className={cn("font-medium", profileStyle.value)}>
                            {PROFILE_STATUS_LABELS[lead.admission_profile.status] ?? lead.admission_profile.status}
                          </span>
                        </div>
                        {lead.admission_profile.student_code && (
                          <div>
                            <span className={profileStyle.label}>Mã SV:</span>{" "}
                            <span className={cn("font-medium", profileStyle.value)}>
                              {lead.admission_profile.student_code}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })()}
                <Button className="w-full" onClick={onViewProfile}>
                  <FileText className="mr-2 h-4 w-4" />
                  Xem chi tiết hồ sơ
                </Button>
              </div>
            ) : (
              <div className="text-center py-8">
                <div className="w-12 h-12 bg-muted rounded-2xl flex items-center justify-center mx-auto mb-3">
                  <FileText className="w-6 h-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground">Chưa có hồ sơ tuyển sinh</p>
                {lead.offering_id && (
                  <Button
                    variant="link"
                    className="mt-3 text-sm font-medium text-indigo-600"
                    onClick={onCreateProfile}
                  >
                    + Tạo hồ sơ mới
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Audit Log Tab */}
        {activeTab === "audit" && (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <History className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-muted-foreground">
                Lịch sử thay đổi
              </h3>
            </div>
            <AuditLogTimeline entityType="Lead" entityId={lead.id} />
          </div>
        )}
      </SwipeableTabs>
    </div>
  );
}

export default LeadInfoTabs;
