// src/lib/auth/route-config.ts
/**
 * Navigation Guard Configuration
 * Defines role-based route access rules
 * 
 * Based on Enterprise 3-Layer Guard System best practices
 */

export type UserRole = "admin" | "manager" | "officer";

/**
 * Role hierarchy - higher number = more permissions
 */
export const roleHierarchy: Record<UserRole, number> = {
  admin: 3,
  manager: 2,
  officer: 1,
};

/**
 * Route access configuration
 */
export interface RouteAccess {
  /** Minimum role level required to access this route */
  minRole?: UserRole;
  /** Specific roles allowed (overrides minRole) */
  allowedRoles?: UserRole[];
  /** Redirect path for officers if they try to access this route */
  officerRedirect?: string;
  /** Redirect path for denied access (default: /403) */
  denyRedirect?: string;
}

/**
 * Route access matrix
 * Key is the route pattern (exact or prefix match with *)
 */
export const routeAccessConfig: Record<string, RouteAccess> = {
  // Dashboard routes
  "/dashboard": {
    allowedRoles: ["admin", "manager"],
    officerRedirect: "/dashboard/officer",
  },
  "/dashboard/officer": {
    allowedRoles: ["admin", "manager", "officer"],
  },

  // Admin routes - admin only
  "/admin": {
    allowedRoles: ["admin"],
    denyRedirect: "/403",
  },
  "/admin/*": {
    allowedRoles: ["admin"],
    denyRedirect: "/403",
  },

  // Settings - admin and manager
  "/settings": {
    allowedRoles: ["admin", "manager"],
    denyRedirect: "/403",
  },
  "/settings/*": {
    allowedRoles: ["admin", "manager"],
    denyRedirect: "/403",
  },

  // Leads - all roles
  "/leads": {
    allowedRoles: ["admin", "manager", "officer"],
  },
  "/leads/*": {
    allowedRoles: ["admin", "manager", "officer"],
  },
};

/**
 * Get the default dashboard path for a given role
 * @param role User's role
 * @returns Dashboard path
 */
export function getDefaultDashboard(role: string): string {
  switch (role) {
    case "officer":
      return "/dashboard/officer";
    case "admin":
    case "manager":
    default:
      return "/dashboard";
  }
}

/**
 * Check if a role has access to a route
 * @param userRole User's role
 * @param routePath Route to check
 * @returns { hasAccess, redirectTo }
 */
export function checkRouteAccess(
  userRole: string | undefined,
  routePath: string
): { hasAccess: boolean; redirectTo?: string } {
  if (!userRole) {
    return { hasAccess: false, redirectTo: "/login" };
  }

  // Find matching route config
  let config = routeAccessConfig[routePath];

  // Try prefix match with wildcard
  if (!config) {
    for (const pattern of Object.keys(routeAccessConfig)) {
      if (pattern.endsWith("*")) {
        const prefix = pattern.slice(0, -1);
        if (routePath.startsWith(prefix)) {
          config = routeAccessConfig[pattern];
          break;
        }
      }
    }
  }

  // No config = allow (public route within dashboard)
  if (!config) {
    return { hasAccess: true };
  }

  // Check allowed roles
  const role = userRole as UserRole;
  const allowed = config.allowedRoles?.includes(role) ?? false;

  if (allowed) {
    return { hasAccess: true };
  }

  // Officer trying to access restricted route - use officer redirect if defined
  if (role === "officer" && config.officerRedirect) {
    return { hasAccess: false, redirectTo: config.officerRedirect };
  }

  // General deny
  return { hasAccess: false, redirectTo: config.denyRedirect || "/403" };
}

/**
 * Public routes that don't require authentication
 */
export const publicRoutes = ["/login", "/register", "/forgot-password", "/reset-password"];

/**
 * Check if path is a public route
 */
export function isPublicRoute(path: string): boolean {
  return publicRoutes.some((route) => path.startsWith(route));
}
