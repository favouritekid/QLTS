/**
 * PR-CO-2-FE / PR-3E — Multi-action magic-link Zod schemas.
 *
 * Mirrors BE Pydantic models in `Backend_FastAPI/app/schemas/magic_link.py`:
 *   - MagicLinkAction enum (4 values, locked by DB CHECK)
 *   - MagicLinkConsumeRequest (cccd: 4 digits)
 *   - MagicLinkConsumeResponse (profile_id, action, status, consumed_at)
 *
 * Thin client per FRONTEND_ARCHITECTURE_V3.md: schemas are validation
 * only; no derivation, no business logic. Response shape trusted from
 * BE without re-deriving any state.
 */
import * as z from "zod"

/**
 * 4-action enum. Order matches BE for stable diffs; lowercase string
 * values match the DB CHECK constraint on `action_type`.
 */
export const magicLinkActionSchema = z.enum([
  "submit",
  "resubmit",
  "confirm",
  "withdraw",
])
export type MagicLinkAction = z.infer<typeof magicLinkActionSchema>

/**
 * Request body for POST /api/v2/admissions/magic-link/{action}/{token}.
 *
 * `cccd` is the last 4 digits of citizen ID (matches BE `^\d{4}$`
 * regex). NOT the full 12-digit CCCD — keeps UX consistent with the
 * existing /confirm/{token} 4-digit keypad.
 */
export const magicLinkConsumeRequestSchema = z.object({
  cccd: z
    .string()
    .regex(/^\d{4}$/u, "Vui lòng nhập đúng 4 chữ số"),
})
export type MagicLinkConsumeRequest = z.infer<
  typeof magicLinkConsumeRequestSchema
>

/**
 * Success response shape. `consumed_at` is ISO datetime string from BE
 * (Pydantic serialises `datetime` → ISO 8601).
 */
export const magicLinkConsumeResponseSchema = z.object({
  message: z.string(),
  profile_id: z.number().int().positive(),
  action: magicLinkActionSchema,
  status: z.string(),
  consumed_at: z.string(),
  next_url: z.string().nullable().optional(),
})
export type MagicLinkConsumeResponse = z.infer<
  typeof magicLinkConsumeResponseSchema
>
