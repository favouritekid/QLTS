import { test, expect } from '@playwright/test';

// Define the mobile viewport
const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe('Mobile Responsiveness Checks Final', () => {
    test.use({
        viewport: MOBILE_VIEWPORT,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        hasTouch: true
     });

    // Set timeout to 3 minutes to accommodate all page loads and screenshots
    test.setTimeout(180000);

  test('Capture ALL mobile screenshots', async ({ page }) => {
    // 1. Force Sidebar to be Collapsed (Fix for obscured content)
    await page.addInitScript(() => {
        window.localStorage.setItem('ui-storage', JSON.stringify({ state: { isSidebarCollapsed: true }, version: 0 }));
    });

    // storageState (officer) applied by project config — navigate directly to pages
    // Officer routes only; /admin/* routes are covered by Mobile_Admin project
    const pagesToTest = [
      { name: 'dashboard_mobile_final', path: '/dashboard' },
      { name: 'leads_pipeline_mobile_final', path: '/leads/pipeline' },
      { name: 'admissions_mobile_final', path: '/admissions' },
      { name: 'notifications_mobile_final', path: '/notifications' },
      { name: 'profile_mobile_final', path: '/profile' },
      // Settings
      { name: 'settings_security_mobile_final', path: '/settings/security' },
    ];

    for (const pageItem of pagesToTest) {
      console.log(`Navigating to ${pageItem.path}...`);
      try {
        await page.goto(pageItem.path);
        // Wait for basic load
        await page.waitForLoadState('domcontentloaded');
        // Give explicit time for client-side rendering/data fetching
        await page.waitForTimeout(3000);

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
