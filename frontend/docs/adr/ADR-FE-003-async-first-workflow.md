# ADR-FE-003: Async-First Workflow UI

## Status
**Accepted** - 2026-01-09

## Context
Current `useSubmitAdmission` assumes immediate approval/rejection:

```typescript
// CURRENT (wrong)
onSuccess: (data) => {
  if (data.status === 'approved') {
    toast.success("Hồ sơ đã được duyệt")
  } else {
    toast.error("Hồ sơ bị từ chối")
  }
}
```

This violates FRONTEND_ARCHITECTURE_V3 Section 2.3 which mandates:
> Never assume synchronous completion. Always handle pending states.

### Current Problems
- Backend transitions `DRAFT → SUBMITTED` (pending review)
- Frontend expects immediate `APPROVED` or `REJECTED`
- User sees confusing messages when submission is actually pending

## Decision
All workflow mutations MUST handle ALL possible status outcomes using the Status Rendering Contract.

```typescript
// REQUIRED PATTERN
onSuccess: (data) => {
  const config = getStatusConfig(data.status)
  toast[config.bannerType ?? 'info'](config.bannerMessage ?? config.label)
}
```

Or explicit switch:
```typescript
onSuccess: (data) => {
  switch (data.status) {
    case 'submitted': toast.info('Hồ sơ đang chờ duyệt'); break;
    case 'resubmitted': toast.info('Hồ sơ đã được nộp lại'); break;
    case 'approved': toast.success('Hồ sơ đã được duyệt'); break;
    case 'rejected': toast.error('Hồ sơ bị từ chối'); break;
    default: toast.info(`Trạng thái: ${data.status}`);
  }
}
```

### UI Changes
1. Show "Chờ duyệt" banner for `submitted` profiles
2. Toast shows accurate status, not assumed outcome
3. Unknown statuses get graceful fallback

## Consequences

### Positive
- Accurate state representation
- Users understand their application is pending
- Future-proofed for new statuses

### Negative
- UX change: Users see "Chờ duyệt" instead of immediate result
- More statuses to handle in UI

## Implementation
- New file: `src/lib/status-config.ts`
- New component: `StatusBanner.tsx`
- Refactor: `useAdmissions.ts` mutation handlers

## Related
- [status-config.ts](file:///d:/QLTS/frontend/src/lib/status-config.ts)
- [FRONTEND_ARCHITECTURE_V3.md](file:///d:/QLTS/frontend/FRONTEND_ARCHITECTURE_V3.md) Section 2.3
