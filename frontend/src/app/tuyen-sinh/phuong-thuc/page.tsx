import type { Metadata } from "next"

import PublicAdmissionMethodsPage from "@/components/public/PublicAdmissionMethodsPage"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = {
  title: "Phương thức xét tuyển | QLTS",
  description:
    "So sánh phương thức xét tuyển, tổ hợp môn và checklist hồ sơ trên cổng tuyển sinh QLTS.",
}

export default async function AdmissionsMethodsPage() {
  let catalog = null

  try {
    catalog = await serverApi.publicAdmissions.getMethodsCatalog()
  } catch (error) {
    console.error("Failed to load public admissions methods catalog", error)
  }

  return <PublicAdmissionMethodsPage catalog={catalog} />
}
