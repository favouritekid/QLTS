import { test, expect } from '@playwright/test';

// Define the mobile viewport
const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe('Mobile Responsiveness Checks Part 2', () => {
    test.use({
        viewport: MOBILE_VIEWPORT,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        hasTouch: true
     });

  test('Capture remaining mobile screenshots', async ({ page }) => {
    // storageState (officer) applied by project config — navigate directly to pages
    // Settings routes only; /admin/* routes are covered by Mobile_Admin project
    const pagesToTest = [
      { name: 'settings_sessions_mobile_p2', path: '/settings/sessions' },
      { name: 'settings_login_history_mobile_p2', path: '/settings/login-history' },
    ];

    for (const pageItem of pagesToTest) {
      console.log(`Navigating to ${pageItem.path}...`);
      try {
        await page.goto(pageItem.path);
        await page.waitForLoadState('domcontentloaded');
        await page.waitForTimeout(3000); // Wait for potential skeleton loaders to disappear

        console.log(`Taking screenshot for ${pageItem.name}...`);
        await page.screenshot({
          path: `d:/QLTS/frontend/test-results/screenshots/${pageItem.name}.png`,
          fullPage: true
        });
      } catch (error) {
        console.error(`Error capturing ${pageItem.name}:`, error);
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
