/**
 * HealthCheckGrid Component
 *
 * Section 2: Lưới Kiểm Tra Nhanh
 * Container for 3 health check cards: Legal, Academic, Admin
 */

"use client"

import { LegalDocsCard } from "./LegalDocsCard"
import { AcademicCard } from "./AcademicCard"
import { AdminCard } from "./AdminCard"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface HealthCheckGridProps {
  profile: AdmissionProfileResponse
}

export function HealthCheckGrid({ profile }: HealthCheckGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Khối 1: Hồ Sơ Pháp Lý */}
      <LegalDocsCard profile={profile} />

      {/* Khối 2: Năng Lực Học Tập */}
      <AcademicCard profile={profile} />

      {/* Khối 3: Thủ Tục & Tài Chính */}
      <AdminCard profile={profile} />
    </div>
  )
}
