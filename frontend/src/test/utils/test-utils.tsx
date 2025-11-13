/**
 * Test Utilities
 * Reusable testing utilities and custom render functions
 */

import { ReactElement, ReactNode } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Create a test query client with default options
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Disable retries in tests
        retry: false,
        // Disable caching in tests
        gcTime: 0,
      },
      mutations: {
        // Disable retries in tests
        retry: false,
      },
    },
    logger: {
      log: console.log,
      warn: console.warn,
      // Suppress errors in tests
      error: () => {},
    },
  })
}

// Custom render with providers
interface AllProvidersProps {
  children: ReactNode
}

function AllProviders({ children }: AllProvidersProps) {
  const testQueryClient = createTestQueryClient()

  return (
    <QueryClientProvider client={testQueryClient}>
      {children}
    </QueryClientProvider>
  )
}

function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) {
  return render(ui, { wrapper: AllProviders, ...options })
}

// Re-export everything from @testing-library/react
export * from '@testing-library/react'

// Override render with custom render
export { customRender as render }

// Export test query client creator
export { createTestQueryClient }
