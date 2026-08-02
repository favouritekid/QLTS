// @vitest-environment jsdom
/**
 * `LoginSessionResetGate` — trang đăng nhập phải DỌN state phiên cũ trước khi
 * chạm vào `useAuth()`.
 *
 * Vì sao cần một cổng riêng thay vì gọi dọn dẹp trong `LoginForm`:
 * `auth.store` giữ `user` trong localStorage và đặt `isAuthenticated = !!user`
 * lúc rehydrate, còn `useAuth()` có `useQuery(["auth","me"], { enabled:
 * isAuthenticated })`. Nên chỉ cần `useAuth()` chạy MỘT lần với store chưa dọn
 * là `/users/me` bay đi bằng danh tính của phiên vừa chết — request đó 401 và
 * đi thẳng vào đường refresh mà nhánh `reauth` vừa cố tránh.
 *
 * Test render component THẬT với `QueryClientProvider` thật và theo dõi
 * `api.get`. Mock `useAuth` sẽ làm mọi ca dưới đây vô nghĩa: chính cái hook đó
 * là thứ đang được kiểm.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Chỉ mock HẠ TẦNG router (jsdom không có app router). `useAuth` — thứ đang
// được kiểm — vẫn là hàng thật.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/login",
}));

import { api } from "@/lib/api/client";
import { isApiLoggedOut, setApiLoggedOut } from "@/lib/api/session-flags";
import { useAuthStore } from "@/lib/stores/auth.store";
import { acquireRefreshLock } from "@/lib/api/refresh-coordination/lock";
import { selectJournalStore } from "@/lib/api/refresh-coordination/storage";
import {
  installFakeIdb,
  removeWebLocks,
} from "@/lib/api/refresh-coordination/test-harness";
import type { User } from "@/types/api.types";

import { LoginForm } from "./LoginForm";

const T0 = 1_800_000_000_000;

/** Người dùng của phiên CŨ, còn sót trong localStorage. */
const staleUser = {
  id: 25,
  username: "officer1",
  email: "officer1@example.com",
  role: "officer",
  is_active: true,
} as unknown as User;

function renderGate() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LoginForm />
    </QueryClientProvider>,
  );
}

function setUrl(search: string) {
  window.history.replaceState({}, "", `/login${search}`);
}

/** Nhật ký `ambiguous` — bản ghi đang CẤM mọi tab POST refresh. */
async function seedAmbiguousJournal() {
  const acquired = await acquireRefreshLock("gen-1", T0);
  if (acquired.status !== "acquired") throw new Error("không dựng được nhật ký");
  await acquired.handle.update({ phase: "in-flight" });
  await acquired.handle.update({ resultKind: "ambiguous" });
  await acquired.handle.release();
}

beforeEach(() => {
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  setApiLoggedOut(false);
  setUrl("");
  useAuthStore.setState({ user: staleUser, isAuthenticated: true });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LoginSessionResetGate — dọn trước, render sau", () => {
  it("KHÔNG phát /users/me dù store còn user của phiên cũ", async () => {
    const get = vi.spyOn(api, "get");

    renderGate();
    // Chờ tới khi form thật đã hiện — nếu request rò rỉ thì nó đã đi trong
    // khoảng này.
    await waitFor(() => expect(screen.getByLabelText(/tên đăng nhập/i)).toBeTruthy());

    const meCalls = get.mock.calls.filter((call) =>
      String(call[0]).includes("/users/me"),
    );
    expect(meCalls).toEqual([]);
  });

  it("dọn `user` khỏi store và bật cờ chặn request", async () => {
    renderGate();
    await waitFor(() => expect(screen.getByLabelText(/tên đăng nhập/i)).toBeTruthy());

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(isApiLoggedOut()).toBe(true);
  });
});

describe("LoginSessionResetGate — nhật ký refresh có vòng đời RIÊNG", () => {
  /**
   * Đây là chỗ dễ gộp nhầm nhất: "dọn state client" và "dọn nhật ký refresh"
   * nghe như một việc, nhưng `reauth` CỐ Ý giữ cookie refresh — nên một bản ghi
   * `ambiguous` đang cấm POST phải sống tới khi đăng nhập thành công. Xoá nó ở
   * đây là mở lại đúng cánh cửa mà fail-closed vừa đóng.
   */
  it("?reauth=true ⇒ GIỮ nhật ký ambiguous", async () => {
    await seedAmbiguousJournal();
    setUrl("?reauth=true");

    renderGate();
    await waitFor(() => expect(screen.getByLabelText(/tên đăng nhập/i)).toBeTruthy());

    const store = await selectJournalStore();
    await waitFor(async () => {
      expect(await store!.read()).not.toBeNull();
    });
    // Và state client vẫn phải được dọn — hai việc độc lập nhau.
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("?force_login=true ⇒ XOÁ nhật ký (cookie đã thực sự bị xoá)", async () => {
    await seedAmbiguousJournal();
    setUrl("?force_login=true");

    renderGate();
    await waitFor(() => expect(screen.getByLabelText(/tên đăng nhập/i)).toBeTruthy());

    const store = await selectJournalStore();
    await waitFor(async () => {
      expect(await store!.read()).toBeNull();
    });
  });

  it("vào /login thẳng (không cờ) ⇒ GIỮ nhật ký", async () => {
    await seedAmbiguousJournal();
    setUrl("");

    renderGate();
    await waitFor(() => expect(screen.getByLabelText(/tên đăng nhập/i)).toBeTruthy());

    const store = await selectJournalStore();
    await waitFor(async () => {
      expect(await store!.read()).not.toBeNull();
    });
  });
});
