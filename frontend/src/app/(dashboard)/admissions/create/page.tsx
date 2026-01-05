// src/app/(dashboard)/admissions/create/page.tsx
/**
 * Create Admission Profile Page
 * 
 * Creates a new AdmissionProfile for a Lead.
 * Requires lead_id query parameter.
 */
"use client"

import { useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ClipboardCheck, ArrowLeft, Loader2 } from "lucide-react"
import { useCreateAdmission } from "@/hooks/admissions"
import { useLead } from "@/hooks/useLeads"
import { toast } from "sonner"

export default function CreateAdmissionPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const leadId = searchParams.get("lead_id")
  
  const { data: lead, isLoading: isLoadingLead } = useLead(
    leadId ? parseInt(leadId) : 0,
    !!leadId // enabled - only fetch when leadId is present
  )
  
  const createMutation = useCreateAdmission()
  
  useEffect(() => {
    if (!leadId) {
      toast.error("Thiếu thông tin Lead")
      router.push("/leads")
    }
  }, [leadId, router])
  
  const handleCreate = async () => {
    if (!leadId) return
    
    try {
      const result = await createMutation.mutateAsync({
        lead_id: parseInt(leadId),
      })
      
      toast.success("Đã tạo hồ sơ tuyển sinh")
      router.push(`/admissions/${result.id}`)
    } catch (error: unknown) {
      const errorMessage = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Không thể tạo hồ sơ"
      toast.error(errorMessage)
    }
  }
  
  if (!leadId) {
    return null
  }
  
  return (
    <div className="container mx-auto py-6 max-w-2xl">
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
            </div>
          )}
          
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
              disabled={createMutation.isPending || !lead}
            >
              {createMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang tạo...
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
    </div>
  )
}
