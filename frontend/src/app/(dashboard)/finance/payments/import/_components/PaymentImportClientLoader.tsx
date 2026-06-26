"use client"

import dynamic from "next/dynamic"

/**
 * Loader client-only cho trang Import thu học phí.
 *
 * Vì sao `ssr: false`: trang là công cụ nội bộ sau đăng nhập (không SEO). Dưới
 * Next.js 16 Cache Components, `page.tsx` bị prerender TĨNH lúc build — sinh ra
 * HTML shell CHƯA-đăng-nhập, lệch với cây client ĐÃ-đăng-nhập lúc hydrate →
 * React #418 (hydration mismatch, chỉ hiện ở production build; dev luôn render
 * động nên không repro). `export const dynamic = "force-dynamic"` KHÔNG được
 * Cache Components tôn trọng (route vẫn ○ Static).
 *
 * `ssr: false` để server + client-initial cùng render `loading` fallback → khớp,
 * không hydrate lệch; form thật mount sau ở client. Cùng pattern với
 * `SocketHandler` trong `(dashboard)/layout.tsx`.
 */
const PaymentImportClient = dynamic(
  () => import("./PaymentImportClient").then((m) => m.PaymentImportClient),
  {
    ssr: false,
    loading: () => (
      <div className="container mx-auto space-y-6 py-6">
        <div className="h-8 w-72 animate-pulse rounded-md bg-muted" />
        <div className="h-64 w-full animate-pulse rounded-md bg-muted" />
      </div>
    ),
  },
)

export function PaymentImportClientLoader() {
  return <PaymentImportClient />
}
