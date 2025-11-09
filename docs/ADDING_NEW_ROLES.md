# Adding New Roles - Developer Guide

## 📋 Overview

This guide explains how to add new roles to the system while maintaining security and consistency between frontend and backend.

## 🔐 Architecture

Our system uses a **multi-layer authorization approach**:

1. **Frontend Middleware** (Next.js) - UX optimization (early check)
2. **Backend Casbin** (FastAPI) - **SINGLE SOURCE OF TRUTH** (final authority)
3. **JWT Payload** - Embeds user role for middleware

```
User Request
    ↓
[1] Frontend Middleware (Quick check - prevent flash)
    ↓
[2] Backend Casbin (Authoritative check)
    ↓
Response
```

## ⚠️ Important Principles

- **Backend Casbin is ALWAYS the final authority**
- Frontend middleware is **optional UX optimization**
- **Always keep frontend and backend in sync**
- When in doubt, rely on backend authorization

## 📝 Steps to Add a New Role

### Example: Adding "supervisor" role with admin access

#### Step 1: Update Backend Casbin Policies

Add role policies to Casbin:

```python
# Backend_FastAPI/app/casbin_init.py or via Admin UI

# Grant supervisor access to admin resources
enforcer.add_grouping_policy("supervisor", "admin")

# Or define specific permissions:
enforcer.add_policy("supervisor", "/api/admin/*", "GET")
enforcer.add_policy("supervisor", "/api/admin/*", "POST")
```

#### Step 2: Update Frontend Role Config

Update `frontend/src/lib/config/roles.ts`:

```typescript
// BEFORE
export const ADMIN_ROLES = ["admin", "manager"] as const;

// AFTER
export const ADMIN_ROLES = ["admin", "manager", "supervisor"] as const;
```

#### Step 3: Verify JWT Embedding

Ensure backend embeds role in JWT (already implemented):

```python
# Backend_FastAPI/app/routers/auth.py (line 137-139)
access_token = security.create_access_token(
    data={"sub": user.username, "user_id": user.id, "role": user.role},
    refresh_jti=refresh_jti,
)
```

#### Step 4: Test End-to-End

```bash
# 1. Create user with new role in database
UPDATE users SET role = 'supervisor' WHERE id = 123;

# 2. Login with that user
# 3. Access /admin routes
# 4. Verify:
#    - Middleware allows access (no redirect to /dashboard)
#    - Backend allows access (no 403 error)
#    - Logs show: "Admin access granted for role 'supervisor'"
```

## 🧪 Testing Checklist

- [ ] Backend Casbin policy added
- [ ] Frontend config updated
- [ ] User can login with new role
- [ ] User can access authorized routes (frontend + backend)
- [ ] User CANNOT access unauthorized routes (403 from backend)
- [ ] Middleware logs correct role
- [ ] No TypeScript errors (`npm run type-check`)

## 🔍 Troubleshooting

### User sees "Unauthorized role" in middleware logs

**Cause:** Frontend config not updated
**Fix:** Add role to `ADMIN_ROLES` in `frontend/src/lib/config/roles.ts`

### User redirected by middleware but backend would allow

**Cause:** Frontend config more restrictive than backend
**Fix:** Update frontend config to match backend Casbin policies

### Backend returns 403 but middleware allowed

**Cause:** Frontend config more permissive than backend
**Fix:** Update backend Casbin policies (this is expected - backend is authority)

## 🎯 Best Practices

### ✅ DO:

- Always update backend Casbin first
- Update frontend config immediately after
- Test both frontend and backend
- Document role purpose and permissions
- Use semantic role names (e.g., "billing_admin" not "role5")

### ❌ DON'T:

- Don't rely solely on frontend middleware for security
- Don't add roles to frontend without backend policies
- Don't hard-code role checks in components (use config)
- Don't skip testing after adding roles

## 📚 Related Files

**Frontend:**
- `frontend/src/lib/config/roles.ts` - Role configuration
- `frontend/src/middleware.ts` - Middleware role check
- `frontend/src/lib/auth/jwt-decode.ts` - JWT decoding

**Backend:**
- `Backend_FastAPI/app/routers/auth.py` - JWT creation with role
- `Backend_FastAPI/app/core/deps.py` - Auth dependency
- `Backend_FastAPI/app/casbin_init.py` - Casbin initialization

## 🚀 Advanced: Role Hierarchy

Future enhancement to implement role inheritance:

```typescript
// frontend/src/lib/config/roles.ts
export const ROLE_HIERARCHY = {
  admin: ["manager", "user"],      // admin inherits manager + user perms
  manager: ["user"],                // manager inherits user perms
  supervisor: ["user"],             // supervisor inherits user perms
  user: [],
} as const;
```

Casbin already supports this via grouping policies:
```
enforcer.add_grouping_policy("admin", "manager")
enforcer.add_grouping_policy("manager", "user")
```

## 📞 Questions?

Contact the security team or refer to:
- [Casbin Documentation](https://casbin.org/docs/overview)
- [Next.js Middleware Docs](https://nextjs.org/docs/app/building-your-application/routing/middleware)
