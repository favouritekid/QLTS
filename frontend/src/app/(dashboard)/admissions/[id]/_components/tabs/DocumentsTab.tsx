"use client"

/**
 * Documents Tab Component (REFACTORED)
 * 
 * Comprehensive document submission table per wireframe:
 * - Tên giấy tờ | Loại nộp | Hình thức | Trạng thái | Thao tác
 * 
 * Features:
 * - Display ALL documents from doc_configs (not just requires_upload=true)
 * - submission_format badges (photo, certified_copy, original)
 * - requires_upload column (Online vs Nộp giấy)
 * - paper_submitted status support
 * - Officer-only checkbox for paper submission
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { 
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle 
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { 
  FileText, Check, AlertCircle, Clock, XCircle, Upload, Loader2, Eye, ExternalLink,
  Camera, FileCheck, FileSpreadsheet, Globe, Building2, Ban
} from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { useUploadAdmissionDocument, useMarkPaperSubmitted, useRejectDocument } from "@/hooks/admissions/useAdmissions"
import { useRef, useState } from "react"
import { toast } from "sonner"

interface DocumentsTabProps {
  profile: AdmissionProfileResponse
  isEditable: boolean
  isOfficer?: boolean // NEW: Officer can mark paper submitted or reject
}

// ============================================================================
// STATUS CONFIG
// ============================================================================

const STATUS_CONFIG: Record<string, {
  label: string
  color: string
  icon: typeof AlertCircle
}> = {
  missing: {
    label: "Chưa nộp",
    color: "bg-gray-100 text-gray-700",
    icon: AlertCircle,
  },
  uploaded: {
    label: "Đã tải",
    color: "bg-blue-100 text-blue-700",
    icon: Check,
  },
  paper_submitted: {
    label: "Đã nộp",
    color: "bg-green-100 text-green-700",
    icon: Check,
  },
  verified: {
    label: "Đã xác minh",
    color: "bg-green-100 text-green-700",
    icon: Check,
  },
  rejected: {
    label: "Không hợp lệ",
    color: "bg-red-100 text-red-700",
    icon: XCircle,
  },
}

// ============================================================================
// SUBMISSION FORMAT CONFIG
// ============================================================================

const FORMAT_CONFIG: Record<string, {
  label: string
  icon: typeof Camera
}> = {
  photo: {
    label: "Ảnh chụp",
    icon: Camera,
  },
  certified_copy: {
    label: "Sao y",
    icon: FileCheck,
  },
  original: {
    label: "Bản gốc",
    icon: FileSpreadsheet,
  },
}

function getStatusConfig(status: string) {
  return STATUS_CONFIG[status] ?? {
    label: status,
    color: "bg-gray-100 text-gray-700",
    icon: AlertCircle,
  }
}

function getFormatConfig(format: string | null | undefined) {
  if (!format) return null
  return FORMAT_CONFIG[format] ?? { label: format, icon: FileSpreadsheet }
}

// ============================================================================
// COMPONENT
// ============================================================================

export function DocumentsTab({ profile, isEditable, isOfficer = false }: DocumentsTabProps) {
  const documents = profile.documents_checklist || []
  const uploadMutation = useUploadAdmissionDocument(profile.id)
  const paperMutation = useMarkPaperSubmitted(profile.id)
  const rejectMutation = useRejectDocument(profile.id)
  
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedDocCode, setSelectedDocCode] = useState<string | null>(null)
  
  // Rejection Dialog State
  const [rejectItem, setRejectItem] = useState<{code: string, label: string} | null>(null)
  const [rejectReason, setRejectReason] = useState("")

  // Upload config
  const uploadConfig = profile.applied_rules.upload_config
  const allowedTypes = uploadConfig?.allowed_types || []
  const maxFileSize = uploadConfig?.max_file_size || 0
  const allowedExtensionsDisplay = uploadConfig?.allowed_extensions 
    ? uploadConfig.allowed_extensions.map(ext => `.${ext}`).join(", ")
    : "N/A"

  const handleUploadClick = (code: string) => {
    setSelectedDocCode(code)
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
      fileInputRef.current.click()
    }
  }

  const validateFile = (file: File): string | null => {
    if (!allowedTypes.includes(file.type)) {
      return `Loại file không hợp lệ. Chỉ chấp nhận: ${allowedExtensionsDisplay}`
    }
    if (file.size > maxFileSize) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1)
      return `File quá lớn (${sizeMB}MB). Tối đa 10MB.`
    }
    return null
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && selectedDocCode) {
      const error = validateFile(file)
      if (error) {
        toast.error(error)
        return
      }
      uploadMutation.mutate({ docCode: selectedDocCode, file })
    }
  }

  const handlePaperSubmit = (code: string) => {
    paperMutation.mutate(code)
  }
  
  const handleRejectClick = (code: string, label: string) => {
    setRejectItem({ code, label })
    setRejectReason("")
  }
  
  const confirmReject = () => {
    if (!rejectItem) return
    if (!rejectReason.trim()) {
      toast.error("Vui lòng nhập lý do từ chối")
      return
    }
    
    rejectMutation.mutate(
      { docCode: rejectItem.code, reason: rejectReason },
      {
        onSuccess: () => {
          setRejectItem(null)
        }
      }
    )
  }

  const handleViewDocument = (filePath: string) => {
    const url = `${process.env.NEXT_PUBLIC_API_URL || ""}/${filePath}`
    window.open(url, "_blank", "noopener,noreferrer")
  }
  
  // Stats
  const completedCount = documents.filter(
    (d) => d.status === "uploaded" || d.status === "verified" || d.status === "paper_submitted"
  ).length
  const mandatoryDocs = documents.filter((d) => d.is_mandatory)
  const mandatoryCompletedCount = mandatoryDocs.filter(
    (d) => d.status === "uploaded" || d.status === "verified" || d.status === "paper_submitted"
  ).length

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Tài liệu hồ sơ
              </CardTitle>
              <CardDescription>
                {completedCount} / {documents.length} tài liệu đã nộp
                {mandatoryDocs.length > 0 && (
                  <span className="ml-2">
                    (Bắt buộc: {mandatoryCompletedCount}/{mandatoryDocs.length})
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
                      ? `${(completedCount / documents.length) * 100}%`
                      : "0%",
                  }}
                />
              </div>
              <span className="text-sm text-muted-foreground font-medium">
                {documents.length > 0
                  ? Math.round((completedCount / documents.length) * 100)
                  : 0}%
              </span>
            </div>
          </div>
          
          <p className="text-xs text-muted-foreground mt-2">
            Định dạng: {allowedExtensionsDisplay} • Tối đa {Math.round(maxFileSize / (1024 * 1024))}MB
          </p>
        </CardHeader>
        
        <CardContent>
          {documents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p>Chưa có danh sách tài liệu</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc, index) => {
                const statusConfig = getStatusConfig(doc.status)
                const formatConfig = getFormatConfig(doc.submission_format)
                const StatusIcon = statusConfig.icon
                const FormatIcon = formatConfig?.icon || FileSpreadsheet
                
                const isUploading = uploadMutation.isPending && selectedDocCode === doc.code
                const isPaperPending = paperMutation.isPending && paperMutation.variables === doc.code
                const hasFile = doc.file_path && (doc.status === "uploaded" || doc.status === "verified")
                const requiresUpload = doc.requires_upload !== false // Default true if undefined
                const isPaperDoc = !requiresUpload
                const canReject = isOfficer && (doc.status === "uploaded" || doc.status === "paper_submitted" || doc.status === "verified")
                
                return (
                  <div
                    key={doc.code || index}
                    className="flex items-center justify-between p-3 border rounded-lg hover:bg-muted/30 transition-colors"
                  >
                    {/* Column 1: Tên giấy tờ */}
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <div className="p-2 bg-muted rounded">
                        <FileText className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium flex items-center gap-1 truncate">
                          {doc.label}
                          {doc.is_mandatory && (
                            <span className="text-red-500 text-xs">*</span>
                          )}
                        </p>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>Mã: {doc.code}</span>
                          {doc.uploaded_at && (
                            <span>• {new Date(doc.uploaded_at).toLocaleDateString("vi-VN")}</span>
                          )}
                          {doc.status === "rejected" && doc.rejection_reason && (
                            <span className="text-red-600 font-medium">
                              • Lý do: {doc.rejection_reason}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    {/* Column 2: Loại nộp (submission_format) */}
                    <div className="w-24 flex-shrink-0">
                      {formatConfig && (
                        <Badge variant="outline" className="text-xs gap-1">
                          <FormatIcon className="h-3 w-3" />
                          {formatConfig.label}
                        </Badge>
                      )}
                    </div>
                    
                    {/* Column 3: Hình thức (Online vs Nộp giấy) */}
                    <div className="w-24 flex-shrink-0">
                      <Badge variant="secondary" className="text-xs gap-1">
                        {requiresUpload ? (
                          <>
                            <Globe className="h-3 w-3" />
                            Online
                          </>
                        ) : (
                          <>
                            <Building2 className="h-3 w-3" />
                            Nộp giấy
                          </>
                        )}
                      </Badge>
                    </div>
                    
                    {/* Column 4: Trạng thái */}
                    <div className="w-28 flex-shrink-0">
                      <Badge className={statusConfig.color}>
                        <StatusIcon className="h-3 w-3 mr-1" />
                        {statusConfig.label}
                      </Badge>
                    </div>
                    
                    {/* Column 5: Thao tác */}
                    <div className="w-32 flex-shrink-0 flex items-center justify-end gap-2">
                      {/* View button for uploaded documents */}
                      {hasFile && (
                        <Button 
                          size="sm" 
                          variant="ghost"
                          onClick={() => handleViewDocument(doc.file_path!)}
                          title="Xem tài liệu"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      )}
                      
                      {/* Upload button for online documents */}
                      {requiresUpload && isEditable && (doc.status === "missing" || doc.status === "rejected") && (
                        <Button 
                          size="sm" 
                          variant="outline" 
                          onClick={() => handleUploadClick(doc.code)}
                          disabled={uploadMutation.isPending}
                        >
                          {isUploading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Upload className="h-4 w-4" />
                          )}
                        </Button>
                      )}
                      
                      {/* Paper submission checkbox (Officer only) */}
                      {isPaperDoc && isOfficer && doc.status === "missing" && (
                        <div className="flex items-center gap-1">
                          <Checkbox 
                            id={`paper-${doc.code}`}
                            disabled={isPaperPending}
                            onCheckedChange={(checked) => {
                              if (checked) handlePaperSubmit(doc.code)
                            }}
                          />
                          <label 
                            htmlFor={`paper-${doc.code}`}
                            className="text-xs text-muted-foreground cursor-pointer select-none"
                          >
                            Đã nộp
                          </label>
                        </div>
                      )}
                      
                      {/* Paper already submitted indicator */}
                      {isPaperDoc && doc.status === "paper_submitted" && (
                        <Check className="h-4 w-4 text-green-600" />
                      )}
                      
                      {/* Reject Button (Officer Only) */}
                      {canReject && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                          onClick={() => handleRejectClick(doc.code, doc.label)}
                          title="Từ chối tài liệu"
                        >
                          <Ban className="h-4 w-4" />
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
          accept={allowedExtensionsDisplay}
        />
      </Card>
      
      {/* Rejection Dialog */}
      <Dialog open={!!rejectItem} onOpenChange={(open) => !open && setRejectItem(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Từ chối tài liệu</DialogTitle>
            <DialogDescription>
              Vui lòng nhập lý do từ chối tài liệu <strong>{rejectItem?.label}</strong>.
              Học sinh sẽ nhận được thông báo để nộp lại.
            </DialogDescription>
          </DialogHeader>
          
          <div className="py-4">
            <Label htmlFor="reject-reason" className="mb-2 block">Lý do từ chối</Label>
            <Textarea
              id="reject-reason"
              placeholder="VD: Tài liệu mờ, không đúng định dạng..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
            />
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectItem(null)}>Huỷ</Button>
            <Button 
              variant="destructive" 
              onClick={confirmReject}
              disabled={rejectMutation.isPending || !rejectReason.trim()}
            >
              {rejectMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Xác nhận từ chối
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
