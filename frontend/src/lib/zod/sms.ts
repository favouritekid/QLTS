// src/lib/zod/sms.ts
// Mirror Backend Pydantic: SmsLandingResponse + SmsPublicOptOut* (PR-5 §19.4).
// Public landing /lp/{code} — KHÔNG lộ PII recipient.
import { z } from "zod"

export const smsLandingResponseSchema = z.object({
  school_name: z.string(),
  headline: z.string().nullable().optional(),
  body: z.string().nullable().optional(),
  cta_label: z.string().nullable().optional(),
  cta_url: z.string().nullable().optional(),
  consent_notice: z.string(),
  already_opted_out: z.boolean(),
})
export type SmsLandingResponse = z.infer<typeof smsLandingResponseSchema>

export const smsPublicOptOutResponseSchema = z.object({
  success: z.boolean(),
  already_opted_out: z.boolean(),
})
export type SmsPublicOptOutResponse = z.infer<
  typeof smsPublicOptOutResponseSchema
>
