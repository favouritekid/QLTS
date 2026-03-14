import type { Metadata } from "next"

import PublicDocumentsPage from "@/components/public/PublicDocumentsPage"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = {
  title: "Hồ sơ tuyển sinh | QLTS",
  description:
    "Xem checklist hồ sơ theo hệ đào tạo và phương thức xét tuyển trên cổng tuyển sinh QLTS.",
}

export default async function AdmissionsDocumentsPage() {
  let catalog = null

  try {
    catalog = await serverApi.publicAdmissions.getDocumentsCatalog()
  } catch (error) {
    console.error("Failed to load public admissions documents catalog", error)
  }

  return <PublicDocumentsPage catalog={catalog} />
}
