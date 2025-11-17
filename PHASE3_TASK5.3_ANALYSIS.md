# TASK 5.3: Move Model Business Logic to Services - Analysis

## Models Analyzed

### 1. NotificationPreference Model

**File:** `app/models/notification_preference.py`

**Methods Found:**
```python
def get_type_preference(self, notification_type: str) -> dict:
    """Get preference for a specific notification type."""
    if not self.type_preferences:
        return {"enabled": True, "email": True, "sound": True}
    return self.type_preferences.get(
        notification_type, {"enabled": True, "email": True, "sound": True}
    )

def is_notification_allowed(self, notification_type: str) -> bool:
    """Check if notification type is enabled."""
    pref = self.get_type_preference(notification_type)
    return pref.get("enabled", True)

def is_email_allowed(self, notification_type: str) -> bool:
    """Check if email notification is allowed for this type."""
    if not self.email_enabled:
        return False
    pref = self.get_type_preference(notification_type)
    return pref.get("email", True)

def is_sound_allowed(self, notification_type: str) -> bool:
    """Check if sound notification is allowed for this type."""
    if not self.sound_enabled:
        return False
    pref = self.get_type_preference(notification_type)
    return pref.get("sound", True)
```

**Analysis:**
- ✅ **Type:** Data access helpers (query JSON field)
- ✅ **Complexity:** Low (simple dictionary lookups)
- ✅ **Dependencies:** None (no external services or database calls)
- ✅ **Side Effects:** None (pure functions)

**Recommendation:** **KEEP IN MODEL**
- These are accessor methods for model's own data
- Following "Fat Model, Thin Controller" pattern (acceptable in many frameworks)
- No business logic complexity
- Moving to service would add unnecessary indirection
- Common pattern in Django, SQLAlchemy, ActiveRecord

---

### 2. MajorAcademicInfo Model

**File:** `app/models/major_academic_info.py`

**Method Found:**
```python
def calculate_fee_change_percentage(self, previous_year_fee: Decimal) -> float | None:
    """
    Calculate percentage change from previous year.

    Args:
        previous_year_fee: Tuition fee from previous year

    Returns:
        Percentage change (positive = increase, negative = decrease)
    """
    if not self.tuition_fee_per_year or not previous_year_fee:
        return None

    if previous_year_fee == 0:
        return None

    change = (
        (self.tuition_fee_per_year - previous_year_fee) / previous_year_fee
    ) * 100
    return float(change)
```

**Analysis:**
- ✅ **Type:** Pure calculation utility
- ✅ **Complexity:** Low (simple percentage calculation)
- ✅ **Dependencies:** None
- ✅ **Side Effects:** None (pure function)
- ✅ **Reusability:** Model-specific (uses self.tuition_fee_per_year)

**Recommendation:** **KEEP IN MODEL**
- Pure calculation based on model's own data
- No external dependencies
- Following "Calculated Property" pattern
- Alternative: Could be @property or @hybrid_property (SQLAlchemy)
- Moving to service would make code less intuitive

---

## Alternative Approaches (If Needed)

### Option A: Convert to Properties (Better OOP)

```python
# In MajorAcademicInfo model
@property
def fee_change_percentage(self) -> float | None:
    """
    Percentage change from previous year (if available).
    Requires previous_year_fee to be passed or cached.
    """
    # Implementation would need refactoring to work as property
    pass
```

**Pros:**
- More Pythonic (accessed like `info.fee_change_percentage`)
- Clearer intent (it's a calculated value)

**Cons:**
- Requires previous_year_fee to be available
- May need caching/memoization

### Option B: Move to Service (Traditional Layering)

```python
# In services/academic_info_service.py
def calculate_fee_change_percentage(
    current_fee: Decimal,
    previous_fee: Decimal
) -> float | None:
    """Calculate percentage change between fees."""
    if not current_fee or not previous_fee or previous_fee == 0:
        return None

    change = ((current_fee - previous_fee) / previous_fee) * 100
    return float(change)
```

**Pros:**
- Pure function (easier to test)
- Can be reused across different models

**Cons:**
- Loses OOP encapsulation
- Requires passing values explicitly
- More verbose at call site: `service.calculate_fee_change_percentage(info.tuition_fee_per_year, prev_fee)`
  vs `info.calculate_fee_change_percentage(prev_fee)`

---

## Industry Best Practices

### When to Keep Logic in Models:

1. ✅ **Accessor Methods** - Getting nested data from JSON/JSONB fields
2. ✅ **Calculated Properties** - Simple calculations based on model's own fields
3. ✅ **Validation** - Field-level validation
4. ✅ **String Representation** - `__str__`, `__repr__`
5. ✅ **Type Conversions** - Converting between formats

### When to Move to Services:

1. ❌ **Business Rules** - Complex validation involving multiple models
2. ❌ **External API Calls** - Calling third-party services
3. ❌ **Database Queries** - Queries involving multiple tables
4. ❌ **Orchestration** - Coordinating multiple operations
5. ❌ **Side Effects** - Sending emails, notifications, etc.

---

## Conclusion

**Status:** ✅ **NO ACTION NEEDED**

Both methods analyzed are **appropriate to keep in models**:

1. **NotificationPreference methods:**
   - Data accessor helpers
   - No business logic
   - Common OOP pattern

2. **MajorAcademicInfo.calculate_fee_change_percentage:**
   - Pure calculation utility
   - Model-specific
   - No side effects

**Recommendation:**
- Keep current implementation
- Focus on higher-impact refactoring tasks:
  - TASK 5.4: Redis distributed locks (fixes concurrency issues)
  - TASK 5.5: ESLint rules (improves code quality)

**If Future Refactoring Needed:**
- Consider converting to `@property` or `@hybrid_property` (SQLAlchemy)
- Only move to service if business logic becomes complex
- Follow "Move when it hurts" principle

---

## References

- [SQLAlchemy Hybrid Attributes](https://docs.sqlalchemy.org/en/20/orm/extensions/hybrid.html)
- [Domain-Driven Design: Fat Models](https://martinfowler.com/bliki/AnemicDomainModel.html)
- [Django Best Practices: Model Methods](https://docs.djangoproject.com/en/stable/topics/db/models/#model-methods)
