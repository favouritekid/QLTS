/**
 * Desktop Responsive Tests
 *
 * Tests desktop-specific UI behaviors including:
 * - Grid layouts (multi-column forms)
 * - Dropdown menus (vs mobile action sheets)
 * - Side panels
 *
 * Run with: npx playwright test desktop-responsive.spec.ts --project=chromium
 */

import { test, expect, devices } from "@playwright/test";

// Use Desktop Chrome viewport for all tests in this file
test.use({ ...devices["Desktop Chrome"] });

test.describe("Desktop Responsive - LeadDialog FormLayout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");
    // Open create lead dialog
    await page.locator('button:has-text("Thêm Lead")').first().click();
    await expect(page.locator('[role="dialog"]')).toBeVisible();
  });

  test("form fields should be in grid layout on desktop (2 columns)", async ({ page }) => {
    const dialog = page.locator('[role="dialog"]');

    // Get the name and phone fields
    const nameField = dialog.locator('input[placeholder*="Nguyễn"]');
    const phoneField = dialog.locator('input[placeholder*="0901234567"]');

    await expect(nameField).toBeVisible();
    await expect(phoneField).toBeVisible();

    const nameBox = await nameField.boundingBox();
    const phoneBox = await phoneField.boundingBox();

    expect(nameBox).toBeTruthy();
    expect(phoneBox).toBeTruthy();

    if (nameBox && phoneBox) {
      // On desktop, fields should be side by side (same Y position approximately)
      const yDiff = Math.abs(nameBox.y - phoneBox.y);
      expect(yDiff).toBeLessThan(10); // Allow small variation

      // Phone field should be to the right of name field
      expect(phoneBox.x).toBeGreaterThan(nameBox.x);
    }
  });

  test("form actions should be in row layout on desktop", async ({ page }) => {
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
      // On desktop, buttons should be on the same row (same Y approximately)
      const yDiff = Math.abs(submitBox.y - cancelBox.y);
      expect(yDiff).toBeLessThan(10);

      // Buttons should NOT be full width on desktop
      expect(submitBox.width).toBeLessThan(200);
      expect(cancelBox.width).toBeLessThan(200);
    }
  });
});

test.describe("Desktop Responsive - LeadsTable RowActions", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");
  });

  test("should show dropdown menu on desktop when clicking row actions", async ({ page }) => {
    // Wait for table to load
    const tableBody = page.locator("tbody");
    await expect(tableBody).toBeVisible({ timeout: 10000 });

    // Find the action button (three dots menu)
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    // Check if there are leads in the table
    if (await actionButton.isVisible({ timeout: 5000 })) {
      // Click the action button
      await actionButton.click();

      // On desktop, DropdownMenu should appear (not bottom sheet)
      // Dropdown uses role="menu"
      const dropdown = page.locator('[role="menu"]');

      // Wait for dropdown to appear
      await expect(dropdown).toBeVisible({ timeout: 5000 });

      // Dropdown should be positioned near the button, not at bottom of screen
      const buttonBox = await actionButton.boundingBox();
      const dropdownBox = await dropdown.boundingBox();
      const viewportSize = page.viewportSize();

      expect(buttonBox).toBeTruthy();
      expect(dropdownBox).toBeTruthy();
      expect(viewportSize).toBeTruthy();

      if (buttonBox && dropdownBox && viewportSize) {
        // Dropdown should be near the button (within 200px)
        const distance = Math.abs(dropdownBox.y - buttonBox.y);
        expect(distance).toBeLessThan(200);

        // Dropdown should NOT be at the very bottom (like mobile action sheet)
        expect(dropdownBox.y + dropdownBox.height).toBeLessThan(viewportSize.height - 50);
      }

      // Check for action items
      const editAction = dropdown.locator('[role="menuitem"]:has-text("Chỉnh sửa")');
      const deleteAction = dropdown.locator('[role="menuitem"]:has-text("Xóa")');

      await expect(editAction).toBeVisible();
      await expect(deleteAction).toBeVisible();
    }
  });

  test("dropdown should close when clicking outside", async ({ page }) => {
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    if (await actionButton.isVisible({ timeout: 5000 })) {
      await actionButton.click();

      const dropdown = page.locator('[role="menu"]');
      await expect(dropdown).toBeVisible({ timeout: 5000 });

      // Click outside the dropdown (on the page body)
      await page.locator("body").click({ position: { x: 10, y: 10 } });

      // Dropdown should close
      await expect(dropdown).not.toBeVisible({ timeout: 3000 });
    }
  });

  test("edit action should open edit dialog", async ({ page }) => {
    const actionButton = page.locator('button:has(svg.lucide-more-horizontal)').first();

    if (await actionButton.isVisible({ timeout: 5000 })) {
      await actionButton.click();

      const dropdown = page.locator('[role="menu"]');
      await expect(dropdown).toBeVisible({ timeout: 5000 });

      // Click edit action
      const editAction = dropdown.locator('[role="menuitem"]:has-text("Chỉnh sửa")');
      await editAction.click();

      // Edit dialog should open
      const editDialog = page.locator('[role="dialog"]:has-text("Chỉnh sửa Lead")');
      await expect(editDialog).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe("Desktop Responsive - LeadDetailPanel", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");
  });

  test("should show detail panel on the right side", async ({ page }) => {
    // Click on a lead row
    const tableRow = page.locator("tbody tr").first();

    if (await tableRow.isVisible({ timeout: 5000 })) {
      await tableRow.click();

      // Wait for detail panel
      const detailPanel = page.locator('[data-testid="lead-detail-panel"]');

      // If not using data-testid, try finding the sheet
      const sheet = page.locator('[role="dialog"]').first();

      if (await sheet.isVisible({ timeout: 5000 })) {
        const sheetBox = await sheet.boundingBox();
        const viewportSize = page.viewportSize();

        expect(sheetBox).toBeTruthy();
        expect(viewportSize).toBeTruthy();

        if (sheetBox && viewportSize) {
          // On desktop, panel should be on the right side
          expect(sheetBox.x).toBeGreaterThan(viewportSize.width * 0.3);
        }
      }
    }
  });

  test("detail panel should use dropdown for actions on desktop", async ({ page }) => {
    const tableRow = page.locator("tbody tr").first();

    if (await tableRow.isVisible({ timeout: 5000 })) {
      await tableRow.click();

      // Wait for panel to open
      await page.waitForTimeout(500);

      // Find the actions button in the panel (three dots)
      const actionsButton = page.locator('[role="dialog"] button:has(svg.lucide-more-vertical)').first();

      if (await actionsButton.isVisible({ timeout: 3000 })) {
        await actionsButton.click();

        // Should show dropdown, not bottom sheet
        const dropdown = page.locator('[role="menu"]');
        await expect(dropdown).toBeVisible({ timeout: 3000 });

        // Verify it's a dropdown positioned near button
        const buttonBox = await actionsButton.boundingBox();
        const dropdownBox = await dropdown.boundingBox();

        if (buttonBox && dropdownBox) {
          const distance = Math.abs(dropdownBox.y - buttonBox.y);
          expect(distance).toBeLessThan(200);
        }
      }
    }
  });
});

test.describe("Desktop Responsive - Table Layout", () => {
  test("table should display all columns on desktop", async ({ page }) => {
    await page.goto("/leads");
    await page.waitForLoadState("networkidle");

    const table = page.locator("table");
    await expect(table).toBeVisible({ timeout: 10000 });

    // Check for key columns that should be visible on desktop
    const headers = page.locator("thead th");
    const headerCount = await headers.count();

    // Desktop should show more columns than mobile
    expect(headerCount).toBeGreaterThanOrEqual(5);

    // Check specific columns are visible
    const nameHeader = page.locator('thead th:has-text("Tên Lead")');
    await expect(nameHeader).toBeVisible();

    const stageHeader = page.locator('thead th:has-text("Giai đoạn")');
    await expect(stageHeader).toBeVisible();
  });
});
