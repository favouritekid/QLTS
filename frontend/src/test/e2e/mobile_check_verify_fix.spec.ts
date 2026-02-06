import { test, expect } from '@playwright/test';

const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe('Mobile verification for Sidebar Fix', () => {
  test.use({ 
      viewport: MOBILE_VIEWPORT,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
      hasTouch: true
  });

  test('Capture Dashboard without Sidebar Overlay', async ({ page }) => {
    // 1. Clear Local Storage to ensure we test the default state
    await page.addInitScript(() => {
        localStorage.clear();
    });

    console.log('Navigating to login page...');
    await page.goto('/login');
    
    console.log('Filling credentials...');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', 'Admin@12345');
    await page.click('button[type="submit"]');
    
    await page.waitForURL('**/dashboard', { timeout: 30000 });
    await page.waitForLoadState('networkidle');

    // Slight delay for any animations
    await page.waitForTimeout(2000);

    console.log('Taking verification screenshot...');
    await page.screenshot({ 
      path: 'd:/QLTS/frontend/test-results/screenshots/dashboard_mobile_verify.png', 
      fullPage: true 
    });
  });
});
