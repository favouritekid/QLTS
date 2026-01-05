# 📘 Frontend Architecture Playbook
## React 19 / Next.js 16 – QLTS Project

**Version:** 2.0  
**Status:** Production Standard  
**Last Updated:** 2026-01-03

---

## Table of Contents

1. [Architecture Principles (Immutable Rules)](#part-1-architecture-principles)
2. [Next.js 16 cacheComponents Guide](#part-2-nextjs-16-cachecomponents-guide)
3. [Anti-patterns & Guardrails](#part-3-anti-patterns--guardrails)
4. [Security & Trust Boundaries](#part-4-security--trust-boundaries)
5. [Data Fetching Decision Matrix](#part-5-data-fetching-decision-matrix)
6. [Component Classification](#part-6-component-classification)
7. [Quick Reference](#part-7-quick-reference)
8. [Implementation Roadmap](#part-8-implementation-roadmap)

---

## Part 1: Architecture Principles

> **These are immutable rules. Violations require explicit ADR approval.**

### Principle 1: Server-First Rendering

```
DEFAULT = Server Component
"use client" = Exception, not rule
```

**Rationale:** React 19 Server Components eliminate client JS for static content, improving Core Web Vitals.

**Enforcement:**
- ✅ Pages without `"use client"` by default
- ✅ `"use client"` only in leaf interactive components
- ❌ Never add `"use client"` to layouts

---

### Principle 2: State Separation

```
UI State → Zustand
Server State → React Query
Form State → React Hook Form
URL State → Next.js Router
```

**Violations:**
- ❌ Using Zustand to cache server data
- ❌ Using React Query for UI toggles
- ❌ Syncing server state to localStorage

---

### Principle 3: Token Security

```
Access Token → httpOnly cookie (set by backend)
Refresh Token → httpOnly cookie (set by backend)
Frontend → NEVER stores tokens
```

**Violations:**
- ❌ `localStorage.setItem('token', ...)`
- ❌ `sessionStorage.setItem('token', ...)`
- ❌ Passing token via URL query params
- ❌ Reading token from non-httpOnly cookies

---

### Principle 4: Auth Gate at Edge

```
Authentication → proxy.ts (server-side)
Authorization → Backend Casbin (API level)
```

**Rationale:** Client-side auth guards leak HTML before redirect.

**Enforcement:**
- ✅ All protected routes checked in `proxy.ts`
- ❌ Never rely on client-side `useAuth()` for page protection

---

### Principle 5: Mutation Strategy

```
Simple Forms → Server Actions (preferred)
Complex Mutations → React Query mutations
Optimistic UI → useOptimistic + React Query
```

**Decision factors:**
- Need loading state? → React Query
- Need offline retry? → React Query
- Need progress tracking? → React Query
- Simple submit + redirect? → Server Action

---

### Principle 6: Real-time ≠ Full Refetch

```
Socket.IO → Targeted cache invalidation
NOT → Refetch all queries on every event
```

**Implementation:**
```typescript
// ✅ CORRECT - Targeted invalidation
socket.on('lead_updated', ({ leadId }) => {
  queryClient.invalidateQueries(['lead', leadId]);
});

// ❌ WRONG - Full refetch
socket.on('lead_updated', () => {
  queryClient.invalidateQueries(); // Too aggressive
});
```

---

### Principle 7: Mobile-First Touch Targets

```
All interactive elements ≥ 44px (min-h-11)
Spacing between touch targets ≥ 8px
```

**Rationale:** WCAG 2.1 AAA / Apple HIG compliance.

---

## Part 2: Next.js 16 cacheComponents Guide

> **🆕 NEW in v2.0** – Critical patterns for `cacheComponents: true`

### 2.1 Configuration

```typescript
// next.config.ts
const nextConfig: NextConfig = {
  reactCompiler: true,       // ✅ React Compiler enabled
  cacheComponents: true,     // ✅ Partial Prerendering enabled
};
```

---

### 2.2 Dynamic Route Requirements

**⚠️ CRITICAL:** All `[param]` routes MUST export `generateStaticParams`

```typescript
// ❌ WRONG - Build will fail with cacheComponents
export default async function Page({ params }) {
  const { id } = await params;
  return <div>Item {id}</div>;
}

// ✅ CORRECT - Placeholder pattern
export function generateStaticParams() {
  return [{ id: '__placeholder__' }];
}

export default async function Page({ params }) {
  const { id } = await params;
  
  if (id === '__placeholder__') {
    notFound();
  }
  
  return <div>Item {id}</div>;
}
```

**Applied to:**
- `/leads/[id]/page.tsx` ✅
- `/admissions/[id]/page.tsx` ✅
- `/admin/users/[id]/page.tsx` ✅

---

### 2.3 Suspense Boundaries

**Rule:** Async data fetching MUST be wrapped in `<Suspense>`

```typescript
// ✅ CORRECT Pattern - SSR with Suspense
import { Suspense } from 'react';
import { serverApi } from '@/lib/api/server';

function LoadingFallback() {
  return <Skeleton className="h-96" />;
}

async function DataContent({ id }: { id: number }) {
  const data = await serverApi.leads.getLead(id);
  return <LeadDetailClient initialData={data} />;
}

export default async function Page({ params }) {
  const { id } = await params;
  return (
    <Suspense fallback={<LoadingFallback />}>
      <DataContent id={Number(id)} />
    </Suspense>
  );
}
```

---

### 2.4 `use cache` Directive

**NEW in Next.js 16:** Cache expensive computations at build time

```typescript
// ✅ Cache data that changes infrequently
async function getStatistics() {
  'use cache';
  return await fetchDashboardStats();
}

// ✅ Cache with custom lifetime
import { cacheLife } from 'next/cache';

async function getLeaderboard() {
  'use cache';
  cacheLife('hours'); // Cache for 1 hour
  return await fetchLeaderboard();
}
```

**Use `use cache` for:**
- Dashboard statistics
- Pipeline aggregations
- User leaderboards
- Static configuration data

**DO NOT use `use cache` for:**
- User-specific data
- Real-time data
- Form submissions

---

### 2.5 Incompatible Route Segment Configs

**⚠️ NOT allowed with `cacheComponents: true`:**

```typescript
// ❌ WILL FAIL - Route segment configs incompatible
export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';
```

**Instead, use:**
- `generateStaticParams` with placeholder
- `<Suspense>` for dynamic content
- `use cache` for cacheable data

---

### 2.6 Rendering Strategy Summary

```
┌─────────────────────────────────────────────────────────────┐
│              NEXT.JS 16 RENDERING STRATEGIES                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─── BUILD TIME ───┐    ┌─── REQUEST TIME ───┐            │
│  │                  │    │                    │            │
│  │  Static Shell    │    │  Dynamic Content   │            │
│  │  (HTML + RSC)    │    │  (Streamed)        │            │
│  │                  │    │                    │            │
│  │  • Layouts       │    │  • User data       │            │
│  │  • Loading UI    │    │  • Auth-dependent  │            │
│  │  • Static text   │    │  • Filtered lists  │            │
│  │  • use cache     │    │  • <Suspense>      │            │
│  │                  │    │                    │            │
│  └──────────────────┘    └────────────────────┘            │
│                                                             │
│  ═══════════════════════════════════════════════════════   │
│                    PARTIAL PRERENDERING                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 3: Anti-patterns & Guardrails

### ❌ NEVER DO: Token in Client Storage

```typescript
// ❌ CRITICAL SECURITY VIOLATION
localStorage.setItem('accessToken', token);
sessionStorage.setItem('accessToken', token);
document.cookie = `token=${token}`; // Without httpOnly

// ✅ CORRECT - Token handled by backend cookies
// Frontend never sees or stores tokens
```

---

### ❌ NEVER DO: dangerouslySetInnerHTML with User Data

```typescript
// ❌ XSS VULNERABILITY
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// ✅ CORRECT - React auto-escapes
<div>{userInput}</div>

// ✅ IF HTML NEEDED - Sanitize first
import DOMPurify from 'dompurify';
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />
```

---

### ❌ NEVER DO: Optimistic for Destructive Actions

```typescript
// ❌ DANGEROUS - Can't undo delete
const deleteOptimistic = useOptimistic(...);
deleteOptimistic(leadId); // User thinks it's deleted
await deleteLead(leadId); // But API might fail!

// ✅ CORRECT - Wait for confirmation
const mutation = useMutation({
  mutationFn: deleteLead,
  onSuccess: () => {
    queryClient.invalidateQueries(['leads']);
    toast.success('Deleted');
  }
});
```

**Rule:** `useOptimistic` only for:
- Toggle states (read/unread)
- Like/favorite
- Status changes that can be reverted

---

### ❌ NEVER DO: Fetch in Deeply Nested Components

```typescript
// ❌ WATERFALL - Each component waits for parent
function DeepChild() {
  const { data } = useQuery(['child-data']); // Starts after render
  return <div>{data}</div>;
}

// ✅ CORRECT - Parallel fetch at page level
async function Page() {
  const [user, leads] = await Promise.all([
    getUser(),
    getLeads()
  ]);
  return <DeepChild leads={leads} />;
}
```

---

### ❌ NEVER DO: Zustand as Server Cache

```typescript
// ❌ WRONG - Reinventing React Query
const useStore = create((set) => ({
  leads: [],
  fetchLeads: async () => {
    const data = await api.get('/leads');
    set({ leads: data }); // Manual cache
  }
}));

// ✅ CORRECT - React Query handles caching
const { data: leads } = useQuery({
  queryKey: ['leads'],
  queryFn: getLeads,
  staleTime: 60_000
});
```

---

### ❌ NEVER DO: "use client" in Pages/Layouts

```typescript
// ❌ WRONG - Defeats Server Components
// app/leads/page.tsx
"use client";
export default function LeadsPage() { ... }

// ✅ CORRECT - Page as Server, interactivity in components
// app/leads/page.tsx
export default async function LeadsPage() {
  const leads = await getLeads();
  return <LeadTable leads={leads} />; // Only LeadTable is client
}
```

---

### ❌ NEVER DO: Empty generateStaticParams

```typescript
// ❌ WRONG - Will fail with cacheComponents
export function generateStaticParams() {
  return []; // Empty array NOT allowed
}

// ✅ CORRECT - Use placeholder
export function generateStaticParams() {
  return [{ id: '__placeholder__' }];
}
```

---

## Part 4: Security & Trust Boundaries

### 4.1 Trust Boundary Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRUST ZONES                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    ZONE 0: UNTRUSTED                        │ │
│  │                                                              │ │
│  │  • Browser localStorage/sessionStorage                       │ │
│  │  • URL query parameters                                      │ │
│  │  • User input (forms, text fields)                          │ │
│  │  • Third-party scripts                                       │ │
│  │                                                              │ │
│  │  🔴 RULE: Never trust. Always validate.                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    ZONE 1: SEMI-TRUSTED                     │ │
│  │                                                              │ │
│  │  • Next.js proxy.ts (edge middleware)                       │ │
│  │  • Server Components                                         │ │
│  │  • Server Actions                                            │ │
│  │                                                              │ │
│  │  🟡 RULE: Can read JWT claims, but CANNOT authorize.        │ │
│  │           UX optimization only.                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    ZONE 2: TRUSTED                          │ │
│  │                                                              │ │
│  │  • Backend FastAPI                                           │ │
│  │  • Casbin RBAC                                               │ │
│  │  • Database                                                  │ │
│  │  • Redis session store                                       │ │
│  │                                                              │ │
│  │  🟢 RULE: Final authority for all authorization.            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

### 4.2 Token Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                     TOKEN LIFECYCLE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [Login] ───► [Backend sets httpOnly cookies] ───► [Browser]    │
│                                                                  │
│  [Request] ───► [Browser auto-sends cookies] ───► [Backend]     │
│                                                                  │
│  [401 Error] ───► [Axios interceptor] ───► [Refresh attempt]    │
│        │                                          │              │
│        ▼                                          ▼              │
│  ┌──────────┐                           ┌─────────────────┐     │
│  │ Mutex    │  Only 1 refresh at a time │ Queue others    │     │
│  │ Lock     │◄──────────────────────────│ for retry       │     │
│  └──────────┘                           └─────────────────┘     │
│        │                                                         │
│        ▼                                                         │
│  [Success] ───► [100ms wait] ───► [Retry queued requests]       │
│                                                                  │
│  [Failure] ───► [Clear cookies] ───► [Redirect /login]         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 5: Data Fetching Decision Matrix

| Scenario | Approach | Reason |
|----------|----------|--------|
| Initial page data | Server Component `await` + Suspense | No client JS |
| List with filters | React Query | Client-side state |
| Simple form submit | Server Action | Less bundle |
| Form with validation | RHF + React Query | Complex feedback |
| File upload | React Query | Progress tracking |
| Optimistic toggle | `useOptimistic` | Instant feedback |
| Polling | React Query `refetchInterval` | Built-in |
| Real-time | Socket + targeted invalidation | Efficient |
| **Static aggregations** | **`use cache`** | **🆕 Prerendered** |

---

## Part 6: Component Classification

### 6.1 Server Components (No "use client")

- `app/**/page.tsx` - Pages
- `app/**/layout.tsx` - Layouts
- Data display without interaction
- Static UI (headers, footers)

### 6.2 Client Components ("use client")

- Forms with state
- Event handlers (onClick, onChange)
- Browser APIs (window, localStorage)
- Third-party client libs (Recharts, DnD)
- Real-time updates

### 6.3 Co-location Pattern

```
app/(dashboard)/leads/[id]/
├── page.tsx              # Server Component (SSR)
├── loading.tsx           # Loading UI
├── error.tsx             # Error boundary (Client)
└── _components/
    └── LeadDetailClient.tsx  # Client Component
```

---

## Part 7: Quick Reference

### File Naming

| Type | Pattern | Example |
|------|---------|---------|
| Page | `page.tsx` | `app/leads/page.tsx` |
| Layout | `layout.tsx` | `app/(dashboard)/layout.tsx` |
| Loading | `loading.tsx` | `app/leads/loading.tsx` |
| Error | `error.tsx` | `app/leads/error.tsx` |
| Hook | `use*.ts` | `useLeads.ts` |
| Type | `*.types.ts` | `lead.types.ts` |

### Import Order

```typescript
// 1. React/Next
import { useState, Suspense } from 'react';
import { notFound } from 'next/navigation';

// 2. External libs
import { useQuery } from '@tanstack/react-query';

// 3. Internal - server API
import { serverApi } from '@/lib/api/server';

// 4. Internal - components
import { Button } from '@/components/ui/button';

// 5. Types
import type { Lead } from '@/types/lead.types';
```

### Dynamic Route Checklist

- [ ] `generateStaticParams` exported with placeholder
- [ ] `notFound()` called for placeholder
- [ ] Async content wrapped in `<Suspense>`
- [ ] `loading.tsx` exists for route
- [ ] `error.tsx` exists for route

---

## Part 8: Implementation Roadmap

> **Last Audit:** 2026-01-03 | **Next Review:** Monthly

### Phase 1: cacheComponents Compliance ✅ COMPLETED

| # | Task | Status |
|---|------|--------|
| 1 | Add `generateStaticParams` to `/leads/[id]` | ✅ Done |
| 2 | Add `generateStaticParams` to `/admissions/[id]` | ✅ Done |
| 3 | Add `generateStaticParams` to `/admin/users/[id]` | ✅ Done |
| 4 | Build passes with cacheComponents | ✅ Done |

---

### Phase 2: `use cache` Adoption ⏳ NOT STARTED

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 5 | Add `use cache` to dashboard statistics | 2h | ⚡ Faster load |
| 6 | Add `use cache` to pipeline aggregations | 2h | ⚡ Faster load |
| 7 | Add `cacheLife` for time-sensitive data | 2h | 🔄 Fresh data |

---

### Phase 3: Error Boundary Coverage ⏳ PARTIAL

| # | Task | Status |
|---|------|--------|
| 8 | Add `error.tsx` to `/settings/*` | ❌ Not done |
| 9 | Add `error.tsx` to `/notifications` | ❌ Not done |
| 10 | Add `error.tsx` to `/profile` | ❌ Not done |

---

### Phase 4: Mobile UX & PWA ⏳ NOT STARTED

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 11 | Add `MobileBottomNav` component | 2h | 📱 Mobile UX |
| 12 | Add `manifest.json` (PWA) | 1h | � Install capability |
| 13 | Audit touch targets ≥ 44px | 2h | ♿ Accessibility |

---

## Appendix: ADR Template

When violating principles, create an ADR:

```markdown
# ADR-001: [Title]

## Status
Accepted / Proposed / Deprecated

## Context
Why do we need to violate the principle?

## Decision
What we decided to do.

## Consequences
What are the trade-offs?

## Alternatives Considered
What else could we have done?
```

---

*Playbook v2.0 – Updated for Next.js 16 cacheComponents – Maintained by Frontend Team*
