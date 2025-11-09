// src/app/(dashboard)/admin/layout.tsx

/**
 * Admin Layout
 *
 * ✅ SECURITY FIX: Removed client-side role checking
 *
 * Authorization is now enforced by server-side middleware BEFORE page render.
 * This prevents the security vulnerability where:
 * - HTML/data was sent to client before role check
 * - Attackers could view admin page structure by disabling JavaScript
 *
 * Middleware checks:
 * 1. User is authenticated (has valid access_token cookie)
 * 2. User role is 'admin' or 'manager' (from JWT payload)
 * 3. Redirect to /dashboard if unauthorized
 *
 * This layout now only serves as a container for admin pages.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  // ✅ SECURITY FIX: No client-side auth/role checks needed
  // Middleware has already verified user is admin/manager

  return <>{children}</>;
}
