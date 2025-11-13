// src/components/admin/organization/OrganizationServerWrapper.tsx
import { cookies } from "next/headers";
import { OrganizationClientPage } from "./OrganizationClientPage";
import type { OrganizationUnit } from "@/types/organization.types";

/**
 * ⚡ PERFORMANCE: Server Component wrapper for organization page
 * Fetches initial data on server-side to improve FCP (First Contentful Paint)
 *
 * Benefits:
 * - Faster initial page load (data ready before hydration)
 * - Better SEO (if needed in future)
 * - Reduced client-side bundle size
 * - No loading spinner on initial render
 */
export async function OrganizationServerWrapper() {
  // Fetch initial organization data on server
  const initialData = await fetchOrganizationUnits();

  // Pass initial data to Client Component
  return <OrganizationClientPage initialData={initialData} />;
}

/**
 * Fetch organization units on server-side
 * Uses Next.js 15 fetch with automatic caching
 */
async function fetchOrganizationUnits(): Promise<OrganizationUnit[] | null> {
  try {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get("access_token")?.value;

    if (!accessToken) {
      console.warn("[Server] No access token found, skipping prefetch");
      return null;
    }

    // ⚡ Next.js 15 auto-caches this fetch
    const response = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/api/organization-units`,
      {
        headers: {
          Cookie: `access_token=${accessToken}`,
        },
        // Cache for 60 seconds (adjust based on data freshness needs)
        next: { revalidate: 60 },
      }
    );

    if (!response.ok) {
      console.error("[Server] Failed to fetch organizations:", response.status);
      return null;
    }

    const data = await response.json();
    return data as OrganizationUnit[];
  } catch (error) {
    console.error("[Server] Error fetching organizations:", error);
    return null;
  }
}
