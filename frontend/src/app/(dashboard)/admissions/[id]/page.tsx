/**
 * Admission Profile Detail Page
 *
 * Architecture:
 * - Client Component for data fetch with authentication
 * - Uses TanStack Query for client-side data fetching
 * - Avoids SSR auth issues by fetching on client
 */
"use client"

// Skip static prerendering - this route requires auth cookies
export const dynamic = 'force-dynamic'

import { useParams, notFound } from "next/navigation"
import { useGetAdmission } from "@/hooks/admissions"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

import { AdmissionDetailClient } from "./AdmissionDetailClient"

/**
 * Page Component (Client Component)
 *
 * Uses client-side data fetching to properly include auth cookies
 */
export default function AdmissionProfilePage() {
  const params = useParams()
  const id = params?.id as string
  const profileId = parseInt(id, 10)

  // Use hook for client-side fetch with auth cookies
  const { data: profile, isLoading, isError } = useGetAdmission(profileId, {
    enabled: !isNaN(profileId) && profileId > 0,
  })

  if (isNaN(profileId)) {
    notFound()
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-32" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-32 w-full" />
          </CardContent>
        </Card>
      </div>
    )
  }

  if (isError || !profile) {
    notFound()
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      <AdmissionDetailClient
        profileId={profileId}
        initialData={profile}
      />
    </div>
  )
}
