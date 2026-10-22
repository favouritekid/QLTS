/**
 * `isAuthStateUnavailable` — status 503 AND exactly `AUTH_STATE_UNAVAILABLE`.
 *
 * The value is written out as a literal here on purpose: it is what the
 * backend puts on the wire (`AuthStateUnavailable.error_code`), so a change of
 * the constant on this side alone must turn this red.
 */
import { describe, it, expect } from "vitest";

import {
  AUTH_STATE_UNAVAILABLE_ERROR_CODE,
  isAuthStateUnavailable,
  t6PublishStopDetail,
} from "./error-codes";

const NGINX_503_HTML =
  "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n" +
  "<body>\r\n<center><h1>503 Service Temporarily Unavailable</h1></center>\r\n" +
  "<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n";

describe("AUTH_STATE_UNAVAILABLE_ERROR_CODE", () => {
  it("is the backend's wire value", () => {
    expect(AUTH_STATE_UNAVAILABLE_ERROR_CODE).toBe("AUTH_STATE_UNAVAILABLE");
  });
});

describe("isAuthStateUnavailable", () => {
  it("true for the backend's 503 with the code", () => {
    expect(
      isAuthStateUnavailable({
        status: 503,
        data: {
          detail: "Hệ thống xác thực tạm thời không sẵn sàng. Vui lòng thử lại sau.",
          error_code: "AUTH_STATE_UNAVAILABLE",
        },
      }),
    ).toBe(true);
  });

  it.each([
    ["no response (network error)", undefined],
    ["nginx 503, HTML body", { status: 503, data: NGINX_503_HTML }],
    ["503, empty JSON body", { status: 503, data: {} }],
    ["503, null body", { status: 503, data: null }],
    ["503, another code", { status: 503, data: { error_code: "SERVICE_UNAVAILABLE" } }],
    ["503, code in another case", { status: 503, data: { error_code: "auth_state_unavailable" } }],
    ["503, code with padding", { status: 503, data: { error_code: " AUTH_STATE_UNAVAILABLE" } }],
    ["500 carrying the code", { status: 500, data: { error_code: "AUTH_STATE_UNAVAILABLE" } }],
    ["429 carrying the code", { status: 429, data: { error_code: "AUTH_STATE_UNAVAILABLE" } }],
  ])("false for %s", (_name, response) => {
    expect(isAuthStateUnavailable(response)).toBe(false);
  });
});

describe("t6PublishStopDetail — T6 dừng có nhãn ở MỌI status", () => {
  it("503 / 500 / 400 có mã dừng ⇒ trả detail của BE", () => {
    for (const [status, code] of [
      [503, "PRIORITY_RATE_NOT_CONFIGURED"],
      [500, "PRIORITY_FREEZE_FAILED"],
      [400, "PRIORITY_KV_UNRESOLVED"],
    ] as const) {
      expect(
        t6PublishStopDetail({ status, data: { error_code: code, detail: `d-${code}` } }),
      ).toBe(`d-${code}`);
    }
  });

  it("mã khác hoặc thân không phải JSON ⇒ null", () => {
    expect(t6PublishStopDetail({ status: 500, data: { error_code: "INTERNAL_ERROR", detail: "x" } })).toBeNull();
    expect(t6PublishStopDetail({ status: 503, data: NGINX_503_HTML })).toBeNull();
  });
});
