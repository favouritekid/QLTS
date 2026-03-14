import type { Metadata } from "next"

import PublicAdmissionsLanding from "@/components/public/PublicAdmissionsLanding"

export const metadata: Metadata = {
  title: "Cổng tuyển sinh | QLTS",
  description:
    "Khám phá chương trình đào tạo, phương thức xét tuyển, học phí và học bổng trên cổng tuyển sinh public của QLTS.",
}

export default function AdmissionsIndexPage() {
  return <PublicAdmissionsLanding />
}
