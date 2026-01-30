import { test, expect } from '@playwright/test';
import path from 'path';

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

    // 2. Login
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
    await page.waitForURL('**/dashboard', { timeout: 20000 }).catch(() => console.log('Timeout waiting for dashboard URL, proceeding anyway...'));
    await page.waitForLoadState('networkidle');

    // All pages
    const pagesToTest = [
      { name: 'dashboard_mobile', path: '/dashboard' },
      { name: 'leads_pipeline_mobile', path: '/leads/pipeline' },
      { name: 'admissions_mobile', path: '/admissions' },
      { name: 'notifications_mobile', path: '/notifications' },
      { name: 'profile_mobile', path: '/profile' },
      // Settings
      { name: 'settings_sessions_mobile', path: '/settings/sessions' },
      { name: 'settings_login_history_mobile', path: '/settings/login-history' },
      // Admin
      { name: 'admin_users_mobile', path: '/admin/users' },
      { name: 'admin_admission_config_mobile', path: '/admin/admission-config' },
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
