/**
 * Tests cho useProactiveTokenRefresh.
 *
 * Trọng tâm: visible-only guard, cross-tab localStorage guard, không
 * logout khi fail + rollback CAS.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const refreshAccessToken = vi.fn();
const isRefreshRateLimitedMock = vi.fn(() => false);
vi.mock("@/lib/api/refresh", () => ({
  refreshAccessToken: () => refreshAccessToken(),
  isRefreshRateLimited: () => isRefreshRateLimitedMock(),
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
    isRefreshRateLimitedMock.mockReturnValue(false);
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

  // Cooldown sau 429 RATE_LIMITED (xem lib/api/refresh.ts). Hook là nguồn phát
  // request nền lớn nhất — onWake gắn cả visibilitychange lẫn focus — nên nó
  // phải im lặng hẳn khi bucket đã cạn, và KHÔNG được đụng vào timestamp.
  it("đang cooldown → không gọi refresh và không ghi timestamp", async () => {
    isRefreshRateLimitedMock.mockReturnValue(true);

    renderHook(() => useProactiveTokenRefresh(true));
    await tick();

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("đang cooldown → KHÔNG xoá timestamp đang có (giữ throttle 12')", async () => {
    const prev = String(Date.now() - 20 * 60_000); // đủ cũ để bình thường sẽ refresh
    localStorage.setItem(KEY, prev);
    isRefreshRateLimitedMock.mockReturnValue(true);

    renderHook(() => useProactiveTokenRefresh(true));
    await tick();

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(localStorage.getItem(KEY)).toBe(prev);
  });

  // Race thật: lúc pre-check chưa bị chặn, nhưng chính request này ăn 429 và
  // bật cooldown. Nếu vẫn rollback theo CAS thì throttle 12' bị xoá đúng lúc
  // bucket vừa cạn, và mỗi lần alt-tab lại phát thêm một request.
  it("refresh trả 429 (cooldown bật sau đó) → GIỮ timestamp, không rollback", async () => {
    const prev = String(Date.now() - 20 * 60_000);
    localStorage.setItem(KEY, prev);
    isRefreshRateLimitedMock.mockReturnValueOnce(false); // pre-check: chưa bị chặn
    refreshAccessToken.mockImplementation(() => {
      isRefreshRateLimitedMock.mockReturnValue(true); // 429 → cooldown bật
      return Promise.reject(new Error("429"));
    });

    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    await tick();

    // Slot đã được claim trước await; KHÔNG rollback về prev.
    expect(localStorage.getItem(KEY)).not.toBe(prev);
    expect(localStorage.getItem(KEY)).not.toBeNull();
  });
});
