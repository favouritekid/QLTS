/**
 * Admission Profile Detail Page
 *
 * Architecture:
 * - Server Component (async) for initial data fetch
 * - Hydrates Client Components with initialData
 * - Next.js 16 App Router with SSR
 *
 * Features:
 * - SEO-friendly (server-rendered content)
 * - No loading spinner on initial render
 * - TanStack Query hydration for client-side updates
 */

import { Suspense } from "react"
import { notFound } from "next/navigation"
import { api } from "@/lib/api/client"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

import { AdmissionDetailClient } from "./AdmissionDetailClient"

/**
 * Server-side data fetching
 * Runs on server, not included in client bundle
 */
async function getAdmissionProfile(
  id: string
): Promise<AdmissionProfileResponse | null> {
  try {
    const response = await api.get<AdmissionProfileResponse>(
      `/api/admissions/${id}`
    )
    return response.data
  } catch (error: unknown) {
    if (error && typeof error === 'object' && 'response' in error) {
      const axiosError = error as { response?: { status?: number } };
      if (axiosError.response?.status === 404) {
        return null;
      }
    }
    throw error
  }
}

/**
 * Page Component (Server Component)
 *
 * Next.js 16: params is now a Promise that must be awaited
 */
export default async function AdmissionProfilePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params;
  const profileId = parseInt(id, 10)

  if (isNaN(profileId)) {
    notFound()
  }

  // Server-side fetch (no loading spinner)
  const initialData = await getAdmissionProfile(id)

  if (!initialData) {
    notFound()
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      <Suspense fallback={<div>Loading...</div>}>
        <AdmissionDetailClient
          profileId={profileId}
          initialData={initialData}
        />
      </Suspense>
    </div>
  )
}

/**
 * Metadata for SEO
 *
 * Next.js 16: params is now a Promise that must be awaited
 */
export async function generateMetadata({
  params
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params;
  const profile = await getAdmissionProfile(id)

  if (!profile) {
    return {
      title: "Hồ sơ không tìm thấy",
    }
  }

  return {
    title: `Hồ sơ tuyển sinh #${profile.id}`,
    description: `Quản lý hồ sơ tuyển sinh - Trạng thái: ${profile.status}`,
  }
}
