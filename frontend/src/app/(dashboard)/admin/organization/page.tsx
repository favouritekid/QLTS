// src/app/(dashboard)/admin/organization/page.tsx
import { OrganizationClientPage } from "@/components/admin/organization/OrganizationClientPage";

/**
 * Organization Management Page
 *
 * Modern column-based layout:
 * - Left: Units tree (with search and create)
 * - Right: Unit details with 3 tabs (Majors, Users, Settings)
 *
 * Features:
 * - Temporal data architecture for MajorAcademicInfo
 * - Real-time updates via Socket.IO
 * - Optimistic UI updates
 * - Soft delete for Units and Majors
 */
export default function OrganizationPage() {
  return (
    <div className="h-[calc(100vh-4rem)]">
      <OrganizationClientPage />
    </div>
  );
}
