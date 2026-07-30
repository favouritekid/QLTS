// @vitest-environment jsdom
/**
 * Runtime test cho điểm quyết định logout THỨ HAI (`useAuth`).
 *
 * Vì sao phải chạy hook thật thay vì chỉ test marker/detector: interceptor giữ
 * phiên khi refresh hỏng tạm thời (429 RATE_LIMITED / 5xx / mạng đứt) và reject
 * chính lỗi 401 gốc — nhưng query `/users/me` trong `useAuth` cũng tự đăng xuất
 * trên mọi 401. Nếu chỉ test `markSessionKeptAlive`/`isSessionKeptAliveError`
 * thì xoá hẳn nhánh mới trong `useAuth` vẫn xanh cả suite, và officer vẫn bị
 * đá về /login đúng tình huống vừa được quyết định là tạm thời.
 *
 * Ở đây khẳng định 3 tác dụng phụ CÓ THẬT: `logout()` của store,
 * `queryClient.clear()`, và `router.push(/login)`.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { AxiosError } from "axios";

import { markSessionKeptAlive } from "@/lib/api/refresh";

const logoutStore = vi.hoisted(() => vi.fn());
const routerPush = vi.hoisted(() => vi.fn());
const queryClientClear = vi.hoisted(() => vi.fn());
const queryState = vi.hoisted(() => ({
  data: undefined as unknown,
  isError: false,
  error: undefined as unknown,
  isLoading: false,
  isFetching: false,
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => queryState,
  useMutation: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useQueryClient: () => ({
    clear: queryClientClear,
    invalidateQueries: vi.fn(),
    setQueryData: vi.fn(),
    removeQueries: vi.fn(),
    cancelQueries: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

const storeState = vi.hoisted(() => ({
  user: { id: 1, username: "officer" },
  isAuthenticated: true,
  setAuth: vi.fn(),
  logout: logoutStore,
  setUser: vi.fn(),
}));

vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: Object.assign(
    (selector: (s: typeof storeState) => unknown) => selector(storeState),
    { getState: () => storeState },
  ),
}));

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  setApiLoggedOut: vi.fn(),
  isApiLoggedOut: () => false,
}));

vi.mock("@/components/layouts/SecurityBanner", () => ({
  triggerBannerCheck: vi.fn(),
  triggerSuspiciousLoginBanner: vi.fn(),
}));

import { useAuth } from "./useAuth";

function unauthorizedError(): AxiosError {
  return {
    isAxiosError: true,
    name: "AxiosError",
    message: "Unauthorized",
    response: { status: 401, data: {}, statusText: "", headers: {}, config: {} },
    config: {},
    toJSON: () => ({}),
  } as unknown as AxiosError;
}

describe("useAuth — 401 và quyết định đăng xuất", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryState.data = undefined;
    queryState.isError = false;
    queryState.error = undefined;
    storeState.isAuthenticated = true;
  });

  it("401 THƯỜNG → vẫn logout: clear store, clear cache, đẩy về /login", () => {
    queryState.isError = true;
    queryState.error = unauthorizedError();

    renderHook(() => useAuth());

    expect(logoutStore).toHaveBeenCalled();
    expect(queryClientClear).toHaveBeenCalled();
    expect(routerPush).toHaveBeenCalledWith(expect.stringContaining("/login"));
  });

  // Regression: interceptor đã cố ý giữ phiên (429 RATE_LIMITED / 5xx / mạng
  // đứt) và reject chính lỗi 401 gốc kèm cờ.
  it("401 CÓ CỜ giữ phiên → KHÔNG logout, KHÔNG clear cache, KHÔNG redirect", () => {
    queryState.isError = true;
    queryState.error = markSessionKeptAlive(unauthorizedError());

    renderHook(() => useAuth());

    expect(logoutStore).not.toHaveBeenCalled();
    expect(queryClientClear).not.toHaveBeenCalled();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it("401 CÓ CỜ giữ phiên → isAuthenticated vẫn true", () => {
    queryState.isError = true;
    queryState.error = markSessionKeptAlive(unauthorizedError());

    const { result } = renderHook(() => useAuth());

    // Trả false ở đây sẽ mâu thuẫn với chính quyết định "giữ phiên".
    expect(result.current.isAuthenticated).toBe(true);
  });

  it("401 THƯỜNG → isAuthenticated false", () => {
    queryState.isError = true;
    queryState.error = unauthorizedError();

    const { result } = renderHook(() => useAuth());

    expect(result.current.isAuthenticated).toBe(false);
  });
});
