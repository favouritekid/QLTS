// src/lib/api/enrollment-letter.ts
//
// API client for the official "Giấy báo nhập học" PDF.
// - issue: POST returns the PDF as a blob (+ X-Enrollment-Letter-Id header).
// - list / download: re-download a previously issued letter.
//
// Errors come back as a JSON body wrapped in a Blob (responseType: 'blob'),
// so callers must unwrap them with `blobErrorMessage` (see the hooks).

import { api } from "./client"
import { filenameFromDisposition } from "@/lib/utils/download-blob"

export interface IssueEnrollmentLetterInput {
  /** ISO date (YYYY-MM-DD). */
  enrollmentStartDate: string
  /** ISO date (YYYY-MM-DD). Backend re-validates end >= start. */
  enrollmentEndDate: string
}

export interface EnrollmentLetterBlob {
  blob: Blob
  filename: string
}

export interface EnrollmentLetterSummary {
  id: number
  profile_id: number
  enrollment_start_date: string
  enrollment_end_date: string
  generated_by_id: number | null
  generated_at: string
  file_size: number
  expires_at: string | null
}

function toBlob(res: { data: Blob; headers: Record<string, unknown> }, profileId: number): EnrollmentLetterBlob {
  const disposition = res.headers["content-disposition"] as string | undefined
  return {
    blob: res.data,
    filename: filenameFromDisposition(disposition, `giay-bao-nhap-hoc-${profileId}.pdf`),
  }
}

/** Issue a NEW official letter and return the PDF blob. */
export async function issueEnrollmentLetter(
  profileId: number,
  input: IssueEnrollmentLetterInput,
): Promise<EnrollmentLetterBlob> {
  const res = await api.post<Blob>(
    `/api/admissions/${profileId}/enrollment-letter`,
    {
      enrollment_start_date: input.enrollmentStartDate,
      enrollment_end_date: input.enrollmentEndDate,
    },
    { responseType: "blob" },
  )
  return toBlob(res, profileId)
}

/** List letters already issued for a profile (newest first). */
export async function listEnrollmentLetters(
  profileId: number,
): Promise<EnrollmentLetterSummary[]> {
  const res = await api.get<EnrollmentLetterSummary[]>(
    `/api/admissions/${profileId}/enrollment-letters`,
  )
  return res.data
}

/** Re-download a previously issued letter by id. */
export async function downloadEnrollmentLetter(
  profileId: number,
  letterId: number,
): Promise<EnrollmentLetterBlob> {
  const res = await api.get<Blob>(
    `/api/admissions/${profileId}/enrollment-letter/${letterId}/download`,
    { responseType: "blob" },
  )
  return toBlob(res, profileId)
}
