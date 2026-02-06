// src/components/leads/LeadInfoTab.tsx
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Building, GraduationCap, MapPin, Calendar, User } from "lucide-react";
import type { Lead } from "@/types/lead.types";

interface LeadInfoTabProps {
  lead: Lead;
}

export function LeadInfoTab({ lead }: LeadInfoTabProps) {
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

  const getSourceLabel = (source: string) => {
    const labels: Record<string, string> = {
      website: "Website",
      referral: "Giới thiệu",
      social_media: "Mạng xã hội",
      walk_in: "Đến trực tiếp",
      email: "Email",
      phone: "Điện thoại",
      event: "Sự kiện",
      other: "Khác",
    };
    return labels[source] || source;
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* Thông tin liên hệ */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin liên hệ</CardTitle>
          <CardDescription>Thông tin liên lạc cơ bản</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium text-muted-foreground">Họ và tên</label>
            <p className="text-base font-semibold">{lead.full_name}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Email</label>
            <p className="text-base">{lead.email}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Số điện thoại</label>
            <p className="text-base">{lead.phone}</p>
          </div>
          {lead.location && (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Địa chỉ</label>
              <div className="flex items-center gap-2">
                <MapPin aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                <p className="text-base">{lead.location}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Thông tin học vấn */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin học vấn</CardTitle>
          <CardDescription>Lý lịch học tập</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {lead.education_level ? (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Trình độ học vấn</label>
              <div className="flex items-center gap-2">
                <GraduationCap aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                <p className="text-base">
                  {getEducationLevelLabel(lead.education_level)}
                </p>
              </div>
            </div>
          ) : (
            <div>
              <label className="text-sm font-medium text-muted-foreground">Trình độ học vấn</label>
              <p className="text-base text-muted-foreground">Chưa cung cấp</p>
            </div>
          )}

          {lead.gpa !== null && lead.gpa !== undefined ? (
            <div>
              <label className="text-sm font-medium text-muted-foreground">GPA</label>
              <p className="text-base font-semibold">{lead.gpa.toFixed(2)} / 4.0</p>
            </div>
          ) : (
            <div>
              <label className="text-sm font-medium text-muted-foreground">GPA</label>
              <p className="text-base text-muted-foreground">Chưa cung cấp</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Thông tin Lead */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin Lead</CardTitle>
          <CardDescription>Nguồn và thông tin theo dõi</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium text-muted-foreground">Nguồn</label>
            <div className="mt-1">
              <Badge variant="outline">
                {getSourceLabel(lead.source)}
              </Badge>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Điểm Lead</label>
            <p className="text-base font-semibold">{lead.lead_score}/100</p>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Ngày tạo</label>
            <div className="flex items-center gap-2">
              <Calendar aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">
                {new Date(lead.created_at).toLocaleString("vi-VN")}
              </p>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium text-muted-foreground">Cập nhật lần cuối</label>
            <div className="flex items-center gap-2">
              <Calendar aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">
                {new Date(lead.updated_at).toLocaleString("vi-VN")}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Thông tin phân công */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin phân công</CardTitle>
          <CardDescription>Chi tiết phân công tư vấn viên</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {lead.assigned_officer_id ? (
            <>
              <div>
                <label className="text-sm font-medium text-muted-foreground">
                  Tư vấn viên phụ trách
                </label>
                <div className="flex items-center gap-2">
                  <User aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                  <p className="text-base">Tư vấn viên #{lead.assigned_officer_id}</p>
                </div>
              </div>
              {lead.assigned_at && (
                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Ngày phân công
                  </label>
                  <div className="flex items-center gap-2">
                    <Calendar aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                    <p className="text-base">
                      {new Date(lead.assigned_at).toLocaleString("vi-VN")}
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div>
              <p className="text-muted-foreground">Chưa được phân công cho tư vấn viên nào</p>
            </div>
          )}

          <div>
            <label className="text-sm font-medium text-muted-foreground">Đơn vị</label>
            <div className="flex items-center gap-2">
              <Building aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              <p className="text-base">Đơn vị #{lead.unit_id}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
