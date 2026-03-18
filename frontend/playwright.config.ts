import { defineConfig, devices } from '@playwright/test'
import path from 'path'

// Path to store authentication state
const authFile = path.join(__dirname, 'src/test/.auth/user.json')

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './src/test/e2e',

  /* Run tests in files in parallel */
  fullyParallel: true,

  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,

  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,

  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,

  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [
    ['html'],
    ['list'],
    ['json', { outputFile: 'test-results/results.json' }],
  ],

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',

    /* Screenshot on failure */
    screenshot: 'only-on-failure',

    /* Video on failure */
    video: 'retain-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    // Auth setup — officer account (no MFA), runs first
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
    },

    // Desktop chromium — smoke + responsive + ui-smoke
    {
      name: 'chromium',
      testMatch: /smoke-all-pages\.spec\.ts|(responsive|ui-smoke)\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: authFile,
      },
      dependencies: ['setup'],
    },

    // Desktop firefox — smoke only (full matrix nightly with @nightly tag)
    {
      name: 'firefox',
      testMatch: /smoke-all-pages\.spec\.ts/,
      use: {
        ...devices['Desktop Firefox'],
        storageState: authFile,
      },
      dependencies: ['setup'],
    },

    // Desktop webkit — smoke only
    {
      name: 'webkit',
      testMatch: /smoke-all-pages\.spec\.ts/,
      use: {
        ...devices['Desktop Safari'],
        storageState: authFile,
      },
      dependencies: ['setup'],
    },

    // Mobile officer suite — officer storageState, no /admin/* routes
    {
      name: 'Mobile_Chrome',
      testMatch: /mobile_checks(|_part2|_final)\.spec\.ts/,
      use: {
        ...devices['Pixel 5'],
        storageState: authFile,
      },
      dependencies: ['setup'],
    },
    {
      name: 'Mobile_Safari',
      testMatch: /mobile_checks(|_part2|_final)\.spec\.ts/,
      use: {
        ...devices['iPhone 12'],
        storageState: authFile,
      },
      dependencies: ['setup'],
    },

    // Mobile admin suite — API login with TOTP (no storageState, no setup dependency)
    {
      name: 'Mobile_Admin',
      testMatch: /mobile_checks_admin\.spec\.ts/,
      use: {
        ...devices['Pixel 5'],
      },
    },

    // E2E workflow — all API-level workflow tests, login inline with MFA
    // IMPORTANT: run with --workers=1 (npm run test:e2e:workflow) to prevent concurrent admin
    // logins from hitting rate-limiting. Serial per-file is enforced via test.describe.configure.
    {
      name: 'e2e-workflow',
      testMatch: /(lifecycle|workflow|bulk|regression|settings-security)\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],

  /* Run your local dev server before starting the tests */
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
})
