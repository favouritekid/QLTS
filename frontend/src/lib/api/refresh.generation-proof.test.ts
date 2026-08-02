// src/lib/api/refresh.generation-proof.test.ts
/**
 * Bằng chứng "phiên đã sang thế hệ mới" phải ĐÓNG đường POST, không chỉ dùng
 * để dọn nhật ký rồi mở một lần thử mới.
 *
 * Backend sinh `csrf_token` mới ở mỗi lần login/refresh thành công, nên
 * generation đổi = đã có token mới. Nếu ta thấy bằng chứng đó rồi vẫn POST
 * tiếp thì đang trình lại một refresh token vừa bị rotate — đúng hành vi bị
 * server tính là reuse, và tới lần thứ năm là thu hồi toàn bộ phiên.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import axios from "axios";

import { acquireRefreshLock } from "./refresh-coordination/lock";
import { selectJournalStore } from "./refresh-coordination/storage";
import { installFakeIdb, removeWebLocks } from "./refresh-coordination/test-harness";

const T0 = 1_800_000_000_000;

function setCsrf(value: string | null) {
  if (value === null) {
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    return;
  }
  document.cookie = `csrf_token=${value}; path=/`;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(T0);
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  setCsrf(null);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("generation đổi ⇒ KHÔNG được POST nữa", () => {
  it("tab gọi muộn sau khi tab khác đã refresh xong ⇒ thành công mà không chạm mạng", async () => {
    // Tab A đã refresh xong ở thế hệ cũ và để lại nhật ký của mình.
    setCsrf("gen-old");
    const a = await acquireRefreshLock("gen-old", T0);
    if (a.status !== "acquired") throw new Error("tab A không giành được lease");
    await a.handle.update({ phase: "in-flight" });
    await a.handle.update({ resultKind: "success" });
    await a.handle.release();

    // Cookie đã mang thế hệ mới — bằng chứng token mới đã có.
    setCsrf("gen-new");

    const post = vi.spyOn(axios, "post");
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();

    // Đây là điểm của cả test: thấy bằng chứng rồi thì thôi, đừng thử lại.
    expect(post).not.toHaveBeenCalled();
  });

  it("nhật ký cũ thuộc thế hệ khác ⇒ dọn xong PHẢI dừng, không mở attempt mới", async () => {
    // Một nhật ký `ambiguous` còn sót lại từ thế hệ trước.
    setCsrf("gen-old");
    const stale = await acquireRefreshLock("gen-old", T0);
    if (stale.status !== "acquired") throw new Error("không dựng được nhật ký cũ");
    await stale.handle.update({ phase: "in-flight" });
    await stale.handle.update({ resultKind: "ambiguous" });
    await stale.handle.release();

    setCsrf("gen-new");

    const post = vi.spyOn(axios, "post");
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("nhật ký CŨ không được biến chu kỳ refresh mới thành no-op", () => {
  /**
   * `generation đã đổi` có HAI nghĩa hoàn toàn khác nhau, và gộp chúng lại là
   * một lỗi im lặng rất đắt:
   *
   *  (a) một tab khác VỪA refresh xong vài giây trước ⇒ token mới còn nguyên,
   *      ta không cần POST;
   *  (b) nhật ký còn sót từ chu kỳ TRƯỚC (13 phút trước) ⇒ token của chu kỳ đó
   *      sắp hết hạn, ta BẮT BUỘC phải POST.
   *
   * Nếu (b) cũng được coi là thành công thì hook proactive ở phút 13 chỉ dọn
   * nhật ký rồi báo xong — nhưng nó đã ghi timestamp throttle trước khi gọi,
   * nên lần thử kế tiếp mãi tới phút ~26. Access token thật hết hạn ở phút 15.
   * Người dùng gặp lại đúng triệu chứng mà cả kế hoạch này sinh ra để chữa.
   */
  it("nhật ký `success` VỪA XONG ⇒ không POST (late follower)", async () => {
    setCsrf("gen-old");
    const leader = await acquireRefreshLock("gen-old", T0);
    if (leader.status !== "acquired") throw new Error("không giành được lease");
    await leader.handle.update({ phase: "in-flight" });
    await leader.handle.update({ resultKind: "success" });
    await leader.handle.release();

    setCsrf("gen-new");

    const post = vi.spyOn(axios, "post");
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  });

  it("nhật ký `success` đã 13 PHÚT ⇒ vẫn phải POST một lần", async () => {
    setCsrf("gen-old");
    const leader = await acquireRefreshLock("gen-old", T0);
    if (leader.status !== "acquired") throw new Error("không giành được lease");
    await leader.handle.update({ phase: "in-flight" });
    await leader.handle.update({ resultKind: "success" });
    await leader.handle.release();

    // Chu kỳ proactive kế tiếp: 13 phút sau, cookie vẫn ở thế hệ của lần trước.
    const later = T0 + 13 * 60_000;
    vi.setSystemTime(later);
    setCsrf("gen-new");

    const post = vi
      .spyOn(axios, "post")
      .mockImplementation(async () => {
        setCsrf("gen-newer");
        return { status: 200, data: {} } as never;
      });
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();
    // Đúng MỘT POST: nhật ký cũ bị dọn, rồi một attempt mới thật sự chạy.
    expect(post).toHaveBeenCalledTimes(1);
  });
});

describe("follower thấy generation đổi GIỮA LÚC CHỜ", () => {
  /**
   * ⚠️ Cookie phải đổi SAU khi lời gọi đã vào vòng chờ.
   *
   * Đổi trước khi gọi thì `supersedeIfGenerationChanged` bắt được ngay ở đầu
   * `doRefresh()` và trả về luôn — `followOtherTab()` không hề chạy, và test
   * chỉ đang kiểm lại nhánh `cleared` một lần nữa dưới một cái tên khác.
   */
  async function startFollowerThenChangeCookie() {
    setCsrf("gen-old");

    // Leader giành lease ở CÙNG thế hệ mà tab này đọc → tab này thành follower.
    const leader = await acquireRefreshLock("gen-old", T0);
    if (leader.status !== "acquired") throw new Error("leader không giành được lease");
    await leader.handle.update({ phase: "in-flight" });
    // Cố ý KHÔNG ghi `resultKind`: mô phỏng tab leader bị đóng giữa chừng.

    const post = vi.spyOn(axios, "post");
    const { refreshAccessToken } = await import("./refresh");

    const pending = refreshAccessToken();
    // Để nó kịp nhận `busy` và bước vào vòng poll.
    await new Promise((r) => setTimeout(r, 60));
    return { pending, post };
  }

  it("leader chết trước khi ghi kết quả nhưng cookie đã đổi ⇒ dừng chờ, coi là thành công", async () => {
    const { pending, post } = await startFollowerThenChangeCookie();

    // Leader ĐÃ rotate xong, chỉ là chưa kịp ghi lại. Bằng chứng nằm ở cookie,
    // không nằm ở nhật ký.
    setCsrf("gen-new");

    await expect(pending).resolves.toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  }, 9_000);

  it("nhật ký bị tab khác XOÁ giữa lúc chờ ⇒ vẫn nhận ra cookie đã đổi", async () => {
    const { pending, post } = await startFollowerThenChangeCookie();

    // Tab khác dọn nhật ký (đăng nhập lại chẳng hạn) rồi cookie sang thế hệ
    // mới. Nếu chỉ so generation KHI CÒN bản ghi thì follower mất luôn mốc so
    // sánh và ngồi chờ hết 15 giây cho một lần refresh đã xong.
    const store = await selectJournalStore();
    await store!.clear();
    setCsrf("gen-new");

    await expect(pending).resolves.toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  }, 9_000);
});
