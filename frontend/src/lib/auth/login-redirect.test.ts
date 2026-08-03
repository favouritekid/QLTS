/**
 * Tests cho login-redirect helper (return-url an toàn).
 *
 * Trọng tâm: isValidRedirect CHỈ validate path-part (query/hash tự do),
 * và buildLoginRedirect giữ thứ tự param cố định + chỉ đính redirect hợp lệ.
 */
import { describe, it, expect } from "vitest";
import { isValidRedirect, buildLoginRedirect } from "./login-redirect";

// Ký tự điều khiển dựng qua fromCharCode: giữ tệp nguồn không chứa ký tự thô
// (grep/diff sẽ coi tệp là binary) mà vẫn truyền được KÝ TỰ THẬT vào hàm.
const NUL = String.fromCharCode(0);
const TAB = String.fromCharCode(9);
const LF = String.fromCharCode(10);
const CR = String.fromCharCode(13);
const DEL = String.fromCharCode(127);

describe("isValidRedirect", () => {
  it("accept path nội bộ thường", () => {
    expect(isValidRedirect("/leads/1")).toBe(true);
    expect(isValidRedirect("/dashboard")).toBe(true);
  });

  it("accept query/hash chứa ':' hoặc encoded — chỉ validate path-part", () => {
    expect(isValidRedirect("/finance?from=2026-06-24T10:00:00")).toBe(true);
    expect(isValidRedirect("/leads?q=a:b")).toBe(true);
    expect(isValidRedirect("/x#sec")).toBe(true);
    // encoded slash NẰM Ở QUERY → vẫn hợp lệ (path-part sạch; router.push không đổi origin)
    expect(isValidRedirect("/finance?next=%2f%2fevil")).toBe(true);
  });

  it("reject falsy / non-internal / path-part xấu", () => {
    expect(isValidRedirect(null)).toBe(false);
    expect(isValidRedirect(undefined)).toBe(false);
    expect(isValidRedirect("")).toBe(false);
    expect(isValidRedirect("http://evil.com")).toBe(false);
    expect(isValidRedirect("//evil.com")).toBe(false);
    expect(isValidRedirect("/a:b")).toBe(false); // ':' ở path-part
    expect(isValidRedirect("\\evil")).toBe(false);
    expect(isValidRedirect("/%2f%2fevil")).toBe(false); // encoded slash ở path-part
    expect(isValidRedirect("/%5cevil")).toBe(false);
  });

  it("reject public auth path (tránh loop redirect về /login)", () => {
    expect(isValidRedirect("/login")).toBe(false);
    expect(isValidRedirect("/login?x=1")).toBe(false);
    expect(isValidRedirect("/login/abc")).toBe(false);
    expect(isValidRedirect("/register")).toBe(false);
    expect(isValidRedirect("/forgot-password")).toBe(false);
    expect(isValidRedirect("/reset-password")).toBe(false);
    // Không nhầm prefix: '/loginx' KHÔNG phải '/login' hay '/login/'
    expect(isValidRedirect("/loginx")).toBe(true);
  });

  it("reject /session-refresh (trang bootstrap nhận return-url, không được làm return-url)", () => {
    expect(isValidRedirect("/session-refresh")).toBe(false);
    expect(isValidRedirect("/session-refresh?redirect=/leads/1")).toBe(false);
    expect(isValidRedirect("/session-refreshed")).toBe(true); // không nhầm prefix
  });

  it("reject ký tự điều khiển THẬT ở path-part", () => {
    // Ký tự thật qua fromCharCode, KHÔNG viết literal "%09": URLSearchParams đã
    // giải mã trước khi giá trị tới hàm này, nên literal "%09" không hề chạm
    // tới lỗ hổng (nó chỉ là chuỗi 3 ký tự vô hại và vốn đã được accept).
    expect(isValidRedirect(`/${TAB}//evil.com`)).toBe(false);
    expect(isValidRedirect(`/${CR}${LF}//evil.com`)).toBe(false);
    expect(isValidRedirect(`/${LF}//evil.com`)).toBe(false);
    expect(isValidRedirect(`/${NUL}//evil.com`)).toBe(false);
    expect(isValidRedirect(`/x${DEL}/y`)).toBe(false);
  });

  it("reject ký tự điều khiển cả ở query/hash (ranh giới ?/# hết đáng tin)", () => {
    expect(isValidRedirect(`/leads?q=a${TAB}b`)).toBe(false);
    expect(isValidRedirect(`/x#sec${LF}`)).toBe(false);
  });

  it("KIỂM NGƯỢC: chính payload đó thoát ra origin ngoài nếu lọt qua validate", () => {
    // Chứng minh guard đang chặn thứ NGUY HIỂM THẬT, không phải chuỗi vô hại:
    // WHATWG URL parser xoá TAB/CR/LF trước khi parse, nên "/<TAB>//evil.com"
    // trở thành "///evil.com" và phân giải ra host evil.com.
    expect(new URL(`/${TAB}//evil.com`, "https://qlts.example").origin).toBe(
      "https://evil.com",
    );
    expect(new URL(`/${CR}${LF}//evil.com`, "https://qlts.example").origin).toBe(
      "https://evil.com",
    );
    // …và guard chặn được cả hai.
    expect(isValidRedirect(`/${TAB}//evil.com`)).toBe(false);
    expect(isValidRedirect(`/${CR}${LF}//evil.com`)).toBe(false);
  });

  it("đường đi THẬT: ?redirect=%2F%09%2F%2Fevil.com qua URLSearchParams", () => {
    // Đúng cách useAuth.ts:127/:171 đọc param — URLSearchParams tự giải mã.
    const decoded = new URLSearchParams(
      "redirect=%2F%09%2F%2Fevil.com",
    ).get("redirect");
    expect(decoded).toBe(`/${TAB}//evil.com`); // đã là TAB thật, không còn "%09"
    expect(isValidRedirect(decoded)).toBe(false);
  });
});

describe("buildLoginRedirect", () => {
  it("trả /login khi không path hợp lệ và không opts", () => {
    expect(buildLoginRedirect(null)).toBe("/login");
    expect(buildLoginRedirect("http://evil")).toBe("/login");
    expect(buildLoginRedirect(undefined)).toBe("/login");
  });

  it("đính redirect (gồm query) khi path hợp lệ", () => {
    const url = new URL(
      buildLoginRedirect("/finance/invoices?profile=123"),
      "http://localhost",
    );
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("redirect")).toBe("/finance/invoices?profile=123");
  });

  it("force_login + reason + redirect theo THỨ TỰ cố định", () => {
    const url = new URL(
      buildLoginRedirect("/leads/1", {
        forceLogin: true,
        reason: "session_expired",
      }),
      "http://localhost",
    );
    expect(Array.from(url.searchParams.keys())).toEqual([
      "force_login",
      "reason",
      "redirect",
    ]);
    expect(url.searchParams.get("redirect")).toBe("/leads/1");
  });

  it("forceLogin nhưng path không hợp lệ → chỉ force_login (giữ contract cũ)", () => {
    const url = new URL(
      buildLoginRedirect(null, { forceLogin: true }),
      "http://localhost",
    );
    expect(Array.from(url.searchParams.keys())).toEqual(["force_login"]);
  });

  it("bỏ redirect khi cross-origin, vẫn giữ reason", () => {
    const url = new URL(
      buildLoginRedirect("http://evil", { reason: "session_expired" }),
      "http://localhost",
    );
    expect(url.searchParams.has("redirect")).toBe(false);
    expect(url.searchParams.get("reason")).toBe("session_expired");
  });
});
