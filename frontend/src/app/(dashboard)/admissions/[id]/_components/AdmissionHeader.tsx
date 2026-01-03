"use client"

/**
 * Admission Header Component
 * 
 * Displays profile header with status badge and lead information.
 */

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { User, Calendar, FileCheck } from "lucide-react"
import { getStatusColor, getStatusLabel, type AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse
}

export function AdmissionHeader({ profile }: AdmissionHeaderProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary/10 rounded-lg">
              <FileCheck className="h-6 w-6 text-primary" />
            </div>
            <div>
              <CardTitle className="text-xl">Hồ sơ tuyển sinh #{profile.id}</CardTitle>
              <CardDescription>
                <span className="flex items-center gap-4 mt-1">
                  <span className="flex items-center gap-1">
                    <User className="h-3 w-3" />
                    Lead #{profile.lead_id}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {new Date(profile.created_at).toLocaleDateString("vi-VN")}
                  </span>
                </span>
              </CardDescription>
            </div>
          </div>
          <Badge className={getStatusColor(profile.status)}>
            {getStatusLabel(profile.status)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">CCCD/CMND</p>
            <p className="font-medium">{profile.citizen_id || "Chưa nhập"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">GPA</p>
            <p className="font-medium">
              {profile.admission_scores?.gpa?.toFixed(2) || "Chưa nhập"}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Thành viên gia đình</p>
            <p className="font-medium">{profile.family_info?.length || 0}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Tài liệu</p>
            <p className="font-medium">
              {profile.documents_checklist?.filter((d) => d.status === "uploaded" || d.status === "verified").length || 0} / {profile.documents_checklist?.length || 0}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
