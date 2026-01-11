"use client"

import { Badge } from "@/components/ui/badge"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { AlertCircle, CheckCircle2, XCircle } from "lucide-react"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse | null
  validation: {
    isEligible: boolean
    missingItems: { code: string; label: string; status: "error" | "warning" }[]
  }
}

export function AdmissionHeader({ profile, validation }: AdmissionHeaderProps) {
  const { isEligible } = validation
  
  // Phase 0.9: Use backend-computed validation_summary for grouped badges
  const summary = profile?.validation_summary

  return (
    <div className="h-16 px-6 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div>
           <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold">Hồ sơ #{profile?.lead_id || "---"}</h1>
              {isEligible ? (
                 <Badge variant="default" className="bg-green-100 text-green-700 hover:bg-green-100 border-green-200">
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    Đủ điều kiện
                 </Badge>
              ) : (
                 <Badge variant="destructive" className="bg-red-100 text-red-700 hover:bg-red-100 border-red-200">
                    <XCircle className="w-3 h-3 mr-1" />
                    Chưa đủ điều kiện
                 </Badge>
              )}
           </div>
           
           <div className="text-xs text-muted-foreground flex items-center gap-3 mt-1">
              <span>Lead: #{profile?.lead_id}</span>
              <span>•</span>
              <span>Tạo: {profile?.created_at ? new Date(profile.created_at).toLocaleDateString("vi-VN") : "---"}</span>
              <span>•</span>
              <span>Phụ trách: {profile?.lead?.assigned_officer_id || "---"}</span>
           </div>
        </div>
      </div>
      
      {/* Quick Status Bar - Now uses grouped badges from backend validation_summary */}
      <div className="flex items-center gap-2">
         {/* GPA Badge */}
         {summary?.gpa?.has_error && (
             <StatusBadge label={summary.gpa.label} status="error" />
         )}
         
         {/* Documents Badge (grouped) */}
         {summary?.documents?.has_error && (
             <StatusBadge 
                label={`Thiếu ${summary.documents.count} tài liệu`} 
                status="error" 
             />
         )}
         
         {/* Personal Info Badge */}
         {summary?.personal?.has_error && (
             <StatusBadge label={summary.personal.label} status="error" />
         )}
         
         {/* All good */}
         {!summary?.gpa?.has_error && !summary?.documents?.has_error && !summary?.personal?.has_error && (
             <span className="text-sm text-green-600 flex items-center">
                 <CheckCircle2 className="w-4 h-4 mr-1" />
                 Hồ sơ đầy đủ
             </span>
         )}
      </div>
    </div>
  )
}

function StatusBadge({ label, status, value }: { label: string, status: "success" | "error" | "warning", value?: string }) {
    const colors = {
        success: "bg-green-50 text-green-700 border-green-200",
        error: "bg-red-50 text-red-700 border-red-200",
        warning: "bg-yellow-50 text-yellow-700 border-yellow-200",
    }
    const icons = {
        success: null, // Minimalist
        error: <XCircle className="w-3 h-3" />,
        warning: <AlertCircle className="w-3 h-3" />,
    }

    return (
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium cursor-pointer transition-colors hover:bg-opacity-80 ${colors[status]}`}>
            <span>{label}</span>
            {value && <span>{value}</span>}
            {icons[status]}
        </div>
    )
}
