# Testing Guide for QLTS Frontend

## Overview

This frontend uses a comprehensive testing setup with:
- **Vitest** - Fast unit and integration testing
- **React Testing Library** - Component testing
- **MSW (Mock Service Worker)** - API mocking
- **Playwright** - End-to-end testing

## Test Structure

```
src/test/
├── setup.ts                 # Global test setup
├── mocks/
│   ├── server.ts            # MSW server setup
│   ├── handlers/            # API mock handlers
│   │   ├── index.ts
│   │   ├── auth.ts
│   │   ├── leads.ts
│   │   └── pipeline.ts
│   └── data/                # Mock data
│       ├── leads.ts
│       └── pipeline.ts
├── utils/
│   └── test-utils.tsx       # Custom render utilities
└── e2e/                     # Playwright E2E tests
    └── (E2E test files)
```

## Running Tests

### Unit & Integration Tests (Vitest)

```bash
# Run all tests
npm run test

# Run tests in watch mode
npm run test:watch

# Run tests with UI
npm run test:ui

# Run tests with coverage
npm run test:coverage
```

### End-to-End Tests (Playwright)

```bash
# Run E2E tests
npm run test:e2e

# Run E2E tests with UI
npm run test:e2e:ui

# Debug E2E tests
npm run test:e2e:debug
```

## Writing Tests

### 1. API Client Tests

Test API functions with MSW:

```typescript
// src/lib/api/leads.test.ts
import { describe, it, expect } from 'vitest'
import { server } from '@/test/mocks/server'
import { http, HttpResponse } from 'msw'
import { api } from './client'

describe('Leads API', () => {
  it('should fetch leads', async () => {
    // Mock API response
    server.use(
      http.get('/api/leads', () => {
        return HttpResponse.json({
          total_count: 10,
          leads: [...],
        })
      })
    )

    // Make API call
    const response = await api.get('/api/leads')

    // Assert response
    expect(response.data.total_count).toBe(10)
  })
})
```

### 2. React Hook Tests

Test custom hooks with React Query:

```typescript
// src/hooks/useLeads.test.ts
import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useLeads } from './useLeads'

describe('useLeads', () => {
  it('should fetch leads successfully', async () => {
    // Setup query client
    const queryClient = new QueryClient()
    const wrapper = ({ children }) => (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    )

    // Render hook
    const { result } = renderHook(() => useLeads({ page: 1 }), { wrapper })

    // Wait for data
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    // Assert data
    expect(result.current.data).toBeDefined()
    expect(result.current.data.leads).toBeInstanceOf(Array)
  })
})
```

### 3. Component Tests

Test React components with RTL:

```typescript
// src/components/leads/LeadCard.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@/test/utils/test-utils'
import { LeadCard } from './LeadCard'

describe('LeadCard', () => {
  const mockLead = {
    id: 1,
    full_name: 'Test Lead',
    email: 'test@example.com',
    phone: '0901234567',
    status: 'new',
    lead_score: 75,
  }

  it('should render lead information', () => {
    render(<LeadCard lead={mockLead} />)

    expect(screen.getByText('Test Lead')).toBeInTheDocument()
    expect(screen.getByText('test@example.com')).toBeInTheDocument()
    expect(screen.getByText('0901234567')).toBeInTheDocument()
  })

  it('should display lead score badge', () => {
    render(<LeadCard lead={mockLead} />)

    const scoreBadge = screen.getByText('75')
    expect(scoreBadge).toBeInTheDocument()
  })

  it('should handle click events', async () => {
    const onClickMock = vi.fn()
    render(<LeadCard lead={mockLead} onClick={onClickMock} />)

    const card = screen.getByRole('button')
    await userEvent.click(card)

    expect(onClickMock).toHaveBeenCalledWith(mockLead)
  })
})
```

### 4. E2E Tests (Playwright)

Test full user flows:

```typescript
// src/test/e2e/leads/create-lead.spec.ts
import { test, expect } from '@playwright/test'

test.describe('Create Lead Flow', () => {
  test('should create a new lead successfully', async ({ page }) => {
    // Navigate to leads page
    await page.goto('/leads')

    // Click create button
    await page.click('button:has-text("Create Lead")')

    // Fill form
    await page.fill('input[name="full_name"]', 'E2E Test Lead')
    await page.fill('input[name="email"]', 'e2e@example.com')
    await page.fill('input[name="phone"]', '0901234567')
    await page.selectOption('select[name="source"]', 'website')

    // Submit form
    await page.click('button:has-text("Create")')

    // Verify success
    await expect(page.locator('text=Lead created successfully')).toBeVisible()
    await expect(page.locator('text=E2E Test Lead')).toBeVisible()
  })
})
```

## Mock Service Worker (MSW)

### Adding New Mock Handlers

1. Create handler file in `src/test/mocks/handlers/`:

```typescript
// src/test/mocks/handlers/consultations.ts
import { http, HttpResponse } from 'msw'

export const consultationHandlers = [
  http.get('/api/consultations', () => {
    return HttpResponse.json({
      consultations: [...],
    })
  }),
]
```

2. Import in `src/test/mocks/handlers/index.ts`:

```typescript
import { consultationHandlers } from './consultations'

export const handlers = [
  ...authHandlers,
  ...leadHandlers,
  ...consultationHandlers, // Add here
]
```

### Overriding Handlers in Tests

```typescript
import { server } from '@/test/mocks/server'
import { http, HttpResponse } from 'msw'

it('should handle specific scenario', async () => {
  // Override default handler for this test
  server.use(
    http.get('/api/leads', () => {
      return HttpResponse.json({
        total_count: 0,
        leads: [],
      })
    })
  )

  // Test with empty response
  const response = await api.get('/api/leads')
  expect(response.data.leads).toHaveLength(0)
})
```

## Coverage Goals

| Component | Target Coverage | Status |
|-----------|----------------|--------|
| API Clients | 100% | 🔜 |
| Hooks | 90% | 🔜 |
| Components | 80% | 🔜 |
| Utilities | 95% | 🔜 |

## Best Practices

### 1. Test Naming

```typescript
// ✅ Good
describe('LeadCard', () => {
  it('should render lead information', () => {})
  it('should display score badge when score > 0', () => {})
  it('should call onClick when card is clicked', () => {})
})

// ❌ Bad
describe('LeadCard', () => {
  it('test 1', () => {})
  it('renders', () => {})
})
```

### 2. Test Structure (AAA Pattern)

```typescript
it('should create a lead', async () => {
  // Arrange: Setup test data and mocks
  const leadData = { ... }
  server.use(...)

  // Act: Perform the action
  const result = await createLead(leadData)

  // Assert: Verify the outcome
  expect(result).toBeDefined()
  expect(result.id).toBe(1)
})
```

### 3. Testing Async Operations

```typescript
// ✅ Good: Use waitFor for async updates
it('should load leads', async () => {
  render(<LeadsList />)

  await waitFor(() => {
    expect(screen.getByText('Lead 1')).toBeInTheDocument()
  })
})

// ❌ Bad: Don't use arbitrary delays
it('should load leads', async () => {
  render(<LeadsList />)
  await new Promise((resolve) => setTimeout(resolve, 1000))
  expect(screen.getByText('Lead 1')).toBeInTheDocument()
})
```

### 4. Cleanup

```typescript
// Cleanup is automatic with afterEach in setup.ts
// But you can add custom cleanup if needed

afterEach(() => {
  cleanup() // From @testing-library/react
  server.resetHandlers()
})
```

## Debugging Tests

### 1. Debug Single Test

```bash
# Run specific test file
npm run test -- src/lib/api/leads.test.ts

# Run tests matching pattern
npm run test -- --grep "should fetch leads"
```

### 2. Debug in VS Code

Add to `.vscode/launch.json`:

```json
{
  "type": "node",
  "request": "launch",
  "name": "Debug Vitest Tests",
  "runtimeExecutable": "npm",
  "runtimeArgs": ["run", "test"],
  "console": "integratedTerminal"
}
```

### 3. Use screen.debug()

```typescript
it('should render component', () => {
  render(<MyComponent />)

  // Print current DOM
  screen.debug()

  // Or print specific element
  screen.debug(screen.getByTestId('my-element'))
})
```

## CI/CD Integration

Tests run automatically in CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run unit tests
  run: npm run test:coverage

- name: Run E2E tests
  run: npm run test:e2e

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## Troubleshooting

### Issue: "Cannot find module '@/test/...'"

**Solution:** Ensure `vitest.config.ts` has correct path alias:

```typescript
resolve: {
  alias: {
    '@': path.resolve(__dirname, './src'),
  },
}
```

### Issue: "fetch is not defined"

**Solution:** Ensure `jsdom` environment is set in `vitest.config.ts`:

```typescript
test: {
  environment: 'jsdom',
}
```

### Issue: MSW handlers not working

**Solution:** Check that `src/test/setup.ts` is configured in `vitest.config.ts`:

```typescript
test: {
  setupFiles: ['./src/test/setup.ts'],
}
```

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [MSW Documentation](https://mswjs.io/)
- [Playwright Documentation](https://playwright.dev/)

## Next Steps

1. ✅ Setup testing infrastructure
2. 🔜 Write API client tests
3. 🔜 Write hook tests
4. 🔜 Write component tests
5. 🔜 Write E2E tests
6. 🔜 Achieve 80%+ coverage
