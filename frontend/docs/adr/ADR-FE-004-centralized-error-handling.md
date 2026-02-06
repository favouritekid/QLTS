# ADR-FE-004: Centralized Error Handling

## Status
**Accepted** - 2026-01-09

## Context
Each hook handles errors differently:

```typescript
// Module A
toast.error("Lỗi cập nhật", { description: message })

// Module B
toast.error("Đã có lỗi xảy ra")

// Module C (no 409 handling)
console.error(error)
```

This leads to:
- Inconsistent user experience
- 409 Conflict not handled properly (user loses data)
- 403 Permission errors shown as generic errors
- No way to recover from conflicts

## Decision
All mutations MUST use `handleApiError()` from `src/lib/error-handler.ts`.

```typescript
// REQUIRED PATTERN
useMutation({
  mutationFn: updateProfile,
  onError: (error) => handleApiError(error, {
    queryClient,
    invalidateKeys: [profileKeys.detail(id)],
    context: 'cập nhật hồ sơ',
  })
})
```

### Error Taxonomy
| HTTP Status | Error Code | UI Behavior |
|-------------|------------|-------------|
| 400 | VALIDATION_FAILED | Show field errors, callback |
| 401 | AUTHENTICATION_REQUIRED | "Phiên đăng nhập hết hạn" |
| 403 | PERMISSION_DENIED | "Không có quyền" |
| 404 | RESOURCE_NOT_FOUND | "Không tìm thấy" |
| 409 | STATE_CONFLICT | "Làm mới" action button |
| 422 | BUSINESS_RULE_VIOLATION | Show business error |
| 429 | RATE_LIMITED | "Thử lại sau" |
| 5xx | SERVER_ERROR | "Lỗi hệ thống" |

### Rules
1. ❌ FORBIDDEN: Direct `toast.error()` in mutation handlers
2. ✅ REQUIRED: Use `handleApiError()` for all mutations
3. Provide `invalidateKeys` for 409 recovery
4. Optional: `onValidation` callback for form field errors

## Consequences

### Positive
- Consistent UX across all modules
- Proper 409 Conflict recovery
- 403 shows meaningful message
- Centralized Vietnamese translations

### Negative
- All existing `onError` handlers must be updated
- Requires Phase 2.4 audit of all mutations

## Implementation
- New file: `src/lib/error-handler.ts`
- Audit: All hooks in `src/hooks/*.ts`
- Test: V.5 Manual 409 Conflict handling

## Related
- [error-handler.ts](file:///d:/QLTS/frontend/src/lib/error-handler.ts)
- [FRONTEND_ARCHITECTURE_V3.md](file:///d:/QLTS/frontend/FRONTEND_ARCHITECTURE_V3.md) Section 2.4
