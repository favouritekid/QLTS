import { Suspense } from "react"
import type { Metadata } from "next"
import { connection } from "next/server"

import PublicAdmissionMethodsPage from "@/components/public/PublicAdmissionMethodsPage"
import { serverApi } from "@/lib/api/server"
import {
  publicAdmissionsCatalogParams,
  type PublicAdmissionsSearchParams,
} from "@/lib/public-admissions/query"

export const metadata: Metadata = {
  title: "Phương thức xét tuyển | QLTS",
  description:
    "So sánh phương thức xét tuyển, tổ hợp môn và checklist hồ sơ trên cổng tuyển sinh QLTS.",
}

async function MethodsContent({ searchParams }: { searchParams: PublicAdmissionsSearchParams }) {
  await connection()

  let catalog = null
  const params = publicAdmissionsCatalogParams(await searchParams)

  try {
    catalog = await serverApi.publicAdmissions.getMethodsCatalog(params)
  } catch (error) {
    console.error("Failed to load public admissions methods catalog", error)
  }

  return <PublicAdmissionMethodsPage catalog={catalog} />
}

export default function AdmissionsMethodsPage({
  searchParams,
}: {
  searchParams: PublicAdmissionsSearchParams
}) {
  return (
    <Suspense fallback={<div className="container mx-auto px-4 py-8 animate-pulse" />}>
      <MethodsContent searchParams={searchParams} />
    </Suspense>
  )
}
