import { Suspense } from "react"
import type { Metadata } from "next"
import { connection } from "next/server"

import PublicTuitionAidPage from "@/components/public/PublicTuitionAidPage"
import { serverApi } from "@/lib/api/server"
import {
  publicAdmissionsCatalogParams,
  type PublicAdmissionsSearchParams,
} from "@/lib/public-admissions/query"

export const metadata: Metadata = {
  title: "Học phí và học bổng | QLTS",
  description:
    "Xem khung học phí tham chiếu, học bổng đầu vào và lộ trình thanh toán trên cổng tuyển sinh QLTS.",
}

async function TuitionContent({ searchParams }: { searchParams: PublicAdmissionsSearchParams }) {
  await connection()

  let catalog = null
  const params = publicAdmissionsCatalogParams(await searchParams)

  try {
    catalog = await serverApi.publicAdmissions.getTuitionCatalog(params)
  } catch (error) {
    console.error("Failed to load public admissions tuition catalog", error)
  }

  return <PublicTuitionAidPage catalog={catalog} />
}

export default function AdmissionsTuitionPage({
  searchParams,
}: {
  searchParams: PublicAdmissionsSearchParams
}) {
  return (
    <Suspense fallback={<div className="container mx-auto px-4 py-8 animate-pulse" />}>
      <TuitionContent searchParams={searchParams} />
    </Suspense>
  )
}
