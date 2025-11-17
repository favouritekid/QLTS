# TASK 6.1: backref → back_populates Conversion Plan

## Overview

SQLAlchemy `backref` is the old implicit way of creating bidirectional relationships.
`back_populates` is the modern explicit way (recommended since SQLAlchemy 1.4+).

**Benefits of back_populates:**
- ✅ More explicit (both sides visible)
- ✅ Better type hints
- ✅ Easier to understand
- ✅ Recommended by SQLAlchemy docs

## Current Usage (6 instances found)

### 1. Notification.user → User.notifications

**File:** `app/models/notification.py:50`

**Current (backref):**
```python
# notification.py
class Notification(Base):
    user = relationship("User", backref="notifications")
```

**Required Changes:**
```python
# notification.py
class Notification(Base):
    user = relationship("User", back_populates="notifications")

# user.py (ADD THIS)
class User(Base):
    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan"  # Optional: delete notifications when user deleted
    )
```

---

### 2. NotificationPreference.user → User.notification_preference

**File:** `app/models/notification_preference.py:43`

**Current (backref):**
```python
# notification_preference.py
class NotificationPreference(Base):
    user = relationship("User", backref="notification_preference")
```

**Required Changes:**
```python
# notification_preference.py
class NotificationPreference(Base):
    user = relationship("User", back_populates="notification_preference")

# user.py (ADD THIS)
class User(Base):
    notification_preference = relationship(
        "NotificationPreference",
        back_populates="user",
        uselist=False  # One-to-one relationship
    )
```

---

### 3. UserActivity.actor → User.activities_performed

**File:** `app/models/user_activity.py:59`

**Current (backref):**
```python
# user_activity.py
class UserActivityLog(Base):
    actor = relationship(
        "User",
        foreign_keys=[actor_id],
        backref="activities_performed"
    )
```

**Required Changes:**
```python
# user_activity.py
class UserActivityLog(Base):
    actor = relationship(
        "User",
        foreign_keys=[actor_id],
        back_populates="activities_performed"
    )

# user.py (ADD THIS)
class User(Base):
    activities_performed = relationship(
        "UserActivityLog",
        back_populates="actor",
        foreign_keys="UserActivityLog.actor_id"
    )
```

---

### 4. UserActivity.target_user → User.activities_received

**File:** `app/models/user_activity.py:64`

**Current (backref):**
```python
# user_activity.py
class UserActivityLog(Base):
    target_user = relationship(
        "User",
        foreign_keys=[target_user_id],
        backref="activities_received"
    )
```

**Required Changes:**
```python
# user_activity.py
class UserActivityLog(Base):
    target_user = relationship(
        "User",
        foreign_keys=[target_user_id],
        back_populates="activities_received"
    )

# user.py (ADD THIS)
class User(Base):
    activities_received = relationship(
        "UserActivityLog",
        back_populates="target_user",
        foreign_keys="UserActivityLog.target_user_id"
    )
```

---

### 5. OfferingAcademicInfo.created_by → User.created_academic_infos

**File:** `app/models/offering_academic_info.py:112`

**Current (backref):**
```python
# offering_academic_info.py
class OfferingAcademicInfo(Base):
    created_by_user = relationship(
        "User",
        foreign_keys=[created_by],
        backref="created_academic_infos"
    )
```

**Required Changes:**
```python
# offering_academic_info.py
class OfferingAcademicInfo(Base):
    created_by_user = relationship(
        "User",
        foreign_keys=[created_by],
        back_populates="created_academic_infos"
    )

# user.py (ADD THIS)
class User(Base):
    created_academic_infos = relationship(
        "OfferingAcademicInfo",
        back_populates="created_by_user",
        foreign_keys="OfferingAcademicInfo.created_by"
    )
```

---

### 6. OfferingAcademicInfo.updated_by → User.updated_academic_infos

**File:** `app/models/offering_academic_info.py:117`

**Current (backref):**
```python
# offering_academic_info.py
class OfferingAcademicInfo(Base):
    updated_by_user = relationship(
        "User",
        foreign_keys=[updated_by],
        backref="updated_academic_infos"
    )
```

**Required Changes:**
```python
# offering_academic_info.py
class OfferingAcademicInfo(Base):
    updated_by_user = relationship(
        "User",
        foreign_keys=[updated_by],
        back_populates="updated_academic_infos"
    )

# user.py (ADD THIS)
class User(Base):
    updated_academic_infos = relationship(
        "OfferingAcademicInfo",
        back_populates="updated_by_user",
        foreign_keys="OfferingAcademicInfo.updated_by"
    )
```

---

## Summary

### Files to Modify:

1. **notification.py** (1 change)
   - Change `backref` → `back_populates`

2. **notification_preference.py** (1 change)
   - Change `backref` → `back_populates`

3. **user_activity.py** (2 changes)
   - Change 2x `backref` → `back_populates`

4. **offering_academic_info.py** (2 changes)
   - Change 2x `backref` → `back_populates`

5. **user.py** (6 additions)
   - Add 6 new relationship definitions

**Total:** 5 files modified, 12 lines changed

---

## Implementation Order

### Phase 1: Update child models (remove backref)
1. Update notification.py
2. Update notification_preference.py
3. Update user_activity.py
4. Update offering_academic_info.py

### Phase 2: Update parent model (add back_populates)
5. Update user.py (add all 6 relationships)

### Phase 3: Verification
6. Run mypy/type checker
7. Test imports
8. Verify no breaking changes

---

## Testing Strategy

After conversion, verify:

1. **No Import Errors:**
```bash
python -c "from app.models import User, Notification"
```

2. **Type Hints Work:**
```python
user: User
notifications = user.notifications  # Should have proper type hints
```

3. **Relationships Still Work:**
```python
# In services/code - verify usage patterns still work
notification.user  # Should still work
user.notifications  # Should still work
```

---

## Risk Assessment

**Risk Level:** LOW

**Why:**
- Purely refactoring (no logic change)
- Same behavior, different syntax
- Backward compatible

**Mitigation:**
- Test after each file change
- Run type checker
- Verify no circular import issues

---

## Status

**Status:** READY TO IMPLEMENT

**Time Estimate:** 2-3 hours (conservative: 4h budgeted)

**Implementation:** Convert all at once (atomic commit)

---

## Recommendation

✅ **PROCEED WITH CONVERSION**

This is a low-risk, high-value refactoring that improves code quality and follows SQLAlchemy best practices.
