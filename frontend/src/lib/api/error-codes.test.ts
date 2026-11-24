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
  COMBINED_KEY_CHANGE_AND_REVOKE_ERROR_CODE,
  combinedKeyChangeAndRevokeDetail,
  isAuthStateUnavailable,
  t6PublishStopDetail,
  userFacingUnavailableDetail,
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

describe("combinedKeyChangeAndRevokeDetail — PR-B lượt 8, chặn lưu gộp", () => {
  it("hằng là giá trị máy chủ gửi (CombinedKeyChangeAndRevokeError.error_code)", () => {
    expect(COMBINED_KEY_CHANGE_AND_REVOKE_ERROR_CODE).toBe("COMBINED_KEY_CHANGE_AND_REVOKE");
  });

  it("409 + mã + detail ⇒ trả NGUYÊN detail của máy chủ", () => {
    expect(
      combinedKeyChangeAndRevokeDetail({
        status: 409,
        data: { error_code: "COMBINED_KEY_CHANGE_AND_REVOKE", detail: "câu máy chủ" },
      }),
    ).toBe("câu máy chủ");
  });

  it.each([
    ["no response", undefined],
    ["409 CONFLICT chung", { status: 409, data: { error_code: "CONFLICT", detail: "x" } }],
    ["409 mã đúng nhưng không detail", { status: 409, data: { error_code: "COMBINED_KEY_CHANGE_AND_REVOKE" } }],
    ["400 mang mã", { status: 400, data: { error_code: "COMBINED_KEY_CHANGE_AND_REVOKE", detail: "x" } }],
    ["409 thân HTML", { status: 409, data: "<html>409</html>" }],
  ])("null cho %s", (_ten, response) => {
    expect(combinedKeyChangeAndRevokeDetail(response)).toBeNull();
  });
});

describe("userFacingUnavailableDetail — 503 họ fail-closed", () => {
  it.each([
    ["SERVICE_UNAVAILABLE"],
    ["INITIAL_LEAD_STATUS_NOT_CONFIGURED"],
    ["AUTH_STATE_UNAVAILABLE"],
    ["AUDIT_TRAIL_UNAVAILABLE"],
    ["PRIORITY_RATE_NOT_CONFIGURED"],
    ["CHOICE_TARGET_LEVEL_NOT_CONFIGURED"],
  ])("503 + %s + detail ⇒ trả detail", (code) => {
    expect(userFacingUnavailableDetail({ status: 503, data: { error_code: code, detail: `d-${code}` } })).toBe(`d-${code}`);
  });

  it.each([
    ["no response (network error)", undefined],
    ["nginx 503, HTML body", { status: 503, data: NGINX_503_HTML }],
    ["503, empty JSON body", { status: 503, data: {} }],
    ["503, null body", { status: 503, data: null }],
    ["503, HTTPException code", { status: 503, data: { error_code: "HTTP_503", detail: "Celery service unavailable" } }],
    ["503, code without detail", { status: 503, data: { error_code: "SERVICE_UNAVAILABLE" } }],
    ["503, code in another case", { status: 503, data: { error_code: "service_unavailable", detail: "x" } }],
    ["500 carrying a family code", { status: 500, data: { error_code: "SERVICE_UNAVAILABLE", detail: "x" } }],
    ["503 frozen (code, no error_code)", { status: 503, data: { code: "ADMISSION_FROZEN", detail: "x" } }],
  ])("null for %s", (_name, response) => {
    expect(userFacingUnavailableDetail(response)).toBeNull();
  });
});
