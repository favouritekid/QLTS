/**
 * Hook cho màn đồng bộ ký túc xá.
 *
 * 🔴 Toàn bộ quyết định "được bấm gì" nằm ở đây, và nó chỉ đọc những trường
 * backend đã tính sẵn: `can_apply`, `expires_at`, `outcome`, `ledger_saved`,
 * `next_action`. Không giải mã phiếu, không suy trạng thái từ câu chữ, không
 * đoán lại từ `source_count`.
 */
"use client"

import { useCallback, useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"

import {
  applyDormSync,
  DormSyncBlockedError,
  getDormSyncContext,
  previewDormSync,
} from "@/lib/api/dorm-sync"
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
  })

  const mutGhi = useMutation({
    mutationFn: applyDormSync,
    onSuccess: (kq) => {
      setKetQua(kq)
      // 🔴 Phiếu đã dùng xong. Giữ lại là mời bấm lần hai với cùng một vé —
      // backend sẽ chặn, nhưng giao diện không nên bày ra thao tác đó.
      setPreview(null)
    },
    onError: (loi) => {
      if (loi instanceof DormSyncBlockedError) {
        setChan(dungTrangThaiChan(loi))
        setPreview(null)
      }
      // Lỗi không nhận diện được: để nguyên cho `handleApiError` ở tầng
      // component. Không đoán trạng thái từ nó.
    },
  })

  const daHetHan = useMemo(() => {
    if (!preview?.expires_at) return false
    // Dùng THẲNG `expires_at` — không giải mã `exp` trong phiếu.
    return now() >= preview.expires_at * 1000
  }, [preview, now])

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
      // `choPhepGhi` đã gộp mọi lý do khoá; gọi khi nó `false` là bỏ qua chính
      // hàng rào vừa dựng.
      if (!preview?.preview_token) return
      mutGhi.mutate(preview.preview_token)
    },
    doiNamHoc: () => {
      xoaPhieu()
      setChan(null)
    },
  }
}

export { DormSyncBlockedError }
