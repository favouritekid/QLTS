// src/hooks/useAuth.test.tsx
// @vitest-environment jsdom
/**
 * Option-B Commit 6 — useAuth surfaces the REAL pending count.
 *
 * Source-inspection contract test. The actual login flow involves
 * router + queryClient + axios + sonner + Zustand stores + the
 * SecurityBanner store — full runtime testing here would need MSW +
 * deeply nested mocks and would mostly assert that the mocks did the
 * mocking. The behaviours that matter for this commit are static:
 *
 *   1. ``triggerSuspiciousLoginBanner`` is no longer fed the literal
 *      ``1`` — it reads ``loginResponse.suspicious_login_count`` from
 *      the BE response (Commit 5 contract).
 *   2. ``?? 1`` fallback covers an older BE that hasn't shipped
 *      Commit 5 yet — banner still surfaces, just with the old
 *      approximation rather than ``undefined``.
 *   3. Toast message text uses the real count too, so the user reads
 *      "Phát hiện 3 đăng nhập đáng ngờ" instead of always "1".
 *   4. Both login and MFA verify paths apply the same fix — the bug
 *      was duplicated across the two callsites in useAuth.ts.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const useAuthSrc = readFileSync(
  resolve(__dirname, "./useAuth.ts"),
  "utf-8"
);

describe("useAuth — Option-B Commit 6 banner count contract", () => {
  it("no longer calls triggerSuspiciousLoginBanner with the literal 1", () => {
    // The bug: ``triggerSuspiciousLoginBanner(1)`` appeared twice in
    // useAuth.ts (login + MFA verify) before Commit 6. Either call
    // alone hid the real backlog count from the user.
    const matches = useAuthSrc.match(/triggerSuspiciousLoginBanner\(\s*1\s*\)/g);
    expect(
      matches,
      "Found a hardcoded triggerSuspiciousLoginBanner(1) — Commit 6 was supposed " +
        "to feed the response field. ``?? 1`` fallback in a non-literal call is fine; " +
        "a bare literal is the regression."
    ).toBeNull();
  });

  it("reads suspicious_login_count from the login response", () => {
    // Destructure the BE-provided count from loginResponse — Commit 5
    // contract. The fallback ``?? 1`` is included so the test allows
    // both the new and back-compat shapes.
    expect(useAuthSrc).toContain("suspicious_login_count");
    expect(useAuthSrc).toContain("loginResponse");
  });

  it("uses ?? 1 fallback for back-compat with old BE responses", () => {
    expect(useAuthSrc).toMatch(/suspicious_login_count\s*\?\?\s*1/);
  });

  it("applies the count fix to BOTH login and MFA verify callsites", () => {
    // Pre-PR the same hardcoded ``1`` appeared at lines 96 and 158.
    // Both callsites must now feed the real count.
    const callsiteCount = (useAuthSrc.match(/triggerSuspiciousLoginBanner\(pendingCount\)/g) ?? [])
      .length;
    expect(callsiteCount).toBeGreaterThanOrEqual(2);
  });

  it("toast message interpolates the real count, not a static word", () => {
    // Toast text changed from "Phát hiện đăng nhập đáng ngờ" (no number)
    // to "Phát hiện ${pendingCount} đăng nhập đáng ngờ".
    expect(useAuthSrc).toMatch(/Phát hiện\s*\$\{pendingCount\}\s*đăng nhập đáng ngờ/);
  });
});

describe("LoginResponse type carries suspicious_login_count", () => {
  it("api.types.ts declares the field", () => {
    const typesSrc = readFileSync(
      resolve(__dirname, "../types/api.types.ts"),
      "utf-8"
    );
    expect(typesSrc).toMatch(/suspicious_login_count\?:\s*number/);
  });

  it("declares SuspiciousLoginSocketPayload with login_history_id (not login_id)", () => {
    const typesSrc = readFileSync(
      resolve(__dirname, "../types/api.types.ts"),
      "utf-8"
    );
    // The BE payload uses ``login_history_id`` (auth.py:_notif_payload).
    // FE listener (Commit 8) will read the same key — locking it here
    // catches a silent FE rename to ``login_id``.
    expect(typesSrc).toContain("SuspiciousLoginSocketPayload");
    expect(typesSrc).toMatch(/login_history_id:\s*number/);
  });
});

describe("SecurityClient dead invalidations are gone", () => {
  it("does not invalidate the non-existent ['suspiciousCount'] cache key", () => {
    const securityClientSrc = readFileSync(
      resolve(
        __dirname,
        "../app/(dashboard)/settings/security/_components/SecurityClient.tsx"
      ),
      "utf-8"
    );
    // No useQuery in the FE consumes ``["suspiciousCount"]`` — the
    // invalidation was a no-op left over from a hook that never shipped.
    // Commit 6 removed both occurrences (confirmMutation +
    // secureMutation onSuccess).
    expect(securityClientSrc).not.toMatch(/invalidateQueries\(\{\s*queryKey:\s*\["suspiciousCount"\]/);
  });
});
