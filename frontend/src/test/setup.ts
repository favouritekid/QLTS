/**
 * Vitest Test Setup
 * Runs before all tests to configure the test environment
 */

import '@testing-library/jest-dom'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, afterAll, vi } from 'vitest'
import { server } from './mocks/server'
import {
  dangChanRequestRo,
  kiemRequestRoCuoiCa,
  xuLyRequestKhongHandler,
} from './review-sessions-msw'

// Establish API mocking before all tests — `listen()` ĐÚNG MỘT lần trong cả bộ test: gọi lần hai thì
// MSW gắn thêm listener "request" ⇒ mọi request đi qua handler hai lần (đối chiếu CI F4 lượt 2).
// Request không handler: tệp thường ⇒ như chiến lược 'warn' cũ; tệp test lần xét đã `chanRequestRo()`
// ⇒ ghi lại + máy giả trả 500 (xem `./review-sessions-msw.ts`).
beforeAll(() => {
  server.listen({ onUnhandledRequest: xuLyRequestKhongHandler })
})

// Reset request handlers after each test
afterEach(async () => {
  if (!dangChanRequestRo()) {
    server.resetHandlers()
    cleanup()
    return
  }
  // Tệp đã chặn request rò: dọn cây React TRƯỚC (không phát request mới), chờ request đang bay rồi
  // kiểm; `resetHandlers` LUÔN chạy — vitest bỏ các afterEach còn lại khi một afterEach ném, nên ca
  // đỏ không được để lại cây / handler cho ca sau.
  cleanup()
  try {
    await kiemRequestRoCuoiCa()
  } finally {
    server.resetHandlers()
  }
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
