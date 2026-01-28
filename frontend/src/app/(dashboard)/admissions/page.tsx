// src/app/(dashboard)/admissions/page.tsx
/**
 * Admissions List Page
 * 
 * Displays all admission profiles with filtering by status.
 */
"use client"

import { useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ClipboardCheck, User, Calendar, ArrowRight } from "lucide-react"
import { useListAdmissions } from "@/hooks/admissions"
import { PageContainer } from "@/components/layouts/PageContainer"
import { EmptyState, ErrorEmptyState } from "@/components/common/EmptyState"

const STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  enrolled: "Đã nhập học",
}

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  approved: "bg-success-100 text-success-700",
  rejected: "bg-error-100 text-error-700",
  enrolled: "bg-info-100 text-info-700",
}

export default function AdmissionsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all")
  
  const { data: profiles, isLoading, isError } = useListAdmissions(
    statusFilter !== "all" ? { status: statusFilter } : undefined
  )

  return (
    <PageContainer maxWidth="xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ClipboardCheck className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold font-display">Hồ sơ tuyển sinh</h1>
            <p className="text-muted-foreground">Quản lý và theo dõi hồ sơ tuyển sinh</p>
          </div>
        </div>
        
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Lọc theo trạng thái" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả</SelectItem>
            <SelectItem value="draft">Nháp</SelectItem>
            <SelectItem value="approved">Đã duyệt</SelectItem>
            <SelectItem value="rejected">Từ chối</SelectItem>
            <SelectItem value="enrolled">Đã nhập học</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-4 w-full mb-2" />
                <Skeleton className="h-4 w-3/4" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {isError && (
        <Card>
          <CardContent className="p-0">
            <ErrorEmptyState
              message="Không thể tải danh sách hồ sơ. Vui lòng thử lại."
            />
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && profiles?.length === 0 && (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<ClipboardCheck className="h-12 w-12" />}
              title="Chưa có hồ sơ nào"
              description="Để tạo hồ sơ mới, vào trang chi tiết Lead và nhấn 'Tạo hồ sơ tuyển sinh'"
            />
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && profiles && profiles.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {profiles.map((profile) => (
            <Card key={profile.id} className="hover:shadow-md transition-shadow">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg flex items-center gap-2">
                    <User className="h-4 w-4 text-muted-foreground" />
                    {profile.lead?.full_name || `Lead #${profile.lead_id}`}
                  </CardTitle>
                  <Badge className={STATUS_COLORS[profile.status] || "bg-muted"}>
                    {STATUS_LABELS[profile.status] || profile.status}
                  </Badge>
                </div>
                <CardDescription>Hồ sơ #{profile.id}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 text-sm text-muted-foreground">
                  {profile.citizen_id_masked && (
                    <div>CCCD: {profile.citizen_id_masked}</div>
                  )}
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Ngày tạo: {new Date(profile.created_at).toLocaleDateString("vi-VN")}
                  </div>
                </div>
                
                <div className="mt-4">
                  <Link href={`/admissions/${profile.id}`}>
                    <Button variant="outline" size="sm" className="w-full">
                      Xem chi tiết
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageContainer>
  )
}
