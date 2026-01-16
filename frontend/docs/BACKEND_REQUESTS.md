# Backend Improvement Requests – Admission Module

> **Created:** 2026-01-16  
> **Related:** ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md  
> **Priority:** High

---

## Ticket #1: Type `applied_rules` with Proper Pydantic Schema

### Current State
```python
# admission.py:393
applied_rules: dict  # Generic dict - NOT typed
```

### Problem
- Frontend has strongly-typed `appliedRulesSchema` with 18 fields
- Backend uses generic `dict` which can silently change structure
- Breaks BE-FE contract principle

### Proposed Solution
```python
class AppliedRulesSchema(BaseModel):
    """Applied admission rules snapshot for a profile."""
    
    # Path Info
    admission_path_id: int
    admission_path_name: str
    
    # Method Info
    admission_method_id: Optional[int] = None
    admission_method: Optional[str] = None
    method_type: Optional[Literal["gpa_only", "subject_based", "combined"]] = None
    
    # Score Requirements
    min_gpa: Optional[float] = None
    min_score: Optional[float] = None
    
    # Subject Groups
    subject_groups: Optional[List[SubjectGroupSnapshot]] = None
    
    # Document Requirements
    mandatory_docs: Optional[List[str]] = None
    optional_docs: Optional[List[str]] = None
    
    # Validity
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
```

### Impact
- Type safety between BE-FE
- Auto-generated API docs
- Runtime validation

---

## Ticket #2: Add `is_qualified` Field to AdmissionProfileResponse

### Current State
Frontend calculates qualification status locally (VIOLATION)
```typescript
// ScoresTab.tsx (OLD - WRONG)
const isQualified = isGpaOnlyMethod 
  ? currentGpa >= minGpa 
  : totalScore >= minScore
```

### Problem
- Business logic in frontend
- Source of truth mismatch
- Potential for inconsistent results

### Proposed Solution
```python
class AdmissionProfileResponse(BaseModel):
    # ... existing fields ...
    
    # NEW: Backend-computed qualification status
    is_qualified: Optional[bool] = Field(
        None,
        description="Whether profile meets admission criteria. Computed by backend based on admission method rules."
    )
```

### Backend Computation Logic
```python
# In admission_service.py
def _compute_is_qualified(profile: AdmissionProfile) -> bool:
    rules = profile.applied_rules
    if not rules:
        return False
    
    method_type = rules.get("method_type", "combined")
    
    if method_type == "gpa_only":
        gpa = profile.admission_scores.get("gpa", 0)
        min_gpa = rules.get("min_gpa", 5.0)
        return gpa >= min_gpa
    else:
        total_score = profile.total_score or 0
        min_score = rules.get("min_score", 0)
        return total_score >= min_score
```

### Impact
- Frontend only reads `is_qualified` from backend
- Single source of truth for business logic
- Consistent results across all clients

---

## Ticket #3: Add `method_type` to Applied Rules

### Current State
Frontend infers method type from string matching (VIOLATION)
```typescript
// ScoresTab.tsx (OLD - WRONG)
const isGpaOnlyMethod = (
  selectedCriterion?.method_name?.toLowerCase().includes("học bạ") || 
  selectedCriterion?.method_name?.toLowerCase().includes("gpa")
)
```

### Problem
- Fragile string matching
- Language-dependent
- Not explicit

### Proposed Solution
```python
# In applied_rules structure
method_type: Literal["gpa_only", "subject_based", "combined"]
```

### Where to Set
```python
# When snapshotting applied_rules in admission_service.py
applied_rules = {
    # ... existing fields ...
    "method_type": admission_method.get_method_type(),  # NEW
}
```

### Impact
- Explicit method classification
- No string matching needed
- Clean frontend logic

---

## Ticket #4: Upload Config API Endpoint

### Current State
Frontend hardcodes file validation rules (VIOLATION)
```typescript
// DocumentsTab.tsx:24-26
const ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/jpg"]
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
```

### Problem
- Config changes require frontend deployment
- Not consistent with backend validation

### Proposed Solution

#### Option A: Include in `applied_rules`
```python
applied_rules = {
    # ... existing fields ...
    "upload_config": {
        "allowed_types": ["application/pdf", "image/jpeg", "image/png"],
        "max_file_size": 10485760,
        "allowed_extensions": ["pdf", "jpg", "jpeg", "png"],
    }
}
```

#### Option B: Dedicated Config Endpoint
```python
@router.get("/config/upload-rules")
def get_upload_config() -> UploadConfigResponse:
    return UploadConfigResponse(
        allowed_types=settings.ALLOWED_UPLOAD_TYPES,
        max_file_size=settings.MAX_UPLOAD_SIZE,
        allowed_extensions=settings.ALLOWED_EXTENSIONS,
    )
```

### Preferred: Option A
- No additional API call
- Already have `applied_rules` structure
- Consistency with other rules

---

## Summary

| Ticket | Priority | Effort | Impact |
|--------|----------|--------|--------|
| #1 Type applied_rules | High | 2h | Contract safety |
| #2 Add is_qualified | High | 1h | Remove FE business logic |
| #3 Add method_type | Medium | 30m | Remove string matching |
| #4 Upload config | Low | 1h | Config consistency |

---

*Created from architecture violation analysis*
