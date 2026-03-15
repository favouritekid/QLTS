/**
 * Zod Validation Schemas for Lead Module
 *
 * Mirrors Backend Pydantic schemas (app/schemas/lead.py) for type safety.
 */

import { z } from "zod"

// ==============================================================================
// LEAD STATUS UPDATE
// ==============================================================================

/**
 * Lead Status Update Schema
 * Mirrors backend: app/schemas/lead.py -> LeadStatusUpdate
 *
 * Used by PATCH /api/leads/{lead_id}/status endpoint.
 * Validated by the FSM engine before being applied.
 */
export const leadStatusUpdateSchema = z.object({
  consultation_status_id: z.string().min(1, "Consultation status ID is required"),
  version: z.number().int().positive("Version must be a positive integer"),
  loss_reason_code: z.string().optional().nullable(),
})

export type LeadStatusUpdate = z.infer<typeof leadStatusUpdateSchema>
