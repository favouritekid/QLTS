/**
 * Navigation Hook
 * Provides centralized navigation utilities with breadcrumbs and smart back button
 */

import { usePathname, useRouter } from "next/navigation";
import { getBreadcrumbs, getBackPath, type RouteConfig } from "@/lib/navigation/routes";

export function useNavigation() {
  const pathname = usePathname();
  const router = useRouter();

  /**
   * Get breadcrumb trail for current page
   */
  const breadcrumbs = getBreadcrumbs(pathname);

  /**
   * Get back navigation path for current page
   */
  const backPath = getBackPath(pathname);

  /**
   * Navigate back using smart routing
   * - Uses explicit backTo if defined
   * - Falls back to parent route
   * - Uses browser history if no route config
   */
  const goBack = () => {
    if (backPath) {
      router.push(backPath);
    } else {
      router.back();
    }
  };

  /**
   * Check if back navigation is available
   */
  const canGoBack = !!backPath;

  return {
    pathname,
    breadcrumbs,
    backPath,
    goBack,
    canGoBack,
  };
}

export type { RouteConfig };
