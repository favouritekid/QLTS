# ADR-FE-005: submission_format_confirmed Field

## Status
Accepted

## Date
2026-01-16

## Context

The field `submission_format_confirmed` exists in the frontend `documentItemSchema` (lib/zod/admissions.ts:172) but is NOT present in the backend Pydantic `DocumentItemSchema` (admission.py:194-249).

This was flagged as a potential architecture violation during the FRONTEND_ARCHITECTURE_V3.md compliance audit (Violation #15).

## Decision

**This is an intentional FE-only UI state field.**

### Rationale

1. **Purpose**: Tracks whether the user has explicitly acknowledged/confirmed the required submission format (photo, certified copy, original) for each document.

2. **Backend doesn't need this**: The backend only validates:
   - Document code exists
   - File is uploaded
   - File format is valid (PDF, JPG, PNG)
   
   The backend does NOT care whether the user saw a UI confirmation dialog.

3. **UX Enhancement**: This field enables the frontend to:
   - Show a confirmation prompt before upload
   - Track which documents have been reviewed by the user
   - Provide visual feedback in the checklist

## Consequences

### Must Do
- Frontend MUST filter out `submission_format_confirmed` before sending to backend API
- This is handled by the update mutation which only sends fields the backend expects

### Implementation
```typescript
// In mutation hooks
const { submission_format_confirmed, ...rest } = document
await api.updateDocument(rest) // Exclude FE-only field
```

### Documentation
- Added JSDoc comment in documentItemSchema explaining FE-only nature
- This ADR serves as permanent documentation

## References
- [FRONTEND_ARCHITECTURE_V3.md](file:///d:/QLTS/frontend/FRONTEND_ARCHITECTURE_V3.md) Section 0.7.4
- [ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md](file:///C:/Users/hapha/.gemini/antigravity/brain/b9c9f738-0351-4fe2-8093-70da7773300a/ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md) Violation #15
