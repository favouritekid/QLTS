import { z } from "zod";

export const configSystemCategorySchema = z.object({
  id: z.number(),
  type: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  display_order: z.number().nullable().optional(),
  is_active: z.boolean().nullable().optional(),
});

export type ConfigSystemCategory = z.infer<typeof configSystemCategorySchema>;
