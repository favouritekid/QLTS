// src/app/(dashboard)/finance/invoices/[invoiceId]/page.tsx
/**
 * Invoice Detail Page (Server Component)
 *
 * Shows invoice details with payment history and actions.
 */

import { Suspense } from "react"
import { notFound } from "next/navigation"
import { Skeleton } from "@/components/ui/skeleton"
import { InvoiceDetailClient } from "./_components/InvoiceDetailClient"

// Placeholder param for Next.js 16 cacheComponents build validation
// Real params are handled at runtime
export function generateStaticParams() {
  return [{ invoiceId: "__placeholder__" }]
}

interface PageProps {
  params: Promise<{ invoiceId: string }>
}

/**
 * Loading skeleton for invoice detail
 */
function InvoiceDetailLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      <Skeleton className="h-8 w-24" />
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="h-80 rounded-lg lg:col-span-2" />
        <Skeleton className="h-80 rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Invoice Detail Page
 */
export default async function InvoiceDetailPage({ params }: PageProps) {
  const { invoiceId } = await params

  // Handle placeholder used for build validation
  if (invoiceId === "__placeholder__") {
    notFound()
  }

  return (
    <Suspense fallback={<InvoiceDetailLoading />}>
      <InvoiceDetailClient invoiceId={parseInt(invoiceId)} />
    </Suspense>
  )
}
