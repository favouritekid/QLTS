/**
 * Q9 #07 Phase E.2 — Manual KV override Zod schema.
 *
 * Mirrors BE Pydantic `OverridePriorityKvRequest` trong
 * `Backend_FastAPI/app/schemas/admission.py` — keep in sync.
 *
 * Cross-field invariants enforced by BE service-layer:
 * * Version guard FIRST → 409 ConflictError nếu mismatch
 * * Status whitelist (officer: submitted/reviewing/revision_requested;
 *   admin bypass với acknowledge_post_publish=true cho post-publish)
 * * Reason 20-500 char mandatory (persisted in snapshot + audit log)
 */
import { z } from "zod"

/** KV codes — matches `KV_BADGE` keys trong `kv-labels.ts`. */
export const KV_CODES = ["KV1", "KV2-NT", "KV2", "KV3"] as const
export type KvCode = (typeof KV_CODES)[number]

export const overridePriorityKvRequestSchema = z.object({
  /** Optimistic lock — must match profile.version. 409 on mismatch. */
  version: z.number().int().min(0),
  /** New KV code to assign manually. */
  kv_resolved: z.enum(KV_CODES),
  /** 20-500 char justification. Persisted in snapshot + audit log. */
  reason: z
    .string()
    .trim()
    .min(20, "Lý do ấn định phải có ít nhất 20 ký tự")
    .max(500, "Lý do ấn định không được vượt quá 500 ký tự"),
  /** Optional FK soft-reference to supporting evidence document. */
  evidence_file_id: z.number().int().positive().nullable().optional(),
  /**
   * Admin-only escape hatch for post-publish profile (enrolled/approved/
   * confirmed/...). Officer always refused for those states. UI gates
   * via secondary checkbox trong PriorityOverrideDialog.
   */
  acknowledge_post_publish: z.boolean().default(false),
})

export type OverridePriorityKvRequest = z.infer<
  typeof overridePriorityKvRequestSchema
>
