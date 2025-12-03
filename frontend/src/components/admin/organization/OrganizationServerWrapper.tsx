// src/components/admin/organization/OrganizationServerWrapper.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 2: Organization Server Component
 *
 * REFACTOR: Manual fetch → standardized serverApi
 *
 * Benefits:
 * - Consistent server-side API calls
 * - Cookie forwarding handled by serverApi
 * - Better error handling and logging
 */
import { serverApi } from "@/lib/api/server";
import { OrganizationClientPage } from "./OrganizationClientPage";

/**
 * Server Component - Fetches initial organization units
 */
export async function OrganizationServerWrapper() {
  // ✅ Use standardized server API client
  const initialData = await serverApi.admin.organization.getUnitsTree();

  // ✅ Pass initial data to Client Component
  return <OrganizationClientPage initialData={initialData} />;
}
