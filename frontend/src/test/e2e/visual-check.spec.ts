/**
 * Visual verification for Officer Dashboard
 *
 * Captures screenshots of every visible section and metric
 * to verify rendering correctness after code changes.
 *
 * Coverage:
 *  - SmartHeader (greeting, date picker, scope/unit/officer selectors)
 *  - KPI Cards Tier 1 (4 primary cards) + Tier 2 (3 secondary stats)
 *  - Performance Chart (line chart + summary stats)
 *  - Funnel Chart (pipeline stages, NCR, trend indicator)
 *  - Recommendations Panel
 *  - Workload Card (donut, capacity, availability toggle)
 *  - Today Schedule (mini calendar + activities)
 *  - Priority Actions Panel
 *  - Weekly Leaderboard (rankings, trend badges)
 *  - Annual Progress Card (target, progress bar, status)
 *  - Date preset switching (7d → 30d → Tháng này)
 */
import { test, expect } from "@playwright/test";

// Run tests sequentially — same account login causes rate limiting with parallel workers
// Use "default" mode so a single failure doesn't skip remaining tests
test.describe.configure({ mode: "default" });

const USERNAME = "nguyenhuuhieu";
const PASSWORD = "@Hieuj9993!";
const DIR = "tests/screenshots";

// ---------------------------------------------------------------------------
// Helper: login & navigate
// ---------------------------------------------------------------------------
async function loginAndNavigate(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.fill('input[name="username"]', USERNAME);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');

  // Wait for redirect — may go to /dashboard/officer or /dashboard etc.
  // Use broader pattern and longer timeout to handle rate-limit delays
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
  await page.goto("/dashboard/officer");

  // Wait for real data (not skeleton) — KPI card title is stable text
  await page.waitForSelector('text=Leads đang xử lý', { timeout: 20_000 });
  await page.waitForTimeout(2500); // let charts finish rendering
}

// ---------------------------------------------------------------------------
// Helper: safe element screenshot (skip if not visible)
// ---------------------------------------------------------------------------
async function screenshotLocator(
  locator: import("@playwright/test").Locator,
  path: string,
) {
  try {
    if (await locator.isVisible({ timeout: 3000 })) {
      await locator.screenshot({ path });
      return true;
    }
  } catch {
    /* element not found — skip */
  }
  return false;
}

// ===========================================================================
// TEST 1: Full dashboard + all sections (default 7d preset)
// ===========================================================================
test.describe("Officer Dashboard — Visual Verification", () => {
  test.setTimeout(120_000);

  test("1 — Full page & all sections (7d default)", async ({ page }) => {
    await loginAndNavigate(page);

    // ---- Full page ----
    await page.screenshot({
      path: `${DIR}/01-full-dashboard-7d.png`,
      fullPage: true,
    });

    // ---- Smart Header ----
    // The header contains greeting + controls — it's the first .container child
    const header = page.locator(".container.mx-auto > .flex").first();
    await screenshotLocator(header, `${DIR}/02-smart-header.png`);

    // ---- KPI Cards Tier 1 (4 primary cards) ----
    const kpiTier1 = page.locator(".grid.grid-cols-2.lg\\:grid-cols-4").first();
    await screenshotLocator(kpiTier1, `${DIR}/03-kpi-tier1-7d.png`);

    // Verify all 4 KPI card titles exist (use .first() to avoid strict mode on duplicate text)
    await expect(page.getByText("Tư vấn hôm nay").first()).toBeVisible();
    await expect(page.getByText("Leads đang xử lý").first()).toBeVisible();
    await expect(page.getByText("Tỉ lệ chốt đơn").first()).toBeVisible();
    await expect(page.getByText("Chuyển đổi lead mới").first()).toBeVisible();

    // ---- KPI Cards Tier 2 (secondary stats strip) ----
    const kpiTier2 = page.locator(
      ".grid.grid-cols-1.sm\\:grid-cols-3.divide-y"
    ).first();
    await screenshotLocator(kpiTier2, `${DIR}/04-kpi-tier2-secondary.png`);

    // Verify secondary stat labels
    await expect(page.getByText("Tuân thủ SLA").first()).toBeVisible();
    await expect(page.getByText("Hiệu quả tư vấn").first()).toBeVisible();
    await expect(page.getByText("Thời gian phản hồi").first()).toBeVisible();

    // ---- Performance Chart ----
    const perfChart = page.locator('text=Xu hướng hiệu suất').first();
    if (await perfChart.isVisible()) {
      const perfCard = perfChart.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(perfCard, `${DIR}/05-performance-chart.png`);
    }

    // ---- Funnel Chart ----
    const funnelTitle = page.locator('text=Phễu Pipeline').first();
    if (await funnelTitle.isVisible()) {
      const funnelCard = funnelTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(funnelCard, `${DIR}/06-funnel-chart.png`);
    }

    // Verify NCR label inside funnel
    const ncrLabel = page.getByText("Chuyển đổi ròng:").first();
    if (await ncrLabel.isVisible()) {
      // screenshot just the NCR line (metric + trend)
      const ncrRow = ncrLabel.locator("xpath=ancestor::div[contains(@class, 'flex')]").first();
      await screenshotLocator(ncrRow, `${DIR}/06b-ncr-metric.png`);
    }

    // ---- Recommendations Panel ----
    const recsTitle = page.locator(
      'h3:has-text("Khuyến nghị"), [class*="CardTitle"]:has-text("Khuyến nghị")'
    ).first();
    if (await recsTitle.isVisible()) {
      const recsCard = recsTitle.locator(
        "xpath=ancestor::div[contains(@class, 'border')]"
      ).last();
      await screenshotLocator(recsCard, `${DIR}/07-recommendations.png`);
    }

    // ---- Right column components ----

    // Annual Progress Card
    const annualTitle = page.getByText(/Chỉ tiêu năm/).first();
    if (await annualTitle.isVisible()) {
      const annualCard = annualTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(annualCard, `${DIR}/08-annual-progress.png`);
    }

    // Workload Card
    const workloadTitle = page.getByText("Khối lượng công việc").first();
    if (await workloadTitle.isVisible()) {
      const workloadCard = workloadTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(workloadCard, `${DIR}/09-workload-card.png`);
    }

    // Today Schedule
    const scheduleTitle = page.getByText("Lịch hẹn").first();
    if (await scheduleTitle.isVisible()) {
      const scheduleCard = scheduleTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(scheduleCard, `${DIR}/10-today-schedule.png`);
    }

    // Priority Actions Panel
    const priorityTitle = page.getByText("Ưu tiên hàng đầu").first();
    if (await priorityTitle.isVisible()) {
      const priorityCard = priorityTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(priorityCard, `${DIR}/11-priority-actions.png`);
    }

    // Weekly Leaderboard
    const lbTitle = page.getByText("Bảng xếp hạng").first();
    if (await lbTitle.isVisible()) {
      const lbCard = lbTitle.locator(
        "xpath=ancestor::div[contains(@class, 'rounded-')]"
      ).last();
      await screenshotLocator(lbCard, `${DIR}/12-weekly-leaderboard.png`);
    }
  });

  // =========================================================================
  // TEST 2: Date preset switching (7d → 30d → Tháng này)
  // =========================================================================
  test("2 — Date preset: 30 ngày", async ({ page }) => {
    await loginAndNavigate(page);

    // Switch to "30 ngày"
    const btn30d = page.getByRole("button", { name: "30 ngày" });
    if (await btn30d.isVisible()) {
      await btn30d.click();
      await page.waitForTimeout(4000); // data reload

      await page.screenshot({
        path: `${DIR}/13-full-dashboard-30d.png`,
        fullPage: true,
      });

      // KPI Tier 1 with 30d — label should be "Tư vấn trong kỳ"
      const kpiTier1 = page.locator(".grid.grid-cols-2.lg\\:grid-cols-4").first();
      await screenshotLocator(kpiTier1, `${DIR}/14-kpi-tier1-30d.png`);

      // Verify label changed
      await expect(page.getByText("Tư vấn trong kỳ")).toBeVisible();
    }
  });

  test("3 — Date preset: Tháng này", async ({ page }) => {
    await loginAndNavigate(page);

    const btnMonth = page.getByRole("button", { name: "Tháng này" });
    if (await btnMonth.isVisible()) {
      await btnMonth.click();
      await page.waitForTimeout(4000);

      await page.screenshot({
        path: `${DIR}/15-full-dashboard-this-month.png`,
        fullPage: true,
      });

      const kpiTier1 = page.locator(".grid.grid-cols-2.lg\\:grid-cols-4").first();
      await screenshotLocator(kpiTier1, `${DIR}/16-kpi-tier1-this-month.png`);

      // "Tháng này" is not "7d" so label should be "Tư vấn trong kỳ"
      await expect(page.getByText("Tư vấn trong kỳ")).toBeVisible();
    }
  });

  // =========================================================================
  // TEST 3: Funnel view toggle (Chart ↔ Table)
  // =========================================================================
  test("4 — Funnel view toggle: Bảng", async ({ page }) => {
    await loginAndNavigate(page);

    // Click "Bảng" toggle
    const tableBtn = page.getByRole("button", { name: "Bảng" });
    if (await tableBtn.isVisible()) {
      await tableBtn.click();
      await page.waitForTimeout(1500);

      // Screenshot the table view
      const funnelArea = page.locator('text=Phễu Pipeline').first();
      if (await funnelArea.isVisible()) {
        // Get the parent container that holds the toggle + content
        const funnelContainer = funnelArea.locator(
          "xpath=ancestor::div[contains(@class, 'space-y')]"
        ).first();
        await screenshotLocator(
          funnelContainer,
          `${DIR}/17-funnel-table-view.png`
        );
      }
    }
  });

  // =========================================================================
  // TEST 4: Tooltip interactions
  // =========================================================================
  test("5 — KPI tooltips on hover", async ({ page }) => {
    await loginAndNavigate(page);

    // Hover over "Tư vấn hôm nay" KPI card to trigger tooltip
    const consultCard = page.locator('span:text-is("Tư vấn hôm nay")').first();
    if (await consultCard.isVisible()) {
      await consultCard.hover();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${DIR}/18-tooltip-consultations.png` });
    }

    // Hover over "Tỉ lệ chốt đơn" to see win rate tooltip
    const winRateCard = page.locator('span:text-is("Tỉ lệ chốt đơn")').first();
    if (await winRateCard.isVisible()) {
      await winRateCard.hover();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${DIR}/19-tooltip-win-rate.png` });
    }

    // Hover NCR in funnel to see detailed breakdown tooltip
    const ncrText = page.locator('span:text-is("Chuyển đổi ròng:")').first();
    if (await ncrText.isVisible()) {
      await ncrText.hover();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${DIR}/20-tooltip-ncr-breakdown.png` });
    }
  });
});
