/**
 * F131 — 403 PASSWORD_CHANGE_REQUIRED trong Server Component đi về form.
 *
 * Trước bản vá: `detail` là object nên thông điệp thành `API Error (403):
 * [object Object]` và trang rơi vào error boundary — không lối nào tới form.
 * `redirect` được mock để NÉM như Next thật (NEXT_REDIRECT): ca kiểm nó không
 * bị nuốt trên đường ra khỏi `serverFetch`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const redirectMock = vi.hoisted(() =>
  vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
);

vi.mock("next/headers", () => ({
  cookies: async () => ({ toString: () => "", get: () => undefined }),
  headers: async () => ({ get: () => null }),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
  unstable_rethrow: (error: unknown) => {
    throw error;
  },
}));

const fetchMock = vi.fn();

function respond(status: number, body: string) {
  fetchMock.mockResolvedValue({ ok: false, status, text: async () => body });
}

beforeEach(() => {
  vi.stubEnv("BACKEND_INTERNAL_URL", "http://backend:8000");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  redirectMock.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

async function call() {
  const { serverFetch } = await import("./server");
  return serverFetch("/api/leads/42");
}

describe("serverFetch 403", () => {
  it("PASSWORD_CHANGE_REQUIRED → redirect tới /settings?forced=true, lệnh redirect không bị nuốt", async () => {
    respond(
      403,
      JSON.stringify({
        detail: { code: "PASSWORD_CHANGE_REQUIRED", message: "x" },
        error_code: "HTTP_403",
      }),
    );

    await expect(call()).rejects.toThrow("NEXT_REDIRECT:/settings?forced=true");
    expect(redirectMock).toHaveBeenCalledTimes(1);
  });

  it("403 khác → KHÔNG redirect, giữ thông điệp lỗi cũ", async () => {
    respond(403, JSON.stringify({ detail: "Not enough permissions" }));

    await expect(call()).rejects.toThrow("API Error (403): Not enough permissions");
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("403 thân không phải JSON → KHÔNG redirect", async () => {
    respond(403, "<html>forbidden</html>");

    await expect(call()).rejects.toThrow("API Error (403): <html>forbidden</html>");
    expect(redirectMock).not.toHaveBeenCalled();
  });
});
