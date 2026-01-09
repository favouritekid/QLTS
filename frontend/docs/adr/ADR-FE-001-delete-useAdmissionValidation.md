# ADR-FE-001: Delete useAdmissionValidation Hook

## Status
**Accepted** - 2026-01-09

## Context
The `useAdmissionValidation` hook (127 lines) in `src/app/(dashboard)/admissions/[id]/_hooks/useAdmissionValidation.ts` calculates eligibility, GPA thresholds, and document requirements on the frontend.

This violates FRONTEND_ARCHITECTURE_V3 Section 0.5.1 which mandates:
> **Eligibility** | Backend Service | READ ONLY. No local calculation.

### Current Problems
- Frontend calculates `isEligible` based on local validation
- Frontend compares GPA against `minGpa` threshold (line 82-84)
- Frontend determines step status (`stepsStatus`) locally
- Frontend uses `useWatch({ control })` causing re-render storms

## Decision
**DELETE the entire hook.** Replace with reading backend-provided fields:

```typescript
// BEFORE (deleted)
const { stepsStatus, isEligible, missingItems, metrics } = useAdmissionValidation(form, profile)

// AFTER
const { eligibility_status, validation_errors, available_actions } = profile
```

## Consequences

### Positive
- Single source of truth for eligibility (backend)
- No more re-render storms (removed `useWatch`)
- Consistent behavior across devices/sessions
- Backend can change rules without frontend deployment

### Negative
- Requires backend to compute and return these fields
- Temporary need for `permission-adapter` fallback during migration

### Risks
- If backend doesn't provide fields, UI will show empty state
- Migration period may have inconsistent behavior

## Mitigation
1. Use `permission-adapter.ts` for backward compatibility
2. Feature flag `USE_PERMISSION_HOOK` for gradual rollout
3. Test V.8: Feature flag OFF test before production

## Related
- [FRONTEND_ARCHITECTURE_V3.md](file:///d:/QLTS/frontend/FRONTEND_ARCHITECTURE_V3.md)
- [implementation_plan.md](file:///C:/Users/hapha/.gemini/antigravity/brain/e4e0f85f-eca1-4c6f-afa1-291bc922cba4/implementation_plan.md)
