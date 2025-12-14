// src/hooks/useAppNavigation.ts
/**
 * Custom hook for configuration-driven navigation
 * Handles role-based filtering and active state detection
 */
import { useMemo, useCallback } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { navigationConfig } from "@/lib/config/navigation";
import type { NavItem, NavGroup } from "@/types/navigation";

/**
 * Hook return type
 */
interface UseAppNavigationReturn {
  navigation: NavGroup[];
  isActive: (href: string, matchPath?: string[], excludePaths?: string[]) => boolean;
}

/**
 * Custom hook that provides filtered navigation based on user role
 * and helper function to determine active state
 *
 * @returns {UseAppNavigationReturn} Filtered navigation and isActive helper
 *
 * @example
 * const { navigation, isActive } = useAppNavigation();
 */
export function useAppNavigation(): UseAppNavigationReturn {
  const { user } = useAuth();
  const pathname = usePathname();

  /**
   * Checks if a navigation item is accessible to the current user
   * @param roles - Array of allowed roles (empty array = all roles)
   * @param excludeRoles - Array of roles that should NOT see this item
   * @returns true if user can access this item
   */
  const hasAccess = useCallback(
    (roles?: string[], excludeRoles?: string[]): boolean => {
      // No user logged in = no access to role-restricted items
      if (!user?.role) {
        // If no roles specified, allow access (public item)
        return !roles || roles.length === 0;
      }

      // Check excludeRoles first (blacklist takes priority)
      if (excludeRoles && excludeRoles.length > 0) {
        if (excludeRoles.includes(user.role)) {
          return false;
        }
      }

      // No roles specified = accessible to all (unless excluded above)
      if (!roles || roles.length === 0) return true;

      // Check if user's role is in the allowed roles
      return roles.includes(user.role);
    },
    [user]
  );

  /**
   * Recursively filters navigation items based on user role
   * @param items - Array of navigation items to filter
   * @returns Filtered array of navigation items
   */
  const filterNavItems = useCallback(
    (items: NavItem[]): NavItem[] => {
      const filter = (itemsToFilter: NavItem[]): NavItem[] => {
        return itemsToFilter
          .filter((item) => hasAccess(item.roles, item.excludeRoles))
          .map((item) => {
            // If item has children, filter them recursively
            if (item.children && item.children.length > 0) {
              const filteredChildren = filter(item.children);
              // Only include parent if it has accessible children
              if (filteredChildren.length > 0) {
                return { ...item, children: filteredChildren };
              }
              // If no children are accessible, exclude parent
              return null;
            }
            return item;
          })
          .filter((item): item is NavItem => item !== null);
      };
      return filter(items);
    },
    [hasAccess]
  );

  /**
   * Filters navigation groups based on user role
   * Memoized to avoid unnecessary recalculations
   */
  const navigation = useMemo((): NavGroup[] => {
    return navigationConfig.groups
      .map((group) => ({
        ...group,
        items: filterNavItems(group.items),
      }))
      .filter((group) => group.items.length > 0); // Only include groups with items
  }, [filterNavItems]);

  /**
   * Determines if a navigation item should be marked as active
   * Handles exact matches, child paths, custom matchPath, and excludePaths
   *
   * @param href - The navigation item's href
   * @param matchPath - Optional array of additional paths that should activate this item
   * @param excludePaths - Optional array of paths to exclude from activation
   * @returns true if the item should be marked as active
   *
   * @example
   * // Basic usage
   * isActive('/dashboard')
   *
   * // With custom match paths
   * isActive('/users', ['/users/profile', '/users/settings'])
   *
   * // With exclusions (fixes parent active state when on child route)
   * isActive('/leads', undefined, ['/leads/pipeline'])
   */
  const isActive = useCallback(
    (href: string, matchPath?: string[], excludePaths?: string[]): boolean => {
      // First, check if current path is in excludePaths
      if (excludePaths && excludePaths.length > 0) {
        const isExcluded = excludePaths.some((excludePath) => {
          if (pathname === excludePath) return true;
          // Also check if pathname starts with excludePath (for nested routes)
          if (excludePath !== "/" && pathname.startsWith(excludePath + "/")) {
            return true;
          }
          return false;
        });

        // If current path is excluded, return false immediately
        if (isExcluded) return false;
      }

      // Exact match
      if (pathname === href) return true;

      // Check custom matchPath
      if (matchPath && matchPath.length > 0) {
        const isMatched = matchPath.some((path) => {
          if (pathname === path) return true;
          // Match child paths
          if (path !== "/" && pathname.startsWith(path + "/")) {
            return true;
          }
          return false;
        });
        if (isMatched) return true;
      }

      // Never match root with startsWith
      if (href === "/") return false;

      // Match child paths (pathname starts with href + "/")
      return pathname.startsWith(href + "/");
    },
    [pathname]
  );

  return {
    navigation,
    isActive,
  };
}
