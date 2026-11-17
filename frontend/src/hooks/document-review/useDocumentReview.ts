/**
 * GĐ1b — hook nút lẻ (gửi `expected_row_version`, lý do, cam kết) + lịch sử giấy K2.
 *
 * Sau MỌI thao tác (thành công hoặc 409) làm mới: chi tiết hồ sơ, danh sách, bộ đếm trạng thái, lịch sử giấy — báo cáo
 * rà giao diện §b: các hook giấy cũ chỉ làm mới `detail`. Không lưu lý do ở đâu ngoài thân yêu cầu (không "lý do gần
 * đây", không storage). Không toast ở đây — thành phần quyết câu hiển thị.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import axios from "axios"

import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import {
  downloadEvidenceFile,
  getDocumentHistory,
  rejectDocumentGd1b,
  resetDocumentGd1b,
  verifyDocumentGd1b,
} from "@/lib/api/document-review"
import { downloadBlob } from "@/lib/utils/download-blob"
import type { RejectDocumentBody, ResetDocumentBody, VerifyDocumentBody } from "@/lib/zod/document-review"

export const documentReviewKeys = {
  all: ["document-review"] as const,
  histories: () => [...documentReviewKeys.all, "history"] as const,
  history: (profileId: number, documentRowId: number) =>
    [...documentReviewKeys.histories(), profileId, documentRowId] as const,
}

/** Làm mới mọi nơi có thể hiện trạng thái giấy của một hồ sơ. */
export function invalidateAfterDocumentChange(queryClient: QueryClient, profileIds: Iterable<number>): void {
  for (const id of new Set(profileIds)) {
    void queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(id) })
    void queryClient.invalidateQueries({ queryKey: [...documentReviewKeys.histories(), id] })
  }
  void queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
  void queryClient.invalidateQueries({ queryKey: [...admissionsKeys.all, "status-counts"] })
}

function isConflict(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 409
}

export function useDocumentHistory(profileId: number, documentRowId: number, enabled: boolean) {
  return useQuery({
    queryKey: documentReviewKeys.history(profileId, documentRowId),
    queryFn: () => getDocumentHistory(profileId, documentRowId),
    enabled,
    staleTime: 0,
    retry: false,
  })
}

/**
 * Tải MỘT tệp bằng chứng (§2.3). 410 `EVIDENCE_FILE_MISSING` ⇒ máy chủ đã đánh dấu `file_missing` ⇒ làm mới lịch sử.
 * Thành phần chỉ hiện câu (không gọi API trực tiếp — kiến trúc 2.6.2).
 */
export function useDownloadEvidence(profileId: number, documentRowId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (evidenceId: number) => downloadEvidenceFile(profileId, documentRowId, evidenceId),
    retry: false,
    gcTime: 0,
    onSuccess: (f) => downloadBlob(f.blob, f.filename),
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 410) {
        void queryClient.invalidateQueries({ queryKey: documentReviewKeys.history(profileId, documentRowId) })
      }
    },
  })
}

interface DocAction<B> {
  docCode: string
  body: B
}

export function useVerifyDocumentGd1b(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ docCode, body }: DocAction<VerifyDocumentBody>) => verifyDocumentGd1b(profileId, docCode, body),
    retry: false,
    gcTime: 0,
    onSuccess: () => invalidateAfterDocumentChange(queryClient, [profileId]),
    onError: (error) => {
      // 409 (VERSION_CHANGED / luật nghiệp vụ): trạng thái giấy đã khác lúc xem ⇒ làm mới
      if (isConflict(error)) invalidateAfterDocumentChange(queryClient, [profileId])
    },
  })
}

export function useRejectDocumentGd1b(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ docCode, body }: DocAction<RejectDocumentBody>) => rejectDocumentGd1b(profileId, docCode, body),
    retry: false,
    gcTime: 0,
    onSuccess: () => invalidateAfterDocumentChange(queryClient, [profileId]),
    onError: (error) => {
      if (isConflict(error)) invalidateAfterDocumentChange(queryClient, [profileId])
    },
  })
}

export function useResetDocumentGd1b(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ docCode, body }: DocAction<ResetDocumentBody>) => resetDocumentGd1b(profileId, docCode, body),
    retry: false,
    gcTime: 0,
    onSuccess: () => invalidateAfterDocumentChange(queryClient, [profileId]),
    onError: (error) => {
      if (isConflict(error)) invalidateAfterDocumentChange(queryClient, [profileId])
    },
  })
}
