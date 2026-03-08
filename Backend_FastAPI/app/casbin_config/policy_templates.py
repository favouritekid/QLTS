# app/config/policy_templates.py
"""
Policy Templates Configuration

This module defines reusable policy templates for common permission patterns.
Templates can be applied to roles to quickly set up standard permission sets.

Each template contains:
- display_name: Human-readable name
- description: What permissions this template grants
- category: Group similar templates together
- policies: List of policy rules (subject placeholder will be replaced)

=============================================================================
DIAMOND INHERITANCE PATTERN
=============================================================================

Role hierarchy uses diamond inheritance for separation of duties:

                       ┌─────────────┐
                       │    Admin    │  Full system access
                       └──────┬──────┘
                         ▲         ▲
              ┌──────────┘         └──────────┐
              │                               │
        ┌─────┴──────┐                 ┌──────┴─────┐
        │  Manager   │                 │ Accountant │
        │ (Users/    │                 │  (Finance  │
        │  Leads)    │                 │   Ops)     │
        └─────┬──────┘                 └──────┬─────┘
              │                               │
              └──────────┐     ┌──────────────┘
                         ▼     ▼
                      ┌───────────┐
                      │  Officer  │  Admission consultant
                      └─────┬─────┘
                            │
                      ┌─────┴─────┐
                      │   User    │  Basic permissions
                      └───────────┘

Casbin Grouping Policies (g-type rules):
  g, role:officer, role:user
  g, role:accountant, role:officer
  g, role:manager, role:officer        # Manager does NOT inherit Accountant!
  g, role:admin, role:manager
  g, role:admin, role:accountant       # Admin inherits BOTH branches

Benefits:
  - Separation of Duties: Manager cannot do finance ops, Accountant cannot manage users
  - Least Privilege: Each role only has required permissions
  - Admin Override: Admin inherits all permissions from both branches

Template Design:
  - Each template defines ONLY the permissions UNIQUE to that role
  - Inherited permissions come automatically via Casbin g-rules
  - Example: Accountant template has finance-specific policies only,
    officer permissions come via inheritance

=============================================================================
"""

from typing import Dict, List, TypedDict


class PolicyRule(TypedDict):
    """Type definition for a single policy rule."""
    subject: str  # Placeholder: {role} will be replaced
    object: str   # Resource path (e.g., /api/leads/*)
    action: str   # HTTP method or regex (e.g., GET, POST, .*)


class PolicyTemplate(TypedDict):
    """Type definition for a policy template."""
    display_name: str
    description: str
    category: str
    policies: List[PolicyRule]


# =============================================================================
# CORE ROLE TEMPLATES (Based on system defaults)
# =============================================================================

OFFICER_TEMPLATE: PolicyTemplate = {
    "display_name": "Officer (Lead Access)",
    "description": "Standard permissions for sales officers: view and manage assigned leads",
    "category": "core",
    "policies": [
        # Lead access
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "POST"},  # Create lead
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},  # Update lead
        {"subject": "{role}", "object": "/api/leads/check-duplicate", "action": "GET"},  # Duplicate check for create/edit form
        {"subject": "{role}", "object": "/api/leads/{id}/workflow-context", "action": "GET"},  # Workflow context
        {"subject": "{role}", "object": "/api/leads/{id}/consultations", "action": "GET"},  # List consultations
        {"subject": "{role}", "object": "/api/leads/{id}/consultations", "action": "POST"},  # Create consultation
        {"subject": "{role}", "object": "/api/leads/{id}/consultations/{consultation_id}", "action": "PUT"},  # Update
        {"subject": "{role}", "object": "/api/leads/{id}/consultations/{consultation_id}", "action": "DELETE"},  # Delete own
        {"subject": "{role}", "object": "/api/leads/{id}/action", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{id}/timeline", "action": "GET"},  # Lead timeline
        {"subject": "{role}", "object": "/api/leads/{id}/insights", "action": "GET"},  # Lead insights
        {"subject": "{role}", "object": "/api/leads/{id}/audit-logs", "action": "GET"},  # Lead audit log history
        {"subject": "{role}", "object": "/api/leads/my/reassign-quota", "action": "GET"},  # Reassign quota
        {"subject": "{role}", "object": "/api/leads/import/template", "action": "GET"},  # Import template
        {"subject": "{role}", "object": "/api/leads/import", "action": "POST"},  # Import leads
        # Admin users (read-only) — needed for officer filter bar and lead assignment dialog
        {"subject": "{role}", "object": "/api/admin/users", "action": "GET"},
        # Collaborators (read-only) — needed for CTV referrer dropdown in lead form
        {"subject": "{role}", "object": "/api/collaborators", "action": "GET"},
        # Organization units (read-only) — needed for SmartUnitSelector in LeadDialog & dashboard
        {"subject": "{role}", "object": "/api/organization-units", "action": "GET"},
        # Pipeline access (for consultation statuses in QuickDisposition)
        {"subject": "{role}", "object": "/api/pipeline/stages", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/all", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/allowed-next-statuses", "action": "GET"},
        # Officer Dashboard access (Phase 4: Unified Dashboard)
        {"subject": "{role}", "object": "/api/officer/stats", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/dashboard", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/leaderboard", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/team-stats", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/upcoming-activities", "action": "GET"},
        {"subject": "{role}", "object": "/api/officer/availability", "action": "POST"},
        {"subject": "{role}", "object": "/api/officer/recommendations", "action": "GET"},  # Phase 7
        # Admissions access (Admission Profile workflow)
        {"subject": "{role}", "object": "/api/admissions", "action": "GET"},   # List profiles
        {"subject": "{role}", "object": "/api/admissions", "action": "POST"},  # Create profile
        {"subject": "{role}", "object": "/api/admissions/{id}", "action": "GET"},   # Read profile
        {"subject": "{role}", "object": "/api/admissions/{id}", "action": "PUT"},   # Update profile
        {"subject": "{role}", "object": "/api/admissions/{id}/submit", "action": "POST"},  # Submit
        {"subject": "{role}", "object": "/api/admissions/{id}/resubmit", "action": "POST"},  # Resubmit after rejection
        {"subject": "{role}", "object": "/api/admissions/{id}/send-confirmation", "action": "POST"},  # Send magic link
        # REMOVED: enroll is ADMIN-ONLY per Decision 10 (Admission State ≠ Authorization)
        # {"subject": "{role}", "object": "/api/admissions/{id}/enroll", "action": "POST"},
        {"subject": "{role}", "object": "/api/admissions/{id}/documents/{doc_code}/upload", "action": "POST"},  # Upload doc
        # Admission aggregate endpoints (read-only)
        {"subject": "{role}", "object": "/api/admissions/stats", "action": "GET"},  # Stats dashboard
        {"subject": "{role}", "object": "/api/admissions/status-counts", "action": "GET"},  # Tab badges
        {"subject": "{role}", "object": "/api/admissions/academic-years", "action": "GET"},  # Year filter
        # Admission config (read-only lookup data)
        {"subject": "{role}", "object": "/api/program-offerings", "action": "GET"},  # Dropdown data
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/criteria", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/criteria/{criteria_code}", "action": "GET"},
        # Admission Configuration Console (Phase 1)
        {"subject": "{role}", "object": "/api/admission-config/years", "action": "GET"},  # Academic years dropdown
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
        # Finance Module - Officer (Tư vấn viên) can only VIEW fees/invoices/payments
        # and CREATE payment intents (to send payment links to parents)
        # Officer CANNOT record cash payments or verify payments (accounting staff only)
        {"subject": "{role}", "object": "/api/fees", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/by-profile/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/summary/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/by-fee/{fee_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/by-invoice/{invoice_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/intents", "action": "POST"},  # Create payment intent (online)
        {"subject": "{role}", "object": "/api/payments/intents/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/methods", "action": "GET"},
    ]
}

ACCOUNTANT_TEMPLATE: PolicyTemplate = {
    "display_name": "Accountant (Kế toán viên)",
    "description": "Finance staff: record payments, issue invoices, verify payments, waive fees. Inherits from Officer via g-rules.",
    "category": "core",
    "policies": [
        # =========================================================================
        # DIAMOND INHERITANCE: Accountant inherits Officer permissions via:
        #   g, role:accountant, role:officer
        # These are ADDITIONAL accountant-only permissions (Finance operations)
        # Accountant does NOT inherit Manager (separation of duties)
        # =========================================================================
        # Profile access (SELF only)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
        # Sessions & Security (SELF only)
        {"subject": "{role}", "object": "/api/sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/sessions/{id}", "action": "DELETE"},
        {"subject": "{role}", "object": "/api/sessions/revoke-all", "action": "POST"},
        {"subject": "{role}", "object": "/api/security/login-history", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/active-sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/not-me", "action": "POST"},

        # =====================================================================
        # FINANCE MODULE - Full accounting operations
        # =====================================================================

        # FEES - Read + Calculate + Waive + Recalculate (not Cancel - admin only)
        {"subject": "{role}", "object": "/api/fees", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/by-profile/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/summary/{profile_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/fees/calculate", "action": "POST"},
        {"subject": "{role}", "object": "/api/fees/{id}/waive", "action": "POST"},
        {"subject": "{role}", "object": "/api/fees/{id}/recalculate", "action": "POST"},

        # INVOICES - Full CRUD (except delete)
        {"subject": "{role}", "object": "/api/invoices", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/by-fee/{fee_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/invoices/{id}/issue", "action": "PUT"},
        {"subject": "{role}", "object": "/api/invoices/{id}/cancel", "action": "PUT"},
        {"subject": "{role}", "object": "/api/invoices/{id}/apply-penalty", "action": "POST"},

        # PAYMENTS - Record + Verify + Reject (giai đoạn đầu accountant tự verify)
        {"subject": "{role}", "object": "/api/payments", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments", "action": "POST"},  # Record payment
        {"subject": "{role}", "object": "/api/payments/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/by-invoice/{invoice_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/{id}/verify", "action": "PUT"},  # Verify payment
        {"subject": "{role}", "object": "/api/payments/{id}/reject", "action": "PUT"},  # Reject payment
        {"subject": "{role}", "object": "/api/payments/intents", "action": "POST"},
        {"subject": "{role}", "object": "/api/payments/intents/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/payments/methods", "action": "GET"},

        # ACCOUNTING PERIODS - View only (create/close is admin only)
        {"subject": "{role}", "object": "/api/accounting/periods", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/current", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/accounting/periods/{id}/summary", "action": "GET"},

        # REFUNDS - Request + Process (approve is manager only)
        {"subject": "{role}", "object": "/api/refunds", "action": "GET"},
        {"subject": "{role}", "object": "/api/refunds/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/refunds/request", "action": "POST"},
        {"subject": "{role}", "object": "/api/refunds/{id}/process", "action": "PUT"},

        # Admission config (read-only lookup data)
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},
    ]
}

MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "Manager (User & Lead Manager)",
    "description": "Manager permissions: lead CRUD (except DELETE) + user administration. Inherits from Officer via g-rules.",
    "category": "core",
    "policies": [
        # =========================================================================
        # DIAMOND INHERITANCE: Manager inherits Officer permissions via:
        #   g, role:manager, role:officer
        # These are ADDITIONAL manager-only permissions (not in Officer template)
        # Manager does NOT inherit Accountant (separation of duties)
        # =========================================================================
        # User management
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        # Lead management - explicit policies (no wildcard)
        # Manager can: List, Create, View, Update leads
        # Manager CANNOT: Delete leads (requires admin) - Security Decision #3
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/leads/{id}/assign", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{id}/applications", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}/applications", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/export/csv", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/export/excel", "action": "GET"},
        # Bulk operations (manager-specific)
        {"subject": "{role}", "object": "/api/leads/bulk-assign", "action": "POST"},  # Bulk assign
        {"subject": "{role}", "object": "/api/leads/distribution-preview", "action": "GET"},  # Preview distribution
        {"subject": "{role}", "object": "/api/leads/import/template", "action": "GET"},  # Import template
        {"subject": "{role}", "object": "/api/leads/import", "action": "POST"},  # Import leads
        # Admission State Machine (ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md)
        {"subject": "{role}", "object": "/api/admissions/{id}/approve", "action": "POST"},  # Approve profile
        {"subject": "{role}", "object": "/api/admissions/{id}/reject", "action": "POST"},  # Reject profile
        {"subject": "{role}", "object": "/api/admissions/{id}/request-revision", "action": "POST"},  # Request revision
        {"subject": "{role}", "object": "/api/admissions/{id}/override", "action": "POST"},  # Override decision
        {"subject": "{role}", "object": "/api/admissions/{id}/claim", "action": "POST"},  # Claim profile for review
        {"subject": "{role}", "object": "/api/admissions/{id}/unclaim", "action": "POST"},  # Unclaim profile
        {"subject": "{role}", "object": "/api/admissions/{id}/drop", "action": "POST"},  # Drop enrolled student
        {"subject": "{role}", "object": "/api/admissions/{id}/send-confirmation", "action": "POST"},  # Send magic link
        # Admission Configuration Console (Phase 1: Admission Path Management)
        # NOTE: Manager can create/edit paths, but ONLY ADMIN can activate/deactivate
        {"subject": "{role}", "object": "/api/admission-config/years", "action": "GET"},  # Academic years
        {"subject": "{role}", "object": "/api/admission-config/paths", "action": "GET"},  # List paths
        {"subject": "{role}", "object": "/api/admission-config/paths", "action": "POST"},  # Create path (draft)
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}", "action": "GET"},  # Get path
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}", "action": "PUT"},  # Update path
        # REMOVED: activate/deactivate - Admin only (Manager creates, Admin approves)
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}/documents", "action": "GET"},  # Resolved docs
        {"subject": "{role}", "object": "/api/admission-config/paths/{path_id}/validate-activation", "action": "GET"},  # Validate
        # Finance Module - Manager can verify/reject payments, waive fees, apply penalties
        {"subject": "{role}", "object": "/api/fees/{id}/waive", "action": "POST"},  # Waive fee
        {"subject": "{role}", "object": "/api/fees/{id}/recalculate", "action": "POST"},  # Recalculate fee
        {"subject": "{role}", "object": "/api/invoices/{id}/cancel", "action": "PUT"},  # Cancel invoice
        {"subject": "{role}", "object": "/api/invoices/{id}/apply-penalty", "action": "POST"},  # Apply penalty
        {"subject": "{role}", "object": "/api/payments/{id}/verify", "action": "PUT"},  # Verify payment (maker-checker)
        {"subject": "{role}", "object": "/api/payments/{id}/reject", "action": "PUT"},  # Reject payment
        {"subject": "{role}", "object": "/api/accounting/periods/{id}", "action": "GET"},  # View period details
        {"subject": "{role}", "object": "/api/accounting/periods/{id}/summary", "action": "GET"},  # View period summary
        # CTV Management (Phase 1: Collaborator System)
        {"subject": "{role}", "object": "/api/collaborators", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/approve", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/suspend", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/claims", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/claims/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/collaborators/claims/{id}/review", "action": "POST"},
        {"subject": "{role}", "object": "/api/collaborators/{id}/reactivate", "action": "POST"},
        # Lead validity management (Phase 1: CTV System)
        {"subject": "{role}", "object": "/api/leads/{id}/validity", "action": "POST"},
        # Commission Management (Phase 2: CTV Commission System)
        {"subject": "{role}", "object": "/api/admin/commission-policies", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commission-policies", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commission-policies/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commission-policies/{id}", "action": "PUT"},
        {"subject": "{role}", "object": "/api/admin/commissions", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/approve", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/reject", "action": "POST"},
        {"subject": "{role}", "object": "/api/admin/commissions/{id}/pay", "action": "POST"},
    ]
}

# =============================================================================
# COLLABORATOR TEMPLATE (Phase 1: CTV System)
# NO inheritance from user — standalone permissions
# =============================================================================

COLLABORATOR_TEMPLATE: PolicyTemplate = {
    "display_name": "Collaborator (CTV)",
    "description": "External collaborator: submit leads, view own stats only. No inheritance.",
    "category": "core",
    "policies": [
        # CTV self-service ONLY
        {"subject": "{role}", "object": "/api/ctv/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/leads/submit", "action": "POST"},
        {"subject": "{role}", "object": "/api/ctv/leads/check-phone", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/claims", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/stats", "action": "GET"},
        # CTV Commission (Phase 2)
        {"subject": "{role}", "object": "/api/ctv/commissions", "action": "GET"},
        {"subject": "{role}", "object": "/api/ctv/commissions/stats", "action": "GET"},
        # Minimal auth-related (NO session management, NO security endpoints)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
    ]
}

ADMIN_TEMPLATE: PolicyTemplate = {
    "display_name": "Administrator (Full Access)",
    "description": "Complete system access with no restrictions",
    "category": "core",
    "policies": [
        # Wildcard access to everything
        {"subject": "{role}", "object": "/*", "action": ".*"},
    ]
}

# =============================================================================
# CUSTOM ROLE TEMPLATES (Business-specific)
# =============================================================================

AUDITOR_TEMPLATE: PolicyTemplate = {
    "display_name": "Auditor (Report Analyst)",
    "description": "Read-only access to reports, statistics, and activity logs",
    "category": "custom",
    "policies": [
        # Read-only access to analytics
        {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

LEAD_VIEWER_TEMPLATE: PolicyTemplate = {
    "display_name": "Lead Viewer (Read Only)",
    "description": "View-only access to leads module without modification rights",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
    ]
}

USER_MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "User Manager",
    "description": "Manage users (create, edit, delete) without lead access",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{id}", "action": "DELETE"},
    ]
}

BASIC_USER_TEMPLATE: PolicyTemplate = {
    "display_name": "Basic User",
    "description": "Minimal permissions: profile, notifications, sessions, security",
    "category": "core",
    "policies": [
        # Profile access (SELF only - IDOR protected)
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access (SELF only - IDOR protected)
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{id}", "action": "DELETE"},
        # Notification preferences (SELF only)
        {"subject": "{role}", "object": "/api/notifications/preferences", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/preferences", "action": "PUT"},
        {"subject": "{role}", "object": "/api/notifications/preferences/{channel}", "action": "PUT"},
        # Notification event group preferences (SELF only)
        {"subject": "{role}", "object": "/api/notifications/event-groups", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/event-groups", "action": "PATCH"},
        # Sessions (SELF only - manage own sessions)
        {"subject": "{role}", "object": "/api/sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/sessions/{id}", "action": "DELETE"},
        {"subject": "{role}", "object": "/api/sessions/revoke-all", "action": "POST"},
        # Security (SELF only - security settings)
        {"subject": "{role}", "object": "/api/security/login-history", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/active-sessions", "action": "GET"},
        {"subject": "{role}", "object": "/api/security/not-me", "action": "POST"},
        # Admission config (read-only lookup data for all users)
        {"subject": "{role}", "object": "/api/admission-config/subjects", "action": "GET"},
        {"subject": "{role}", "object": "/api/admission-config/methods", "action": "GET"},
        # NOTE: Admission confirmation is now PUBLIC via magic link
        # POST /api/admissions/confirm/{token} - no auth required (token + CCCD = auth)
    ]
}

# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================

POLICY_TEMPLATES: Dict[str, PolicyTemplate] = {
    # Core templates (system roles)
    "admin": ADMIN_TEMPLATE,
    "manager": MANAGER_TEMPLATE,
    "accountant": ACCOUNTANT_TEMPLATE,  # Finance staff
    "officer": OFFICER_TEMPLATE,
    "collaborator": COLLABORATOR_TEMPLATE,  # External CTV
    "user": BASIC_USER_TEMPLATE,

    # Custom templates (business-specific)
    "auditor": AUDITOR_TEMPLATE,
    "lead_viewer": LEAD_VIEWER_TEMPLATE,
    "user_manager": USER_MANAGER_TEMPLATE,
}

# =============================================================================
# SYSTEM ROLES (Cannot be deleted or modified)
# =============================================================================

SYSTEM_ROLES = [
    {
        "name": "role:admin",
        "display_name": "Administrator",
        "description": "Full system access with all permissions",
        "is_system_role": True,
        "template_id": "admin",
    },
    {
        "name": "role:manager",
        "display_name": "Manager",
        "description": "Manage users and leads with elevated permissions",
        "is_system_role": True,
        "template_id": "manager",
    },
    {
        "name": "role:accountant",
        "display_name": "Accountant",
        "description": "Finance staff: record payments, issue invoices, verify payments",
        "is_system_role": True,
        "template_id": "accountant",
    },
    {
        "name": "role:officer",
        "display_name": "Officer",
        "description": "Admission consultant with lead management capabilities",
        "is_system_role": True,
        "template_id": "officer",
    },
    {
        "name": "role:collaborator",
        "display_name": "Collaborator",
        "description": "External collaborator: submit leads, view own stats",
        "is_system_role": True,
        "template_id": "collaborator",
    },
    {
        "name": "role:user",
        "display_name": "User",
        "description": "Basic user with minimal permissions",
        "is_system_role": True,
        "template_id": "user",
    },
]

# =============================================================================
# CRITICAL POLICIES (Cannot be deleted - will lock system)
# =============================================================================

CRITICAL_POLICIES = [
    # Admin wildcard access - removing this locks all admins out
    ("role:admin", "/*", ".*"),
]


def get_template(template_id: str) -> PolicyTemplate:
    """
    Get a policy template by ID.

    Args:
        template_id: Template identifier (e.g., "officer", "manager")

    Returns:
        PolicyTemplate dict

    Raises:
        KeyError: If template not found
    """
    return POLICY_TEMPLATES[template_id]


def apply_template(template_id: str, role: str) -> List[PolicyRule]:
    """
    Apply a template to a specific role, replacing {role} placeholder.

    Args:
        template_id: Template identifier
        role: Role name (with prefix, e.g., "role:custom")

    Returns:
        List of policy rules with role substituted

    Example:
        >>> apply_template("officer", "role:custom")
        [
            {"subject": "role:custom", "object": "/api/leads", "action": "GET"},
            ...
        ]
    """
    template = get_template(template_id)
    policies = []

    for policy in template["policies"]:
        policies.append({
            "subject": policy["subject"].replace("{role}", role),
            "object": policy["object"],
            "action": policy["action"],
        })

    return policies


def is_system_role(role: str) -> bool:
    """
    Check if a role is a system role (cannot be deleted).

    Args:
        role: Role name (e.g., "role:admin")

    Returns:
        True if system role, False otherwise
    """
    return any(r["name"] == role for r in SYSTEM_ROLES)


def is_critical_policy(subject: str, obj: str, action: str) -> bool:
    """
    Check if a policy is critical (cannot be deleted).

    Args:
        subject: Policy subject (e.g., "role:admin")
        obj: Policy object (e.g., "/*")
        action: Policy action (e.g., ".*")

    Returns:
        True if critical policy, False otherwise
    """
    return (subject, obj, action) in CRITICAL_POLICIES


# =============================================================================
# FEATURE-BASED PERMISSION MAP (Business-Level Abstraction)
# =============================================================================

class FeatureDefinition(TypedDict):
    """Type definition for a feature permission set."""
    display_name: str
    policies: List[PolicyRule]


FEATURE_MAP: Dict[str, FeatureDefinition] = {
    "view_leads": {
        "display_name": "Xem Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "GET"},
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "GET"},
        ]
    },
    "edit_leads": {
        "display_name": "Sửa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "PUT"},
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "PATCH"},
        ]
    },
    "create_leads": {
        "display_name": "Tạo Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "POST"},
        ]
    },
    "delete_leads": {
        "display_name": "Xóa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}", "action": "DELETE"},
        ]
    },
    "restore_leads": {
        "display_name": "Khôi phục Leads đã xóa",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{id}/restore", "action": "POST"},
        ]
    },
    "manage_users": {
        "display_name": "Quản lý Users",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
            {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        ]
    },
    "view_reports": {
        "display_name": "Xem Báo cáo",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
            {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        ]
    },
    "manage_notifications": {
        "display_name": "Quản lý Thông báo",
        "policies": [
            {"subject": "{role}", "object": "/api/notifications", "action": ".*"},
            {"subject": "{role}", "object": "/api/notifications/*", "action": ".*"},
        ]
    },
}
