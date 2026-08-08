/**
 * Hook cho màn đồng bộ ký túc xá.
 *
 * 🔴 Toàn bộ quyết định "được bấm gì" nằm ở đây, và nó chỉ đọc những trường
 * backend đã tính sẵn: `can_apply`, `expires_at`, `outcome`, `ledger_saved`,
 * `next_action`. Không giải mã phiếu, không suy trạng thái từ câu chữ, không
 * đoán lại từ `source_count`.
 */
"use client"

import { useCallback, useEffect, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import type { QueryClient } from "@tanstack/react-query"
import { isAxiosError } from "axios"
import type { AxiosError } from "axios"
import { toast } from "sonner"

import {
  applyDormSync,
  DormSyncBlockedError,
  getDormSyncContext,
  previewDormSync,
} from "@/lib/api/dorm-sync"
import { handleApiError } from "@/lib/error-handler"
import type { ApiErrorResponse } from "@/lib/error-handler"
import type {
  DormSyncApplyResult,
  DormSyncNextAction,
  DormSyncPreview,
} from "@/lib/zod/dorm-sync"

export const DORM_SYNC_KEYS = {
  context: ["admin", "dorm-sync", "context"] as const,
}

/**
 * Trạng thái CHẶN của màn hình, suy ra từ `next_action` — và chỉ từ nó.
 *
 * ⚠️ KHÔNG suy từ `operation_status`, không từ mã HTTP 409, không từ `detail`.
 * `handleApiError` cố ý che `detail` của mã `CONFLICT`, nên câu chữ có thể
 * không bao giờ tới được đây; và ba trạng thái sổ cái đòi ba hành động trái
 * ngược nhau nên đoán sai là đắt.
 */
export interface TrangThaiChan {
  nextAction: DormSyncNextAction
  message: string
  /** `manual_reconcile` khoá MỌI mutation, kể cả nút Xem trước. */
  khoaMoiThaoTac: boolean
  /** `preview_again` là ca DUY NHẤT cho phép xem trước lại. */
  choXemTruocLai: boolean
}

function dungTrangThaiChan(loi: DormSyncBlockedError): TrangThaiChan {
  return {
    nextAction: loi.nextAction,
    message: loi.message,
    // `wait`: lượt đang chạy — khoá thao tác, KHÔNG tự retry và không mời
    // xem trước lại. Bấm lại chỉ vướng khoá năm học của hệ KTX.
    //
    // `manual_reconcile`: KHÔNG rõ hệ KTX tới đâu — khoá tất cả. Đây là ca đắt
    // nhất: mời "thử lại" ở đây là chạy lượt thứ hai chồng lên một lượt có thể
    // đang sống.
    khoaMoiThaoTac:
      loi.nextAction === "wait" || loi.nextAction === "manual_reconcile",
    choXemTruocLai: loi.nextAction === "preview_again",
  }
}

/**
 * Đưa một lỗi KHÔNG nhận diện được ra màn hình.
 *
 * 🔴 `handleApiError` đòi `AxiosError<ApiErrorResponse>`; ép kiểu bằng `as`
 * làm `tsc` im nhưng không làm lỗi đúng hình dạng — và lỗi PARSE của Zod
 * không phải `AxiosError` chút nào. Bản trước ép kiểu, `tsc` vẫn đỏ, và cả hai
 * đường đều chưa được xử.
 *
 * Hai nhánh, hai cách xử:
 *
 * * lỗi HTTP → `handleApiError` (nó biết 401/403/409… và biết invalidate);
 * * lỗi khác (Zod parse hỏng, TypeError) → nói thẳng rằng phản hồi sai hình
 *   dạng. Im lặng ở đây là để người vận hành nhìn nút quay về trạng thái
 *   thường như chưa có gì xảy ra.
 */
function baoLoiLa(loi: unknown, queryClient?: QueryClient): void {
  if (isAxiosError(loi)) {
    handleApiError(loi as AxiosError<ApiErrorResponse>, { queryClient })
    return
  }
  toast.error("Máy chủ trả về dữ liệu không đọc được", {
    description: "Thử lại sau; nếu lặp lại, báo quản trị.",
  })
}


export function useDormSyncContext() {
  return useQuery({
    queryKey: DORM_SYNC_KEYS.context,
    queryFn: getDormSyncContext,
  })
}

export interface DormSyncState {
  preview: DormSyncPreview | null
  ketQua: DormSyncApplyResult | null
  chan: TrangThaiChan | null
  dangXemTruoc: boolean
  dangGhi: boolean
  /** Bấm Ghi được hay không — đã gộp mọi lý do khoá. */
  choPhepGhi: boolean
  /** Bấm Xem trước được hay không. */
  choPhepXemTruoc: boolean
  xemTruoc: (namHoc: number) => void
  ghi: () => void
  /** Đổi năm học ⇒ XOÁ phiếu cũ. */
  doiNamHoc: () => void
}

/**
 * @param now - đồng hồ TRUYỀN VÀO, không gọi `Date.now()` bên trong.
 *   Một hook tự đọc đồng hồ là một hook không kiểm được ca hết hạn.
 */
export function useDormSync(now: () => number = () => Date.now()): DormSyncState {
  const [preview, setPreview] = useState<DormSyncPreview | null>(null)
  const [ketQua, setKetQua] = useState<DormSyncApplyResult | null>(null)
  const [chan, setChan] = useState<TrangThaiChan | null>(null)

  const xoaPhieu = useCallback(() => {
    setPreview(null)
    setKetQua(null)
  }, [])

  const mutXemTruoc = useMutation({
    mutationFn: previewDormSync,
    onMutate: () => {
      // Phiếu cũ hết giá trị ngay khi bắt đầu xem trước lượt mới.
      xoaPhieu()
      setChan(null)
    },
    onSuccess: setPreview,
    onError: (loi) => {
      baoLoiLa(loi)
    },
  })

  const queryClient = useQueryClient()

  const mutGhi = useMutation({
    mutationFn: applyDormSync,
    onSuccess: (kq) => {
      setKetQua(kq)
      // 🔴 Phiếu đã dùng xong. Giữ lại là mời bấm lần hai với cùng một vé —
      // backend sẽ chặn, nhưng giao diện không nên bày ra thao tác đó.
      setPreview(null)
      // 🔴 `return` để mutation còn `pending` cho tới khi làm mới xong.
      //
      // Không `return` thì nút mở lại trong khi bối cảnh còn là bản cũ, và
      // người bấm nhìn một màn hình đã lỗi thời ngay sau thao tác nặng nhất
      // của hệ.
      return queryClient.invalidateQueries({ queryKey: DORM_SYNC_KEYS.context })
    },
    onError: (loi) => {
      if (loi instanceof DormSyncBlockedError) {
        setChan(dungTrangThaiChan(loi))
        setPreview(null)
        return
      }
      // 🔴 Lỗi KHÔNG nhận diện được vẫn phải hiện ra.
      //
      // Bản trước chỉ ghi chú "để component xử" rồi không ai xử: một lỗi mạng
      // hay một phản hồi sai hình dạng im lặng tuyệt đối, và người vận hành
      // nhìn nút quay về trạng thái thường như chưa có gì xảy ra.
      baoLoiLa(loi, queryClient)
    },
  })

  // 🔴 Hết hạn phải TỰ tới, không đợi lần render sau.
  //
  // `useMemo` chỉ tính lại khi có thứ gì đó kích render. Một màn hình mở sẵn,
  // người bấm đi họp mười phút rồi quay lại bấm Ghi — không có render nào xảy
  // ra giữa chừng, nên nút vẫn mở và request vẫn được gửi với một phiếu đã
  // chết. Backend sẽ chặn, nhưng giao diện không được bày ra thao tác đó.
  //
  // Đặt hẹn giờ ĐÚNG tới mốc `expires_at` và tự hạ cờ.
  const [daHetHan, setDaHetHan] = useState(false)

  const mocHetHan = preview?.expires_at ?? null

  useEffect(() => {
    if (mocHetHan === null) {
      setDaHetHan(false)
      return
    }
    // Dùng THẲNG `expires_at` — không giải mã `exp` trong phiếu.
    const conLai = mocHetHan * 1000 - now()
    if (conLai <= 0) {
      setDaHetHan(true)
      return
    }
    setDaHetHan(false)
    const hen = setTimeout(() => setDaHetHan(true), conLai)
    return () => clearTimeout(hen)
    // `now` cố ý KHÔNG nằm trong deps: nó là đồng hồ, không phải dữ liệu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mocHetHan])

  const choPhepGhi = Boolean(
    preview?.can_apply &&
      preview.preview_token &&
      !daHetHan &&
      !chan?.khoaMoiThaoTac &&
      !mutGhi.isPending,
  )

  const choPhepXemTruoc = !mutXemTruoc.isPending && !chan?.khoaMoiThaoTac

  return {
    preview,
    ketQua,
    chan,
    dangXemTruoc: mutXemTruoc.isPending,
    dangGhi: mutGhi.isPending,
    choPhepGhi,
    choPhepXemTruoc,
    xemTruoc: (namHoc: number) => mutXemTruoc.mutate(namHoc),
    ghi: () => {
      // 🔴 Fail-closed theo TOÀN BỘ `choPhepGhi`, không chỉ sự tồn tại của
      // phiếu.
      //
      // Đường hỏng đã đo được: mở hộp xác nhận lúc phiếu còn hạn, hẹn giờ chạy
      // qua mốc, nút NỀN bị khoá — nhưng hộp thoại vẫn mở và nút xác nhận vẫn
      // bấm được. Kiểm mỗi `preview_token` thì request vẫn được gửi với một
      // phiếu đã chết.
      if (!choPhepGhi || !preview?.preview_token) return
      mutGhi.mutate(preview.preview_token)
    },
    doiNamHoc: () => {
      xoaPhieu()
      setChan(null)
    },
  }
}

export { DormSyncBlockedError }
