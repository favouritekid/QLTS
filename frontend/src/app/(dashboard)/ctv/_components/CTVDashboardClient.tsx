"use client"

import { useState } from "react"
import { Database, CheckCircle, Award, Clock, Plus, DollarSign, AlertTriangle } from "lucide-react"
import { PageContainer } from "@/components/layouts/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { useCTVProfile, useCTVStats, useCTVLeads, useCTVClaims } from "@/hooks/useCollaborators"
import { useCTVCommissions, useCTVCommissionStats } from "@/hooks/useCommissions"
import { getLeadValidityLabel } from "@/constants/lead.constants"
import { SubmitLeadDialog } from "@/components/ctv/SubmitLeadDialog"
import type { LeadClaimStatus } from "@/types/collaborator.types"
import type { CommissionRecordStatus } from "@/types/commission.types"

// =============================================================================
// CONSTANTS
// =============================================================================

const PAGE_SIZE = 10

const CLAIM_STATUS_VARIANT: Record<LeadClaimStatus, "secondary" | "default" | "destructive"> = {
  pending: "secondary",
  approved: "default",
  rejected: "destructive",
}

const CLAIM_STATUS_LABEL: Record<LeadClaimStatus, string> = {
  pending: "Chờ duyệt",
  approved: "Đã duyệt",
  rejected: "Từ chối",
}

const COMMISSION_STATUS_CONFIG: Record<CommissionRecordStatus, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Chờ duyệt", variant: "secondary" },
  approved: { label: "Đã duyệt", variant: "default" },
  paid: { label: "Đã thanh toán", variant: "default" },
  rejected: { label: "Từ chối", variant: "destructive" },
  cancelled: { label: "Đã hủy", variant: "outline" },
}

function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "-"
  try {
    return new Date(isoString).toLocaleDateString("vi-VN")
  } catch {
    return "-"
  }
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(amount)
}

// =============================================================================
// STAT CARD
// =============================================================================

interface StatCardProps {
  title: string
  value: number | string | undefined
  icon: React.ReactNode
  isLoading: boolean
}

function StatCard({ title, value, icon, isLoading }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <div className="p-2 rounded-full bg-primary/10 text-primary" aria-hidden="true">
          {icon}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <div className="text-2xl font-bold">{value ?? 0}</div>
        )}
      </CardContent>
    </Card>
  )
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function CTVDashboardClient() {
  const [submitDialogOpen, setSubmitDialogOpen] = useState(false)
  const [leadsPage, setLeadsPage] = useState(1)
  const [claimsPage, setClaimsPage] = useState(1)
  const [commissionsPage, setCommissionsPage] = useState(1)

  const { data: profile, isLoading: profileLoading } = useCTVProfile()
  const { data: stats, isLoading: statsLoading, isError: statsError } = useCTVStats()
  const { data: leadsData, isLoading: leadsLoading, isError: leadsError } = useCTVLeads({
    skip: (leadsPage - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  })
  const { data: claimsData, isLoading: claimsLoading, isError: claimsError } = useCTVClaims({
    skip: (claimsPage - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  })
  const { data: commissionsData, isLoading: commissionsLoading, isError: commissionsError } = useCTVCommissions({
    skip: (commissionsPage - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  })
  const { data: commissionStats, isLoading: commissionStatsLoading } = useCTVCommissionStats()

  const leadsTotalPages = leadsData ? Math.ceil(leadsData.total_count / PAGE_SIZE) : 0
  const claimsTotalPages = claimsData ? Math.ceil(claimsData.total_count / PAGE_SIZE) : 0
  const commissionsTotalPages = commissionsData ? Math.ceil(commissionsData.total_count / PAGE_SIZE) : 0

  return (
    <PageContainer maxWidth="xl">
      {/* Header */}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard CTV</h1>
          <p className="text-muted-foreground">
            {profileLoading ? (
              <Skeleton className="h-5 w-48 inline-block" />
            ) : (
              <>
                Xin chào, <span className="font-medium">{profile?.full_name}</span>
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {profile?.code && (
            <Badge variant="outline" className="text-sm">
              {profile.code}
            </Badge>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          title="Tổng lead"
          value={stats?.total_leads}
          icon={<Database className="h-4 w-4" />}
          isLoading={statsLoading}
        />
        <StatCard
          title="Lead hợp lệ"
          value={stats?.valid_leads}
          icon={<CheckCircle className="h-4 w-4" />}
          isLoading={statsLoading}
        />
        <StatCard
          title="Lead đủ ĐK"
          value={stats?.qualified_leads}
          icon={<Award className="h-4 w-4" />}
          isLoading={statsLoading}
        />
        <StatCard
          title="Claim chờ duyệt"
          value={stats?.pending_claims}
          icon={<Clock className="h-4 w-4" />}
          isLoading={statsLoading}
        />
        <StatCard
          title="Hoa hồng chờ"
          value={commissionStats ? formatCurrency(commissionStats.total_pending) : undefined}
          icon={<DollarSign className="h-4 w-4" />}
          isLoading={commissionStatsLoading}
        />
      </div>

      {/* Error banner */}
      {(statsError || leadsError || claimsError || commissionsError) && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-2 pt-4 text-destructive">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <p className="text-sm">Có lỗi khi tải dữ liệu. Vui lòng tải lại trang.</p>
          </CardContent>
        </Card>
      )}

      {/* Submit Lead Button */}
      <div>
        <Button onClick={() => setSubmitDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" aria-hidden="true" />
          Gửi lead mới
        </Button>
      </div>

      {/* Tabs: Leads, Claims, Commissions */}
      <Tabs defaultValue="leads">
        <TabsList>
          <TabsTrigger value="leads">Leads của tôi</TabsTrigger>
          <TabsTrigger value="claims">Yêu cầu claim</TabsTrigger>
          <TabsTrigger value="commissions">Hoa hồng</TabsTrigger>
        </TabsList>

        {/* Leads Tab */}
        <TabsContent value="leads" className="space-y-4">
          <Card>
            <CardContent className="p-0">
              {leadsLoading ? (
                <div className="p-4 md:p-6 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : !leadsData?.leads?.length ? (
                <div className="p-8 text-center text-muted-foreground">
                  <p>Chưa có lead nào.</p>
                  <Button variant="outline" size="sm" className="mt-3" onClick={() => setSubmitDialogOpen(true)}>
                    <Plus className="h-4 w-4 mr-2" aria-hidden="true" />
                    Gửi lead mới
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Họ tên</TableHead>
                      <TableHead>SĐT</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead>Hợp lệ</TableHead>
                      <TableHead>Ngày tạo</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {leadsData.leads.map((lead) => (
                      <TableRow key={lead.id}>
                        <TableCell className="font-medium">{lead.full_name}</TableCell>
                        <TableCell>{lead.phone_masked}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{lead.status}</Badge>
                        </TableCell>
                        <TableCell>
                          {lead.validity_status ? (
                            <Badge variant="secondary">
                              {getLeadValidityLabel(lead.validity_status)}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell>{formatDate(lead.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* F-1: Leads pagination */}
          {leadsData && leadsData.total_count > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <p className="text-muted-foreground text-sm">
                Hiển thị {(leadsPage - 1) * PAGE_SIZE + 1}-{Math.min(leadsPage * PAGE_SIZE, leadsData.total_count)} / {leadsData.total_count}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setLeadsPage((p) => Math.max(1, p - 1))} disabled={leadsPage === 1}>
                  Trước
                </Button>
                <Button variant="outline" size="sm" onClick={() => setLeadsPage((p) => Math.min(leadsTotalPages, p + 1))} disabled={leadsPage === leadsTotalPages}>
                  Sau
                </Button>
              </div>
            </div>
          )}
        </TabsContent>

        {/* Claims Tab */}
        <TabsContent value="claims" className="space-y-4">
          <Card>
            <CardContent className="p-0">
              {claimsLoading ? (
                <div className="p-4 md:p-6 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : !claimsData?.claims?.length ? (
                <div className="p-8 text-center text-muted-foreground">
                  Chưa có yêu cầu claim nào.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tên lead</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead>Lý do từ chối</TableHead>
                      <TableHead>Ngày gửi</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {claimsData.claims.map((claim) => (
                      <TableRow key={claim.id}>
                        <TableCell className="font-medium">
                          {claim.claim_data?.full_name ?? claim.lead?.full_name ?? "-"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={CLAIM_STATUS_VARIANT[claim.status] ?? "outline"}>
                            {CLAIM_STATUS_LABEL[claim.status] ?? claim.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {claim.status === "rejected" && claim.rejection_reason ? (
                            <span className="text-destructive text-sm">
                              {claim.rejection_reason}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell>{formatDate(claim.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* F-1: Claims pagination */}
          {claimsData && claimsData.total_count > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <p className="text-muted-foreground text-sm">
                Hiển thị {(claimsPage - 1) * PAGE_SIZE + 1}-{Math.min(claimsPage * PAGE_SIZE, claimsData.total_count)} / {claimsData.total_count}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setClaimsPage((p) => Math.max(1, p - 1))} disabled={claimsPage === 1}>
                  Trước
                </Button>
                <Button variant="outline" size="sm" onClick={() => setClaimsPage((p) => Math.min(claimsTotalPages, p + 1))} disabled={claimsPage === claimsTotalPages}>
                  Sau
                </Button>
              </div>
            </div>
          )}
        </TabsContent>

        {/* Commissions Tab (Task 6.4) */}
        <TabsContent value="commissions" className="space-y-4">
          {/* Commission Stats Cards */}
          {commissionStats && (
            <div className="grid gap-4 sm:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">Tổng hoa hồng</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-xl font-bold">{formatCurrency(commissionStats.total_earned)}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">Chờ duyệt</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-xl font-bold text-yellow-600">{formatCurrency(commissionStats.total_pending)}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">Đã thanh toán</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-xl font-bold text-green-600">{formatCurrency(commissionStats.total_paid)}</div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Commission Records Table */}
          <Card>
            <CardContent className="p-0">
              {commissionsLoading ? (
                <div className="p-4 md:p-6 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : !commissionsData?.records?.length ? (
                <div className="p-8 text-center text-muted-foreground">
                  Chưa có hoa hồng nào.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Chính sách</TableHead>
                      <TableHead className="text-right">Số tiền</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead>Ngày tạo</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {commissionsData.records.map((record) => {
                      const statusConfig = COMMISSION_STATUS_CONFIG[record.status] ?? { label: record.status, variant: "outline" as const }
                      return (
                        <TableRow key={record.id}>
                          <TableCell className="font-medium text-sm">
                            {record.policy?.name ?? `#${record.policy_id}`}
                          </TableCell>
                          <TableCell className="text-right font-medium">
                            {formatCurrency(record.amount)}
                          </TableCell>
                          <TableCell>
                            <Badge variant={statusConfig.variant}>
                              {statusConfig.label}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-muted-foreground text-sm">
                            {formatDate(record.triggered_at)}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Commissions pagination */}
          {commissionsData && commissionsData.total_count > PAGE_SIZE && (
            <div className="flex items-center justify-between">
              <p className="text-muted-foreground text-sm">
                Hiển thị {(commissionsPage - 1) * PAGE_SIZE + 1}-{Math.min(commissionsPage * PAGE_SIZE, commissionsData.total_count)} / {commissionsData.total_count}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setCommissionsPage((p) => Math.max(1, p - 1))} disabled={commissionsPage === 1}>
                  Trước
                </Button>
                <Button variant="outline" size="sm" onClick={() => setCommissionsPage((p) => Math.min(commissionsTotalPages, p + 1))} disabled={commissionsPage === commissionsTotalPages}>
                  Sau
                </Button>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Submit Lead Dialog */}
      <SubmitLeadDialog open={submitDialogOpen} onOpenChange={setSubmitDialogOpen} />
    </PageContainer>
  )
}
