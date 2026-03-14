import type { Metadata } from "next"

import PublicAdmissionsLanding from "@/components/public/PublicAdmissionsLanding"

export const metadata: Metadata = {
  title: "Tuyển sinh | QLTS",
  description:
    "Tra cứu chương trình đào tạo, phương thức xét tuyển, học phí, học bổng và lộ trình nhập học trên cổng tuyển sinh QLTS.",
}

export default function Home() {
  return <PublicAdmissionsLanding />
}
