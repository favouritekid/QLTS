/**
 * Lock-in test cho WIRING của interceptor 401 — không chỉ cho predicate.
 *
 * Vì sao cần: hành vi gây sự cố nằm ở chỗ interceptor QUYẾT ĐỊNH logout, chứ
 * không ở `shouldLogoutAfterRefreshFailure`. Nếu chỉ test predicate thì đảo
 * một dấu `!` trong client.ts vẫn xanh toàn bộ suite, và bug prod quay lại
 * nguyên trạng. Ở đây test chạy đúng handler mà `client.ts` đăng ký với axios,
 * dùng predicate THẬT, và khẳng định 3 tác dụng phụ có thật:
 * `setApiLoggedOut`, `window.location.href`, và request gốc có retry hay không.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Handler mà client.ts đăng ký ở import time — capture để gọi trực tiếp.
// `vi.hoisted` vì factory của `vi.mock` được hoist lên trước mọi khai báo
// thường; một `let` ở đây sẽ vướng TDZ khi factory chạy.
const captured = vi.hoisted(() => ({
  onError: undefined as ((error: unknown) => Promise<unknown>) | undefined,
}));

vi.mock("axios", () => {
  const isAxiosError = (e: unknown) =>
    !!(e as { isAxiosError?: boolean } | null | undefined)?.isAxiosError;

  const instance = vi.fn(() => Promise.resolve({ data: "retried" })) as unknown as {
    (config: unknown): Promise<unknown>;
    interceptors: {
      request: { use: ReturnType<typeof vi.fn> };
      response: { use: ReturnType<typeof vi.fn> };
    };
    defaults: { headers: { common: Record<string, unknown> } };
  };
  instance.interceptors = {
    request: { use: vi.fn() },
    response: {
      use: vi.fn((_onSuccess: unknown, onError: (error: unknown) => Promise<unknown>) => {
        captured.onError = onError;
      }),
    },
  };
  instance.defaults = { headers: { common: {} } };

  const mockAxios = {
    create: vi.fn(() => instance),
    post: vi.fn(),
    isAxiosError,
    Cancel: class Cancel extends Error {},
  };
  return { default: mockAxios, ...mockAxios };
});

// Chỉ mock việc GỌI refresh; `shouldLogoutAfterRefreshFailure` giữ bản THẬT để
// test khoá được cả phân loại lẫn wiring.
vi.mock("./refresh", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./refresh")>();
  return { ...actual, refreshAccessToken: vi.fn() };
});

// Store thật khởi tạo zustand + persist; nhánh logout chỉ cần nó không nổ.
vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: { getState: () => ({ logout: vi.fn() }) },
}));

import { refreshAccessToken } from "./refresh";
import { isApiLoggedOut, setApiLoggedOut } from "./client";

const mockedRefresh = vi.mocked(refreshAccessToken);

function requestError401() {
  return {
    isAxiosError: true,
    message: "Unauthorized",
    response: { status: 401, data: {} },
    config: { url: "/api/admissions/611", headers: {} },
  };
}

function refreshFailure(status: number, data: Record<string, unknown> = {}) {
  return {
    isAxiosError: true,
    message: "Refresh failed",
    response: { status, data },
    config: { url: "/api/auth/refresh", headers: {} },
  };
}

describe("interceptor 401 — quyết định logout khi refresh thất bại", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setApiLoggedOut(false);
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { pathname: "/admissions/611", search: "", href: "" },
    });
  });

  afterEach(() => {
    setApiLoggedOut(false);
  });

  it("handler đã được đăng ký (nếu không, mọi assert dưới đây là vô nghĩa)", () => {
    expect(captured.onError).toBeTypeOf("function");
  });

  // Ca gây sự cố prod: 32% request /auth/refresh bị slowapi chặn.
  it("429 RATE_LIMITED → GIỮ phiên, không redirect, không retry request gốc", async () => {
    mockedRefresh.mockRejectedValueOnce(refreshFailure(429, { error_code: "RATE_LIMITED" }));

    await expect(captured.onError!(requestError401())).rejects.toMatchObject({
      response: { status: 429 },
    });

    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  });

  it("429 REFRESH_ABUSE_LOCKED → logout + redirect /login (session đã bị thu hồi)", async () => {
    mockedRefresh.mockRejectedValueOnce(
      refreshFailure(429, { error_code: "REFRESH_ABUSE_LOCKED" }),
    );

    await expect(captured.onError!(requestError401())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
  });

  it("429 thiếu error_code → logout (fail-safe)", async () => {
    mockedRefresh.mockRejectedValueOnce(refreshFailure(429));

    await expect(captured.onError!(requestError401())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
  });

  it("401 từ /auth/refresh → logout", async () => {
    mockedRefresh.mockRejectedValueOnce(refreshFailure(401));

    await expect(captured.onError!(requestError401())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
  });

  // Lỗi không có `response` sẽ lọt qua retry predicate ở providers.tsx (chỉ
  // chặn 4xx CÓ response) → phải reject lỗi GỐC 401 để React Query không retry
  // 3 lần, mỗi lần lại bắn thêm một POST /auth/refresh.
  it("mạng đứt khi refresh → giữ phiên và reject lỗi GỐC 401 (chặn retry storm)", async () => {
    mockedRefresh.mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" });

    await expect(captured.onError!(requestError401())).rejects.toMatchObject({
      response: { status: 401 },
    });

    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  });

  it("refresh thành công → retry request gốc, không logout", async () => {
    mockedRefresh.mockResolvedValueOnce(undefined);

    await expect(captured.onError!(requestError401())).resolves.toMatchObject({
      data: "retried",
    });

    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  });
});
