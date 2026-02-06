import { test, expect } from '@playwright/test';
import path from 'path';

// Define the mobile viewport
const MOBILE_VIEWPORT = { width: 375, height: 812 };

test.describe('Mobile Responsiveness Checks Part 2', () => {
    test.use({ 
        viewport: MOBILE_VIEWPORT, 
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        hasTouch: true
     });

  test('Capture remaining mobile screenshots', async ({ page }) => {
     // 1. Re-login (just in case state wasn't persisted or we need a fresh session)
    console.log('Navigating to login page...');
    await page.goto('/login');
    
    // Clear inputs and login as admin
    console.log('Filling credentials...');
    await page.fill('input[name="username"]', '');
    await page.fill('input[name="username"]', 'admin');
    await page.fill('input[name="password"]', '');
    await page.fill('input[name="password"]', 'Admin@12345');
    
    console.log('Submitting login form...');
    await page.click('button[type="submit"]');
    
    // Wait for dashboard or redirection
    await page.waitForURL('**/dashboard', { timeout: 15000 }).catch(() => console.log('Timeout waiting for dashboard URL, proceeding anyway...'));
    await page.waitForLoadState('networkidle');

    // Remaining pages
    const pagesToTest = [
      { name: 'settings_sessions_mobile', path: '/settings/sessions' },
      { name: 'settings_login_history_mobile', path: '/settings/login-history' },
      { name: 'admin_users_mobile', path: '/admin/users' },
      { name: 'admin_admission_config_mobile', path: '/admin/admission-config' },
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
