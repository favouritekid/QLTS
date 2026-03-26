# Notification System Specification

> Version: 1.0
> Date: 2026-03-25
> Scope: Channel configuration, action triggers, recipient routing
> Source: Derived from codebase audit of 67 services, 48 routers, 45 dispatch calls

---

## 1. Channel Configuration

### 1.1 Current channels

| Channel | Implementation | Delivery mechanism | Status |
|---|---|---|---|
| `browser` | `SocketChannel` | DB Notification row + Socket.IO real-time push + Redis inbox cache | **Active** |
| `email` | `EmailChannel` | SMTP via EmailService, requires Notification row for content | **Active** |
| `zalo` | — | ZNS template-based, Celery queue `zalo`, webhook callback | **Planned (Phase 1)** |
| `sms` | — | — | **Planned (Future)** |

### 1.2 Channel selection per event

Channels are configured in `notification_registry.py` per event. Current production:

| Channels config | Meaning |
|---|---|
| `(browser,)` | Inbox notification only |
| `(browser, email)` | Inbox + email delivery |
| `(browser, email, zalo)` | Future: inbox + email + Zalo ZNS |

### 1.3 Webhook integration points

| Integration | Current state | Webhook direction | Notes |
|---|---|---|---|
| **Zalo ZNS** | Planned | Inbound (Zalo → system) | Delivery status callback, update `actual_cost` |
| **MoMo** | Active (`gateways/momo.py`) | Inbound (MoMo → system) | Payment confirmation, could trigger `PAYMENT_VERIFIED` |
| **VNPay** | Active (`gateways/vnpay.py`) | Inbound (VNPay → system) | Payment confirmation, could trigger `PAYMENT_VERIFIED` |
| **Future: SMS gateway** | Not started | Inbound (provider → system) | Delivery status |
| **Future: Email tracking** | Not started | Inbound (email provider → system) | Open/click tracking |

### 1.4 User preference model

Each user controls channels independently:

| Preference field | Default | Scope |
|---|---|---|
| `browser_enabled` | `true` | Global on/off for inbox/Socket.IO |
| `email_enabled` | `true` | Global on/off for email |
| `zalo_enabled` | `false` | Global on/off for Zalo (opt-in required) |
| `sound_enabled` | `true` | Browser notification sound |
| `quiet_hours_enabled` | `false` | Suppress all channels during hours |
| `type_preferences` | `{}` | Per-event-group channel overrides |

Per-channel filtering: disabling one channel does NOT suppress others. Implemented in `notification_dispatcher.py` Step 3.

---

## 2. Action Triggers — What fires notifications

### 2.1 Lead Management

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Create lead | `lead_service.create_lead()` | `LEAD_CREATED` | browser | Active |
| Create lead + assign | `lead_service.create_lead()` | `LEAD_CREATED` + `LEAD_ASSIGNED` | browser; browser+email | Active |
| Auto-assign lead | `assignment_tasks.py` Celery | `LEAD_ASSIGNED` | browser, email | Active |
| Update lead | `routers/leads.py` PUT | `LEAD_UPDATED` | browser | Active |
| Update lead status | `routers/leads.py` PATCH | `LEAD_STATUS_CHANGED` | browser | Active |
| Reassign lead | `lead_service.update_lead()` | `LEAD_REASSIGNED` | browser, email | Active |
| Delete lead | `routers/leads.py` DELETE | `LEAD_DELETED` | browser | Active |
| Restore lead | `routers/leads.py` POST restore | — | — | **No notification** |
| Import leads | `routers/leads.py` import | — | — | **No notification** |

### 2.2 Consultation Management

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Create consultation | `routers/leads.py` POST | `CONSULTATION_CREATED` | browser | Active |
| Update consultation | `routers/leads.py` PUT | `CONSULTATION_UPDATED` | browser | Active |
| Delete consultation | `routers/leads.py` DELETE | `CONSULTATION_DELETED` | browser | Active |
| Scheduled reminder | `notification_tasks.py` Celery Beat (60s) | `CONSULTATION_REMINDER` | browser | Active |
| Restore consultation | `routers/leads.py` POST restore | — | — | **No notification** |

### 2.3 Admission Profile (Legacy: APPLICATION_*)

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Create profile | `routers/admissions.py` POST | `APPLICATION_CREATED` | browser, email | Active |
| Submit + evaluate → approved | `routers/admissions.py` submit_and_evaluate | `APPLICATION_STATUS_CHANGED` | browser, email | Active |
| Enroll student | `routers/admissions.py` enroll | `APPLICATION_STATUS_CHANGED` + `LEAD_STATUS_CHANGED` | browser, email | Active |
| Approve/reject profile | `routers/admissions.py` approve/reject | `LEAD_STATUS_CHANGED` | browser | Active |
| Request revision | `routers/admissions.py` request-revision | `LEAD_STATUS_CHANGED` | browser | Active |
| Resubmit profile | `routers/admissions.py` resubmit | `LEAD_STATUS_CHANGED` | browser | Active |
| Drop student | `routers/admissions.py` drop | `LEAD_STATUS_CHANGED` | browser | Active |
| Update documents | — | `APPLICATION_DOCUMENTS_UPDATED` | — | **Defined, not emitted** |
| Delete profile | — | `APPLICATION_DELETED` | — | **Defined, not emitted** |

### 2.4 Finance

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Verify payment (maker-checker) | `payment_service.verify_payment()` | `PAYMENT_VERIFIED` | browser, email | Active |
| Record payment | `payment_service.record_manual_payment()` | — | — | **No notification** |
| Reject payment | `payment_service.reject_payment()` | — | — | **No notification** |
| Payment overdue check | — | `PAYMENT_OVERDUE` | browser, email | **Defined, not emitted** |
| Create invoice | `invoice_service` | — | — | **No notification** |
| Create fee | `fee_calculation_service` | `DORM_FEE_CREATED` | browser, email | **Defined, not emitted** |

### 2.5 User Administration

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Change user role | `routers/admin/users.py` PUT | `USER_ROLE_CHANGED` | browser, email | Active |
| Deactivate user | `routers/admin/users.py` PUT | `USER_DEACTIVATED` | browser | Active |
| Admin updates user profile | `routers/admin/users.py` PUT | `SYSTEM_ALERT` | browser, email | Active |
| Create user | — | — | — | **No notification** |
| Delete user | — | — | — | **No notification** |
| Reset password | — | — | — | **No notification** |

### 2.6 Collaborator (CTV)

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Submit lead claim | `routers/collaborators.py` | `CTV_CLAIM_SUBMITTED` | browser | Active |
| Approve claim | `routers/collaborators.py` | `CTV_CLAIM_APPROVED` | browser, email | Active |
| Reject claim | `routers/collaborators.py` | `CTV_CLAIM_REJECTED` | browser, email | Active |
| Approve CTV | `routers/collaborators.py` | `CTV_APPROVED` | browser, email | Active |
| Suspend CTV | `routers/collaborators.py` | `CTV_SUSPENDED` | browser, email | Active |
| Create commission | `commission_service` | `CTV_COMMISSION_CREATED` | browser, email | Active |
| Attribution expiring | Celery task | `CTV_ATTRIBUTION_EXPIRING` | browser, email | Active |
| Attribution expired | Celery task | `CTV_ATTRIBUTION_EXPIRED` | browser, email | Active |
| Weekly summary | Celery task | `CTV_WEEKLY_SUMMARY` | browser, email | Active |
| Lead converted | — | `CTV_LEAD_CONVERTED` | browser | **Defined, emitter unconfirmed** |
| Reactivate CTV | — | — | — | **No notification** |

### 2.7 System & Pipeline Admin

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Send system alert | `routers/admin/system.py` | `SYSTEM_ALERT` | browser, email | Active |
| Send announcement | `routers/admin/system.py` | `SYSTEM_ANNOUNCEMENT` | browser, email | Active |
| Holiday calendar check | `cache_tasks.py` Celery | `HOLIDAY_CALENDAR_INCOMPLETE` | browser | Active |
| Pipeline stage CRUD | `routers/admin/pipeline.py` | `PIPELINE_CONFIG_UPDATED` | browser | Active |
| Suspicious login | `routers/auth.py` | `SUSPICIOUS_LOGIN` | browser, email | Active |
| Officer availability | `officer_service` | `OFFICER_AVAILABILITY_CHANGED` | browser | Active |

### 2.8 Organization Config

| Action | Service/Router | Event(s) | Channels | Status |
|---|---|---|---|---|
| Unit CRUD | `routers/admin/organization.py` | `UNIT_CREATED/UPDATED/DELETED` | — | **Domain broadcast only, no user notification** |
| Program CRUD | `routers/admin/organization.py` | `PROGRAM_CREATED/UPDATED/DELETED` | — | **Domain broadcast only** |
| Offering CRUD | `routers/admin/organization.py` | `OFFERING_CREATED/UPDATED/DELETED` | — | **Domain broadcast only** |

### 2.9 Actions with NO notification (candidates for future)

| Action | Service | Priority to add |
|---|---|---|
| Payment recorded (pending verification) | `payment_service` | High — finance officer should know |
| Payment rejected | `payment_service` | High — submitter should know |
| Invoice created/issued | `invoice_service` | Medium |
| Lead restored | `lead_service` | Low |
| Consultation restored | `lead_service` | Low |
| User created | `user_service` | Medium — new user welcome |
| Password reset by admin | `user_service` | Medium — user should know |
| CTV reactivated | `collaborator_service` | Medium |
| Lead import completed | `lead_service` | Low |
| Fee fully paid | `fee_calculation_service` | High — enrollment trigger |
| Refund processed | `payment_service` | Medium |

---

## 3. Recipient Routing — Who sees what

### 3.1 Role definitions

| Role | Code | Scope | Description |
|---|---|---|---|
| `admin` | `UserRole.ADMIN` | System-wide | Full access, all units |
| `manager` | `UserRole.MANAGER` | Unit-scoped | Manages officers in unit |
| `accountant` | `UserRole.ACCOUNTANT` | Unit-scoped | Finance operations |
| `officer` | `UserRole.OFFICER` | Unit-scoped | Direct lead/consultation work |
| `collaborator` | `UserRole.COLLABORATOR` | External | CTV, limited system access |
| `user` | `UserRole.USER` | Minimal | Basic access |
| **applicant** | **Not in system** | **External** | **Lead/student — no system account** |

### 3.2 Existing resolvers

| Resolver | Target | Used by events |
|---|---|---|
| `LeadOwnerResolver` | Officer assigned to lead | LEAD_ASSIGNED, LEAD_UPDATED, CONSULTATION_* |
| `UnitManagersResolver` | Managers/admins in unit | LEAD_CREATED |
| `AllAdminsResolver` | All admin users | APPLICATION_CREATED, HOLIDAY_CALENDAR, PIPELINE_CONFIG |
| `AllUsersResolver` | All active users | SYSTEM_ALERT, SYSTEM_ANNOUNCEMENT |
| `SpecificUsersResolver` | Explicit user IDs | USER_ROLE_CHANGED, USER_DEACTIVATED, PAYMENT_VERIFIED |
| `CollaboratorUserResolver` | CTV's linked user | All CTV_* events |
| `CompositeResolver` | Merge multiple | LEAD_CREATED (managers + admins) |
| `ActorExcludedResolver` | Exclude triggering user | LEAD_CREATED, APPLICATION_CREATED |
| `DormResidentsResolver` | Dorm residents | **Placeholder, returns []** |
| `DormStaffResolver` | Dorm staff | **Placeholder, returns []** |

### 3.3 Current recipient matrix by action

#### Lead actions

| Action | Admin sees | Manager sees | Officer sees | Accountant sees | CTV sees | Applicant sees |
|---|---|---|---|---|---|---|
| Lead created | Yes (if in unit) | Yes (if in unit) | No (unless assigned) | No | No | **No** |
| Lead assigned | No | No | **Yes (assignee)** | No | No | **No** |
| Lead updated | No | Yes (unit) | **Yes (owner)** | No | No | **No** |
| Lead status changed | No | No | **Yes (owner)** | No | No | **No** |
| Lead reassigned | No | Yes (target unit) | **Yes (old+new)** | No | No | **No** |
| Lead deleted | No | Yes (unit) | **Yes (ex-owner)** | No | No | **No** |

#### Admission actions

| Action | Admin sees | Manager sees | Officer sees | Accountant sees | CTV sees | Applicant sees |
|---|---|---|---|---|---|---|
| Profile created | **Yes** | No | No | No | No | **No** |
| Profile approved | **Yes** (via composite) | No | No | No | No | **No** |
| Student enrolled | **Yes** | No | No | No | No | **No** |
| Profile rejected | No | No | **Yes** (via LEAD_STATUS) | No | No | **No** |

#### Finance actions

| Action | Admin sees | Manager sees | Officer sees | Accountant sees | CTV sees | Applicant sees |
|---|---|---|---|---|---|---|
| Payment verified | No | No | **Yes (lead owner)** | **No** | No | **No** |
| Payment recorded | **No notification** | | | | | |
| Payment rejected | **No notification** | | | | | |
| Payment overdue | **Not emitted** | | | | | |

#### User admin actions

| Action | Admin sees | Manager sees | Officer sees | Accountant sees |
|---|---|---|---|---|
| Role changed | No | No | **Yes (affected user)** | No |
| User deactivated | No | No | **Yes (affected user)** | No |
| Profile updated by admin | No | No | **Yes (affected user)** | No |

#### CTV actions

| Action | Admin sees | Manager sees | Officer sees | CTV sees |
|---|---|---|---|---|
| Claim submitted | **Yes (unit managers)** | **Yes (unit managers)** | No | No |
| Claim approved/rejected | No | No | No | **Yes** |
| CTV approved/suspended | No | No | No | **Yes** |
| Commission created | No | No | No | **Yes** |
| Attribution expiring | No | No | No | **Yes** |

#### System actions

| Action | Admin sees | Manager sees | Officer sees | All users |
|---|---|---|---|---|
| System alert | Yes | Yes | Yes | **Yes** |
| System announcement | Yes | Yes | Yes | **Yes** |
| Holiday calendar incomplete | **Yes** | No | No | No |
| Pipeline config updated | **Yes** | No | No | No |
| Suspicious login | **Yes** | Yes | Yes | **Yes** |

### 3.4 Gaps identified — resolvers needed

| Gap | Current | Needed | Priority |
|---|---|---|---|
| **Manager visibility into unit activity** | Manager only sees LEAD_CREATED | Manager should see payment verified, admission status, lead assigned in their unit | **High** |
| **Accountant visibility** | No resolver targets accountant role | Need `UnitAccountantsResolver` or include in `UnitManagersResolver` | **High** |
| **Applicant/External** | No external recipient support | Need `ExternalRecipientResolver` (lead phone/email) — Zalo ZNS Phase 1 | **High** |
| **Supervisor chain** | No hierarchy-based routing | Need resolver that walks unit parent chain | **Low** |
| **Fee fully paid → enrollment team** | No notification | Need event + composite resolver | **Medium** |
| **Payment recorded → verifier queue** | No notification | Need event targeting accountants/managers | **High** |
| **Payment rejected → original recorder** | No notification | Need `SpecificUsersResolver` targeting `created_by_id` | **Medium** |

### 3.5 Proposed resolver additions

```
ExternalLeadResolver       → Lead.phone (for Zalo/SMS)
UnitAccountantsResolver    → Users with role=accountant in payload.unit_id
PaymentCreatorResolver     → Payment.created_by_id (notify original recorder)
LeadOwnerAndManagerResolver → Composite: officer + unit managers (for key events)
```

---

## 4. Summary: What works, what's missing

### Works well
- Lead CRUD notifications — mature, correct resolver routing
- CTV lifecycle — comprehensive, correct routing
- System alerts — broadcast to all users
- Per-channel preference filtering — independent channel control
- Deduplication — prevents duplicate notifications
- Actor exclusion — actor doesn't notify themselves

### Missing / Needs work
- **Applicant/external delivery** — zero external notifications (Zalo ZNS Phase 1 solves this)
- **Manager blind spot** — managers don't see most unit activity beyond lead creation
- **Accountant role** — no resolver, no notifications for finance role
- **Payment flow gaps** — no notification for record/reject, overdue not emitted
- **Admission mixed semantics** — dual event emission (APPLICATION_* + LEAD_STATUS_CHANGED)
- **Organization events** — emitted but produce no user notifications
- **Configurable routing** — resolver selection is hardcoded, not admin-configurable

### Recommended priority for next phase
1. Zalo ZNS Phase 1 (external applicant notifications) — Epic 2-3
2. Manager visibility expansion (add `UnitManagersResolver` to key events)
3. Accountant resolver + finance notification gaps
4. Admin-configurable recipient routing (DB rule override for resolvers)
