// src/app/(dashboard)/admissions/create/page.tsx
/**
 * Create Admission Profile Page
 * 
 * Creates a new AdmissionProfile for a Lead.
 * Requires lead_id query parameter.
 * REFACTORED (Phase 2): Now requires admission_method_id selection
 */
"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { ClipboardCheck, ArrowLeft, Loader2, AlertCircle } from "lucide-react"
import { useCreateAdmission } from "@/hooks/admissions"
import { useLead } from "@/hooks/useLeads"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api/client"
import { toast } from "sonner"
import { PageContainer } from "@/components/layouts/PageContainer"
import type { LeadAdmissionBlocker } from "@/types/lead.types"

// Blocker code → user-facing VN message. Source of truth lives in backend
// (admission_service.check_lead_level_admission_eligibility); frontend only renders.
const BLOCKER_MESSAGES: Record<LeadAdmissionBlocker, string> = {
  forbidden: "Bạn không có quyền tạo hồ sơ cho lead này.",
  already_has_profile: "Lead này đã có hồ sơ tuyển sinh.",
  invalid_lead_status: "Lead đang ở trạng thái không cho phép tạo hồ sơ.",
  missing_offering: "Lead chưa có chương trình đào tạo.",
  no_consultation: "Lead chưa có lịch sử tư vấn.",
  consultation_missing_status: "Lần tư vấn gần nhất chưa cập nhật kết quả.",
  consultation_universal_status: "Trạng thái tư vấn hiện tại chỉ là ghi nhận hoạt động, chưa phải kết quả tư vấn.",
}

// Blockers that can be resolved from lead detail page — show a contextual link.
const BLOCKER_HINTS: Partial<Record<LeadAdmissionBlocker, string>> = {
  missing_offering: "Mở lead để chọn chương trình",
  no_consultation: "Thêm tư vấn cho lead",
  consultation_missing_status: "Cập nhật trạng thái tư vấn",
  consultation_universal_status: "Cập nhật trạng thái tư vấn",
}

// Type for admission method from backend
interface AdmissionMethod {
  id: number
  code: string
  name: string
  description?: string
  is_active: boolean
}

interface AdmissionMethodListResponse {
  methods: AdmissionMethod[]
  total: number
}

// Hook to fetch admission methods
function useAdmissionMethods() {
  return useQuery({
    queryKey: ["admission-methods"],
    queryFn: async (): Promise<AdmissionMethod[]> => {
      const response = await api.get<AdmissionMethodListResponse>("/api/admission-config/methods")
      return response.data.methods
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - methods don't change often
  })
}

export default function CreateAdmissionPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const leadId = searchParams.get("lead_id")
  
  // State for selected admission method
  const [selectedMethodId, setSelectedMethodId] = useState<number | null>(null)
  
  const { data: lead, isLoading: isLoadingLead } = useLead(
    leadId ? parseInt(leadId) : 0,
    !!leadId // enabled - only fetch when leadId is present
  )
  
  const { data: methods = [], isLoading: isLoadingMethods } = useAdmissionMethods()
  
  const createMutation = useCreateAdmission()

  // Thin-client gate: backend computes permissions + action_blockers on LeadDetail.
  // Fallback strategy (rollout safety): if response lacks gate fields (older backend
  // or transient error), preserve old permissive behavior — button enabled, no alert.
  // Backend 400 at POST /admissions remains the defense in depth.
  const hasGateFields = lead?.permissions !== undefined
  const canCreateAdmission = hasGateFields
    ? (lead.permissions.create_admission ?? false)
    : true
  const blockerCode = hasGateFields ? lead?.action_blockers?.create_admission : undefined

  useEffect(() => {
    if (!leadId) {
      toast.error("Thiếu thông tin Lead")
      router.push("/leads")
    }
  }, [leadId, router])
  
  const handleCreate = async () => {
    if (!leadId || !selectedMethodId) return
    
    // Note: useCreateAdmission hook already handles success toast and navigation
    // Error is also handled via handleApiError() in the hook
    await createMutation.mutateAsync({
      lead_id: parseInt(leadId),
      admission_method_id: selectedMethodId,
    })
  }
  
  if (!leadId) {
    return null
  }
  
  // Filter to only active methods
  const activeMethods = methods.filter(m => m.is_active)
  
  return (
    <PageContainer maxWidth="sm">
      <Button 
        variant="ghost" 
        size="sm" 
        className="mb-4"
        onClick={() => router.back()}
      >
        <ArrowLeft className="mr-2 h-4 w-4" />
        Quay lại
      </Button>
      
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <ClipboardCheck className="h-8 w-8 text-primary" />
            <div>
              <CardTitle>Tạo hồ sơ tuyển sinh</CardTitle>
              <CardDescription>
                {isLoadingLead ? (
                  "Đang tải thông tin lead..."
                ) : lead ? (
                  <>Tạo hồ sơ cho: <strong>{lead.full_name}</strong> (Lead #{lead.id})</>
                ) : (
                  "Không tìm thấy Lead"
                )}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {lead && !canCreateAdmission && blockerCode && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Không thể tạo hồ sơ tuyển sinh</AlertTitle>
              <AlertDescription>
                {BLOCKER_MESSAGES[blockerCode]}
                {BLOCKER_HINTS[blockerCode] && leadId && (
                  <>
                    {" "}
                    <Link
                      href={`/leads/${leadId}`}
                      className="underline font-medium"
                    >
                      {BLOCKER_HINTS[blockerCode]}
                    </Link>
                  </>
                )}
              </AlertDescription>
            </Alert>
          )}

          {lead && (
            <div className="bg-muted/50 rounded-lg p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Họ tên:</span>
                <span className="font-medium">{lead.full_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Điện thoại:</span>
                <span className="font-mono">{lead.phone}</span>
              </div>
              {lead.email && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Email:</span>
                  <span>{lead.email}</span>
                </div>
              )}
              {lead.offering?.program?.name && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Ngành:</span>
                  <span>{lead.offering.program.name}</span>
                </div>
              )}
              {lead.offering?.program?.degree_level && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Trình độ:</span>
                  <span>{lead.offering.program.degree_level}</span>
                </div>
              )}
              {lead.offering?.offering_type && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Hình thức đào tạo:</span>
                  <span>{lead.offering.offering_type}</span>
                </div>
              )}
            </div>
          )}
          
          {/* Admission Method Selection - NEW */}
          <div className="space-y-2">
            <Label htmlFor="admission-method">
              Phương thức xét tuyển <span className="text-destructive">*</span>
            </Label>
            {isLoadingMethods ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải phương thức...
              </div>
            ) : activeMethods.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" />
                Không có phương thức xét tuyển khả dụng
              </div>
            ) : (
              <Select
                value={selectedMethodId?.toString() ?? ""}
                onValueChange={(value) => setSelectedMethodId(value ? parseInt(value) : null)}
              >
                <SelectTrigger id="admission-method">
                  <SelectValue placeholder="Chọn phương thức xét tuyển" />
                </SelectTrigger>
                <SelectContent>
                  {activeMethods.map((method) => (
                    <SelectItem key={method.id} value={method.id.toString()}>
                      {method.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <p className="text-xs text-muted-foreground">
              Phương thức xét tuyển xác định quy tắc đánh giá và hồ sơ yêu cầu
            </p>
          </div>
          
          <div className="flex gap-3 pt-4">
            <Button 
              variant="outline" 
              className="flex-1"
              onClick={() => router.back()}
            >
              Huỷ
            </Button>
            <Button
              className="flex-1"
              onClick={handleCreate}
              disabled={createMutation.isPending || !lead || !canCreateAdmission || !selectedMethodId}
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang tạo…
                </>
              ) : (
                <>
                  <ClipboardCheck className="mr-2 h-4 w-4" />
                  Tạo hồ sơ
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
