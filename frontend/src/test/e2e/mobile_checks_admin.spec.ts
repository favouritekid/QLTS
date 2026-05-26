/**
 * E2E Test: Mobile Admin Checks
 *
 * Tests /admin/* routes on mobile viewport using admin credentials.
 * Uses API login + TOTP (not UI form) to bypass MFA step in browser.
 *
 * Project: Mobile_Admin (no storageState, no setup dependency)
 *
 * Chạy:
 *   npx playwright test mobile_checks_admin --project=Mobile_Admin --reporter=list
 */

import { test, expect, type Page } from '@playwright/test';
import * as OTPAuth from 'otpauth';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME || 'admin';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin@123';
const ADMIN_TOTP_SECRET =
  process.env.E2E_ADMIN_TOTP_SECRET || 'WUUT7KVVWRFVMVPZ7K6NGOKL2VYPPFH5';

const API_URL = process.env.E2E_API_URL || 'http://localhost:8000';

const MOBILE_VIEWPORT = { width: 375, height: 812 };

// ---------------------------------------------------------------------------
// Helpers (inline — no cross-file imports per E2E convention)
// ---------------------------------------------------------------------------

function generateTOTP(secret: string): string {
  const totp = new OTPAuth.TOTP({
    secret: OTPAuth.Secret.fromBase32(secret),
    digits: 6,
    period: 30,
    algorithm: 'SHA1',
  });
  return totp.generate();
}

async function extractAndAddCookies(
  page: Page,
  resp: { headersArray(): Array<{ name: string; value: string }> }
): Promise<string> {
  const apiHost = new URL(API_URL).hostname;
  let csrf = '';

  for (const h of resp.headersArray()) {
    if (h.name.toLowerCase() !== 'set-cookie') continue;
    const m = h.value.match(/^([^=]+)=([^;]*)/);
    if (!m) continue;
    const pathM = h.value.match(/path=([^;]*)/i);
    await page.context().addCookies([
      {
        name: m[1].trim(),
        value: m[2],
        domain: apiHost,
        path: pathM ? pathM[1].trim() : '/',
        httpOnly: /httponly/i.test(h.value),
        secure: /secure/i.test(h.value),
      },
    ]);
    if (m[1].trim() === 'csrf_token') csrf = m[2];
  }

  if (!csrf) {
    const fallback = (await page.context().cookies()).find(
      (c) => c.name === 'csrf_token'
    )?.value;
    if (fallback) csrf = fallback;
  }
  return csrf;
}

async function loginAdminViaAPI(page: Page): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.context().clearCookies();

    const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
      form: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
    });

    if (loginResp.status() === 429) {
      console.log(`Rate limited, waiting 65s (attempt ${attempt + 1})...`);
      await new Promise((r) => setTimeout(r, 65_000));
      continue;
    }
    if (!loginResp.ok()) {
      throw new Error(`Admin login failed: ${loginResp.status()}`);
    }

    const loginBody = await loginResp.json();

    if (loginBody.mfa_required) {
      const mfaResp = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
        data: {
          mfa_token: loginBody.mfa_token,
          code: generateTOTP(ADMIN_TOTP_SECRET),
        },
      });
      if (!mfaResp.ok()) {
        console.log(
          `MFA failed (${mfaResp.status()}), waiting 31s and retrying...`
        );
        await new Promise((r) => setTimeout(r, 31_000));
        continue;
      }
      await extractAndAddCookies(page, mfaResp);
    } else {
      await extractAndAddCookies(page, loginResp);
    }

    console.log('Admin logged in via API');
    return;
  }
  throw new Error('Admin login failed after 3 attempts');
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

test.describe('Mobile Admin Checks', () => {
  test.describe.configure({ timeout: 300_000 });

  test.use({
    viewport: MOBILE_VIEWPORT,
    userAgent:
      'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
    hasTouch: true,
  });

  test('Capture admin mobile screenshots', async ({ page }) => {
    // 1. Force Sidebar to be Collapsed
    await page.addInitScript(() => {
      window.localStorage.setItem(
        'ui-storage',
        JSON.stringify({ state: { isSidebarCollapsed: true }, version: 0 })
      );
    });

    // 2. Login via API (bypasses MFA UI step)
    await loginAdminViaAPI(page);

    // 3. Navigate to frontend — cookies are set on API domain, not frontend domain.
    // We need the frontend to pick up the session.
    // Navigate to root first to establish context, then go to admin pages.
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Admin-only pages
    const pagesToTest = [
      { name: 'admin_users_mobile', path: '/admin/users' },
      { name: 'admin_admission_config_mobile', path: '/admin/admission-config' },
    ];

    for (const pageItem of pagesToTest) {
      console.log(`Navigating to ${pageItem.path}...`);
      try {
        await page.goto(pageItem.path);
        await page.waitForLoadState('domcontentloaded');
        await page.waitForTimeout(3000);

        console.log(`Taking screenshot for ${pageItem.name}...`);
        await page.screenshot({
          path: `d:/QLTS/frontend/test-results/screenshots/${pageItem.name}.png`,
          fullPage: true,
        });
      } catch (error) {
        console.error(`Error capturing ${pageItem.name}:`, error);
        try {
          await page.screenshot({
            path: `d:/QLTS/frontend/test-results/screenshots/${pageItem.name}_error.png`,
          });
        } catch (e) {
          console.error('Failed to take error screenshot');
        }
      }
    }
  });
});
