// src/app/(dashboard)/admin/page.tsx
/**
 * Admin Index Page - Redirects to /admin/organization
 *
 * The /admin route is a namespace for admin sub-routes.
 * Direct navigation to /admin redirects to the default admin page.
 */

import { redirect } from "next/navigation"

export default function AdminIndexPage() {
  redirect("/admin/organization")
}
