/**
 * GĐ1b — API client nút lẻ (duyệt / từ chối / Đặt lại theo phiên bản dòng) + lịch sử giấy K2 + tải tệp bằng chứng.
 *
 * Hợp đồng API bản 4 §1 (đã có trong lõi) và §2.3 (tệp bằng chứng, agent bằng chứng). Mọi thân yêu cầu / phản hồi qua
 * Zod (`@/lib/zod/document-review`). Đường dẫn giữ khoá GĐ1 (`doc_code`) cho nút lẻ; lịch sử / bằng chứng theo
 * `document_row_id`.
 *
 * ⚠️ Lý do người dùng gõ CHỈ đi trong THÂN yêu cầu — không URL, không storage, không `console.*`.
 */
import axios from "axios"

import { api } from "@/lib/api/client"
import { filenameFromContentDisposition } from "@/lib/api/council-documents"
import {
  documentHistorySchema,
  profileAckSchema,
  rejectDocumentBodySchema,
  rejectDocumentResponseSchema,
  resetDocumentBodySchema,
  verifyDocumentBodySchema,
  type DocumentHistory,
  type ProfileAck,
  type RejectDocumentBody,
  type RejectDocumentResponse,
  type ResetDocumentBody,
  type VerifyDocumentBody,
} from "@/lib/zod/document-review"

const A = "/api/admissions"
const seg = (s: string) => encodeURIComponent(s)

/** `PATCH …/{profile_id}/documents/{doc_code}/verify-format` — phản hồi = cả hồ sơ. */
export async function verifyDocumentGd1b(
  profileId: number,
  docCode: string,
  body: VerifyDocumentBody,
): Promise<ProfileAck> {
  const data = verifyDocumentBodySchema.parse(body)
  const res = await api.patch(`${A}/${profileId}/documents/${seg(docCode)}/verify-format`, data)
  return profileAckSchema.parse(res.data)
}

/** `POST …/reject` — phản hồi = dict giấy (có `document_row_id`, `row_version` mới). */
export async function rejectDocumentGd1b(
  profileId: number,
  docCode: string,
  body: RejectDocumentBody,
): Promise<RejectDocumentResponse> {
  const data = rejectDocumentBodySchema.parse(body)
  const res = await api.post(`${A}/${profileId}/documents/${seg(docCode)}/reject`, data)
  return rejectDocumentResponseSchema.parse(res.data)
}

/** `POST …/reset` — lý do BẮT BUỘC; phản hồi = cả hồ sơ. */
export async function resetDocumentGd1b(
  profileId: number,
  docCode: string,
  body: ResetDocumentBody,
): Promise<ProfileAck> {
  const data = resetDocumentBodySchema.parse(body)
  const res = await api.post(`${A}/${profileId}/documents/${seg(docCode)}/reset`, data)
  return profileAckSchema.parse(res.data)
}

/** `GET …/{profile_id}/documents/{document_row_id}/history` — Quản lý trong phạm vi / Admin; còn lại 404. */
export async function getDocumentHistory(
  profileId: number,
  documentRowId: number,
): Promise<DocumentHistory> {
  const res = await api.get(`${A}/${profileId}/documents/${documentRowId}/history`)
  return documentHistorySchema.parse(res.data)
}

export interface EvidenceFileBlob {
  blob: Blob
  filename: string
}

/**
 * `GET …/{profile_id}/documents/{document_row_id}/evidence/{evidence_id}/download` (§2.3). Tệp không còn ⇒ 410
 * `EVIDENCE_FILE_MISSING` (máy chủ đánh dấu `file_missing`). Thân lỗi (Blob) đọc lại thành JSON để `readApiError`
 * thấy `error_code`.
 */
export async function downloadEvidenceFile(
  profileId: number,
  documentRowId: number,
  evidenceId: number,
): Promise<EvidenceFileBlob> {
  const url = `${A}/${profileId}/documents/${documentRowId}/evidence/${evidenceId}/download`
  try {
    const res = await api.get<Blob>(url, { responseType: "blob" })
    return {
      blob: res.data,
      filename: filenameFromContentDisposition(
        res.headers["content-disposition"] as string | undefined,
        `bang-chung-${evidenceId}`,
      ),
    }
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.data instanceof Blob) {
      try {
        e.response.data = JSON.parse(await e.response.data.text())
      } catch {
        e.response.data = undefined
      }
    }
    throw e
  }
}
