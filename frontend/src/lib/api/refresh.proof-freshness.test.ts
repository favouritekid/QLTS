// src/lib/api/refresh.proof-freshness.test.ts
/**
 * Một bản ghi `success` chứng minh "đã có token mới **lúc nó được viết**" —
 * không chứng minh token ấy còn hạn BÂY GIỜ.
 *
 * Đây là gốc của vòng lặp `/session-refresh` đo được trên production: access
 * token hết hạn ⇒ proxy đưa sang bootstrap ⇒ bootstrap gọi `refreshAccessToken`
 * ⇒ nhật ký còn bản ghi `success` của chu kỳ trước ⇒ cổng khoá coi đó là "đã
 * xong" và chặn POST ⇒ hàm trả về êm ⇒ bootstrap quay lại trang đích ⇒ token
 * vẫn hết hạn ⇒ lặp lại. Không một lần `POST /api/auth/refresh` nào xảy ra —
 * đúng dấu hiệu đo được: 46,7% traffic là vòng lặp trong khi endpoint refresh
 * chỉ nhận 70 lượt/24h.
 *
 * Bản vá có HAI toạ độ và ca test phải tách đúng hai nhóm dưới đây, vì vá một
 * chỗ không thay được chỗ kia:
 *  - cổng GIÀNH quyền POST  → `refresh-coordination/lock.ts` (`inspect`);
 *  - cổng ĐỌC kết quả tab khác → `refresh.ts` (`outcomeFromRecord`).
 *
 * Chỉ giả lập `Date`. Giả lập `setTimeout` sẽ đóng băng vòng lặp sự kiện mà
 * IndexedDB dựa vào, và mọi ca treo tới timeout thay vì fail — "đỏ vì treo"
 * không nói lên điều gì về bất biến đang kiểm.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import axios from "axios";

import { acquireRefreshLock, LEASE_TTL_MS } from "./refresh-coordination/lock";
import { selectJournalStore } from "./refresh-coordination/storage";
import { installFakeIdb, removeWebLocks } from "./refresh-coordination/test-harness";
import type { ResultKind } from "./refresh-coordination/types";

const T0 = 1_800_000_000_000;

function setCsrf(value: string | null) {
  if (value === null) {
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    return;
  }
  document.cookie = `csrf_token=${value}; path=/`;
}

/**
 * Tab khác đã chạy xong một attempt và để lại bản ghi — dựng qua ĐÚNG đường
 * thật (`acquireRefreshLock` → `update` → `release`), không nhét tay vào kho.
 * Bản ghi vì thế mang đúng hình dạng production để lại, kể cả
 * `phase: "in-flight"` còn sót sau khi đã có kết quả.
 */
async function tabKhacKetThucVoi(
  resultKind: ResultKind,
  extra: Record<string, unknown> = {},
): Promise<string> {
  const a = await acquireRefreshLock("gen-old", T0);
  if (a.status !== "acquired") throw new Error("không dựng được nhật ký cũ");
  await a.handle.update({ phase: "in-flight" });
  await a.handle.update({ resultKind, ...extra });
  await a.handle.release();
  return a.handle.attemptId;
}

/** POST thành công: server rotate xong và cookie mang thế hệ mới. */
function postThanhCong() {
  return vi.spyOn(axios, "post").mockImplementation(async () => {
    setCsrf("gen-new");
    return {} as never;
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(T0);
  window.localStorage.clear();
  installFakeIdb();
  // Nhánh lease-IDB: toàn bộ việc phân xử nằm ở bản ghi, đúng nhánh phơi ra
  // rõ nhất chỗ đang hỏng.
  removeWebLocks();
  setCsrf("gen-old");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("cổng GIÀNH quyền POST — bằng chứng quá tuổi không còn chặn", () => {
  it("🔴 nhật ký `success` QUÁ TUỔI ⇒ PHẢI POST thật (ca tái hiện vòng lặp)", async () => {
    await tabKhacKetThucVoi("success");

    // 30.001ms: lease đã hết từ lâu VÀ bằng chứng đã quá cửa sổ.
    vi.setSystemTime(T0 + 30_001);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();

    // Đây là toàn bộ điểm của ca này. Trước bản vá con số là 0: hàm báo "xong"
    // mà chưa hề chạm mạng, và người dùng quay vòng mãi.
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("nhật ký `success` còn TƯƠI ⇒ KHÔNG được POST (điều phối liên-tab)", async () => {
    await tabKhacKetThucVoi("success");

    // Lease đã hết hạn (20s) nhưng bằng chứng thì chưa (30s) — đúng khoảng mà
    // nới tay sẽ khiến nhiều tab cùng rotate và server tính là reuse.
    const luc = T0 + LEASE_TTL_MS + 1_000;
    expect(luc - T0).toBeLessThan(30_000);
    vi.setSystemTime(luc);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();

    expect(post).not.toHaveBeenCalled();
  });

  it("`terminal` quá tuổi ⇒ VẪN chặn — phiên chết là trạng thái bền, không hết hạn", async () => {
    await tabKhacKetThucVoi("terminal", { status: 401 });

    vi.setSystemTime(T0 + 5 * 60_000);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).rejects.toMatchObject({
      outcome: { kind: "terminal", status: 401 },
    });
    expect(post).not.toHaveBeenCalled();
  });

  it("`ambiguous` quá tuổi ⇒ VẪN chặn vĩnh viễn", async () => {
    await tabKhacKetThucVoi("ambiguous");

    vi.setSystemTime(T0 + 5 * 60_000);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });

  it("`nonterminal-stop` quá tuổi ⇒ VẪN chặn vĩnh viễn", async () => {
    await tabKhacKetThucVoi("nonterminal-stop", { status: 422 });

    vi.setSystemTime(T0 + 5 * 60_000);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });

  it("bỏ qua bằng chứng quá tuổi là GHI ĐÈ bản ghi, KHÔNG phải xoá nó", async () => {
    // Xoá theo hạn lease là một cơ chế khác hẳn (và nằm ngoài phạm vi bản vá
    // này). Ở đây nhật ký phải luôn có chủ: một kho trống nghĩa là "chưa ai
    // thử refresh", tức cấp phép POST cho mọi tab cùng lúc.
    const cuId = await tabKhacKetThucVoi("success");

    vi.setSystemTime(T0 + 30_001);
    postThanhCong();
    const { refreshAccessToken } = await import("./refresh");
    await refreshAccessToken();

    const store = await selectJournalStore();
    const record = await store!.read();
    expect(record).not.toBeNull();
    expect(record?.attemptId).not.toBe(cuId);
  });
});

describe("cổng ĐỌC kết quả tab khác — bằng chứng lệch đồng hồ", () => {
  // Nhánh follower: lease của tab kia CÒN HẠN nên ta không giành khoá mà đọc
  // kết quả của họ. Đây là đường duy nhất còn lại dẫn tới `outcomeFromRecord`
  // với một bản ghi `success` không đáng tin — và nó tới được vì tuổi có thể
  // ÂM: bản ghi mang mốc thời gian muộn hơn "bây giờ".
  it("`success` đến TỪ TƯƠNG LAI ⇒ KHÔNG được nhận là thành công", async () => {
    await tabKhacKetThucVoi("success");

    // Đồng hồ lùi 2 phút sau khi bản ghi được viết: lease vẫn "còn hạn" (mốc
    // của nó ở tương lai) nên ta đi đường follower, nhưng bằng chứng thì không
    // nói được gì về token hiện tại.
    vi.setSystemTime(T0 - 120_000);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).rejects.toThrow();
    // Fail-closed: không nhận bừa là thành công, và cũng không POST đè lên một
    // rotation có thể đang bay.
    expect(post).not.toHaveBeenCalled();
  });

  it("`success` còn TƯƠI ⇒ follower nhận là thành công và không POST", async () => {
    await tabKhacKetThucVoi("success");

    // Lease còn hạn, bản ghi mới 1 giây tuổi — đúng cuộc đua liên-tab bình
    // thường mà lớp này sinh ra để phục vụ.
    vi.setSystemTime(T0 + 1_000);
    const post = postThanhCong();
    const { refreshAccessToken } = await import("./refresh");

    await expect(refreshAccessToken()).resolves.toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  });
});
