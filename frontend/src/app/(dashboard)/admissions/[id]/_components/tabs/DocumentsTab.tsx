"use client"

/**
 * Documents Tab Component
 * 
 * Checklist of required documents with status badges, upload, and view functionality.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { FileText, Check, AlertCircle, Clock, XCircle, Upload, Loader2, Eye, ExternalLink } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { useUploadAdmissionDocument } from "@/hooks/admissions/useAdmissions"
import { useRef, useState } from "react"
import { toast } from "sonner"

interface DocumentsTabProps {
  profile: AdmissionProfileResponse
  isEditable: boolean
}

// File validation constants
const ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
const ALLOWED_EXTENSIONS = ".pdf, .jpg, .jpeg, .png"

const STATUS_CONFIG = {
  missing: {
    label: "Chưa có",
    color: "bg-gray-100 text-gray-700",
    icon: AlertCircle,
  },
  uploaded: {
    label: "Đã tải lên",
    color: "bg-blue-100 text-blue-700",
    icon: Clock,
  },
  verified: {
    label: "Đã xác minh",
    color: "bg-green-100 text-green-700",
    icon: Check,
  },
  rejected: {
    label: "Từ chối",
    color: "bg-red-100 text-red-700",
    icon: XCircle,
  },
}

export function DocumentsTab({ profile, isEditable }: DocumentsTabProps) {
  const documents = profile.documents_checklist || []
  const uploadMutation = useUploadAdmissionDocument(profile.id)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedDocCode, setSelectedDocCode] = useState<string | null>(null)

  const handleUploadClick = (code: string) => {
    setSelectedDocCode(code)
    if (fileInputRef.current) {
        fileInputRef.current.value = "" // Reset input
        fileInputRef.current.click()
    }
  }

  const validateFile = (file: File): string | null => {
    // Check file type
    if (!ALLOWED_TYPES.includes(file.type)) {
      return `Loại file không hợp lệ. Chỉ chấp nhận: ${ALLOWED_EXTENSIONS}`
    }
    // Check file size
    if (file.size > MAX_FILE_SIZE) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1)
      return `File quá lớn (${sizeMB}MB). Tối đa 10MB.`
    }
    return null
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && selectedDocCode) {
      // Validate file
      const error = validateFile(file)
      if (error) {
        toast.error(error)
        return
      }
      // Upload file
      uploadMutation.mutate({ docCode: selectedDocCode, file })
    }
  }

  const handleViewDocument = (filePath: string) => {
    // Construct the URL to view the document
    // Backend serves files from /uploads/* static path
    const url = `${process.env.NEXT_PUBLIC_API_URL || ""}/${filePath}`
    window.open(url, "_blank", "noopener,noreferrer")
  }
  
  const uploadedCount = documents.filter(
    (d) => d.status === "uploaded" || d.status === "verified"
  ).length

  const mandatoryDocs = documents.filter((d) => d.is_mandatory)
  const mandatoryUploadedCount = mandatoryDocs.filter(
    (d) => d.status === "uploaded" || d.status === "verified"
  ).length

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Tài liệu hồ sơ
            </CardTitle>
            <CardDescription>
              {uploadedCount} / {documents.length} tài liệu đã nộp
              {mandatoryDocs.length > 0 && (
                <span className="ml-2">
                  (Bắt buộc: {mandatoryUploadedCount}/{mandatoryDocs.length})
                </span>
              )}
            </CardDescription>
          </div>
          {/* Progress indicator */}
          <div className="flex items-center gap-2">
            <div className="w-32 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{
                  width: documents.length > 0
                    ? `${(uploadedCount / documents.length) * 100}%`
                    : "0%",
                }}
              />
            </div>
            <span className="text-sm text-muted-foreground font-medium">
              {documents.length > 0
                ? Math.round((uploadedCount / documents.length) * 100)
                : 0}%
            </span>
          </div>
        </div>
        
        {/* File type info */}
        <p className="text-xs text-muted-foreground mt-2">
          Định dạng: {ALLOWED_EXTENSIONS} • Tối đa 10MB
        </p>
      </CardHeader>
      <CardContent>
        {documents.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <FileText className="h-12 w-12 mx-auto mb-3 opacity-20" />
            <p>Chưa có danh sách tài liệu</p>
            <p className="text-sm mt-1">
              Danh sách tài liệu sẽ được tạo tự động dựa trên quy định
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {documents.map((doc, index) => {
              const config = STATUS_CONFIG[doc.status] || STATUS_CONFIG.missing
              const StatusIcon = config.icon
              const isUploading = uploadMutation.isPending && selectedDocCode === doc.code
              const hasFile = doc.file_path && (doc.status === "uploaded" || doc.status === "verified")
              
              return (
                <div
                  key={doc.code || index}
                  className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-muted rounded">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="font-medium flex items-center gap-1">
                        {doc.label}
                        {doc.is_mandatory && (
                          <span className="text-red-500 text-xs">*</span>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Mã: {doc.code}
                        {doc.uploaded_at && (
                          <span className="ml-2">
                            • {new Date(doc.uploaded_at).toLocaleDateString("vi-VN")}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <Badge className={config.color}>
                      <StatusIcon className="h-3 w-3 mr-1" />
                      {config.label}
                    </Badge>
                    
                    {/* View button for uploaded documents */}
                    {hasFile && (
                      <Button 
                        size="sm" 
                        variant="ghost"
                        onClick={() => handleViewDocument(doc.file_path!)}
                        title="Xem tài liệu"
                      >
                        <Eye className="h-4 w-4 mr-1" />
                        Xem
                        <ExternalLink className="h-3 w-3 ml-1 opacity-50" />
                      </Button>
                    )}
                    
                    {/* Upload button */}
                    {isEditable && (doc.status === "missing" || doc.status === "rejected") && (
                      <Button 
                        size="sm" 
                        variant="outline" 
                        onClick={() => handleUploadClick(doc.code)}
                        disabled={uploadMutation.isPending}
                      >
                        {isUploading ? (
                            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        ) : (
                            <Upload className="h-4 w-4 mr-1" />
                        )}
                        {doc.status === "rejected" ? "Tải lại" : "Tải lên"}
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
      {/* Hidden File Input */}
      <input 
        type="file" 
        ref={fileInputRef} 
        className="hidden" 
        onChange={handleFileChange}
        accept={ALLOWED_EXTENSIONS}
      />
    </Card>
  )
}
