// @vitest-environment jsdom
/**
 * Nửa SAU của vòng đời nhật ký refresh — chạy qua CALLER THẬT.
 *
 * `reauth` cố ý giữ một bản ghi `ambiguous` (nó đang cấm mọi tab POST refresh).
 * Lối thoát đúng cho bản ghi đó là **đăng nhập thành công**: lúc ấy cookie/CSRF
 * mới đã được áp nên nó hết ý nghĩa. Nếu không caller nào phát transition thì
 * bản ghi chỉ biến mất nhờ lần refresh sau tự supersede theo generation mới —
 * đường phục hồi dự phòng, không phải vòng đời đã thiết kế.
 *
 * ⚠️ Test này KHÔNG mock `@tanstack/react-query` (khác
 * `useAuth.session-kept-alive.test.tsx`): mock nó thì mutation không chạy và
 * `onSuccess` — nơi chứa toàn bộ thứ đang được kiểm — không bao giờ nổ. Ở đây
 * chỉ mock hạ tầng ngoài React (router, toast, banner, axios).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const apiPost = vi.hoisted(() => vi.fn());
const apiGet = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/login",
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

vi.mock("@/components/layouts/SecurityBanner", () => ({
  triggerBannerCheck: vi.fn(),
  triggerSuspiciousLoginBanner: vi.fn(),
  SecurityBanner: () => null,
}));

// Chỉ thay lớp mạng. `setApiLoggedOut` thật (nằm ở `session-flags`) vẫn được
// `clearClientAuthState` dùng, nên thứ tự chặn-request vẫn là hàng thật.
vi.mock("@/lib/api/client", () => ({
  api: { get: apiGet, post: apiPost },
  setApiLoggedOut: vi.fn(),
  isApiLoggedOut: () => false,
}));

import { acquireRefreshLock } from "@/lib/api/refresh-coordination/lock";
import { selectJournalStore } from "@/lib/api/refresh-coordination/storage";
import {
  installFakeIdb,
  removeWebLocks,
} from "@/lib/api/refresh-coordination/test-harness";
import { useAuthStore } from "@/lib/stores/auth.store";

import { useAuth } from "./useAuth";

const T0 = 1_800_000_000_000;

const loggedInUser = {
  id: 25,
  username: "officer1",
  role: "officer",
  password_reset_required: false,
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

/** Nhật ký `ambiguous`: bản ghi đang CẤM mọi tab POST refresh. */
async function seedAmbiguousJournal() {
  const acquired = await acquireRefreshLock("gen-1", T0);
  if (acquired.status !== "acquired") throw new Error("không dựng được nhật ký");
  await acquired.handle.update({ phase: "in-flight" });
  await acquired.handle.update({ resultKind: "ambiguous" });
  await acquired.handle.release();
}

async function readJournal() {
  const store = await selectJournalStore();
  return store!.read();
}

beforeEach(() => {
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  apiPost.mockReset();
  apiGet.mockReset();
  useAuthStore.setState({ user: null, isAuthenticated: false });
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { href: "", search: "", pathname: "/login", replace: vi.fn() },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("đăng nhập thành công ⇒ nhật ký được dọn", () => {
  it("đăng nhập bằng mật khẩu", async () => {
    await seedAmbiguousJournal();
    apiPost.mockResolvedValue({ data: { user: loggedInUser } });

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.login({ username: "officer1", password: "x" });

    await waitFor(async () => expect(await readJournal()).toBeNull());
  });

  // Lối đăng nhập thành công THỨ HAI. Bỏ sót ở đây thì mọi tài khoản bật MFA
  // rơi vào đúng ca mà `login-success` sinh ra để đóng.
  it("xác minh MFA", async () => {
    await seedAmbiguousJournal();
    apiPost.mockResolvedValue({ data: { user: loggedInUser } });

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.verifyMfa({ mfa_token: "tok", code: "123456" });

    await waitFor(async () => expect(await readJournal()).toBeNull());
  });

  it("đăng nhập HỎNG ⇒ nhật ký còn nguyên", async () => {
    await seedAmbiguousJournal();
    apiPost.mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: {} },
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.login({ username: "officer1", password: "sai" });

    await waitFor(() => expect(result.current.loginError).toBeTruthy());
    expect(await readJournal()).not.toBeNull();
  });

  // MFA chưa xong thì CHƯA phải đăng nhập thành công: backend mới trả
  // `mfa_required`, cookie phiên chưa được cấp.
  it("mới qua bước mật khẩu, còn chờ MFA ⇒ nhật ký còn nguyên", async () => {
    await seedAmbiguousJournal();
    apiPost.mockResolvedValue({
      data: { mfa_required: true, mfa_token: "tok" },
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.login({ username: "officer1", password: "x" });

    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    expect(await readJournal()).not.toBeNull();
  });
});

describe("đăng xuất — chỉ backend XÁC NHẬN mới được dọn", () => {
  it("backend trả 200 ⇒ nhật ký mất", async () => {
    await seedAmbiguousJournal();
    apiPost.mockResolvedValue({ data: {} });

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.logout();

    await waitFor(async () => expect(await readJournal()).toBeNull());
  });

  /**
   * Logout hỏng ⇒ KHÔNG biết phiên còn hay mất. Xoá nhật ký lúc này là mở
   * đường cho tab khác POST lại một refresh token mà server có thể đã rotate —
   * đúng hành vi bị tính là reuse.
   */
  it("gọi backend hỏng ⇒ nhật ký còn nguyên", async () => {
    await seedAmbiguousJournal();
    apiPost.mockRejectedValue(new Error("mạng đứt"));

    const { result } = renderHook(() => useAuth(), { wrapper });
    result.current.logout();

    // Chờ tới khi luồng logout đã chạy hết (nó luôn hard-redirect ở cuối).
    await waitFor(() => expect(window.location.href).toBe("/login"));
    expect(await readJournal()).not.toBeNull();
  });
});
