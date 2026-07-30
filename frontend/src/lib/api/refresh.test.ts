/**
 * Tests cho refreshAccessToken — single-flight refresh.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("axios", () => {
  const post = vi.fn();
  // Giữ đúng hành vi của axios thật: isAxiosError chỉ kiểm cờ trên object.
  const isAxiosError = (e: unknown) =>
    !!(e as { isAxiosError?: boolean } | null | undefined)?.isAxiosError;
  return { default: { post, isAxiosError }, post, isAxiosError };
});

import axios from "axios";
import { refreshAccessToken, shouldLogoutAfterRefreshFailure } from "./refresh";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockPost = axios.post as any;

describe("refreshAccessToken — single-flight", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("nhiều lời gọi đồng thời → chỉ 1 POST /api/auth/refresh", async () => {
    mockPost.mockResolvedValue({ data: {} });

    const callers = [
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ];
    await Promise.all(callers);

    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith(
      expect.stringContaining("/api/auth/refresh"),
      {},
      expect.objectContaining({ withCredentials: true }),
    );
  });

  it("fail → mọi caller reject + mutex reset (lần sau phát POST mới)", async () => {
    mockPost.mockRejectedValueOnce(new Error("boom"));

    const callers = [refreshAccessToken(), refreshAccessToken()];
    await expect(Promise.all(callers)).rejects.toThrow("boom");

    // Mutex đã reset → lời gọi mới tạo POST mới (không bị kẹt isRefreshing).
    mockPost.mockResolvedValueOnce({ data: {} });
    await refreshAccessToken();
    expect(mockPost).toHaveBeenCalledTimes(2);
  });
});

describe("shouldLogoutAfterRefreshFailure", () => {
  function axiosErrorWithStatus(status?: number) {
    return {
      isAxiosError: true,
      message: "Request failed",
      response: status === undefined ? undefined : { status, data: {} },
    };
  }

  it("401 → logout (refresh token không còn hiệu lực)", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(401))).toBe(true);
  });

  it("403 → logout", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(403))).toBe(true);
  });

  // Regression: audit prod 2026-07-30 — 86/270 request /auth/refresh trong 24h
  // bị 429 (limit 20/giờ theo IP, cả trường dùng chung một IP NAT). Một lần 429
  // từng đủ để đá officer về /login và mất form đang nhập.
  it("429 → GIỮ phiên", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(429))).toBe(false);
  });

  it.each([500, 502, 503, 504])("%i → GIỮ phiên", (status) => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(status))).toBe(false);
  });

  it("không có response (mạng đứt / timeout / CORS) → GIỮ phiên", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(undefined))).toBe(false);
  });

  it("lỗi không phải Axios → GIỮ phiên", () => {
    expect(shouldLogoutAfterRefreshFailure(new Error("boom"))).toBe(false);
    expect(shouldLogoutAfterRefreshFailure(undefined)).toBe(false);
  });
});
