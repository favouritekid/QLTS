/**
 * MSW Server Setup
 * Mock Service Worker for intercepting API requests in tests
 */

import { setupServer } from 'msw/node'
import { handlers } from './handlers'

// Setup MSW server with all handlers
export const server = setupServer(...handlers)
