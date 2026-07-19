// src/lib/zod/enrollment-letter.ts
//
// Mirror của `EnrollmentLetterResponse` (Backend_FastAPI/app/schemas/
// enrollment_letter.py). Danh sách bản đã phát là dữ liệu của một VĂN BẢN
// CHÍNH THỨC, nên parse ở runtime thay vì chỉ khai interface: backend đổi/bỏ
// field thì TypeScript vẫn biên dịch sạch với interface cũ và UI lặng lẽ hiện
// `undefined` — đúng thứ frontend/CLAUDE.md cấm ("Require server to provide").

import { z } from "zod"

export const enrollmentLetterSummarySchema = z.object({
  id: z.number(),
  profile_id: z.number(),
  /** ISO date (YYYY-MM-DD) — cửa sổ làm thủ tục in trên giấy. */
  enrollment_start_date: z.string(),
  enrollment_end_date: z.string(),
  generated_by_id: z.number().nullable(),
  /** ISO datetime. */
  generated_at: z.string(),
  file_size: z.number(),
  /** Hết hạn lưu trữ; null = không đặt hạn. */
  expires_at: z.string().nullable(),
  /** null = BẢN HIỆN HÀNH; có giá trị = đã bị bản phát sau thay thế. */
  superseded_at: z.string().nullable(),
})

export const enrollmentLetterListSchema = z.array(enrollmentLetterSummarySchema)

export type EnrollmentLetterSummary = z.infer<
  typeof enrollmentLetterSummarySchema
>
