/**
 * Tests cho useProactiveTokenRefresh.
 *
 * Trọng tâm: visible-only guard, cross-tab localStorage guard, không
 * logout khi fail + rollback CAS.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const refreshAccessToken = vi.fn();
vi.mock("@/lib/api/refresh", () => ({
  refreshAccessToken: () => refreshAccessToken(),
}));
const isApiLoggedOutMock = vi.fn(() => false);
vi.mock("@/lib/api/client", () => ({
  isApiLoggedOut: () => isApiLoggedOutMock(),
}));

import { useProactiveTokenRefresh } from "./useProactiveTokenRefresh";

const KEY = "qlts_last_refresh_at";

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

const tick = (ms = 10) => new Promise((r) => setTimeout(r, ms));

describe("useProactiveTokenRefresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear(); // setup.ts không tự clear giữa các test
    setVisibility("visible");
    refreshAccessToken.mockResolvedValue(undefined);
    isApiLoggedOutMock.mockReturnValue(false);
  });

  afterEach(() => {
    // Khôi phục visibilityState về mặc định jsdom — Object.defineProperty KHÔNG
    // bị restoreMocks hoàn tác, phải reset tay tránh leak getter sang file sau.
    setVisibility("visible");
  });

  it("refresh on mount khi visible + chưa có timestamp; có ghi timestamp", async () => {
    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem(KEY)).not.toBeNull();
  });

  it("KHÔNG refresh nếu timestamp < 12' (cross-tab guard)", async () => {
    localStorage.setItem(KEY, String(Date.now()));
    renderHook(() => useProactiveTokenRefresh(true));
    await tick();
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("KHÔNG refresh khi tab hidden", async () => {
    setVisibility("hidden");
    renderHook(() => useProactiveTokenRefresh(true));
    await tick();
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("KHÔNG refresh khi enabled=false", async () => {
    renderHook(() => useProactiveTokenRefresh(false));
    await tick();
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("fail → không throw + rollback timestamp (prev null → xoá key)", async () => {
    refreshAccessToken.mockRejectedValue(new Error("net"));
    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    // Rollback CAS: prev null → khôi phục bằng cách xoá key.
    await waitFor(() => expect(localStorage.getItem(KEY)).toBeNull());
  });
});
