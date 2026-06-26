import type { Metadata } from "next"

import { PaymentImportClient } from "./_components/PaymentImportClient"

export const metadata: Metadata = {
  title: "Import thu học phí | QLTS",
  description: "Import file tổng hợp → tự xác minh thanh toán học phí hàng loạt",
}

export default function PaymentImportPage() {
  return <PaymentImportClient />
}
