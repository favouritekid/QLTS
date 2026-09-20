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

  // Giá trị NẮP cũng phải được gỡ. Một ca chỉ thử `_sr=1` sẽ xanh cả khi ai đó
  // viết phép gỡ theo kiểu so chuỗi `_sr=1`.
  it("`_sr=2` (giá trị nắp) cũng được gỡ, query nghiệp vụ vẫn còn", () => {
    setUrl("/admissions/611?_sr=2&tab=ho-so");
    replaceState.mockClear();

    render(<SessionRefreshMarkerCleanup />);

    expect(replaceState).toHaveBeenCalledTimes(1);
    const next = String(replaceState.mock.calls[0][2]);
    expect(next).not.toContain("_sr");
    expect(next).toContain("tab=ho-so");
  });

  // Sau khi bootstrap cũng gắn marker, MỌI lượt cứu phiên thành công đều đáp
  // xuống một URL mà `_sr` có thể là query DUY NHẤT. Gỡ xong mà còn `?` mồ côi
  // thì người dùng bookmark và chia sẻ một URL có dấu hỏi thừa.
  it("`_sr` là query DUY NHẤT ⇒ gỡ xong không còn dấu `?` mồ côi", () => {
    setUrl("/admissions/611?_sr=1");
    replaceState.mockClear();

    render(<SessionRefreshMarkerCleanup />);

    expect(replaceState).toHaveBeenCalledTimes(1);
    expect(String(replaceState.mock.calls[0][2])).toBe("/admissions/611");
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
