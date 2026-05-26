/**
 * Playwright Authentication Setup
 *
 * This file handles authentication before running tests.
 * It logs in once and saves the browser state for reuse.
 *
 * Credentials are configured via environment variables or defaults.
 */

import { test as setup, expect } from "@playwright/test";
import path from "path";

// Path to store authentication state
const authFile = path.join(__dirname, "..", ".auth", "user.json");

setup("authenticate", async ({ page }) => {
  // Self-diagnose listeners — when login fails the next time, the failure
  // mode (CORS strip / 401 / 500 / cookie reject) shows up in the
  // playwright-report immediately instead of only the timeout message.
  // Lesson from 2026-05-25 nightly-regression debug cycle: original
  // failure was CORS strip (P1 #39); without these listeners, multiple
  // diagnostic rounds were needed to surface "Authentication successful"
  // on server + Network Error on client. The listeners attach BEFORE any
  // navigation so the first /login request is also captured.
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      // eslint-disable-next-line no-console
      console.log(`[browser ${msg.type()}]`, msg.text());
    }
  });
  page.on("pageerror", (err) => {
    // eslint-disable-next-line no-console
    console.log("[browser pageerror]", err.message);
  });
  page.on("response", (resp) => {
    const url = resp.url();
    if (url.includes("/auth/login") || url.includes("/api/auth/")) {
      const corsHeader = resp.headers()["access-control-allow-origin"] || "(none)";
      // eslint-disable-next-line no-console
      console.log(
        `[auth ${resp.status()}] ${url} | CORS allow-origin: ${corsHeader}`,
      );
    }
  });

  // Navigate to login page
  await page.goto("/login");

  // Wait for the login form to be visible
  await expect(page.locator("h1")).toContainText("Chào mừng trở lại");

  // Fill in credentials
  // Use environment variables or defaults for testing
  // Officer account (no MFA) — admin credentials only used in e2e-workflow + Mobile_Admin projects
  const username = process.env.TEST_USERNAME || "vothuhien";
  const password = process.env.TEST_PASSWORD || "@Matkhau123!";

  // Fill username
  await page.fill('input[placeholder="Tên đăng nhập"]', username);

  // Fill password
  await page.fill('input[type="password"]', password);

  // Click login button
  await page.click('button[type="submit"]:has-text("Đăng nhập")');

  // Wait for successful login. Per memory
  // ``nextjs16-router-replace-eventual-consistency``, Next.js 16 router.push
  // is async ~100-500ms. Asserting *absence* of /login substring is race-prone
  // when client-side bootstrap fetches (4+ React Query hooks) are still
  // settling. Switch to: wait networkidle FIRST so router.push resolves +
  // dashboard hydrates, THEN assert *presence* of /dashboard/ destination.
  // This pattern matches what audit agent identified as the root-cause race
  // 2026-05-26 (nightly smoke run 26427220989 — backend logs confirm dashboard
  // rendered: GET /api/officer/dashboard 200 + 8 other officer endpoints 200,
  // but the legacy assertion fired before the URL string actually flipped).
  await page.waitForLoadState("networkidle");
  // Defensive regex: matches /dashboard followed by slash OR end-of-string,
  // so a hypothetical bare /dashboard landing route still passes (in case
  // FE redirect target loses the trailing path segment).
  await expect(page).toHaveURL(/\/dashboard(\/|$)/, { timeout: 30000 });

  // Save authentication state to file
  await page.context().storageState({ path: authFile });

  console.log("Authentication successful! State saved to:", authFile);
});
