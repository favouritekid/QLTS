"use client"

import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api/client"
import { academicYearListResponseSchema } from "@/lib/zod/admission-path"

export const INVOICE_SEMESTER_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8] as const

export function useInvoiceAcademicYears() {
  return useQuery<number[]>({
    queryKey: ["finance", "invoice-filter-options", "academic-years"],
    queryFn: async () => {
      const response = await api.get("/api/admission-config/years")
      // Validate against the shared schema (mirrors the backend Pydantic
      // model). safeParse tolerates a null/empty body (204 / gateway edge)
      // without throwing — degrade to an empty year list instead.
      const parsed = academicYearListResponseSchema.safeParse(response.data)
      if (!parsed.success) return []
      const years = [parsed.data.current_year, ...parsed.data.years].filter(
        (year): year is number => Number.isFinite(year),
      )
      return Array.from(new Set(years)).sort((a, b) => b - a)
    },
    staleTime: 10 * 60 * 1000,
  })
}
