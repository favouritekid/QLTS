/**
 * Tests cho useProactiveTokenRefresh.
 *
 * Trọng tâm: visible-only guard, cross-tab localStorage guard, không
 * logout khi fail + rollback CAS.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const refreshAccessToken = vi.fn();
// Chỉ thay việc GỌI refresh; `RefreshFailure` và `isRefreshFailure` giữ bản
// THẬT. Hook phân biệt "rate limit" bằng chính `outcome` của lỗi, nên mock lại
// classifier là test một hàm giả — và đó cũng là cách bản cũ bỏ sót: nó mock
// đúng hàm trạng thái cooldown nay đã không còn tồn tại.
vi.mock("@/lib/api/refresh", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api/refresh")>();
  return { ...actual, refreshAccessToken: () => refreshAccessToken() };
});
const isApiLoggedOutMock = vi.fn(() => false);
vi.mock("@/lib/api/client", () => ({
  isApiLoggedOut: () => isApiLoggedOutMock(),
}));

import { RefreshFailure } from "@/lib/api/refresh";
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

  /**
   * ⚠️ Contract ĐỔI ở `2e`: hook chỉ ĐỌC mốc throttle, nơi duy nhất GHI là
   * `refresh.ts` — và chỉ sau khi POST thành công.
   *
   * Mốc ấy biểu diễn "lần làm mới THÀNH CÔNG gần nhất". Bản cũ ghi trước
   * `await` để thu hẹp cửa sổ đua cross-tab; nay cửa sổ đó do nhật ký dùng chung
   * lo, nên ghi sớm chỉ còn tác dụng phụ — một lần thử HỎNG cũng đặt mốc và
   * hoãn mọi tab 12 phút vì một lần refresh chưa từng thành công.
   */
  it("refresh on mount khi visible + chưa có mốc; hook KHÔNG tự ghi mốc", async () => {
    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem(KEY)).toBeNull();
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

  /**
   * ⚠️ Ba ca cooldown cũ đã ĐỔI BẢN CHẤT, không phải bị bỏ.
   *
   * Trước đây hook tự hỏi một hàm trạng thái cooldown trước khi gọi — một nguồn
   * cooldown thứ hai, sống song song với nguồn trong `refresh.ts`. Nay cooldown
   * nằm trong nhật ký dùng chung giữa các tab, và `refreshAccessToken()` tự
   * dừng trước khi chạm mạng khi chưa tới `retryAt`. Hook không còn kiểm gì
   * trước; nó chỉ ĐỌC `outcome` của lỗi để quyết định có rollback timestamp hay
   * không.
   *
   * Hai nguồn cooldown là hai thứ sẽ trôi lệch nhau — đó là lý do bỏ cái ở hook.
   */
  it("refresh HỎNG → mốc cũ còn NGUYÊN, hook không đụng vào", async () => {
    const prev = String(Date.now() - 20 * 60_000); // đủ cũ để bình thường sẽ refresh
    localStorage.setItem(KEY, prev);
    refreshAccessToken.mockRejectedValue(
      new RefreshFailure({ kind: "safe-retryable", retryAt: Date.now() + 60_000 }),
    );

    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    await tick();

    // `2e` gỡ cả rollback lẫn claim-slot: hook không ghi gì nên cũng chẳng có gì
    // để hoàn tác. Bất biến cũ vẫn được giữ — và giữ CHẶT hơn: sau một
    // `safe-retryable`, mốc throttle KHÔNG bị xoá, nên `onWake` (gắn cả
    // `visibilitychange` lẫn `focus`) không biến mười lần alt-tab thành mười
    // POST nữa vào đúng cái xô vừa cạn.
    expect(localStorage.getItem(KEY)).toBe(prev);
  });

  it.each([
    ["ambiguous", { kind: "ambiguous", reason: "network" } as const],
    ["nonterminal-stop", { kind: "nonterminal-stop", status: 404 } as const],
    ["terminal", { kind: "terminal", status: 401 } as const],
  ])(
    "refresh trả `%s` → rollback timestamp (cho phép thử lại sớm)",
    async (_label, outcome) => {
      const prev = String(Date.now() - 20 * 60_000);
      localStorage.setItem(KEY, prev);
      refreshAccessToken.mockRejectedValue(new RefreshFailure(outcome));

      renderHook(() => useProactiveTokenRefresh(true));
      await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
      await tick();

      // Chỉ `safe-retryable` mới phải giữ throttle; các lỗi khác không liên
      // quan tới quota nên khôi phục mốc cũ là đúng.
      expect(localStorage.getItem(KEY)).toBe(prev);
    },
  );

  it("hook KHÔNG tự đăng xuất dù lỗi là terminal", async () => {
    refreshAccessToken.mockRejectedValue(
      new RefreshFailure({ kind: "terminal", status: 401 }),
    );

    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    await tick();

    // Quyết định đăng xuất thuộc về reactive 401 của request kế tiếp, không
    // thuộc một hook chạy nền — nếu không, một lỗi nền im lặng sẽ đá người
    // dùng ra giữa lúc họ đang nhập liệu.
    expect(isApiLoggedOutMock).not.toHaveBeenCalledWith(true);
  });
});
