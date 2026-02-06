# ADR-FE-002: Permission-Based Rendering over Role-Based

## Status
**Accepted** - 2026-01-09

## Context
Current code checks status to determine button visibility:

```typescript
// CURRENT (forbidden)
const isDraft = profile?.status === "draft" || profile?.status === "rejected"
const isApproved = profile?.status === "approved"
{isDraft && <SubmitButton />}
{isApproved && <EnrollButton />}
```

This violates FRONTEND_ARCHITECTURE_V3 Section 2.2 which mandates:
> Show/hide UI based on backend-provided permissions, NOT client-side role checks.

### Current Problems
- Frontend infers `canEdit` from status (business logic leak)
- No RBAC: Manager-only buttons not controlled
- Same user sees same buttons regardless of role

## Decision
All action visibility MUST use `usePermissions(resource).can('action')` pattern.

```typescript
// REQUIRED PATTERN
const { can } = usePermissions(profile)
{can('edit') && <SaveButton />}
{can('submit') && <SubmitButton />}
{can('approve') && <ApproveButton />}
{can('enroll') && <EnrollButton />}
```

### Rules
1. ❌ FORBIDDEN: Direct property access `{profile.can_submit && <Button />}`
2. ✅ REQUIRED: Via hook `{can('submit') && <Button />}`
3. Backend computes permissions based on user role + resource state + Casbin policy

## Consequences

### Positive
- Backend controls authorization, frontend just renders
- Proper RBAC: Managers see different buttons than Applicants
- Casbin policies applied correctly
- Single source of truth for permissions

### Negative
- Requires backend to return `permissions` object
- All action buttons must be refactored

### Dependencies
- Backend must return `permissions: Record<string, boolean>` in responses
- Phase 0 must complete before Phase 1

## Implementation
- New files: `src/lib/permissions.ts`, `src/hooks/usePermissions.ts`
- Refactor: `AdmissionActions.tsx`, `AdmissionDetailClient.tsx`

## Related
- [ADR-FE-001](./ADR-FE-001-delete-useAdmissionValidation.md)
- [FRONTEND_ARCHITECTURE_V3.md](file:///d:/QLTS/frontend/FRONTEND_ARCHITECTURE_V3.md) Section 2.2
