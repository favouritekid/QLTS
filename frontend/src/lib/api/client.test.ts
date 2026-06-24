/**
 * Tests for client.ts auth interceptor behavior.
 *
 * Covers:
 * - Logout guard flag management
 * - Redirect URL pattern for force_login
 *
 * Note: Full interceptor integration testing requires a running server
 * (Playwright E2E). These unit tests verify the exported utilities
 * and contracts.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock axios before importing client.ts (it creates axios.create at import time)
vi.mock("axios", () => {
  const mockAxios = {
    create: vi.fn(() => ({
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
      defaults: { headers: { common: {} } },
    })),
    post: vi.fn(),
    Cancel: class Cancel extends Error {},
  };
  return { default: mockAxios, ...mockAxios };
});

// Now safe to import
import { setApiLoggedOut } from "./client";
import { buildLoginRedirect } from "@/lib/auth/login-redirect";

describe("API Client — Logout Guard", () => {
  beforeEach(() => {
    // Reset the flag via the function (which checks typeof window)
    if (typeof globalThis.window !== "undefined") {
      (globalThis.window as unknown as Record<string, unknown>).__qlts_logged_out = false;
    }
  });

  it("setApiLoggedOut does not throw in test environment", () => {
    // In jsdom, window may or may not be available depending on module import order.
    // The function should never throw regardless.
    expect(() => setApiLoggedOut(true)).not.toThrow();
    expect(() => setApiLoggedOut(false)).not.toThrow();
  });
});

describe("API Client — Force Login Contract", () => {
  it("force_login redirect URL has correct format", () => {
    // Verify the contract that the interceptor uses
    const redirectUrl = "/login?force_login=true";
    const url = new URL(redirectUrl, "http://localhost:3000");
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("force_login")).toBe("true");
  });

  it("force_login URL nay kèm redirect khi có path hợp lệ (contract mới)", () => {
    // Interceptor 401 nay dùng buildLoginRedirect(path, { forceLogin: true }).
    const withPath = new URL(
      buildLoginRedirect("/leads/5", { forceLogin: true }),
      "http://localhost:3000",
    );
    expect(Array.from(withPath.searchParams.keys())).toEqual([
      "force_login",
      "redirect",
    ]);
    expect(withPath.searchParams.get("redirect")).toBe("/leads/5");

    // Không có path hợp lệ → vẫn chỉ force_login (giữ contract cũ).
    const noPath = new URL(
      buildLoginRedirect(null, { forceLogin: true }),
      "http://localhost:3000",
    );
    expect(Array.from(noPath.searchParams.keys())).toEqual(["force_login"]);
  });
});
