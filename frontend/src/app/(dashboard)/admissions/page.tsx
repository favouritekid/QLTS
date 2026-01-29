// src/app/(dashboard)/admissions/page.tsx
/**
 * Admissions List Page
 *
 * Displays all admission profiles with filtering by status and pagination.
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
import { Pagination } from "@/components/common/table/Pagination"

const STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  submitted: "Đã nộp",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  enrolled: "Đã nhập học",
}

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  submitted: "bg-warning-100 text-warning-700",
  approved: "bg-success-100 text-success-700",
  rejected: "bg-error-100 text-error-700",
  enrolled: "bg-info-100 text-info-700",
}

const DEFAULT_PAGE_SIZE = 20

export default function AdmissionsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  const { data, isLoading, isError, isFetching } = useListAdmissions({
    status: statusFilter !== "all" ? statusFilter : undefined,
    page,
    page_size: pageSize,
  })

  // Extract data from paginated response
  const profiles = data?.profiles ?? []
  const totalCount = data?.total_count ?? 0

  // Reset to page 1 when filter changes
  const handleStatusChange = (value: string) => {
    setStatusFilter(value)
    setPage(1)
  }

  // Handle page size change
  const handlePageSizeChange = (size: number) => {
    setPageSize(size)
    setPage(1)
  }

  return (
    <PageContainer maxWidth="xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <ClipboardCheck className="h-7 w-7 md:h-8 md:w-8 text-primary" />
          <div>
            <h1 className="text-xl md:text-2xl font-bold font-display">Hồ sơ tuyển sinh</h1>
            <p className="text-sm text-muted-foreground">
              Quản lý và theo dõi hồ sơ tuyển sinh
              {totalCount > 0 && ` (${totalCount} hồ sơ)`}
            </p>
          </div>
        </div>

        <Select value={statusFilter} onValueChange={handleStatusChange}>
          <SelectTrigger className="w-full sm:w-[180px]">
            <SelectValue placeholder="Lọc theo trạng thái" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả</SelectItem>
            <SelectItem value="draft">Nháp</SelectItem>
            <SelectItem value="submitted">Đã nộp</SelectItem>
            <SelectItem value="approved">Đã duyệt</SelectItem>
            <SelectItem value="rejected">Từ chối</SelectItem>
            <SelectItem value="enrolled">Đã nhập học</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
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

      {!isLoading && !isError && profiles.length === 0 && (
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

      {!isLoading && !isError && profiles.length > 0 && (
        <>
          <div className={`grid gap-4 md:grid-cols-2 lg:grid-cols-3 ${isFetching ? "opacity-60" : ""}`}>
            {profiles.map((profile) => (
              <Card key={profile.id} className="hover:shadow-md transition-shadow">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-lg flex items-center gap-2 min-w-0">
                      <User className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <span className="truncate">
                        {profile.lead?.full_name || `Lead #${profile.lead_id}`}
                      </span>
                    </CardTitle>
                    <Badge className={`flex-shrink-0 ${STATUS_COLORS[profile.status] || "bg-muted"}`}>
                      {STATUS_LABELS[profile.status] || profile.status}
                    </Badge>
                  </div>
                  <CardDescription>Hồ sơ #{profile.id}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    {profile.citizen_id_masked && (
                      <div className="truncate">CCCD: {profile.citizen_id_masked}</div>
                    )}
                    <div className="flex items-center gap-1">
                      <Calendar className="h-3 w-3 flex-shrink-0" />
                      <span>Ngày tạo: {new Date(profile.created_at).toLocaleDateString("vi-VN")}</span>
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

          {/* Pagination */}
          {totalCount > pageSize && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={totalCount}
              onPageChange={setPage}
              onPageSizeChange={handlePageSizeChange}
              isLoading={isFetching}
              showPageSizeSelector
              showTotal
              className="border-t mt-4"
            />
          )}
        </>
      )}
    </PageContainer>
  )
}
