# Frontend Architecture

## Overview

This document describes the frontend architecture for the Lead Management System (QLTS).

**Technology Stack:**
- Next.js 14 (App Router)
- React 18 with TypeScript
- TanStack Query (React Query) for data fetching
- Zustand for local state management
- Tailwind CSS + shadcn/ui for styling
- Socket.IO for real-time updates

---

## Navigation Guard System

### Overview

The application implements a **3-Layer Guard System** for role-based access control (RBAC), ensuring secure navigation and protecting routes based on user roles.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      INCOMING REQUEST                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: PROXY GUARD (Server-side)                             │
│  File: src/proxy.ts                                             │
│                                                                 │
│  • JWT token validation from httpOnly cookie                    │
│  • Role extraction from token payload                           │
│  • Route-based access control                                   │
│  • Officer redirect: /dashboard → /dashboard/officer            │
│  • Admin route protection                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: ROUTE GUARD (Client-side)                             │
│  Files: src/hooks/useAuth.ts, src/lib/auth/route-config.ts      │
│                                                                 │
│  • Role-based login redirect                                    │
│  • Route access configuration matrix                            │
│  • 403 Forbidden page for unauthorized access                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: UI GUARD (Component-level)                            │
│  Files: src/hooks/useAppNavigation.ts, components with roles    │
│                                                                 │
│  • Sidebar navigation filtering (roles, excludeRoles)           │
│  • Breadcrumb role-based routing                                │
│  • Component-level visibility based on user role                │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 1: Proxy Guard

**File:** `src/proxy.ts`

The proxy guard intercepts all server-side requests and enforces authentication and authorization before the request reaches the application.

#### Key Features:
- Parses JWT from `access_token` httpOnly cookie
- Validates token and extracts user role
- Protects admin routes (`/admin/*`) from unauthorized access
- Redirects officers from `/dashboard` to `/dashboard/officer`
- Redirects authenticated users from public pages (login/register) to their dashboard

#### Code Flow:
```typescript
// Step 1: Skip public routes and static files
if (isPublicRoute || isStaticFile) return NextResponse.next();

// Step 2: Check authentication
if (!token) redirect to /login;

// Step 3: Validate token
const payload = decodeJWT(token);
if (!payload) redirect to /login;

// Step 4: Admin route protection
if (isAdminRoute && !hasAdminAccess(payload.role)) redirect to /dashboard;

// Step 5: Officer dashboard redirect
if (pathname === "/dashboard" && payload.role === "officer") {
  redirect to /dashboard/officer;
}

// Step 6: Role-based login redirect for authenticated users on public pages
// Step 7: Allow access
```

### Layer 2: Route Guard

**Files:**
- `src/lib/auth/route-config.ts` - Route access configuration
- `src/hooks/useAuth.ts` - Login redirect logic
- `src/app/403/page.tsx` - Forbidden page

#### Route Configuration Matrix

| Route Pattern | Allowed Roles | Officer Redirect |
|---------------|---------------|------------------|
| `/dashboard` | admin, manager | `/dashboard/officer` |
| `/dashboard/officer` | admin, manager, officer | - |
| `/admin/*` | admin | - |
| `/settings` | admin, manager | `/dashboard/officer` |
| `/leads` | admin, manager, officer | - |

#### Login Redirect Logic

```typescript
// In useAuth.ts - onLoginSuccess
const defaultPath = user.role === "officer" 
  ? "/dashboard/officer" 
  : "/dashboard";
router.push(redirect || defaultPath);
```

### Layer 3: UI Guard

**Files:**
- `src/hooks/useAppNavigation.ts` - Navigation filtering
- `src/lib/navigation.ts` - Navigation configuration

#### Sidebar Navigation Filtering

Navigation items can specify which roles can access them:

```typescript
// Navigation item with role restriction
{
  title: "Admin Panel",
  href: "/admin",
  icon: Settings,
  roles: ["admin"], // Only admin can see this
}

// Navigation item excluding specific roles
{
  title: "Dashboard",
  href: "/dashboard",
  icon: LayoutDashboard,
  excludeRoles: ["officer"], // Officers cannot see this
}
```

#### Breadcrumb Role-Based Routing

```typescript
// Dashboard breadcrumb changes based on role
const dashboardPath = user?.role === "officer" 
  ? "/dashboard/officer" 
  : "/dashboard";
```

---

## User Roles

| Role | Description | Dashboard | Admin Access |
|------|-------------|-----------|--------------|
| `admin` | System administrator | `/dashboard` | ✅ Full |
| `manager` | Unit manager | `/dashboard` | ❌ None |
| `officer` | Sales officer | `/dashboard/officer` | ❌ None |

---

## Security Considerations

1. **Server-Side First**: Critical authorization checks happen in `proxy.ts` before reaching client code
2. **httpOnly Cookies**: JWT tokens stored in httpOnly cookies prevent XSS attacks
3. **Defense in Depth**: All 3 layers work together; client-side guards are UX improvements, not security boundaries
4. **Backend Validation**: All API endpoints enforce their own authorization via Casbin policies

---

## Related Files

| File | Purpose |
|------|---------|
| `src/proxy.ts` | Server-side route protection |
| `src/lib/auth/route-config.ts` | Route access configuration |
| `src/hooks/useAuth.ts` | Authentication hook with login redirect |
| `src/hooks/useAppNavigation.ts` | Navigation filtering hook |
| `src/app/403/page.tsx` | Forbidden access page |
| `src/lib/navigation.ts` | Navigation items configuration |
