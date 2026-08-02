// @vitest-environment jsdom
/**
 * Storage bị chặn KHÔNG được giết hook proactive.
 *
 * `maybeRefresh()` được gọi bằng `void` ở ba chỗ (interval, wake, mount), nên
 * một lần ném từ `localStorage` không thành lỗi thấy được — nó thành
 * **unhandled rejection**, và hook im lặng chết trước cả khi kịp gọi refresh.
 * Người dùng ở private mode / tắt cookie mất hẳn refresh chủ động mà không có
 * dấu hiệu nào.
 *
 * ⚖️ Và chiều fail ở đây NGƯỢC với nhật ký: throttle chỉ là tối ưu, nên hỏng
 * thì **vẫn phải refresh** (fail-open). Nhật ký mới là hàng rào, và nó
 * fail-closed riêng.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const refreshAccessToken = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/refresh", () => ({ refreshAccessToken }));

import { useProactiveTokenRefresh } from "./useProactiveTokenRefresh";
import { setApiLoggedOut } from "@/lib/api/session-flags";

/** Bắt mọi unhandled rejection trong lúc test chạy. */
function watchUnhandled() {
  const seen: unknown[] = [];
  const onUnhandled = (event: PromiseRejectionEvent) => {
    seen.push(event.reason);
    event.preventDefault();
  };
  window.addEventListener("unhandledrejection", onUnhandled);
  const onNode = (reason: unknown) => seen.push(reason);
  process.on("unhandledRejection", onNode);
  return {
    seen,
    stop: () => {
      window.removeEventListener("unhandledrejection", onUnhandled);
      process.off("unhandledRejection", onNode);
    },
  };
}

/**
 * Storage bị chặn hoàn toàn — mọi thao tác đều ném, kể cả ĐỌC.
 *
 * ⚠️ Phải THAY CẢ object `localStorage`, không `vi.spyOn` từng phương thức:
 * `localStorage` của jsdom là một accessor trả về đối tượng nội bộ, nên spy lên
 * phương thức của nó **không có tác dụng** — và test sẽ xanh trong khi chẳng
 * chặn gì cả (đã dính đúng bẫy này: gỡ hẳn `try/catch` mà 6/6 vẫn xanh).
 */
function blockStorage() {
  const err = () => {
    const e = new Error("The operation is insecure.");
    e.name = "SecurityError";
    throw e;
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    get: () => ({
      getItem: err,
      setItem: err,
      removeItem: err,
      clear: err,
      key: err,
      length: 0,
    }),
  });

  // Tự kiểm: nếu dòng này KHÔNG ném thì mọi ca dưới đây vô nghĩa.
  expect(() => window.localStorage.getItem("probe")).toThrow();
}

/** Bản gốc để trả lại sau mỗi ca — `blockStorage()` thay hẳn accessor. */
const realLocalStorage = Object.getOwnPropertyDescriptor(window, "localStorage");

beforeEach(() => {
  if (realLocalStorage) {
    Object.defineProperty(window, "localStorage", realLocalStorage);
  }
  window.localStorage.clear();
  refreshAccessToken.mockReset();
  refreshAccessToken.mockResolvedValue(undefined);
  setApiLoggedOut(false);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useProactiveTokenRefresh — storage bị chặn", () => {
  it("KHÔNG sinh unhandled rejection nào", async () => {
    const watcher = watchUnhandled();
    blockStorage();

    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalled());
    // Cho vòng lặp sự kiện chạy hết để rejection kịp nổi lên.
    await new Promise((r) => setTimeout(r, 50));

    watcher.stop();
    expect(watcher.seen).toEqual([]);
  });

  // Fail-OPEN: đọc mốc hỏng ⇒ coi như chưa từng refresh ⇒ VẪN refresh.
  it("vẫn gọi refresh dù không đọc/ghi được mốc throttle", async () => {
    blockStorage();

    renderHook(() => useProactiveTokenRefresh(true));

    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
  });

  // Ngược lại: mốc đọc được và còn mới ⇒ tôn trọng throttle.
  it("mốc vừa ghi (còn mới) ⇒ KHÔNG refresh", async () => {
    window.localStorage.setItem("qlts_last_refresh_at", String(Date.now()));

    renderHook(() => useProactiveTokenRefresh(true));
    await new Promise((r) => setTimeout(r, 60));

    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  /**
   * Mốc nằm ở TƯƠNG LAI (lệch đồng hồ / bị sửa tay) không được kẹt throttle
   * vĩnh viễn — cùng lớp lỗi với cận dưới của cửa sổ freshness ở `refresh.ts`.
   */
  it("mốc ở tương lai ⇒ vẫn refresh, không kẹt throttle", async () => {
    window.localStorage.setItem(
      "qlts_last_refresh_at",
      String(Date.now() + 60 * 60 * 1000),
    );

    renderHook(() => useProactiveTokenRefresh(true));

    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
  });

  it("mốc là rác ⇒ coi như chưa refresh", async () => {
    window.localStorage.setItem("qlts_last_refresh_at", "khong-phai-so");

    renderHook(() => useProactiveTokenRefresh(true));

    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
  });
});

describe("hook KHÔNG được tự ghi mốc throttle", () => {
  /**
   * 🔑 Chỉ `refresh.ts` được ghi, và chỉ sau khi POST đã chứng minh thành công:
   * mốc này nghĩa là "lần làm mới THÀNH CÔNG gần nhất". Hook ghi trước `await`
   * thì một lần thử HỎNG cũng đặt mốc, và mọi tab bị hoãn 12 phút vì một lần
   * refresh chưa từng thành công.
   */
  it("sau một lượt refresh, hook không đụng vào localStorage", async () => {
    const setItem = vi.spyOn(window.localStorage, "setItem");

    renderHook(() => useProactiveTokenRefresh(true));
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalled());

    const ghiMocThrottle = setItem.mock.calls.filter(
      (call) => String(call[0]) === "qlts_last_refresh_at",
    );
    expect(ghiMocThrottle).toEqual([]);
  });
});
