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
  function axiosErrorWithStatus(status?: number, data: Record<string, unknown> = {}) {
    return {
      isAxiosError: true,
      message: "Request failed",
      response: status === undefined ? undefined : { status, data },
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
  it("429 RATE_LIMITED (slowapi) → GIỮ phiên", () => {
    const err = axiosErrorWithStatus(429, { error_code: "RATE_LIMITED" });
    expect(shouldLogoutAfterRefreshFailure(err)).toBe(false);
  });

  // Cổng M4: lần lỗi chạm ngưỡng đã invalidate_all_sessions rồi trả 401; các
  // lần sau mới nhận 429 này. Phiên đã chết → giữ phiên sẽ tạo vòng lặp
  // 401→429→401 mà UI vẫn báo đang đăng nhập.
  it("429 REFRESH_ABUSE_LOCKED (M4) → logout", () => {
    const err = axiosErrorWithStatus(429, { error_code: "REFRESH_ABUSE_LOCKED" });
    expect(shouldLogoutAfterRefreshFailure(err)).toBe(true);
  });

  it("429 thiếu error_code → logout (fail-safe)", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(429))).toBe(true);
  });

  it("429 mã lạ → logout (fail-safe)", () => {
    const err = axiosErrorWithStatus(429, { error_code: "HTTP_429" });
    expect(shouldLogoutAfterRefreshFailure(err)).toBe(true);
  });

  it.each([500, 502, 503, 504])("%i → GIỮ phiên", (status) => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(status))).toBe(false);
  });

  it("không có response (mạng đứt / timeout / CORS) → GIỮ phiên", () => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(undefined))).toBe(false);
  });

  // Liệt kê xuôi (chỉ 401/403/429) sẽ để lọt các mã này và giữ phiên vĩnh viễn
  // với access token đã chết — vd sai NEXT_PUBLIC_API_URL hoặc đổi route proxy.
  it.each([400, 404, 410, 422])("%i (4xx khác) → logout", (status) => {
    expect(shouldLogoutAfterRefreshFailure(axiosErrorWithStatus(status))).toBe(true);
  });

  it("lỗi không phải Axios → GIỮ phiên", () => {
    expect(shouldLogoutAfterRefreshFailure(new Error("boom"))).toBe(false);
    expect(shouldLogoutAfterRefreshFailure(undefined)).toBe(false);
  });
});
