import type { Metadata } from "next"

import PublicProgramsPage from "@/components/public/PublicProgramsPage"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = {
  title: "Ngành học tuyển sinh | QLTS",
  description:
    "Duyệt nhóm ngành, bậc học và hệ đào tạo trên cổng tuyển sinh QLTS để chọn chương trình phù hợp trước khi xem phương thức xét tuyển.",
}

export default async function AdmissionsProgramsPage() {
  let catalog = null

  try {
    catalog = await serverApi.publicAdmissions.getProgramsCatalog()
  } catch (error) {
    console.error("Failed to load public admissions programs catalog", error)
  }

  return <PublicProgramsPage catalog={catalog} />
}
