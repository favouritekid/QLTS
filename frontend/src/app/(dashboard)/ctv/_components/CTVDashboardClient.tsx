"use client"

import { useState } from "react"
import { Database, CheckCircle, Award, Clock, Plus } from "lucide-react"
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
import { getLeadValidityLabel } from "@/constants/lead.constants"
import { SubmitLeadDialog } from "@/components/ctv/SubmitLeadDialog"
import type { LeadClaimStatus } from "@/types/collaborator.types"

// =============================================================================
// HELPERS
// =============================================================================

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

function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "-"
  try {
    return new Date(isoString).toLocaleDateString("vi-VN")
  } catch {
    return "-"
  }
}

// =============================================================================
// STAT CARD
// =============================================================================

interface StatCardProps {
  title: string
  value: number | undefined
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

  const { data: profile, isLoading: profileLoading } = useCTVProfile()
  const { data: stats, isLoading: statsLoading } = useCTVStats()
  const { data: leadsData, isLoading: leadsLoading } = useCTVLeads()
  const { data: claimsData, isLoading: claimsLoading } = useCTVClaims()

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
                Xin ch&agrave;o, <span className="font-medium">{profile?.full_name}</span>
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
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
      </div>

      {/* Submit Lead Button */}
      <div>
        <Button onClick={() => setSubmitDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" aria-hidden="true" />
          Gửi lead mới
        </Button>
      </div>

      {/* Tabs: Leads & Claims */}
      <Tabs defaultValue="leads">
        <TabsList>
          <TabsTrigger value="leads">Leads của tôi</TabsTrigger>
          <TabsTrigger value="claims">Yêu cầu claim</TabsTrigger>
        </TabsList>

        {/* Leads Tab */}
        <TabsContent value="leads">
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
                  Chưa có lead nào. Hãy gửi lead mới!
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
        </TabsContent>

        {/* Claims Tab */}
        <TabsContent value="claims">
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
        </TabsContent>
      </Tabs>

      {/* Submit Lead Dialog */}
      <SubmitLeadDialog open={submitDialogOpen} onOpenChange={setSubmitDialogOpen} />
    </PageContainer>
  )
}
