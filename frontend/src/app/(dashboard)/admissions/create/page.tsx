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
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select"
import { groupByMethodType } from "@/lib/admissions/method-groups"
import { Label } from "@/components/ui/label"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { ClipboardCheck, ArrowLeft, Loader2, AlertCircle } from "lucide-react"
import { useCreateAdmission } from "@/hooks/admissions"
import { useLead } from "@/hooks/useLeads"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api/client"
import { getPathsForOffering } from "@/lib/api/admission-paths"
import { toast } from "sonner"
import { PageContainer } from "@/components/layouts/PageContainer"
import { todayVN } from "@/lib/utils/vn-date"
import { formatRoundLabel } from "@/lib/utils/admission-helpers"
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
  // BE /api/admission-config/methods trả đủ các cờ này (mirror admin-config
  // AdmissionMethod) — dùng để nhóm dropdown theo loại + sort.
  requires_gpa: boolean
  requires_subject_scores: boolean
  display_order?: number
}

interface AdmissionMethodListResponse {
  methods: AdmissionMethod[]
  total: number
}

// Round contract hardening (plan v4): a distinct, usable admission round
// derived from the offering's active paths (``round_*`` flat fields on the
// for-offering response). ``isOpen`` = today within [start, end] in VN time.
interface RoundOption {
  id: number
  code: string | null
  name: string | null
  startDate: string | null
  endDate: string | null
  isOpen: boolean
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

// ADM-017 review-fix: fetch ACTIVE admission paths for the lead's
// offering. Each path carries ``academic_info.academic_year`` + the
// nested ``admission_method`` it's wired to. We derive both the year
// dropdown options AND the method dropdown options from this list,
// scoped to the selected year — this is the single source of truth
// the backend uses at ``create_profile`` time, so a path-driven UI
// guarantees the form can't submit a (year, method) pair the
// backend will reject.
function usePathsForOffering(offeringId: number | null | undefined) {
  return useQuery({
    queryKey: ["admission-paths", "for-offering", offeringId],
    queryFn: () =>
      offeringId ? getPathsForOffering(offeringId) : Promise.resolve([]),
    enabled: !!offeringId,
    staleTime: 5 * 60 * 1000,
  })
}

export default function CreateAdmissionPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const leadId = searchParams.get("lead_id")
  
  // ADM-017 review-fix: NO calendar-year default. State only holds
  // the OFFICER'S EXPLICIT PICK; the effective ``academicYear`` /
  // ``selectedMethodId`` rendered in the UI are *derived* below
  // from picked-state + eligible options. This shape avoids the
  // ``react-hooks/set-state-in-effect`` lint rule (CI-strict) that
  // would otherwise fire on a "useEffect → setState" auto-select
  // pattern.
  const [pickedYear, setPickedYear] = useState<number | null>(null)
  const [pickedRoundId, setPickedRoundId] = useState<number | null>(null)
  const [pickedMethodId, setPickedMethodId] = useState<number | null>(null)

  const { data: lead, isLoading: isLoadingLead } = useLead(
    leadId ? parseInt(leadId) : 0,
    !!leadId // enabled - only fetch when leadId is present
  )

  // Path-driven dropdowns (review-fix). We still keep
  // ``useAdmissionMethods`` around as a fallback display label
  // source — names live there. The actual gate on which methods
  // appear in the dropdown is derived from active paths.
  const { data: paths = [], isLoading: isLoadingPaths } = usePathsForOffering(
    lead?.offering_id ?? null
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

  // ADM-017 review-fix: derive eligible years + per-year method list
  // from the offering's active paths. Path response shape carries
  // ``academic_info.academic_year`` (offering-side cohort) and
  // ``admission_method`` (the path's wired method). Single source of
  // truth = same data the backend reads at ``create_profile``.
  const pathsByYear = new Map<number, typeof paths>()
  for (const p of paths) {
    const year = p.academic_info?.academic_year
    if (typeof year !== "number") continue
    const list = pathsByYear.get(year) ?? []
    list.push(p)
    pathsByYear.set(year, list)
  }
  const eligibleYears = Array.from(pathsByYear.keys()).sort((a, b) => b - a)

  // Effective year (derived) — fall through:
  //   1. officer's explicit pick → use it
  //   2. exactly 1 eligible year → auto-select (no ambiguity to silence)
  //   3. otherwise → null (officer must pick)
  // Auto-selecting only when ``eligibleYears.length === 1`` keeps
  // the original anti-implicit-selection guarantee from the prior
  // review fix.
  const academicYear: number | null =
    pickedYear ?? (eligibleYears.length === 1 ? eligibleYears[0] : null)

  // Round contract hardening (plan v4): derive the usable round options for
  // the selected year from the offering's active paths. Surface a distinct
  // round per ``admission_round_id`` and FILTER OUT archived / explicitly
  // inactive rounds (N4 — BE guard is final; FE just doesn't offer them).
  // ``isOpen`` uses a VN-local YYYY-MM-DD string compare (F39 — never
  // ``new Date("YYYY-MM-DD")``, which parses UTC midnight → off-by-one at
  // GMT+7).
  const today = todayVN()
  const roundsForYear: RoundOption[] =
    academicYear === null
      ? []
      : (() => {
          const yearPaths = pathsByYear.get(academicYear) ?? []
          const byId = new Map<number, RoundOption>()
          for (const p of yearPaths) {
            if (p.round_archived_at != null) continue
            if (p.round_is_active === false) continue
            if (byId.has(p.admission_round_id)) continue
            const startDate = p.round_start_date ?? null
            const endDate = p.round_end_date ?? null
            const isOpen =
              startDate != null &&
              endDate != null &&
              startDate <= today &&
              today <= endDate
            byId.set(p.admission_round_id, {
              id: p.admission_round_id,
              code: p.round_code ?? null,
              name: p.round_name ?? null,
              startDate,
              endDate,
              isOpen,
            })
          }
          return Array.from(byId.values()).sort((a, b) => {
            if (a.isOpen !== b.isOpen) return a.isOpen ? -1 : 1
            return (a.code ?? "").localeCompare(b.code ?? "")
          })
        })()

  // Default round (derived): auto-select ONLY when exactly one round is
  // currently open (today within its window). If multiple overlap (N7) or
  // none is open, leave null so the officer picks explicitly.
  const openRounds = roundsForYear.filter((r) => r.isOpen)
  const defaultRoundId: number | null =
    openRounds.length === 1 ? openRounds[0].id : null

  // Effective round (derived) — invalidates a picked id that's no longer in
  // the eligible set (e.g. after a year change). Mirrors the selectedMethodId
  // pattern below; no setState-in-effect.
  const selectedRoundId: number | null =
    pickedRoundId !== null && roundsForYear.some((r) => r.id === pickedRoundId)
      ? pickedRoundId
      : defaultRoundId

  // Methods filtered by the selected (year, round) paths.
  // ``useAdmissionMethods`` still drives display name lookup; the gate is
  // path-membership in the chosen round.
  const methodsForYear: AdmissionMethod[] =
    academicYear === null || selectedRoundId === null
      ? []
      : (() => {
          const yearPaths = pathsByYear.get(academicYear) ?? []
          const idsInRound = new Set(
            yearPaths
              .filter((p) => p.admission_round_id === selectedRoundId)
              .map((p) => p.admission_method_id)
          )
          return methods.filter((m) => m.is_active && idsInRound.has(m.id))
        })()

  // Effective method (derived) — invalidates the picked id if the
  // year change rendered it ineligible for that year. Replaces the
  // prior ``useEffect(() => setSelectedMethodId(null), [academicYear])``
  // cascade reset; same behaviour, no setState-in-effect.
  const selectedMethodId: number | null =
    pickedMethodId !== null &&
    methodsForYear.some((m) => m.id === pickedMethodId)
      ? pickedMethodId
      : null
  
  const handleCreate = async () => {
    // Submit guard mirrors the disabled state on the button below —
    // year, round and method are all required. This double-check guards
    // against a future change that loosens the disabled prop.
    if (
      !leadId ||
      !selectedMethodId ||
      academicYear === null ||
      selectedRoundId === null
    )
      return

    // Note: useCreateAdmission hook already handles success toast and navigation
    // Error is also handled via handleApiError() in the hook
    await createMutation.mutateAsync({
      lead_id: parseInt(leadId),
      admission_method_id: selectedMethodId,
      // Round contract hardening (plan v4): bind to the explicit round so
      // BE selects the exact (round, offering, method) AdmissionPath.
      admission_round_id: selectedRoundId,
      // ADM-017: bind to the selected recruitment year so BE can
      // resolve the right ``OfferingAcademicInfo`` deterministically.
      academic_year: academicYear,
    })
  }

  if (!leadId) {
    return null
  }
  
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
          
          {/* ADM-017 review-fix: Academic year selection is now
              path-driven. Options come from the offering's active
              paths (``/api/admission-config/paths/for-offering/{id}``);
              same source the backend uses at ``create_profile`` time,
              so the dropdown can never offer a year the backend
              would reject. No calendar-year default — when multiple
              eligible years exist the officer must pick explicitly,
              eliminating the silent-bind-to-wrong-year bug from the
              original FE PR. */}
          <div className="space-y-2">
            <Label htmlFor="academic-year">
              Năm học <span className="text-destructive">*</span>
            </Label>
            {isLoadingPaths ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải năm học khả dụng...
              </div>
            ) : eligibleYears.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" />
                Chương trình của lead này chưa có path tuyển sinh
                active. Vui lòng cấu hình ở Admission Config.
              </div>
            ) : (
              <Select
                value={academicYear?.toString() ?? ""}
                onValueChange={(value) =>
                  setPickedYear(value ? parseInt(value, 10) : null)
                }
              >
                <SelectTrigger id="academic-year">
                  <SelectValue placeholder="Chọn năm tuyển sinh" />
                </SelectTrigger>
                <SelectContent>
                  {eligibleYears.map((year) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <p className="text-xs text-muted-foreground">
              Chỉ liệt kê các năm có path tuyển sinh đang hoạt động cho
              chương trình của lead.
            </p>
          </div>

          {/* Round selection (round contract hardening, plan v4). Options
              derive from the offering's active paths for the selected year
              (``round_*`` flat fields) — the SAME source the backend
              validates at create_profile time. Archived / inactive rounds
              are filtered out (N4). Auto-default only when exactly one round
              is currently open; multiple overlapping open rounds (N7) require
              a manual pick. Window badges are advisory only — the backend
              does NOT hard-gate on dates (Hybrid). */}
          <div className="space-y-2">
            <Label htmlFor="admission-round">
              Đợt tuyển sinh <span className="text-destructive">*</span>
            </Label>
            {academicYear === null ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <AlertCircle className="h-4 w-4" />
                Chọn năm học trước để hiện danh sách đợt tuyển sinh.
              </div>
            ) : isLoadingPaths ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải đợt tuyển sinh...
              </div>
            ) : roundsForYear.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" />
                Năm {academicYear} chưa có đợt tuyển sinh khả dụng cho
                chương trình này.
              </div>
            ) : (
              <Select
                value={selectedRoundId?.toString() ?? ""}
                onValueChange={(value) =>
                  setPickedRoundId(value ? parseInt(value, 10) : null)
                }
              >
                <SelectTrigger id="admission-round">
                  <SelectValue placeholder="Chọn đợt tuyển sinh" />
                </SelectTrigger>
                <SelectContent>
                  {roundsForYear.map((r) => {
                    const windowLabel =
                      r.startDate == null || r.endDate == null
                        ? null
                        : today < r.startDate
                          ? "Chưa mở"
                          : today > r.endDate
                            ? "Đã hết hạn"
                            : null
                    return (
                      <SelectItem key={r.id} value={r.id.toString()}>
                        <span className="flex items-center gap-2">
                          <span>{formatRoundLabel(r)}</span>
                          {windowLabel && (
                            <span className="text-xs text-muted-foreground">
                              ({windowLabel})
                            </span>
                          )}
                        </span>
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            )}
            {openRounds.length > 1 ? (
              <p className="text-xs text-amber-600 dark:text-amber-500">
                Có nhiều đợt đang mở — vui lòng chọn đợt thủ công.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Đợt tuyển sinh xác định chỉ tiêu, lệ phí và quy tắc xét của hồ sơ.
              </p>
            )}
          </div>

          {/* Admission Method Selection — filtered by the selected
              (year, round) active paths. Dropdown is empty until a year
              and round are chosen, so officer can't pick a method that has
              no path for that round. */}
          <div className="space-y-2">
            <Label htmlFor="admission-method">
              Phương thức xét tuyển <span className="text-destructive">*</span>
            </Label>
            {academicYear === null ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <AlertCircle className="h-4 w-4" />
                Chọn năm học trước để hiện danh sách phương thức.
              </div>
            ) : selectedRoundId === null ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <AlertCircle className="h-4 w-4" />
                Chọn đợt tuyển sinh trước để hiện danh sách phương thức.
              </div>
            ) : isLoadingMethods || isLoadingPaths ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải phương thức...
              </div>
            ) : methodsForYear.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" />
                Năm {academicYear} không có phương thức xét tuyển khả
                dụng cho chương trình này.
              </div>
            ) : (
              <Select
                value={selectedMethodId?.toString() ?? ""}
                onValueChange={(value) =>
                  setPickedMethodId(value ? parseInt(value, 10) : null)
                }
              >
                <SelectTrigger id="admission-method">
                  <SelectValue placeholder="Chọn phương thức xét tuyển" />
                </SelectTrigger>
                <SelectContent>
                  {/* Nhóm theo loại (Học bạ / Điểm thi / Kết hợp / Khác) + sort
                      display_order trong nhóm → danh sách có tổ chức, giảm chọn
                      nhầm. Ẩn tiêu đề khi chỉ 1 nhóm. */}
                  {(() => {
                    const groups = groupByMethodType(
                      methodsForYear,
                      (m) => m,
                      (m) => m.display_order ?? 0,
                      (m) => m.name,
                    )
                    const showHeaders = groups.length > 1
                    return groups.map((g) => (
                      <SelectGroup key={g.key}>
                        {showHeaders && <SelectLabel>{g.label}</SelectLabel>}
                        {g.items.map((method) => (
                          <SelectItem key={method.id} value={method.id.toString()}>
                            {method.name}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    ))
                  })()}
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
              disabled={
                createMutation.isPending ||
                !lead ||
                !canCreateAdmission ||
                !selectedMethodId ||
                academicYear === null ||
                selectedRoundId === null
              }
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
