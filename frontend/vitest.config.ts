import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    // Test environment
    environment: 'jsdom',

    // Setup files
    setupFiles: ['./src/test/setup.ts'],

    // Coverage configuration
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        'dist/',
        '.next/',
      ],
      // Coverage thresholds
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },

    // Global test settings
    globals: true,

    // Include patterns
    include: ['src/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}'],

    // Exclude patterns
    exclude: [
      'node_modules',
      'dist',
      '.next',
      'coverage',
      '**/*.config.*',
      // Playwright E2E specs use `@playwright/test` API, incompatible with vitest
      // (FU PR-CO-1: surfaced when full vitest run added at PR gate)
      'src/test/e2e/**',
    ],

    // Test timeout
    testTimeout: 10000,

    // Hooks timeout
    hookTimeout: 10000,

    // Mock reset before each test
    mockReset: true,

    // Clear mocks before each test
    clearMocks: true,

    // Restore mocks after each test
    restoreMocks: true,
  },

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
