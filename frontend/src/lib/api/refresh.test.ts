/**
 * Tests cho refreshAccessToken — single-flight refresh.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("axios", () => {
  const post = vi.fn();
  return { default: { post }, post };
});

import axios from "axios";
import { refreshAccessToken } from "./refresh";

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
