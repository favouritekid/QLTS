# 📘 Frontend Architecture Playbook
## React 19 / Next.js 16 – QLTS Project

**Version:** 1.0  
**Status:** Production Standard  
**Last Updated:** 2025-12-23

---

## Table of Contents

1. [Architecture Principles (Immutable Rules)](#part-1-architecture-principles)
2. [Anti-patterns & Guardrails](#part-2-anti-patterns--guardrails)
3. [Security & Trust Boundaries](#part-3-security--trust-boundaries)
4. [Data Fetching Decision Matrix](#part-4-data-fetching-decision-matrix)
5. [Component Classification](#part-5-component-classification)
6. [Quick Reference](#part-6-quick-reference)
7. [Implementation Roadmap](#part-7-implementation-roadmap)

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

## Part 2: Anti-patterns & Guardrails

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

### ❌ NEVER DO: Overuse Server Actions

**Server Actions are NOT for:**
- File uploads with progress
- Complex multi-step wizards
- Polling / real-time data
- Operations needing offline support

**Server Actions ARE for:**
- Simple form submissions
- One-click actions (approve, reject)
- Actions that redirect after success

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

### ❌ NEVER DO: Double Submit on Forms

```typescript
// ❌ VULNERABLE - User can spam submit
<button type="submit">Submit</button>

// ✅ CORRECT - Disable during submission
<button type="submit" disabled={isPending}>
  {isPending ? 'Submitting...' : 'Submit'}
</button>
```

---

## Part 3: Security & Trust Boundaries

### 3.1 Trust Boundary Diagram

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

### 3.2 Token Lifecycle

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

### 3.3 Socket.IO Auth

| Phase | Action | Security |
|-------|--------|----------|
| Connect | Send cookies | ✅ httpOnly |
| Handshake | Backend verifies JWT | ✅ Server-side |
| Join Room | Backend assigns `user_room_{id}` | ✅ No client control |
| Reconnect | Re-verify + invalidate cache | ✅ Fresh data |
| Disconnect | Session cleanup | ✅ DB updated |

**Enforcement:**
```typescript
// ✅ CORRECT - SocketHandler only after auth
export default function DashboardLayout({ children }) {
  return (
    <>
      {children}
      <SocketHandler /> {/* Only rendered for authenticated users */}
    </>
  );
}
```

---

### 3.4 Props Data Exposure

**Rule:** Never pass sensitive data in props to Client Components that could be logged.

```typescript
// ❌ WRONG - Password visible in React DevTools
<UserSettings user={{ ...user, password: 'hashed' }} />

// ✅ CORRECT - Only safe fields
<UserSettings user={{ id, name, email, role }} />
```

---

### 3.5 Replay Attack Prevention

| Attack | Prevention |
|--------|------------|
| Form double submit | Disable button during `isPending` |
| Token reuse | Backend blacklist + rotation |
| Session fixation | New JTI on login |
| CSRF | SameSite cookies + CORS |

---

## Part 4: Data Fetching Decision Matrix

| Scenario | Approach | Reason |
|----------|----------|--------|
| Initial page data | Server Component `await` | No client JS |
| List with filters | React Query | Client-side state |
| Simple form submit | Server Action | Less bundle |
| Form with validation | RHF + React Query | Complex feedback |
| File upload | React Query | Progress tracking |
| Optimistic toggle | `useOptimistic` | Instant feedback |
| Polling | React Query `refetchInterval` | Built-in |
| Real-time | Socket + targeted invalidation | Efficient |

---

## Part 5: Component Classification

### 5.1 Server Components (No "use client")

- `app/**/page.tsx` - Pages
- `app/**/layout.tsx` - Layouts
- Data display without interaction
- Static UI (headers, footers)

### 5.2 Client Components ("use client")

- Forms with state
- Event handlers (onClick, onChange)
- Browser APIs (window, localStorage)
- Third-party client libs (Recharts, DnD)
- Real-time updates

### 5.3 Shared Components

- `components/ui/*` - shadcn/ui primitives
- Can be used in both, depends on usage

---

## Part 6: Quick Reference

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
import { useState } from 'react';
import { useRouter } from 'next/navigation';

// 2. External libs
import { useQuery } from '@tanstack/react-query';

// 3. Internal - absolute paths
import { api } from '@/lib/api/client';
import { Button } from '@/components/ui/button';

// 4. Types
import type { Lead } from '@/types/lead.types';
```

### State Decision Tree

```
Need state?
├── UI only (modal open, sidebar collapsed)?
│   └── → Zustand
├── Server data (leads, users)?
│   └── → React Query
├── Form values?
│   └── → React Hook Form
├── URL-dependent?
│   └── → Next.js Router (searchParams)
└── Derived value?
    └── → useMemo / compute inline
```

---

## Part 7: Implementation Roadmap

### Phase 1: Quick Wins (1-2 days)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 1 | Add `MobileBottomNav` component | 2h | 📱 Mobile UX |
| 2 | Add `manifest.json` (PWA) | 1h | 📱 Install capability |
| 3 | Audit touch targets ≥ 44px | 2h | ♿ Accessibility |
| 4 | Add `useOptimistic` to notifications | 2h | ⚡ Instant feedback |

---

### Phase 2: React 19 Adoption (3-5 days)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 5 | Server Actions for simple forms | 1d | 📦 Smaller bundle |
| 6 | Add `loading.tsx` to remaining routes | 2h | ⚡ Streaming |
| 7 | Implement `useActionState` for forms | 4h | ⚡ Pending states |

---

### Phase 3: Feature Gaps (2-3 days)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 8 | Build **KPI Config Admin Page** | 2d | 📊 Admin set targets |
| 9 | Build **Profile Settings Page** | 1d | 👤 User edit info |

---

### Phase 4: DX Improvements (Optional)

| # | Task | Effort | Impact |
|---|------|--------|--------|
| 10 | Add Storybook | 2d | 📚 Component catalog |
| 11 | Create ADR documentation | 2h | 📚 Decision tracking |
| 12 | Feature-based folder structure | 3d | 📁 Scalability |

---

### Priority Matrix

```
           HIGH IMPACT
               ↑
    ┌──────────┼──────────┐
    │  Phase 1 │ Phase 3  │
    │ (Mobile) │(Features)│
    │          │          │
LOW ←──────────┼──────────→ HIGH
EFFORT         │          EFFORT
    │  Phase 2 │ Phase 4  │
    │ (React19)│  (DX)    │
    │          │          │
    └──────────┼──────────┘
               ↓
           LOW IMPACT
```

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

*Playbook v1.0 – Maintained by Frontend Team*

