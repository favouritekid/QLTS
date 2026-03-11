import { test, expect } from '@playwright/test';

// Define the mobile viewport
const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe('Mobile Responsiveness Checks', () => {
  // Use a separate context for mobile checks to ensure clean state and correct viewport
  test.use({
    viewport: MOBILE_VIEWPORT,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
    hasTouch: true
  });

  test('Capture mobile screenshots', async ({ page }) => {
    // storageState (officer) applied by project config — navigate directly to pages
    // Officer routes only; /admin/* routes are covered by Mobile_Admin project
    const pagesToTest = [
      { name: 'dashboard_mobile', path: '/dashboard' },
      { name: 'leads_pipeline_mobile', path: '/leads/pipeline' },
      { name: 'admissions_mobile', path: '/admissions' },
      { name: 'notifications_mobile', path: '/notifications' },
      { name: 'profile_mobile', path: '/profile' },
      { name: 'settings_sessions_mobile', path: '/settings/sessions' },
      { name: 'settings_login_history_mobile', path: '/settings/login-history' },
    ];

    for (const pageItem of pagesToTest) {
      console.log(`Navigating to ${pageItem.path}...`);
      try {
        await page.goto(pageItem.path);
        await page.waitForLoadState('domcontentloaded');
        // Give a little extra time for dynamic interactions/animations to settle
        await page.waitForTimeout(2000);

        console.log(`Taking screenshot for ${pageItem.name}...`);
        await page.screenshot({
          path: `d:/QLTS/frontend/test-results/screenshots/${pageItem.name}.png`,
          fullPage: true
        });
      } catch (error) {
        console.error(`Error capturing ${pageItem.name}:`, error);
        // Take an error screenshot if possible
        try {
            await page.screenshot({
                path: `d:/QLTS/frontend/test-results/screenshots/${pageItem.name}_error.png`
            });
        } catch (e) {
            console.error('Failed to take error screenshot');
        }
      }
    }
  });
});
