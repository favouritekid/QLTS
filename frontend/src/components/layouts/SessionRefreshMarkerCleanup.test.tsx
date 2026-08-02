// @vitest-environment jsdom
/**
 * Marker `_sr` phải biến mất khỏi thanh địa chỉ — nhưng **chỉ** nó.
 *
 * Gỡ kèm query nghiệp vụ hoặc hash là làm người dùng mất chỗ đang đứng: họ có
 * thể đang ở `?tab=ho-so&page=3#muc-2` sau một vòng cứu phiên.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";

import { SessionRefreshMarkerCleanup } from "./SessionRefreshMarkerCleanup";

/**
 * Đặt URL bằng đường dẫn TƯƠNG ĐỐI: jsdom chặn `replaceState` sang origin khác
 * (`SecurityError`), và origin ở đây là của môi trường test chứ không phải
 * domain production.
 */
function setUrl(path: string) {
  window.history.replaceState({}, "", path);
}

let replaceState: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  replaceState = vi.spyOn(window.history, "replaceState");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SessionRefreshMarkerCleanup", () => {
  it("gỡ `_sr` nhưng GIỮ query nghiệp vụ và hash", () => {
    setUrl("/admissions/611?tab=ho-so&_sr=1&page=3#muc-2");
    replaceState.mockClear();

    render(<SessionRefreshMarkerCleanup />);

    expect(replaceState).toHaveBeenCalledTimes(1);
    const next = String(replaceState.mock.calls[0][2]);
    expect(next).not.toContain("_sr");
    expect(next).toContain("tab=ho-so");
    expect(next).toContain("page=3");
    expect(next).toContain("#muc-2");
    expect(next).toContain("/admissions/611");
  });

  // Không có marker thì đừng đụng vào lịch sử: mỗi `replaceState` thừa là một
  // lần ghi đè state của router.
  it("không có `_sr` ⇒ KHÔNG chạm history", () => {
    setUrl("/admissions/611?tab=ho-so");
    replaceState.mockClear();

    render(<SessionRefreshMarkerCleanup />);

    expect(replaceState).not.toHaveBeenCalled();
  });
});
