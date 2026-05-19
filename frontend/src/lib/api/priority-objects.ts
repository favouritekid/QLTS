/**
 * Priority Object (UT) catalog API client — Q9 #07 Phase E wireframe.
 *
 * Wraps `GET /api/v2/admissions/priority-objects/catalog?academic_year=`
 * — candidate-facing catalog cho UT (đối tượng ưu tiên) multi-select picker
 * trong PriorityTab.
 *
 * Mirrors `app/schemas/admission.py::PriorityObjectCatalogItem` (subset của
 * `priority_object_config` row, admin metadata excluded).
 *
 * BE auth: any authenticated user — catalog org-wide public, KHÔNG IDOR-scoped.
 *
 * Response is Zod-validated để catch BE field drift sớm (FE convention V3).
 */
import { z } from "zod"

import { api } from "@/lib/api/client"
import {
  GROUP_CODE_REGEX,
  SUB_CODE_REGEX,
} from "@/lib/zod/priority-config"

export const priorityObjectCatalogItemSchema = z.object({
  group_code: z
    .string()
    .regex(GROUP_CODE_REGEX, "Mã nhóm UT không hợp lệ"),
  sub_code: z
    .string()
    .regex(SUB_CODE_REGEX, "sub_code phải là 2 chữ số"),
  description: z.string().min(1),
  bonus_points: z.number().min(0),
  evidence_doc_type: z.string().nullable().optional(),
})

export type PriorityObjectCatalogItem = z.infer<
  typeof priorityObjectCatalogItemSchema
>

export const priorityObjectCatalogSchema = z.array(
  priorityObjectCatalogItemSchema,
)

export const priorityObjectsApi = {
  async getCatalog(academicYear: number): Promise<PriorityObjectCatalogItem[]> {
    const { data } = await api.get<unknown>(
      `/api/v2/admissions/priority-objects/catalog`,
      { params: { academic_year: academicYear } },
    )
    return priorityObjectCatalogSchema.parse(data)
  },
}
