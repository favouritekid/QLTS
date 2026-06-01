/**
 * useAcademicInfoUrlSync — hook chung cho ByMajorView + CoverageMatrix.
 *
 * Gỡ trùng lặp logic Fix #1 (đọc/ghi `?academicInfo` URL param + validate
 * ngành theo năm). academic_info là year-bound → đổi năm giữ academicInfo cũ
 * sẽ mismatch (header năm mới nhưng matrix ngành năm cũ). Xử lý:
 *   - năm có ngành + selection không thuộc năm (hoặc chưa chọn) → ngành đầu
 *   - năm KHÔNG có ngành nào → clear selection (tránh phantom matrix năm cũ)
 *
 * Trả thêm `updateSearchParam` để caller tự sync param khác (vd ByMajorView
 * dùng cho `?pathId`).
 */
"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo } from "react"

import { useQuotaMatrix } from "@/hooks/admissions/useQuotaMatrix"

export function useAcademicInfoUrlSync(academicYear: number) {
  // Reuse global quota-matrix endpoint để populate ngành dropdown + validate.
  const { data: globalData } = useQuotaMatrix(academicYear)

  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const selectedAcademicInfoId = useMemo<number | undefined>(() => {
    const raw = searchParams.get("academicInfo")
    if (!raw) return undefined
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : undefined
  }, [searchParams])

  const updateSearchParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (value === null) params.delete(key)
      else params.set(key, value)
      const qs = params.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const setSelectedAcademicInfoId = useCallback(
    (id: number) => updateSearchParam("academicInfo", id.toString()),
    [updateSearchParam],
  )

  useEffect(() => {
    if (!globalData) return // đang load năm mới — chờ data thật
    const exists = globalData.rows.some(
      (r) => r.academic_info_id === selectedAcademicInfoId,
    )
    if (exists) return
    if (globalData.rows.length > 0) {
      setSelectedAcademicInfoId(globalData.rows[0].academic_info_id)
    } else if (selectedAcademicInfoId !== undefined) {
      updateSearchParam("academicInfo", null)
    }
  }, [
    globalData,
    selectedAcademicInfoId,
    setSelectedAcademicInfoId,
    updateSearchParam,
  ])

  return {
    globalData,
    selectedAcademicInfoId,
    setSelectedAcademicInfoId,
    updateSearchParam,
  }
}
