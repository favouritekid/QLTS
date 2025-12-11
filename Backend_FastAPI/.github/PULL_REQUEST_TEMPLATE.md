## Description
<!-- Brief description of changes -->

## Type of Change
- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature (non-breaking change adding functionality)
- [ ] 💥 Breaking change (fix or feature causing existing functionality to fail)
- [ ] 📝 Documentation update
- [ ] ♻️ Refactoring (no functional changes)
- [ ] 🧪 Test updates

## Related Issues
<!-- Link to related issues: Fixes #123, Closes #456 -->

---

## Architecture Compliance Checklist

### Service Layer
- [ ] Service does **NOT** import `HTTPException` from FastAPI
- [ ] Service does **NOT** import `select`, `func` from SQLAlchemy (use Repository)
- [ ] Service does **NOT** call `db.commit()` (Router handles this)
- [ ] Service uses `db.flush()` for intermediate saves (if needed)
- [ ] Service raises domain exceptions (`ResourceNotFoundError`, `BadRequest`, etc.)

### Router Layer
- [ ] Router calls `await db.commit()` after service operations
- [ ] Router executes post-commit callback: `await callback()`
- [ ] Router has `response_model` defined
- [ ] Router has rate limiting decorator `@limiter.limit()`

### Repository Pattern
- [ ] New database queries go through Repository (not direct in Service)
- [ ] Repository uses eager loading (`selectinload`, `joinedload`) appropriately
- [ ] Repository uses `db.flush()` (not `db.commit()`)

### Security
- [ ] Endpoints have permission check (`PermissionDep`)
- [ ] Resource-specific endpoints have IDOR protection (e.g., `LeadAccessDep`)
- [ ] No sensitive data exposed in response (check `response_model`)

### Code Quality
- [ ] No unused imports
- [ ] Type hints on function signatures
- [ ] Docstrings for public functions
- [ ] Logging for important operations

---

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Screenshots (if applicable)
<!-- Add screenshots for UI changes -->

## Deployment Notes
<!-- Any special deployment considerations, migrations, etc. -->
