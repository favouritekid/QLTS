import { Suspense } from "react"
import type { Metadata } from "next"
import { connection } from "next/server"

import PublicDocumentsPage from "@/components/public/PublicDocumentsPage"
import { serverApi } from "@/lib/api/server"
import {
  publicAdmissionsCatalogParams,
  type PublicAdmissionsSearchParams,
} from "@/lib/public-admissions/query"

export const metadata: Metadata = {
  title: "Hồ sơ tuyển sinh | QLTS",
  description:
    "Xem checklist hồ sơ theo hệ đào tạo và phương thức xét tuyển trên cổng tuyển sinh QLTS.",
}

async function DocumentsContent({ searchParams }: { searchParams: PublicAdmissionsSearchParams }) {
  await connection()

  let catalog = null
  const params = publicAdmissionsCatalogParams(await searchParams)

  try {
    catalog = await serverApi.publicAdmissions.getDocumentsCatalog(params)
  } catch (error) {
    console.error("Failed to load public admissions documents catalog", error)
  }

  return <PublicDocumentsPage catalog={catalog} />
}

export default function AdmissionsDocumentsPage({
  searchParams,
}: {
  searchParams: PublicAdmissionsSearchParams
}) {
  return (
    <Suspense fallback={<div className="container mx-auto px-4 py-8 animate-pulse" />}>
      <DocumentsContent searchParams={searchParams} />
    </Suspense>
  )
}
