import { Suspense } from "react"
import type { Metadata } from "next"
import { connection } from "next/server"

import PublicDocumentsPage from "@/components/public/PublicDocumentsPage"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = {
  title: "Hồ sơ tuyển sinh | QLTS",
  description:
    "Xem checklist hồ sơ theo hệ đào tạo và phương thức xét tuyển trên cổng tuyển sinh QLTS.",
}

async function DocumentsContent() {
  await connection()

  let catalog = null

  try {
    catalog = await serverApi.publicAdmissions.getDocumentsCatalog()
  } catch (error) {
    console.error("Failed to load public admissions documents catalog", error)
  }

  return <PublicDocumentsPage catalog={catalog} />
}

export default function AdmissionsDocumentsPage() {
  return (
    <Suspense fallback={<div className="container mx-auto px-4 py-8 animate-pulse" />}>
      <DocumentsContent />
    </Suspense>
  )
}
