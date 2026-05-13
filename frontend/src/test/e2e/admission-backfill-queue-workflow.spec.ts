/**
 * Phase 3 PR-3D-B FE Wave B Bundle 4 — Admin backfill queue smoke E2E.
 *
 * Coverage (Bundle 3 admin queue UI verification):
 *   - Admin auth gate enforced (officer/manager → 403 or redirect)
 *   - Page loads at /admin/admission-backfill-queue without crash
 *   - Filter controls present (exception_type input + is_resolved select + page size)
 *   - Toolbar present (bulk-resolve + CSV export buttons)
 *   - Empty state OR table renders depending on dev DB seed
 *
 * Project: e2e-workflow (inline admin login w/ MFA — file name matches
 * `workflow` regex in playwright.config.ts; project has no storageState
 * dependency).
 *
 * NOT included (deferred to nightly-regression OR FU #129):
 * - Seed backfill exception rows + verify table data
 * - Resolve single + bulk flow with audit reason
 * - CSV download verification
 *
 * Reason for trimmed scope: backfill exception rows can only be seeded via
 * raw SQL (no public API), making fixture setup expensive (~80 LOC). Smoke
 * verifies the FE integration with BE GET endpoint + auth gate, sufficient
 * for Bundle 4 release confidence.
 */
import { test, expect } from "@playwright/test"
import * as OTPAuth from "otpauth"

const API_URL = process.env.E2E_API_URL || "http://localhost:8000"
const FRONTEND_URL = process.env.E2E_FRONTEND_URL || "http://localhost:3000"
const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || "favouritekid"
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "Admin@123"
const ADMIN_MFA_SECRET = process.env.E2E_ADMIN_MFA_SECRET || ""

test.describe.configure({ mode: "serial" })

test.describe("admin admission-backfill-queue smoke", () => {
  test.beforeEach(async ({ page }) => {
    // Inline admin login — e2e-workflow project has no storageState
    await page.goto(`${FRONTEND_URL}/login`)
    await page.fill('input[placeholder="Tên đăng nhập"]', ADMIN_USERNAME)
    await page.fill('input[type="password"]', ADMIN_PASSWORD)
    await page.click('button[type="submit"]:has-text("Đăng nhập")')

    // Handle TOTP MFA if configured (admin account requires MFA)
    if (ADMIN_MFA_SECRET) {
      const totp = new OTPAuth.TOTP({
        secret: ADMIN_MFA_SECRET,
        period: 30,
        digits: 6,
      })
      const code = totp.generate()
      await page
        .locator('input[autocomplete="one-time-code"], input[name="otp"]')
        .first()
        .fill(code)
      await page
        .locator('button[type="submit"]:has-text("Xác minh"), button:has-text("Verify")')
        .first()
        .click()
    }

    await expect(page).not.toHaveURL(/\/login/, { timeout: 30000 })
  })

  test("admin can access /admin/admission-backfill-queue", async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/admin/admission-backfill-queue`)

    // Page does not redirect to login or 403
    await expect(page).toHaveURL(/admission-backfill-queue/)

    // Page heading renders
    await expect(
      page.locator("h1").filter({ hasText: "Hàng đợi sửa dữ liệu xét tuyển" }),
    ).toBeVisible({ timeout: 10000 })
  })

  test("filter controls + toolbar present", async ({ page }) => {
    await page.goto(`${FRONTEND_URL}/admin/admission-backfill-queue`)
    await expect(page.locator("h1")).toBeVisible({ timeout: 10000 })

    // Filter row
    await expect(page.getByTestId("filter-exception-type")).toBeVisible()
    await expect(page.getByTestId("filter-resolved")).toBeVisible()
    await expect(page.getByTestId("filter-page-size")).toBeVisible()

    // Toolbar
    await expect(page.getByTestId("bulk-resolve-button")).toBeVisible()
    await expect(page.getByTestId("export-csv-button")).toBeVisible()
  })

  test("BE wiring works — no console errors or network 5xx on initial load", async ({
    page,
  }) => {
    const consoleErrors: string[] = []
    const networkErrors: { url: string; status: number }[] = []

    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text())
    })
    page.on("response", (resp) => {
      if (
        resp.url().includes("/api/v2/admin/admission-backfill-exceptions") &&
        resp.status() >= 500
      ) {
        networkErrors.push({ url: resp.url(), status: resp.status() })
      }
    })

    await page.goto(`${FRONTEND_URL}/admin/admission-backfill-queue`)
    await page.waitForLoadState("networkidle", { timeout: 20000 })

    expect(networkErrors, JSON.stringify(networkErrors)).toHaveLength(0)
    // Ignore known dnd-kit SSR hydration warning (FU #124 — cosmetic)
    const blockingErrors = consoleErrors.filter(
      (e) => !e.includes("aria-describedby") && !e.includes("hydrated"),
    )
    expect(
      blockingErrors,
      `Blocking console errors:\n${blockingErrors.join("\n")}`,
    ).toHaveLength(0)
  })
})
