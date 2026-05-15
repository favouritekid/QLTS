/**
 * Phase 3 PR-3D-B FE Wave B — Zod schemas cho AdmissionProfileChoice.
 *
 * Mirror Backend Pydantic models (`app/schemas/admission_profile_choice.py`):
 * - ChoiceDecisionLiteral (5 values)
 * - ChoiceScoreInput (subject_id + score)
 * - AdmissionProfileChoiceCreate (POST payload + scores list)
 * - ChoiceUpdateDisplayOrderRequest (PATCH reorder)
 * - ChoiceScoresReplaceRequest (PATCH /scores)
 * - AdmissionProfileChoiceResponse (GET shape with computed display fields)
 *
 * Per FRONTEND_ARCHITECTURE_V3.md: BE is source of truth — FE Zod is parity
 * layer + runtime validation. NO business logic on FE.
 */
import { z } from "zod"

// Match BE Literal["pending", "admitted", "waitlisted", "rejected", "skip"]
export const choiceDecisionEnum = z.enum([
  "pending",
  "admitted",
  "waitlisted",
  "rejected",
  "skip",
])
export type ChoiceDecision = z.infer<typeof choiceDecisionEnum>

export const choiceScoreInputSchema = z.object({
  subject_id: z.number().int().positive(),
  // Decimal arrives as string from BE; FE input is number → coerce via transform
  score: z
    .union([z.string(), z.number()])
    .transform((v) => Number(v))
    .pipe(z.number().nonnegative()),
})
export type ChoiceScoreInput = z.infer<typeof choiceScoreInputSchema>

export const choiceScoreSummarySchema = z.object({
  subject_id: z.number(),
  subject_code: z.string(),
  subject_name: z.string(),
  score: z.union([z.string(), z.number()]).transform((v) => Number(v)),
  max_score_snapshot: z.union([z.string(), z.number()]).transform((v) => Number(v)),
  min_possible_score_snapshot: z
    .union([z.string(), z.number()])
    .nullable()
    .transform((v) => (v === null ? null : Number(v))),
  weight_snapshot: z.union([z.string(), z.number()]).transform((v) => Number(v)),
})
export type ChoiceScoreSummary = z.infer<typeof choiceScoreSummarySchema>

export const admissionProfileChoiceResponseSchema = z.object({
  id: z.number(),
  admission_profile_id: z.number(),
  admission_path_id: z.number(),
  path_subject_group_config_id: z.number(),
  display_order: z.number().int().min(1).max(10),
  decision: choiceDecisionEnum,
  waitlist_rank: z.number().int().nullable().optional(),
  eligibility_check_result: z.record(z.string(), z.unknown()).nullable().optional(),
  bonus_rule_snapshot: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  display_path_name: z.string(),
  // Phase 3 follow-up Q1: program name + degree level separate fields cho
  // FE render badge "Y sỹ đa khoa · Cao đẳng" cạnh display_subject_group_name
  display_program_name: z.string().default(""),
  display_degree_level: z.string().default(""),
  display_subject_group_name: z.string(),
  scores: z.array(choiceScoreSummarySchema),
})
export type AdmissionProfileChoiceResponse = z.infer<
  typeof admissionProfileChoiceResponseSchema
>

export const admissionProfileChoiceCreateSchema = z.object({
  admission_path_id: z.number().int().positive(),
  path_subject_group_config_id: z.number().int().positive(),
  display_order: z.number().int().min(1).max(10),
  scores: z.array(choiceScoreInputSchema).default([]),
})
export type AdmissionProfileChoiceCreate = z.infer<
  typeof admissionProfileChoiceCreateSchema
>

export const choiceUpdateDisplayOrderRequestSchema = z.object({
  display_order: z.number().int().min(1).max(10),
})
export type ChoiceUpdateDisplayOrderRequest = z.infer<
  typeof choiceUpdateDisplayOrderRequestSchema
>

export const choiceScoresReplaceRequestSchema = z.object({
  scores: z.array(choiceScoreInputSchema),
})
export type ChoiceScoresReplaceRequest = z.infer<
  typeof choiceScoresReplaceRequestSchema
>

export const choiceDeleteResponseSchema = z.object({
  choice_id: z.number(),
  profile_id: z.number(),
})
export type ChoiceDeleteResponse = z.infer<typeof choiceDeleteResponseSchema>
