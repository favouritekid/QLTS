import type { Metadata } from "next"

import { PaymentImportClientLoader } from "./_components/PaymentImportClientLoader"

export const metadata: Metadata = {
  title: "Import thu học phí | QLTS",
  description: "Import file tổng hợp → tự xác minh thanh toán học phí hàng loạt",
}

export default function PaymentImportPage() {
  return <PaymentImportClientLoader />
}
