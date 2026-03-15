/**
 * Tests for auth route configuration.
 *
 * Covers:
 * - Public route detection
 * - Route access checking by role
 * - Default dashboard per role
 */
import { describe, it, expect } from "vitest";
import {
  isPublicRoute,
  getDefaultDashboard,
  checkRouteAccess,
  publicRoutes,
} from "./route-config";

describe("isPublicRoute", () => {
  it("identifies login as public", () => {
    expect(isPublicRoute("/login")).toBe(true);
  });

  it("identifies register as public", () => {
    expect(isPublicRoute("/register")).toBe(true);
  });

  it("identifies forgot-password as public", () => {
    expect(isPublicRoute("/forgot-password")).toBe(true);
  });

  it("identifies reset-password as public", () => {
    expect(isPublicRoute("/reset-password")).toBe(true);
  });

  it("identifies dashboard as NOT public", () => {
    expect(isPublicRoute("/dashboard")).toBe(false);
  });

  it("identifies admin as NOT public", () => {
    expect(isPublicRoute("/admin")).toBe(false);
  });
});

describe("getDefaultDashboard", () => {
  it("returns /dashboard/officer for officer role", () => {
    expect(getDefaultDashboard("officer")).toBe("/dashboard/officer");
  });

  it("returns /dashboard for admin role", () => {
    expect(getDefaultDashboard("admin")).toBe("/dashboard");
  });

  it("returns /dashboard for manager role", () => {
    expect(getDefaultDashboard("manager")).toBe("/dashboard");
  });

  it("returns /dashboard for unknown role", () => {
    expect(getDefaultDashboard("unknown")).toBe("/dashboard");
  });
});

describe("checkRouteAccess", () => {
  it("denies access when no role", () => {
    const result = checkRouteAccess(undefined, "/dashboard");
    expect(result.hasAccess).toBe(false);
    expect(result.redirectTo).toBe("/login");
  });

  it("allows admin to access /dashboard", () => {
    const result = checkRouteAccess("admin", "/dashboard");
    expect(result.hasAccess).toBe(true);
  });

  it("redirects officer from /dashboard to /dashboard/officer", () => {
    const result = checkRouteAccess("officer", "/dashboard");
    expect(result.hasAccess).toBe(false);
    expect(result.redirectTo).toBe("/dashboard/officer");
  });

  it("denies officer access to /admin", () => {
    const result = checkRouteAccess("officer", "/admin");
    expect(result.hasAccess).toBe(false);
    expect(result.redirectTo).toBe("/403");
  });

  it("allows admin to access /admin", () => {
    const result = checkRouteAccess("admin", "/admin");
    expect(result.hasAccess).toBe(true);
  });

  it("allows officer to access /leads", () => {
    const result = checkRouteAccess("officer", "/leads");
    expect(result.hasAccess).toBe(true);
  });
});

describe("publicRoutes constant", () => {
  it("contains expected routes", () => {
    expect(publicRoutes).toContain("/login");
    expect(publicRoutes).toContain("/register");
    expect(publicRoutes).toContain("/forgot-password");
    expect(publicRoutes).toContain("/reset-password");
  });

  it("does not contain protected routes", () => {
    expect(publicRoutes).not.toContain("/dashboard");
    expect(publicRoutes).not.toContain("/admin");
  });
});
