/**
 * Zod schemas for system_config admin surface.
 *
 * Mirrors backend ``Backend_FastAPI/app/schemas/system_config.py`` —
 * ``value`` is intentionally untyped (``z.unknown()``) because the
 * table stores heterogeneous JSONB shapes (bool / int / string /
 * list / nested object). The admin UI renders + edits the raw JSON;
 * shape validation belongs at the consumer site (engine reads
 * ``max_choices_per_profile`` as int, storefront reads
 * ``current_intake_year`` as int, etc.).
 *
 * Endpoints:
 *   GET    /api/v2/admin/system-config
 *   GET    /api/v2/admin/system-config/{key}
 *   PATCH  /api/v2/admin/system-config/{key}   (admin-only)
 */
import { z } from "zod"

export const SystemConfigResponseSchema = z.object({
  key: z.string(),
  value: z.unknown(),
  description: z.string().nullable(),
  updated_at: z.string(),
  updated_by_user_id: z.number().int().nullable(),
})

export const SystemConfigUpdateSchema = z.object({
  // ``value`` REQUIRED per BE contract — to "clear" admin sends explicit
  // null/false/0/"" rather than DELETE row. Keep audit + description intact.
  value: z.unknown(),
  description: z.string().nullable().optional(),
})

export const SystemConfigListResponseSchema = z.object({
  total: z.number().int(),
  items: z.array(SystemConfigResponseSchema),
})

export type SystemConfigResponse = z.infer<typeof SystemConfigResponseSchema>
export type SystemConfigUpdate = z.infer<typeof SystemConfigUpdateSchema>
export type SystemConfigListResponse = z.infer<typeof SystemConfigListResponseSchema>
