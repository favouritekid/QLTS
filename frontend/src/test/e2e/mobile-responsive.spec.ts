/**
 * Mobile Responsive Tests
 *
 * Tests mobile-specific UI behaviors including:
 * - Responsive layouts
 * - Touch interactions
 * - Mobile navigation
 * - Component responsiveness
 *
 * Run with: npx playwright test mobile-responsive.spec.ts --project=Mobile_Chrome
 */

import { test, expect, devices } from "@playwright/test";

// Use iPhone 12 viewport for all tests in this file
test.use({ ...devices["iPhone 12"] });

test.describe("Mobile Responsive - Leads Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    // Wait for page to fully load
    await page.waitForLoadState("networkidle");
  });

  test("should show mobile filter bar with Add Lead button", async ({ page }) => {
    // Check that the mobile Add Lead button is visible (the one in md:hidden section)
    // Use first() since there might be desktop version too
    const addButton = page.locator('button:has-text("Thêm")').first();
    await expect(addButton).toBeVisible();

    // Check that search input is visible and responsive
    const searchInput = page.locator('input[placeholder*="Tìm kiếm"]');
    await expect(searchInput).toBeVisible();

    // Check that filter toggle button is visible
    const filterToggle = page.locator('button:has-text("Lọc")');
    await expect(filterToggle).toBeVisible();
  });

  test("should expand filters when filter button is clicked", async ({ page }) => {
    // Click the filter toggle
    await page.click('button:has-text("Lọc")');

    // Check that mobile filters section appears
    const mobileFilters = page.locator(".md\\:hidden >> text=Nguồn");
    await expect(mobileFilters).toBeVisible();
  });

  test("should open create lead dialog on mobile", async ({ page }) => {
    // Click Add Lead button (first one, which is mobile button)
    await page.locator('button:has-text("Thêm")').first().click();

    // Check that dialog opens
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Check dialog is properly sized for mobile
    const dialogBox = await dialog.boundingBox();
    expect(dialogBox).toBeTruthy();
    if (dialogBox) {
      // Dialog should be less than full viewport width (390px for iPhone 12)
      // Account for potential scrollbar and padding
      expect(dialogBox.width).toBeLessThan(420);
      expect(dialogBox.width).toBeGreaterThan(300); // Should be reasonably sized
    }
  });
});

test.describe("Mobile Responsive - Dialog", () => {
  test("dialog should have proper mobile sizing", async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");

    // Open any dialog (e.g., create lead) - use first() for mobile button
    await page.locator('button:has-text("Thêm")').first().click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    // Check max-height for scroll
    const styles = await dialog.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        maxHeight: computed.maxHeight,
        overflowY: computed.overflowY,
      };
    });

    // Should have max-height set for mobile
    expect(styles.maxHeight).not.toBe("none");
    // Should be scrollable
    expect(["auto", "scroll"]).toContain(styles.overflowY);
  });
});

test.describe("Mobile Responsive - Input", () => {
  test("input should have minimum 36px height for touch", async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");

    // Find an input element
    const input = page.locator('input[placeholder*="Tìm kiếm"]');
    const inputBox = await input.boundingBox();

    expect(inputBox).toBeTruthy();
    if (inputBox) {
      // Should be at least 36px (h-9) for touch target
      expect(inputBox.height).toBeGreaterThanOrEqual(36);
    }
  });

  test("base Input component should have 16px font on mobile", async ({ page }) => {
    // Test on login page where the base Input is used without override
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Test the password input (uses base Input styling)
    const input = page.locator('input[type="password"]');
    await expect(input).toBeVisible();

    const fontSize = await input.evaluate((el) => {
      return window.getComputedStyle(el).fontSize;
    });

    // Base Input should be 16px to prevent iOS auto-zoom
    expect(parseInt(fontSize)).toBeGreaterThanOrEqual(16);
  });
});

test.describe("Mobile Responsive - Navigation", () => {
  test("should show bottom navigation on mobile", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Bottom nav should be visible
    const bottomNav = page.locator("nav.fixed.bottom-0");
    await expect(bottomNav).toBeVisible();

    // Should have main navigation items in bottom nav (scope selector)
    await expect(bottomNav.locator('a[href="/dashboard"]')).toBeVisible();
    await expect(bottomNav.locator('a[href="/leads"]')).toBeVisible();
  });

  test("bottom nav items should have touch-friendly size", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    const bottomNav = page.locator("nav.fixed.bottom-0");
    const navItem = bottomNav.locator("a").first();
    const box = await navItem.boundingBox();

    expect(box).toBeTruthy();
    if (box) {
      // Should meet 44px minimum touch target
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
  });
});

test.describe("Mobile Responsive - Kanban/Pipeline", () => {
  test("pipeline columns should be scrollable horizontally", async ({ page }) => {
    await page.goto("/leads/pipeline");

    // Check for snap-scroll container
    const container = page.locator(".snap-x");
    await expect(container).toBeVisible();

    // Check that columns are snap-center
    const column = page.locator('[class*="snap-center"]').first();
    await expect(column).toBeVisible();
  });

  test("pipeline column should be ~85vw on mobile", async ({ page }) => {
    await page.goto("/leads/pipeline");

    const column = page.locator('[class*="snap-center"]').first();
    const box = await column.boundingBox();

    expect(box).toBeTruthy();
    if (box) {
      // 85% of 390px (iPhone 12) = ~331px
      expect(box.width).toBeGreaterThan(300);
      expect(box.width).toBeLessThan(400);
    }
  });
});

test.describe("Mobile Responsive - Sheet/Drawer", () => {
  test("sheet should have proper mobile width", async ({ page }) => {
    await page.goto("/leads");

    // Click on a lead to open detail sheet (if available)
    // This depends on having data - skip if no leads
    const leadItem = page.locator("[data-lead-item]").first();
    if (await leadItem.isVisible()) {
      await leadItem.click();

      const sheet = page.locator('[role="dialog"][data-state="open"]');
      if (await sheet.isVisible()) {
        const box = await sheet.boundingBox();
        expect(box).toBeTruthy();
        if (box) {
          // Should be ~85vw on mobile
          expect(box.width).toBeGreaterThan(300);
        }
      }
    }
  });
});

// =============================================================================
// RESPONSIVE FORM LAYOUT TESTS
// =============================================================================

test.describe("Mobile Responsive - LeadDialog FormLayout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");
    // Open create lead dialog
    await page.locator('button:has-text("Thêm")').first().click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
  });

  test("form fields should stack vertically on mobile (FormRow)", async ({ page }) => {
    const dialog = page.locator('[role="dialog"]');

    // Get the form container
    const form = dialog.locator("form");
    await expect(form).toBeVisible();

    // Find the first row with two fields (Name + Phone)
    // On mobile, these should be stacked (each taking full width)
    const nameField = dialog.locator('input[placeholder*="Nguyễn"]');
    const phoneField = dialog.locator('input[placeholder*="0901234567"]');

    await expect(nameField).toBeVisible();
    await expect(phoneField).toBeVisible();

    const nameBox = await nameField.boundingBox();
    const phoneBox = await phoneField.boundingBox();

    expect(nameBox).toBeTruthy();
    expect(phoneBox).toBeTruthy();

    if (nameBox && phoneBox) {
      // On mobile (390px), fields should be stacked (phone below name)
      // Verify phone field is below name field, not beside it
      expect(phoneBox.y).toBeGreaterThan(nameBox.y);

      // Both fields should take similar width (full column width)
      const widthDiff = Math.abs(nameBox.width - phoneBox.width);
      expect(widthDiff).toBeLessThan(50); // Allow some variation for padding
    }
  });

  test("form actions should stack with primary button first on mobile", async ({ page }) => {
    const dialog = page.locator('[role="dialog"]');

    // Find the action buttons
    const submitButton = dialog.locator('button[type="submit"]:has-text("Tạo Lead")');
    const cancelButton = dialog.locator('button:has-text("Hủy")');

    await expect(submitButton).toBeVisible();
    await expect(cancelButton).toBeVisible();

    const submitBox = await submitButton.boundingBox();
    const cancelBox = await cancelButton.boundingBox();

    expect(submitBox).toBeTruthy();
    expect(cancelBox).toBeTruthy();

    if (submitBox && cancelBox) {
      // With flex-col-reverse, submit button should appear ABOVE cancel on mobile
      // (primary action is more prominent/accessible at top)
      expect(submitBox.y).toBeLessThan(cancelBox.y);

      // Both buttons should be full width on mobile
      expect(submitBox.width).toBeGreaterThan(200);
      expect(cancelBox.width).toBeGreaterThan(200);
    }
  });

  test("form action buttons should have acceptable touch height", async ({ page }) => {
    const dialog = page.locator('[role="dialog"]');

    // Check primary action buttons (not collapsible triggers or icon-only buttons)
    const submitButton = dialog.locator('button[type="submit"]:has-text("Tạo Lead")');
    const cancelButton = dialog.locator('button:has-text("Hủy")');

    await expect(submitButton).toBeVisible();
    await expect(cancelButton).toBeVisible();

    const submitBox = await submitButton.boundingBox();
    const cancelBox = await cancelButton.boundingBox();

    // Button uses default size (h-9 = 36px on desktop, may vary on mobile)
    // Minimum acceptable touch target is 32px (h-8), ideal is 44px per WCAG
    if (submitBox) {
      expect(submitBox.height).toBeGreaterThanOrEqual(32);
    }
    if (cancelBox) {
      expect(cancelBox.height).toBeGreaterThanOrEqual(32);
    }
  });
});

test.describe("Mobile Responsive - LeadsTable RowActions", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");
  });

  test("should show action sheet on mobile when clicking row actions", async ({ page }) => {
    // Wait for table to load
    const tableBody = page.locator("tbody");
    await expect(tableBody).toBeVisible({ timeout: 10000 });

    // Find the action button (three dots menu)
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    // Check if there are leads in the table
    if (await actionButton.isVisible({ timeout: 5000 })) {
      // Click the action button
      await actionButton.click();

      // On mobile, MobileActionSheet should appear (bottom sheet)
      // It uses data-state="open" from the Sheet component
      const actionSheet = page.locator('[role="dialog"][data-state="open"]');

      // Wait for action sheet to appear
      await expect(actionSheet).toBeVisible({ timeout: 5000 });

      // Check that it's positioned at the bottom (side="bottom")
      const sheetBox = await actionSheet.boundingBox();
      const viewportSize = page.viewportSize();

      expect(sheetBox).toBeTruthy();
      expect(viewportSize).toBeTruthy();

      if (sheetBox && viewportSize) {
        // Bottom sheet should be in the lower portion of the screen
        expect(sheetBox.y + sheetBox.height).toBeGreaterThan(viewportSize.height * 0.5);
      }

      // Check for action items
      const editAction = actionSheet.locator('text=Chỉnh sửa');
      const deleteAction = actionSheet.locator('text=Xóa');

      await expect(editAction).toBeVisible();
      await expect(deleteAction).toBeVisible();

      // Check for cancel button
      const cancelButton = actionSheet.locator('button:has-text("Hủy")');
      await expect(cancelButton).toBeVisible();
    }
  });

  test("action sheet items should have touch-friendly height", async ({ page }) => {
    // Find and click the action button
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    if (await actionButton.isVisible({ timeout: 5000 })) {
      await actionButton.click();

      const actionSheet = page.locator('[role="dialog"][data-state="open"]');
      await expect(actionSheet).toBeVisible({ timeout: 5000 });

      // Check action item height (should be min 48px per MOBILE_STANDARDIZATION.md)
      const actionItem = actionSheet.locator('button:has-text("Chỉnh sửa")');
      const box = await actionItem.boundingBox();

      expect(box).toBeTruthy();
      if (box) {
        expect(box.height).toBeGreaterThanOrEqual(48);
      }
    }
  });

  test("action sheet should close when cancel is clicked", async ({ page }) => {
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    if (await actionButton.isVisible({ timeout: 5000 })) {
      await actionButton.click();

      const actionSheet = page.locator('[role="dialog"][data-state="open"]');
      await expect(actionSheet).toBeVisible({ timeout: 5000 });

      // Click cancel button
      const cancelButton = actionSheet.locator('button:has-text("Hủy")');
      await cancelButton.click();

      // Action sheet should close
      await expect(actionSheet).not.toBeVisible({ timeout: 3000 });
    }
  });
});

test.describe("Mobile Responsive - ConsultationDialog", () => {
  test("consultation dialog actions should stack on mobile", async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");

    // Try to open a lead and then consultation dialog
    // This test requires existing lead data
    const tableRow = page.locator("tbody tr").first();

    if (await tableRow.isVisible({ timeout: 5000 })) {
      // Click on row to select lead
      await tableRow.click();

      // Look for consultation button in detail panel
      const consultationButton = page.locator('button:has-text("Lên lịch tư vấn")');

      if (await consultationButton.isVisible({ timeout: 5000 })) {
        await consultationButton.click();

        const dialog = page.locator('[role="dialog"]:has-text("Lên lịch tư vấn")');
        await expect(dialog).toBeVisible({ timeout: 5000 });

        // Check form actions are stacked
        const submitButton = dialog.locator('button[type="submit"]');
        const cancelButton = dialog.locator('button:has-text("Hủy")');

        if (await submitButton.isVisible() && await cancelButton.isVisible()) {
          const submitBox = await submitButton.boundingBox();
          const cancelBox = await cancelButton.boundingBox();

          expect(submitBox).toBeTruthy();
          expect(cancelBox).toBeTruthy();

          if (submitBox && cancelBox) {
            // Submit should be above cancel (flex-col-reverse)
            expect(submitBox.y).toBeLessThan(cancelBox.y);
          }
        }
      }
    }
  });
});

// Visual regression tests (optional - requires baseline images)
test.describe("Visual Regression - Mobile", () => {
  test.skip("leads page mobile layout", async ({ page }) => {
    await page.goto("/leads");
    await expect(page).toHaveScreenshot("leads-mobile.png", {
      fullPage: true,
    });
  });

  test.skip("dashboard mobile layout", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveScreenshot("dashboard-mobile.png", {
      fullPage: true,
    });
  });
});
