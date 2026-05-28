import { Suspense } from "react"
import type { Metadata } from "next"
import { connection } from "next/server"

import PublicProgramsPage from "@/components/public/PublicProgramsPage"
import { serverApi } from "@/lib/api/server"
import {
  publicAdmissionsCatalogParams,
  type PublicAdmissionsSearchParams,
} from "@/lib/public-admissions/query"

export const metadata: Metadata = {
  title: "Ngành học tuyển sinh | QLTS",
  description:
    "Duyệt nhóm ngành, bậc học và hệ đào tạo trên cổng tuyển sinh QLTS để chọn chương trình phù hợp trước khi xem phương thức xét tuyển.",
}

async function ProgramsContent({ searchParams }: { searchParams: PublicAdmissionsSearchParams }) {
  await connection()

  let catalog = null
  const params = publicAdmissionsCatalogParams(await searchParams)

  try {
    catalog = await serverApi.publicAdmissions.getProgramsCatalog(params)
  } catch (error) {
    console.error("Failed to load public admissions programs catalog", error)
  }

  return <PublicProgramsPage catalog={catalog} />
}

export default function AdmissionsProgramsPage({
  searchParams,
}: {
  searchParams: PublicAdmissionsSearchParams
}) {
  return (
    <Suspense fallback={<div className="container mx-auto px-4 py-8 animate-pulse" />}>
      <ProgramsContent searchParams={searchParams} />
    </Suspense>
  )
}
