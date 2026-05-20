/**
 * Vitest Test Setup
 * Runs before all tests to configure the test environment
 */

import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, afterAll, vi } from 'vitest'
import { server } from './mocks/server'

// Establish API mocking before all tests
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' })
})

// Reset request handlers after each test
afterEach(() => {
  server.resetHandlers()
  cleanup()
})

// Clean up after all tests are done
afterAll(() => {
  server.close()
})

// window.matchMedia polyfill for jsdom.
// MUST use a plain function (not vi.fn) because vitest config has
// `mockReset: true` + `restoreMocks: true`, which wipes any
// `vi.fn().mockImplementation(...)` body between tests — leaving
// `window.matchMedia(query)` returning undefined → `useSyncExternalStore`
// crashes when `useMediaQuery` reads `.matches`. A plain function is
// untouched by mock-reset.
function installMatchMediaStub() {
  ;(window as Window & typeof globalThis).matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as Window['matchMedia']
}

installMatchMediaStub()
beforeEach(() => {
  installMatchMediaStub()
})

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
} as unknown as typeof IntersectionObserver

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
} as unknown as typeof ResizeObserver

// Suppress console errors in tests (optional)
// global.console = {
//   ...console,
//   error: vi.fn(),
//   warn: vi.fn(),
// }
