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

import { useState } from "react";
import {
  Phone,
  Mail,
  MapPin,
  Calendar,
  Globe,
  User,
  GraduationCap,
  AlertCircle,
  Target,
  Briefcase,
  FileText,
  PhoneCall,
  Zap,
  Star,
  UserPlus,
  Video,
  MessageSquare,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CopyableCell } from "@/components/common/CopyableCell";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import type { Lead, TimelineItem } from "@/types/lead.types";

interface LeadInfoTabsProps {
  lead: Lead;
  timeline?: TimelineItem[];
  onAssign?: () => void;
  onCreateProfile?: () => void;
  onViewProfile?: () => void;
}

type TabId = "overview" | "history" | "profile";

const tabs: { id: TabId; label: string }[] = [
  { id: "overview", label: "Tổng quan" },
  { id: "history", label: "Lịch sử" },
  { id: "profile", label: "Hồ sơ" },
];

// Helper functions
const getEducationLevelLabel = (level: string | null | undefined) => {
  if (!level) return "N/A";
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

// Get method icon and color
const getMethodConfig = (method?: string) => {
  switch (method) {
    case "phone":
      return { icon: Phone, color: "text-emerald-600", bg: "bg-emerald-100", label: "Gọi điện" };
    case "email":
      return { icon: Mail, color: "text-blue-600", bg: "bg-blue-100", label: "Email" };
    case "video_call":
    case "video":
      return { icon: Video, color: "text-purple-600", bg: "bg-purple-100", label: "Video" };
    case "sms":
      return { icon: MessageSquare, color: "text-cyan-600", bg: "bg-cyan-100", label: "SMS" };
    case "in_person":
      return { icon: User, color: "text-amber-600", bg: "bg-amber-100", label: "Gặp mặt" };
    default:
      return { icon: PhoneCall, color: "text-slate-600", bg: "bg-slate-100", label: "Tư vấn" };
  }
};

// Get outcome styles
const getOutcomeStyles = (outcomeType?: string | null) => {
  switch (outcomeType) {
    case "positive":
      return { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700" };
    case "negative":
      return { bg: "bg-red-50", border: "border-red-200", text: "text-red-700" };
    default:
      return { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700" };
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
    <div className={cn("p-2.5 bg-slate-50 rounded-xl", className)}>
      <div className="text-xs text-slate-400">{label}</div>
      <div className={cn("text-sm font-medium", isEmpty ? "text-slate-400 italic" : "text-slate-700")}>
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

  const recentTimeline = timeline?.slice(0, 5) || [];

  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
      {/* Tab Headers */}
      <div className="flex border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex-1 px-4 py-3 text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "text-indigo-600 bg-indigo-50 border-b-2 border-indigo-600"
                : "text-slate-500 hover:text-slate-700 hover:bg-slate-50"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="p-4">
        {/* Overview Tab */}
        {activeTab === "overview" && (
          <div className="space-y-4">
            {/* Contact Info */}
            <div>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Liên hệ
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-xl">
                  <div className="flex items-center gap-3">
                    <Phone className="w-4 h-4 text-slate-400" />
                    <CopyableCell
                      value={lead.phone}
                      label="số điện thoại"
                      className="text-sm font-medium text-slate-700"
                    />
                  </div>
                  <span className="text-xs text-emerald-600 font-medium">Chính</span>
                </div>

                {lead.phone2 && (
                  <div className="flex items-center justify-between p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                    <div className="flex items-center gap-3">
                      <Phone className="w-4 h-4 text-slate-400" />
                      <CopyableCell
                        value={lead.phone2}
                        label="số điện thoại phụ"
                        className="text-sm text-slate-600"
                      />
                    </div>
                    <span className="text-xs text-slate-400">Phụ</span>
                  </div>
                )}

                {lead.email && (
                  <div className="flex items-center gap-3 p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                    <Mail className="w-4 h-4 text-slate-400" />
                    <a
                      href={`mailto:${lead.email}`}
                      className="text-sm text-blue-600 hover:underline truncate"
                    >
                      {lead.email}
                    </a>
                  </div>
                )}

                <div className="flex items-center gap-3 p-2.5 hover:bg-slate-50 rounded-xl transition-colors">
                  <MapPin className="w-4 h-4 text-slate-400" />
                  <span className={cn("text-sm", lead.location ? "text-slate-600" : "text-slate-400 italic")}>
                    {lead.location || "N/A"}
                  </span>
                </div>
              </div>
            </div>

            {/* Personal Info */}
            <div>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
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
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Học vấn
              </h3>
              {isWeakStudent(lead) ? (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="w-4 h-4 text-amber-500" />
                    <span className="text-xs font-semibold text-amber-700">Lưu ý khi tư vấn</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <div className="text-xs text-amber-600">Trình độ</div>
                      <div className="text-sm font-semibold text-amber-800">
                        {getEducationLevelLabel(lead.education_level)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-amber-600">Học lực</div>
                      <div className="text-sm font-semibold text-amber-800">
                        {getAcademicPerformanceLabel(lead.academic_performance)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-amber-600">GPA</div>
                      <div className="text-sm font-semibold text-amber-800">
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
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Nguồn & Phân công
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-500">Nguồn</span>
                  <span className="text-sm font-medium text-slate-700 flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5" />
                    {getSourceLabel(lead.source)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-500">Tư vấn viên</span>
                  {lead.assigned_officer ? (
                    <span className="text-sm font-medium text-slate-700">
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
                const isConsultation = item.type === "consultation" || item.event_type === "consultation";
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
                    key={`${item.id}-${index}`}
                    className={cn(
                      "p-3 rounded-xl border transition-colors",
                      index === 0
                        ? outcomeStyles.bg + " " + outcomeStyles.border
                        : "bg-white border-slate-200 hover:bg-slate-50"
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
                              <span
                                className="w-2 h-2 rounded-full flex-shrink-0"
                                style={{ backgroundColor: statusColor }}
                              />
                            )}
                            <span className={cn("text-sm font-medium truncate", index === 0 ? outcomeStyles.text : "text-slate-800")}>
                              {statusName}
                            </span>
                          </div>
                          {/* Actor */}
                          {actorName && (
                            <div className="text-xs text-slate-500">{actorName}</div>
                          )}
                        </div>
                      </div>

                      {/* Timestamp */}
                      <div className="text-right flex-shrink-0">
                        <div className="text-xs font-medium text-slate-600">
                          {new Date(item.timestamp).toLocaleTimeString("vi-VN", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                        <div className="text-xs text-slate-400">
                          {new Date(item.timestamp).toLocaleDateString("vi-VN", {
                            day: "2-digit",
                            month: "2-digit",
                          })}
                        </div>
                      </div>
                    </div>

                    {/* Row 2: Notes (if any, not auto-generated) */}
                    {notes && !notes.startsWith("Ghi nhận:") && !notes.startsWith("Ghi nhận nhanh:") && (
                      <p className="text-xs text-slate-500 italic pl-9 truncate">"{notes}"</p>
                    )}

                    {/* Row 3: Scheduled follow-up */}
                    {scheduledAt && (
                      <div className="flex items-center gap-1 text-xs text-blue-600 pl-9 mt-1">
                        <Clock className="w-3 h-3" />
                        <span>Hẹn: {new Date(scheduledAt).toLocaleString("vi-VN", {
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
                <div className="w-12 h-12 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-3">
                  <Calendar className="w-6 h-6 text-slate-400" />
                </div>
                <p className="text-sm text-slate-500">Chưa có lịch sử tư vấn</p>
              </div>
            )}
          </div>
        )}

        {/* Profile Tab */}
        {activeTab === "profile" && (
          <div>
            {lead.admission_profile ? (
              <div className="space-y-4">
                <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText className="w-4 h-4 text-emerald-600" />
                    <span className="text-sm font-semibold text-emerald-800">
                      Hồ sơ tuyển sinh #{lead.admission_profile.id}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <span className="text-emerald-600">Trạng thái:</span>{" "}
                      <span className="font-medium text-emerald-800">
                        {lead.admission_profile.status}
                      </span>
                    </div>
                    {lead.admission_profile.student_code && (
                      <div>
                        <span className="text-emerald-600">Mã SV:</span>{" "}
                        <span className="font-medium text-emerald-800">
                          {lead.admission_profile.student_code}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
                <Button className="w-full" onClick={onViewProfile}>
                  <FileText className="mr-2 h-4 w-4" />
                  Xem chi tiết hồ sơ
                </Button>
              </div>
            ) : (
              <div className="text-center py-8">
                <div className="w-12 h-12 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-3">
                  <FileText className="w-6 h-6 text-slate-400" />
                </div>
                <p className="text-sm text-slate-500">Chưa có hồ sơ tuyển sinh</p>
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
      </div>
    </div>
  );
}

export default LeadInfoTabs;
