"use client"

/**
 * Bản 6 C2.2 / đặc tả §5.9 — nút "Duyệt giấy theo bộ lọc hiện tại" ở `/admissions`.
 *
 *  - Hiện CHỈ khi máy chủ trả cờ C1 `eligible = true` (`GET …/bulk-verify/eligibility`); đang tải / lỗi ⇒ không hiện.
 *    Không suy theo vai.
 *  - Gửi xem trước với `filter` = bộ lọc ĐANG ÁP của danh sách (`toBulkVerifyFilter`) — máy chủ chọn hồ sơ trên MỌI trang;
 *    KHÔNG nhận / gửi `profile_ids` của trang đang xem (thành phần này không có id dòng nào).
 *  - Quá 100 hồ sơ / N giấy ⇒ câu 422 của máy chủ kèm số đếm (luồng `BulkVerifyFlow`), không tự cắt.
 *  - Đi tiếp đúng luồng xem trước / ô xác nhận / chạy / tra lô đã có.
 */
import { useState } from "react"
import { ListChecks } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useBulkVerifyEligibility } from "@/hooks/document-review/useBulkVerify"
import { toBulkVerifyFilter } from "@/lib/document-review/bulk-filter"
import type { AdmissionListParams } from "@/lib/zod/admissions"

import { BulkVerifyDialog } from "./BulkVerifyDialog"

interface Props {
  /** bộ lọc đang áp của danh sách (`apiFilters` của `useAdmissionsFilter`) */
  filter: AdmissionListParams
}

export function BulkVerifyByFilterButton({ filter }: Props) {
  const eligibility = useBulkVerifyEligibility()
  const [open, setOpen] = useState(false)

  if (!(eligibility.isSuccess && eligibility.data.eligible === true)) return null
  const bulkFilter = toBulkVerifyFilter(filter)

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={bulkFilter === null}
        title={bulkFilter === null ? "Bộ lọc hiện tại không dùng được cho duyệt hàng loạt" : undefined}
        data-testid="nut-duyet-theo-bo-loc"
      >
        <ListChecks className="h-4 w-4" aria-hidden="true" />
        Duyệt giấy theo bộ lọc hiện tại
      </Button>
      {open && bulkFilter && (
        <BulkVerifyDialog
          open
          onOpenChange={(v) => {
            if (!v) setOpen(false)
          }}
          endpoint={{ mode: "batch" }}
          selection={{ kind: "filter", filter: bulkFilter }}
          title="Duyệt giấy theo bộ lọc hiện tại"
          scopeLabel="các hồ sơ chờ xét khớp bộ lọc hiện tại của danh sách (mọi trang, không chỉ trang đang xem)"
        />
      )}
    </>
  )
}
