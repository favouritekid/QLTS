/**
 * Tests cho login-redirect helper (return-url an toàn).
 *
 * Trọng tâm: isValidRedirect CHỈ validate path-part (query/hash tự do),
 * và buildLoginRedirect giữ thứ tự param cố định + chỉ đính redirect hợp lệ.
 */
import { describe, it, expect } from "vitest";
import { isValidRedirect, buildLoginRedirect } from "./login-redirect";

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
