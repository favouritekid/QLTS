import type { Metadata } from "next"

import PublicTuitionAidPage from "@/components/public/PublicTuitionAidPage"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = {
  title: "Học phí và học bổng | QLTS",
  description:
    "Xem khung học phí tham chiếu, học bổng đầu vào và lộ trình thanh toán trên cổng tuyển sinh QLTS.",
}

export default async function AdmissionsTuitionPage() {
  let catalog = null

  try {
    catalog = await serverApi.publicAdmissions.getTuitionCatalog()
  } catch (error) {
    console.error("Failed to load public admissions tuition catalog", error)
  }

  return <PublicTuitionAidPage catalog={catalog} />
}
