// src/hooks/admissions/useEnrollmentLetter.ts
//
// React Query hooks for the enrollment-letter feature. On success we trigger a
// browser download; on error we unwrap the blob-wrapped JSON error body with
// `blobErrorMessage` (the standard axios error handler cannot read a Blob).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { toast } from "sonner"

import {
  downloadEnrollmentLetter,
  issueEnrollmentLetter,
  listEnrollmentLetters,
  type EnrollmentLetterBlob,
  type IssueEnrollmentLetterInput,
} from "@/lib/api/enrollment-letter"
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob"

export const enrollmentLetterKeys = {
  list: (profileId: number) => ["enrollment-letters", profileId] as const,
}

function saveAndToast(result: EnrollmentLetterBlob, successMsg: string) {
  downloadBlob(result.blob, result.filename)
  toast.success(successMsg)
}

/** Issue a NEW letter (POST) → download the returned PDF. */
export function useIssueEnrollmentLetter(profileId: number) {
  const queryClient = useQueryClient()
  return useMutation<EnrollmentLetterBlob, AxiosError, IssueEnrollmentLetterInput>({
    mutationFn: (input) => issueEnrollmentLetter(profileId, input),
    onSuccess: (result) => {
      saveAndToast(result, "Đã xuất giấy báo nhập học")
      queryClient.invalidateQueries({
        queryKey: enrollmentLetterKeys.list(profileId),
      })
    },
    onError: async (error) => {
      toast.error(await blobErrorMessage(error, "Không xuất được giấy báo nhập học"))
    },
  })
}

/** List previously issued letters (for the re-download UI). */
export function useEnrollmentLetters(profileId: number, enabled = true) {
  return useQuery({
    queryKey: enrollmentLetterKeys.list(profileId),
    queryFn: () => listEnrollmentLetters(profileId),
    enabled,
  })
}

/** Re-download a previously issued letter by id. */
export function useDownloadEnrollmentLetter(profileId: number) {
  return useMutation<EnrollmentLetterBlob, AxiosError, number>({
    mutationFn: (letterId) => downloadEnrollmentLetter(profileId, letterId),
    onSuccess: (result) => saveAndToast(result, "Đã tải giấy báo nhập học"),
    onError: async (error) => {
      toast.error(await blobErrorMessage(error, "Không tải được giấy báo nhập học"))
    },
  })
}
