# 🔐 Casbin Policy Management System - Comprehensive Proposal

## 📊 Current State Analysis

### ✅ What We Have
1. **Migration-based Core Policies** (Just implemented)
   - Default policies for admin, manager, officer, user roles
   - Idempotent migrations
   - Version controlled via Alembic

2. **Basic CRUD APIs** (Already exists in `admin.py`)
   ```python
   GET    /api/admin/policies              # List all policies
   POST   /api/admin/policies              # Add new policy
   DELETE /api/admin/policies              # Remove policy
   POST   /api/admin/assign-role           # Assign role to user
   DELETE /api/admin/assign-role           # Remove role from user
   GET    /api/admin/users/{id}/roles      # Get user's roles
   ```

### ❌ What We're Missing
1. **No Frontend UI** for policy management
2. **No Policy Templates** for quick role setup
3. **No Audit Logging** for policy changes
4. **No Safety Checks** (can accidentally lock out admin)
5. **No Batch Operations** (add multiple policies at once)
6. **No Policy Validation** before applying

---

## 🎯 Proposed Solution: Hybrid Approach

### Philosophy

#### 1. **Core/Immutable Policies** → Migration-based (Already done ✅)
- **Purpose**: Ensure system always has base permissions
- **Managed via**: Alembic migrations
- **Examples**:
  - `role:admin → /* → .*` (Admin wildcard access)
  - `role:user → /api/profile → GET|PUT`
- **When to use**: Policies that MUST exist for system to function
- **Change frequency**: Rarely (only with major releases)

#### 2. **Dynamic/Custom Policies** → Admin UI-based (To implement 🆕)
- **Purpose**: Flexible business logic permissions
- **Managed via**: Web-based Admin Panel
- **Examples**:
  - Custom permissions for new features
  - Temporary elevated access
  - Department-specific permissions
- **When to use**: Policies that change based on business needs
- **Change frequency**: Often (as business requirements evolve)

---

## 🏗️ Architecture Design

### Backend Components

#### A. Enhanced API Endpoints (To Add)

```python
# 1. Get Available Roles & Templates
GET /api/admin/roles
Response: {
  "roles": [
    {
      "name": "role:admin",
      "display_name": "Administrator",
      "description": "Full system access",
      "is_system_role": true,  # Cannot be deleted
      "policy_count": 1
    },
    {
      "name": "role:manager",
      "display_name": "Manager",
      "description": "Manage users and leads",
      "is_system_role": true,
      "policy_count": 4
    }
  ]
}

# 2. Get Policy Templates
GET /api/admin/policy-templates
Response: {
  "templates": {
    "lead_viewer": [
      {"subject": "role:viewer", "object": "/api/leads", "action": "GET"},
      {"subject": "role:viewer", "object": "/api/leads/{lead_id}", "action": "GET"}
    ],
    "report_access": [
      {"subject": "role:analyst", "object": "/api/reports/*", "action": "GET"}
    ]
  }
}

# 3. Batch Add Policies (with validation)
POST /api/admin/policies/batch
Request: {
  "policies": [
    {"subject": "role:custom", "object": "/api/custom/*", "action": "*"}
  ],
  "validate_only": false  # Set true to dry-run
}
Response: {
  "added": 1,
  "skipped": 0,
  "errors": [],
  "warnings": ["This grants full access to /api/custom/*"]
}

# 4. Validate Policy (Before applying)
POST /api/admin/policies/validate
Request: {
  "subject": "role:admin",
  "object": "/*",
  "action": "GET"
}
Response: {
  "is_valid": true,
  "is_safe": false,  # Would remove critical permission
  "warnings": ["Removing this policy will lock all admins out"],
  "affected_users": [1, 2, 3]
}

# 5. Get Policy Suggestions (AI-powered, optional)
GET /api/admin/policies/suggest?role=role:analyst
Response: {
  "suggestions": [
    {
      "object": "/api/reports/*",
      "action": "GET",
      "reason": "Analysts typically need read access to reports"
    }
  ]
}
```

#### B. Policy Templates System

Create a templates configuration file:

```python
# app/config/policy_templates.py
POLICY_TEMPLATES = {
    "lead_full_access": {
        "display_name": "Lead Full Access",
        "description": "Complete CRUD access to leads module",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "GET"},
            {"subject": "{role}", "object": "/api/leads", "action": "POST"},
            {"subject": "{role}", "object": "/api/leads/*", "action": "*"},
        ]
    },
    "lead_read_only": {
        "display_name": "Lead Read Only",
        "description": "View-only access to leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "GET"},
            {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        ]
    },
    "user_manager": {
        "display_name": "User Manager",
        "description": "Manage users (create, edit, delete)",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        ]
    },
    "report_analyst": {
        "display_name": "Report Analyst",
        "description": "Access to reports and analytics",
        "policies": [
            {"subject": "{role}", "object": "/api/reports/*", "action": "GET"},
            {"subject": "{role}", "object": "/api/analytics/*", "action": "GET"},
        ]
    }
}
```

#### C. Safety Validation Logic

```python
# app/services/casbin_service.py
class CasbinPolicyService:

    async def validate_policy_removal(
        self,
        subject: str,
        object: str,
        action: str
    ) -> PolicyValidationResult:
        """
        Check if removing a policy is safe.

        Returns warnings if:
        - Would lock out all admins
        - Affects critical system paths
        - Impacts many users
        """
        # Check if this is a critical admin policy
        if subject == "role:admin" and object == "/*":
            return PolicyValidationResult(
                is_safe=False,
                warnings=["DANGER: This will lock all admins out of the system!"],
                severity="critical"
            )

        # Check how many users are affected
        affected_users = await self.get_affected_users(subject, object, action)

        if len(affected_users) > 10:
            return PolicyValidationResult(
                is_safe=True,
                warnings=[f"This change will affect {len(affected_users)} users"],
                severity="warning"
            )

        return PolicyValidationResult(is_safe=True, warnings=[])
```

---

### Frontend Components

#### A. Policy Management Page Structure

```
/admin/policies
├── Overview Section
│   ├── Stats: Total Policies, Roles, Recent Changes
│   └── Quick Actions: Add Role, Import Policies
│
├── Policies Tab
│   ├── Filter by Role/Resource/Action
│   ├── Policy Table (Subject, Object, Action, Actions)
│   ├── Add Policy Button → Dialog
│   └── Bulk Delete Selection
│
├── Roles Tab
│   ├── Role Cards (Admin, Manager, Officer, User)
│   ├── For each role:
│   │   ├── Policy count
│   │   ├── View/Edit policies
│   │   └── Apply template
│   └── Create Custom Role Button
│
├── Templates Tab
│   ├── Template Cards (Lead Full Access, User Manager, etc.)
│   ├── For each template:
│   │   ├── Preview policies
│   │   ├── Apply to role
│   │   └── Edit template (custom templates only)
│   └── Create Template Button
│
└── Audit Log Tab
    ├── Timeline of policy changes
    ├── Filter by User/Action/Date
    └── Rollback capability (optional)
```

#### B. Key UI Components

**1. Policy Builder Component**
```tsx
// Visual policy builder with dropdowns
<PolicyBuilder>
  <RoleSelect />        // Select role:admin, role:manager, etc.
  <ResourceInput />     // Input with autocomplete: /api/leads, /api/users/*
  <ActionSelect />      // Dropdown: GET, POST, PUT, DELETE, *
  <ValidationDisplay /> // Show warnings/errors in real-time
</PolicyBuilder>
```

**2. Template Applier**
```tsx
<TemplateCard template="lead_full_access">
  <TemplatePreview policies={template.policies} />
  <ApplyButton
    onApply={(role) => applyTemplate(template, role)}
    confirmText="This will add 5 policies to role:officer"
  />
</TemplateCard>
```

**3. Safety Confirmation Dialog**
```tsx
<PolicyDeleteDialog>
  <WarningBanner severity="critical">
    ⚠️ DANGER: Removing this policy will lock all admins out!
  </WarningBanner>
  <AffectedUsersTable users={affectedUsers} />
  <ConfirmationCheckbox label="I understand the consequences" />
</PolicyDeleteDialog>
```

---

## 📊 Data Flow

### Adding a New Policy

```
1. User opens Policy Management UI
2. Clicks "Add Policy"
3. Selects: role:custom_role, /api/reports/*, GET
4. Frontend calls: POST /api/admin/policies/validate
5. Backend returns: { is_safe: true, warnings: [] }
6. User confirms
7. Frontend calls: POST /api/admin/policies
8. Backend:
   a. Adds policy to Casbin enforcer
   b. Logs activity to activity_log table
   c. Returns success
9. Frontend refreshes policy list
10. User sees new policy immediately
```

### Applying a Template

```
1. User selects "Lead Full Access" template
2. Clicks "Apply to role:officer"
3. Frontend shows preview of 5 policies to be added
4. User confirms
5. Frontend calls: POST /api/admin/policies/batch
6. Backend:
   a. Validates all policies
   b. Adds them in a transaction
   c. Logs activity
7. Frontend shows success toast
```

---

## 🔒 Security & Safety Features

### 1. **Critical Policy Protection**
```python
PROTECTED_POLICIES = [
    ("role:admin", "/*", ".*"),  # Cannot be deleted
]

# Before deleting, check if it's protected
if (subject, object, action) in PROTECTED_POLICIES:
    raise PermissionDeniedError("Cannot delete system-critical policy")
```

### 2. **Activity Logging**
Every policy change is logged to `activity_log` table:
```python
await activity_service.log_activity(
    actor_id=current_admin.id,
    action="add_policy",
    resource_type="casbin_policy",
    description=f"Added policy: {subject} → {object} → {action}",
    changes={
        "subject": subject,
        "object": object,
        "action": action
    }
)
```

### 3. **Dry-Run Mode**
Before applying changes, users can validate:
```python
POST /api/admin/policies/batch?dry_run=true
# Returns what WOULD happen, without actually applying
```

---

## 🎨 UI/UX Design Mockup

### Policy Management Page

```
┌─────────────────────────────────────────────────────────────┐
│ Policy Management                                  [+ Add Policy] │
├─────────────────────────────────────────────────────────────┤
│                                                                    │
│ 📊 Overview                                                       │
│ ┌───────────┐ ┌───────────┐ ┌───────────┐                      │
│ │ 24 Policies│ │ 4 Roles   │ │ 3 Changes │                      │
│ │ Active     │ │ Defined   │ │ Today     │                      │
│ └───────────┘ └───────────┘ └───────────┘                      │
│                                                                    │
│ Tabs: [Policies] [Roles] [Templates] [Audit Log]                 │
│                                                                    │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ 🔍 Filter: [All Roles ▼] [All Resources ▼] [All Actions ▼]│  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                    │
│ ┌─────────┬──────────────────┬────────┬─────────────────────┐  │
│ │ Subject │ Resource         │ Action │ Actions              │  │
│ ├─────────┼──────────────────┼────────┼─────────────────────┤  │
│ │ 🔑 Admin│ /*               │ .*     │ 🔒 Protected         │  │
│ │ 👔 Manager│ /api/users     │ .*     │ [Edit] [Delete]      │  │
│ │ 👔 Manager│ /api/leads/*   │ .*     │ [Edit] [Delete]      │  │
│ │ 👤 Officer│ /api/leads     │ GET    │ [Edit] [Delete]      │  │
│ └─────────┴──────────────────┴────────┴─────────────────────┘  │
│                                                                    │
│ [1] [2] [3] ... [10] Next                                         │
└────────────────────────────────────────────────────────────────┘
```

---

## 📈 Implementation Roadmap

### Phase 1: Backend Foundation (Priority: HIGH)
**Effort**: 3-4 hours

- [ ] Create `casbin_service.py` with validation logic
- [ ] Add new endpoints:
  - `GET /api/admin/roles`
  - `GET /api/admin/policy-templates`
  - `POST /api/admin/policies/batch`
  - `POST /api/admin/policies/validate`
- [ ] Create `policy_templates.py` config
- [ ] Add safety checks for critical policies
- [ ] Integrate activity logging

### Phase 2: Frontend UI (Priority: HIGH)
**Effort**: 4-5 hours

- [ ] Create `/admin/policies` page
- [ ] Build Policy Table with filters
- [ ] Create PolicyDialog component (Add/Edit)
- [ ] Add TemplateSelector component
- [ ] Implement real-time validation
- [ ] Add confirmation dialogs with warnings

### Phase 3: Advanced Features (Priority: MEDIUM)
**Effort**: 2-3 hours

- [ ] Batch operations UI
- [ ] Policy import/export (JSON/CSV)
- [ ] Audit log viewer
- [ ] Rollback capability
- [ ] Policy diff viewer (compare changes)

### Phase 4: Polish & Documentation (Priority: LOW)
**Effort**: 1-2 hours

- [ ] Add tooltips and help text
- [ ] Create admin user guide
- [ ] Add policy examples library
- [ ] Performance optimization for large policy sets

---

## 🚀 Quick Start Guide (After Implementation)

### For Admins: Managing Policies via UI

**Scenario 1: Create a new custom role with specific permissions**

1. Go to `/admin/policies` → Roles tab
2. Click "Create Custom Role"
3. Enter role name: `role:analyst`
4. Select template: "Report Analyst"
5. Click "Create" → 3 policies are automatically added
6. Assign role to users in User Management page

**Scenario 2: Give temporary elevated access**

1. Go to `/admin/policies` → Policies tab
2. Click "Add Policy"
3. Fill in:
   - Subject: `user:42` (specific user)
   - Resource: `/api/admin/users`
   - Action: `GET`
4. Confirm → User #42 can now view admin users list
5. Remove policy later when no longer needed

**Scenario 3: Bulk add permissions for new feature**

1. Go to `/admin/policies` → Templates tab
2. Click "Create Template"
3. Name: "New Feature Access"
4. Add policies:
   - `/api/new-feature/*` → `GET`
   - `/api/new-feature/*` → `POST`
5. Save template
6. Apply to `role:officer` → All officers get access

---

## ❓ Decision Points for User

Before implementing, please answer:

1. **Scope**: Which phase(s) do you want to implement first?
   - [ ] Phase 1 only (Backend APIs)
   - [ ] Phase 1 + 2 (Full basic system)
   - [ ] All phases (Complete system)

2. **Templates**: Which policy templates are most useful for your use case?
   - Current proposal has: Lead Access, User Manager, Report Analyst
   - Should we add more specific to your business?

3. **Safety Level**: How strict should safety checks be?
   - [ ] Strict (Block dangerous operations)
   - [ ] Warning only (Allow but warn)
   - [ ] Flexible (Admin can override warnings)

4. **Audit**: Do you need rollback capability?
   - [ ] Yes (Can undo policy changes)
   - [ ] No (Just view history)

5. **Priority**: What's most urgent?
   - [ ] UI for managing existing policies
   - [ ] Templates for quick role setup
   - [ ] Audit logging
   - [ ] All equally important

---

## 💡 Recommendations

Based on best practices:

1. **Start with Phase 1 + 2** (Backend + Basic UI)
   - Gives immediate value
   - Allows policy management without code changes
   - Foundation for advanced features

2. **Keep Core Policies in Migration**
   - Migration handles system-critical policies
   - UI handles business-specific policies
   - Best of both worlds

3. **Implement Safety Checks Early**
   - Prevent accidental system lockout
   - Validate before applying
   - Activity logging from day 1

4. **Use Templates for Common Patterns**
   - 80% of policy changes follow patterns
   - Templates reduce errors
   - Faster onboarding for new roles

---

## 📝 Notes

- This is a **non-destructive** approach: existing policies via migration stay
- UI-managed policies are stored in the same `casbin_rule` table
- Can always fall back to SQL if UI fails
- Activity log provides full audit trail

Ready to implement? Let me know which phase you'd like to start with! 🚀
