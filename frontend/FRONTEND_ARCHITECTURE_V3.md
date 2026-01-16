# 📐 QLTS FRONTEND ARCHITECTURE – V3.1 (THIN CLIENT)

> **ABSTRACT**
> This document is the **Single Source of Truth** for QLTS Frontend. It mandates a **Thin Client** architecture where the **Backend is the ultimate source of truth** for all business logic, state, and workflow. 
> **COMPLIANCE LEVEL: MANDATORY.**

---

## PART 0: CORE PHILOSOPHY

### 0.1. The "Thin Client" Mindset

The architecture is designed to make **logic duplication impossible** by default. The Frontend is a **Presentation Machine** that:
- **Renders** what the Backend tells it (status, eligibility, permissions).
- **Collects** user input and sends it to the Backend.
- **Reflects** the outcome of Backend operations.

**It does NOT:**
- Calculate eligibility or validate business rules.
- Infer or predict workflow transitions.
- Own any source of truth beyond transient UI state.

### 0.2. The Immutable Law

> **"Frontend may optimize UX, but may NEVER decide correctness."**

This single sentence governs all decisions. If you are unsure whether something belongs in FE or BE, ask: *"Does this decide if an action is correct?"* If yes → **Backend**.

### 0.3. The 5 Golden Rules (Immutable)

| # | Rule | Violation Example |
|---|------|-------------------|
| 1 | **Backend is Source of Truth** | FE calculates `totalScore` instead of reading `profile.total_score` from API. |
| 2 | **Status-Driven Rendering** | FE shows "Approved" badge based on local state, not `profile.status`. |
| 3 | **No Inferred Workflows** | FE assumes `submit -> approved` immediately, ignoring `SUBMITTED` state. |
| 4 | **Permissions from Server** | FE hides button based on `user.role` string instead of backend `permissions` flag. |
| 5 | **ADR for Exceptions** | Any deviation from these rules requires a documented Architecture Decision Record. |

---

## PART 0.5: BUSINESS STATE OWNERSHIP (CRITICAL)

> [!CAUTION]
> This section defines **where business state lives** and **how FE may read it**.
> Violations here cause the most dangerous bugs: silent data corruption and UX lies.

### 0.5.1. State Ownership Declaration

| State Category | Owner | FE Authority |
|----------------|-------|--------------|
| **Workflow Status** (draft, submitted, approved...) | Backend State Machine | READ ONLY. Render as-is. |
| **Eligibility** (can submit, can enroll...) | Backend Service | READ ONLY. No local calculation. |
| **Business Rules** (min GPA, required docs...) | Backend Config / applied_rules | READ ONLY. No default fallbacks. |
| **Computed Values** (total score, completion %) | Backend Response | READ ONLY. No FE recalculation. |
| **Permissions** (can approve, can reject...) | Backend Casbin | READ ONLY. UX hints only. |

### 0.5.2. The State Contract

> **"Mọi trạng thái nghiệp vụ PHẢI được định nghĩa trong Backend State Machine hoặc Enum Contract. Frontend CHỈ ĐƯỢC render dựa trên state đó, KHÔNG ĐƯỢC suy diễn trạng thái trung gian."**

**FORBIDDEN Inferences:**
```tsx
// ❌ FORBIDDEN - FE inventing intermediate state
const isPending = status === "submitted" && !approved_at;
// This "pending" state does not exist in backend enum!

// ❌ FORBIDDEN - FE combining states
const canEdit = status === "draft" || status === "rejected";
// Backend should return `can_edit: true/false`

// ❌ FORBIDDEN - FE guessing next state
const nextStatus = isEligible ? "approved" : "rejected";
// Only backend decides transitions!
```

**REQUIRED Pattern:**
```tsx
// ✅ CORRECT - FE reads exact backend state
const { status, can_edit, available_actions } = profile;

// Render status badge
<Badge>{STATUS_LABELS[status]}</Badge>

// Show edit button
{can_edit && <EditButton />}

// Show available actions
{available_actions.includes("submit") && <SubmitButton />}
```

### 0.5.3. What Backend MUST Provide

For every resource (AdmissionProfile, Lead, etc.), the API response MUST include:

| Field | Type | Purpose |
|-------|------|---------|
| `status` | `string (enum)` | Exact state from state machine. No ambiguity. |
| `available_actions` | `string[]` | Actions user can perform: `["save", "submit", "approve"]` |
| `can_*` flags | `boolean` | Permission checks: `can_edit`, `can_approve`, `can_delete` |
| `validation_errors` | `string[]` | Why action is blocked (if blocked) |
| `computed_*` fields | `number/string` | Server-calculated values: `total_score`, `completion_percent` |

---

## PART 0.6: API & STATE CONTRACT GOVERNANCE

> [!IMPORTANT]
> This section defines **how FE and BE stay in sync** as contracts evolve.
> Without this, FE will drift from BE over time.

### 0.6.1. Contract First Development

**Process:**
1. **Backend defines** → Pydantic schemas, enums, state machine
2. **Backend publishes** → OpenAPI spec or shared contract file
3. **Frontend mirrors** → Zod schemas from OpenAPI or manually synced
4. **Both teams review** → Contract changes require FE+BE signoff

**Artifacts:**
- `Backend: app/schemas/*.py` → Pydantic models
- `Frontend: lib/zod/*.ts` → Zod schemas (must match Pydantic)
- `Shared: docs/contracts/*.md` → Human-readable contract docs

### 0.6.2. Breaking Change Policy

| Change Type | Allowed? | Process |
|-------------|----------|---------|
| **Add optional field** | ✅ Yes | No FE change needed |
| **Add required field** | ⚠️ Careful | Coordinate deploy order |
| **Rename field** | ❌ Breaking | Deprecation period required |
| **Remove field** | ❌ Breaking | Deprecation period required |
| **Change field type** | ❌ Breaking | New field + deprecate old |
| **Change enum values** | ❌ Breaking | Versioned enum or deprecation |

**Deprecation Process:**
1. Backend adds new field, marks old as `@deprecated`
2. FE migrates to new field within 2 sprints
3. Backend removes old field after FE migration confirmed

### 0.6.3. Enum & Status Versioning

**Rule:** Status enums are part of the API contract. Changing them is a breaking change.

```python
# Backend: Never remove or rename, only add
class AdmissionStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"  # v1.0
    RESUBMITTED = "resubmitted"  # Added v1.1
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"  # Added v1.2
    ENROLLED = "enrolled"
    # PENDING = "pending"  # ❌ NEVER add ambiguous states
```

```typescript
// Frontend: Must match exactly
const AdmissionStatus = z.enum([
  "draft",
  "submitted",
  "resubmitted",
  "approved",
  "rejected",
  "confirmed",
  "enrolled",
]);
```

### 0.6.4. FE Handling Unknown States

**Principle:** FE must gracefully handle states it doesn't recognize (future-proofing).

```tsx
// ✅ CORRECT - Fallback for unknown states
const STATUS_CONFIG: Record<string, StatusConfig> = {
  draft: { label: "Nháp", color: "gray" },
  submitted: { label: "Chờ duyệt", color: "yellow" },
  // ... known states
};

function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] ?? { 
    label: status, // Display raw status as fallback
    color: "gray" 
  };
  return <Badge color={config.color}>{config.label}</Badge>;
}
```

---

## PART 0.7: FRONTEND AUTHORITY LIMITS

> [!WARNING]
> This section defines **what FE is NOT allowed to do**, even if technically possible.
> These are HARD LIMITS, not suggestions.

### 0.7.1. Authority Boundary Statement

| Question | Answer | Rationale |
|----------|--------|-----------|
| Can FE cache business state? | ❌ NO | React Query cache is for UX performance, not truth. Always refetch for critical actions. |
| Can FE batch business actions? | ❌ NO | Each action must be a separate API call. BE owns transaction boundaries. |
| Can FE pre-validate business rules? | ❌ NO | FE may only validate format (email syntax). BE validates business (email unique). |
| Can FE compute derived values? | ❌ NO | If value affects business decision (score, eligibility), BE computes. |
| Can FE store sensitive data? | ❌ NO | No tokens, no full CCCD, no passwords in any client storage. |
| Can FE decide workflow transitions? | ❌ NO | Even if FE "knows" the next state, only BE can transition. |

### 0.7.2. The "Presentation vs Decision" Test

Before writing any logic, ask:

```
Is this logic about HOW to display something?  → FE owns it
Is this logic about WHAT is correct/allowed?   → BE owns it
```

**Examples:**

| Logic | Where? | Reason |
|-------|--------|--------|
| "Format phone as 0xxx-xxx-xxx" | FE | Presentation |
| "Phone must be unique" | BE | Business rule |
| "Show red border if email invalid" | FE | Presentation |
| "Email must match regex + not exist in DB" | BE | Business rule |
| "Disable button if form is incomplete" | FE | UX (can be wrong) |
| "Block submission if eligibility fails" | BE | Correctness (must be right) |

### 0.7.3. Hard Prohibitions (Non-Negotiable)

```yaml
FRONTEND MAY NEVER:
  - Calculate eligibility (GPA thresholds, document counts)
  - Infer status transitions ("if submitted and approved_at exists...")
  - Store or transmit tokens except via httpOnly cookies
  - Override server permissions with local role checks
  - Batch multiple business mutations into one action
  - Cache business state beyond React Query's stale time
  - Default business values (use null, force server to provide)

FRONTEND MAY ONLY:
  - Render what server says
  - Collect user input
  - Validate input FORMAT (not business rules)
  - Optimize UX with loading states, optimistic UI
  - Cache data for performance (not for truth)
```

---

## PART 1: LAYER MODEL

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND LAYERS                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LAYER 1: PRESENTATION                    │  │
│  │                                                           │  │
│  │  • Pages (Server Components)                              │  │
│  │  • Layouts, Loading, Error Boundaries                     │  │
│  │  • Tab / Card / Form Components                           │  │
│  │                                                           │  │
│  │  🔴 RULE: Dumb. Renders props. No calculations.           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LAYER 2: STATE MANAGEMENT                │  │
│  │                                                           │  │
│  │  • React Query (Server State)                             │  │
│  │  • React Hook Form (Form State)                           │  │
│  │  • Zustand (UI-only ephemeral state)                      │  │
│  │                                                           │  │
│  │  🟡 RULE: Caches. No business logic. No calculations.     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LAYER 3: API CLIENT                      │  │
│  │                                                           │  │
│  │  • Axios Instance with Interceptors                       │  │
│  │  • Typed API Functions (admissionsApi.getProfile())       │  │
│  │  • Zod Schemas for Response Validation                    │  │
│  │                                                           │  │
│  │  🟢 RULE: Transforms HTTP to Domain Objects. No logic.    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LAYER 4: BACKEND (TRUSTED)               │  │
│  │                                                           │  │
│  │  • FastAPI Services                                       │  │
│  │  • Casbin RBAC                                            │  │
│  │  • PostgreSQL / Redis                                     │  │
│  │                                                           │  │
│  │  ✅ This is the ONLY source of business truth.            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## PART 2: MANDATORY PATTERNS

### 2.1. Status-Driven Rendering

**Principle:** UI reflects backend status. UI does NOT compute status.

```tsx
// ❌ WRONG - FE infers status
const isEligible = gpa >= minGpa && docsUploaded >= requiredDocs;
<Button disabled={!isEligible}>Submit</Button>

// ✅ CORRECT - FE reads backend flag
const { eligibility_status } = profile; // "eligible" | "ineligible" | "pending"
<Button disabled={eligibility_status !== "eligible"}>Submit</Button>
```

**Implementation:** Backend API MUST return computed flags like:
- `eligibility_status: "eligible" | "ineligible"`
- `available_actions: ["submit", "enroll"]`
- `validation_errors: []`

---

### 2.2. Permission-Based Visibility

**Principle:** Show/hide UI based on backend-provided permissions, NOT client-side role checks.

```tsx
// ❌ WRONG - FE checks role string
{user.role === "manager" && <ApproveButton />}

// ✅ CORRECT - FE checks permission flag from API
{profile.can_approve && <ApproveButton />}
// OR
{user.permissions.includes("admission:approve") && <ApproveButton />}
```

---

### 2.3. Async-First Workflows

**Principle:** Never assume synchronous completion. Always handle pending states.

```tsx
// ❌ WRONG - Assumes immediate approval
onSuccess: (data) => {
  if (data.status === 'approved') toast.success('Approved!');
}

// ✅ CORRECT - Handles all states
onSuccess: (data) => {
  switch (data.status) {
    case 'submitted': toast.info('Chờ duyệt'); break;
    case 'approved': toast.success('Đã duyệt'); break;
    case 'rejected': toast.error('Từ chối'); break;
    default: toast.info(`Trạng thái: ${data.status}`);
  }
}
```

---

### 2.4. Optimistic Locking Handling

**Principle:** Handle `409 Conflict` gracefully. Never lose user data.

```tsx
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 409) {
      toast.error("Data đã được cập nhật bởi người khác.", {
        action: { label: "Làm mới", onClick: () => queryClient.invalidateQueries() }
      });
    }
    return Promise.reject(error);
  }
);
```

---

### 2.5. Thin Validation

| Validation Layer | Purpose | Examples |
|------------------|---------|----------|
| **Client (Zod)** | UX - Format only | `email.includes('@')`, `phone.length === 10` |
| **Server (Pydantic)** | Truth - Business rules | `min_gpa >= program.requirement` |

**Rule:** If validation depends on external data → **Server**.

---

### 2.6. Frontend Domain Service Layer (MANDATORY)

> [!CRITICAL]
> This section formalizes the **Frontend Domain Service Layer**.
> Its purpose is to **prevent logic leakage into components and useEffect**, and to enforce **Hook safety by architecture, not discipline**.

---

#### 2.6.1. Definition

The **Frontend Domain Service Layer** is a mandatory abstraction responsible for **UX-oriented data shaping** that:

* Is **NOT** business logic
* Does **NOT** decide correctness
* Does **NOT** mutate authoritative state

It exists to answer one question:

> **"How should backend data be prepared so UI can render it safely, predictably, and without violating Hooks rules?"**

---

#### 2.6.2. Data Flow Hierarchy

```
Backend API → React Query Cache → Domain Service (View Model) → Component (Render Only)
```

- Components **MUST NOT** access React Query directly for complex domains.
- Components **MUST** consume View Models from Domain Service hooks.

---

#### 2.6.3. State Ownership

| State Type | Owner | Example |
|------------|-------|---------|
| Business State | Backend | `status`, `eligibility`, `permissions` |
| Server Cache | React Query | `useQuery`, `useMutation` |
| UI State | Component/Context | `isModalOpen`, `currentStep`, `selectedTab` |
| Form State | React Hook Form | `useForm`, `watch`, `reset` |

---

#### 2.6.4. Responsibilities (What This Layer MAY Do)

This layer MAY:

* Normalize and reshape API responses for rendering
* Map backend enums → UI labels, colors, icons
* Group, sort, or filter data for **display only**
* Derive **UX-only flags** from backend-provided fields
* Centralize conditional rendering logic based on `status`, `available_actions`, `can_*`

```ts
// ✅ ALLOWED: UX-only derivation
const canShowSubmitHint = available_actions.includes("submit");
const statusLabel = STATUS_LABELS[status] ?? status;
```

---

#### 2.6.5. Prohibitions (Hard Limits)

This layer **MUST NOT**:

* Calculate eligibility, scores, or thresholds
* Infer workflow transitions
* Combine backend states into new pseudo-states
* Override or default missing backend values with business fallbacks
* Perform side effects (no toast, no navigation, no mutation)
* Use `useEffect` to synchronize state

```ts
// ❌ FORBIDDEN: business inference
const isEligible = gpa >= minGpa;

// ❌ FORBIDDEN: invented workflow state
const isPending = status === "submitted" && !approved_at;

// ❌ FORBIDDEN: unsafe type fallback
const rules = profile?.applied_rules || {}; // Loses type info

// ✅ CORRECT: safe optional chaining
const minGpa = profile?.applied_rules?.min_gpa ?? 0;
```

---

#### 2.6.6. Mandatory Implementation Pattern

**Directory Structure:**
```
/hooks/[domain]/
  useDomainViewModel.ts   # Main View Model hook
  useDomainMutations.ts   # Mutations with callbacks
  types.ts                # Domain-specific View Model types
```

**View Model Hook Pattern:**
```ts
// hooks/admissions/useAdmissionViewModel.ts
export function useAdmissionViewModel(id: number) {
  // 1. Fetch from React Query
  const query = useGetAdmission(id);

  // 2. Derive View Model with useMemo (NO useEffect!)
  const viewModel = useMemo(() => {
    if (!query.data) return null;

    const { status, available_actions, applied_rules, ...rest } = query.data;

    return {
      // Pass-through fields
      ...rest,
      status,

      // UI Labels (mapping)
      status_label: STATUS_LABELS[status] ?? status,
      status_color: STATUS_COLORS[status] ?? "gray",

      // Action Flags (from backend permissions)
      can_edit: available_actions.includes("edit"),
      can_submit: available_actions.includes("submit"),
      can_approve: available_actions.includes("approve"),

      // Safe Access (optional chaining, NO fallback objects)
      min_gpa: applied_rules?.min_gpa,
      mandatory_docs: applied_rules?.mandatory_docs ?? [],
    };
  }, [query.data]);

  return { ...query, data: viewModel };
}
```

📌 **Rule:**
Components **MUST consume the View Model** returned by this layer.
Components **MUST NOT re-derive logic locally**.

---

#### 2.6.7. Form Integration Pattern

For forms that need to sync with API data:

**Pattern A: Using `reset()` (Controlled Sync)**
```tsx
function MyFormComponent({ profileId }: Props) {
  const { data: profile } = useAdmissionViewModel(profileId);

  const form = useForm<FormSchema>({
    defaultValues: {} // Empty, will be populated by reset
  });

  // Reset form when profile changes (single, controlled sync point)
  useEffect(() => {
    if (profile) {
      form.reset({
        full_name: profile.full_name ?? "",
        email: profile.email ?? "",
        // ... other fields
      });
    }
  }, [profile, form.reset]); // form.reset is stable

  return <Form {...form}>...</Form>;
}
```

> [!NOTE]
> This is the **ONLY** approved use of `setState`-like operations in `useEffect`.
> The `form.reset` call is idempotent and controlled by React Hook Form.

**Pattern B: Using `key` Prop (Preferred for Simple Cases)**
```tsx
// ✅ BEST: Component re-mounts when ID changes, no useEffect needed
<MyFormComponent key={profileId} profileId={profileId} />
```

---

#### 2.6.8. Derived State Pattern

For UI state that depends on fetched data:

```tsx
// ❌ FORBIDDEN: setState in useEffect
const [selections, setSelections] = useState<Record<number, Item>>({});

useEffect(() => {
  if (apiData?.items) {
    const map = {};
    apiData.items.forEach(item => { map[item.id] = item; });
    setSelections(map); // ❌ Triggers re-render, causes "set-state-in-effect"
  }
}, [apiData]);

// ✅ CORRECT: Derive in useMemo
const selections = useMemo(() => {
  if (!apiData?.items) return {};
  const map: Record<number, Item> = {};
  apiData.items.forEach(item => { map[item.id] = item; });
  return map;
}, [apiData?.items]);
```

---

#### 2.6.9. No Fallback Objects Rule

```tsx
// ❌ FORBIDDEN: Loses TypeScript type information
const appliedRules = profile?.applied_rules || {};
const minGpa = appliedRules.min_gpa; // Error: Property 'min_gpa' does not exist on type '{}'

// ✅ CORRECT: Keep undefined, use optional chaining
const appliedRules = profile?.applied_rules; // Type: AppliedRules | undefined
const minGpa = appliedRules?.min_gpa ?? 0; // Type: number
```

---

#### 2.6.10. Relationship to Other Layers

| Layer                    | Responsibility              |
| ------------------------ | --------------------------- |
| Presentation             | Render View Model only      |
| **Domain Service (2.6)** | Prepare View Model          |
| State Management         | Cache & fetch server state  |
| API Client               | HTTP transport & validation |
| Backend                  | Business truth & decisions  |

This layer is the **only approved place** for UX derivation logic.

---

#### 2.6.11. Hook Safety Guarantees

By construction, this layer:

* ✅ Eliminates `set-state-in-useEffect` lint errors
* ✅ Makes `exhaustive-deps` naturally correct
* ✅ Prevents stale closures
* ✅ Reduces re-render storms

> **If logic fits here, it MUST NOT appear in components or effects.**

---

#### 2.6.12. Review Checklist (Non-Negotiable)

- [ ] Does this logic belong to UX, not correctness?
- [ ] Is it derived only from backend-provided fields?
- [ ] Is it implemented without `useEffect` setState (except form.reset)?
- [ ] Is the component free of conditional business logic?
- [ ] Are all types explicit (no `any`, no `|| {}` fallbacks)?

**Violation of this section is considered a Frontend Architecture breach.**

---



### ❌ The "Thick Validator" Anti-Pattern
FE calculates eligibility from rules it shouldn't own.

### ❌ The "God Component" Anti-Pattern
One component manages everything (form + nav + mutations + validation).

### ❌ The "Re-render Storm" Anti-Pattern
Global `useWatch` causes full re-render on every keystroke.

### ❌ The "Hardcoded Config" Anti-Pattern
Limits and labels hardcoded instead of fetched from API.

### ❌ The "Inferred State" Anti-Pattern
FE combining server fields to create fake intermediate states.

---

## PART 4: STATE CLASSIFICATION

| State Type | Tool | Example | Persisted? |
|------------|------|---------|------------|
| **Server State** | React Query | Lead data, Admission profile | ✅ (cache) |
| **Form State** | React Hook Form | Draft form inputs | Session only |
| **UI State** | Zustand | Sidebar open, modal visibility | ❌ |
| **URL State** | Next.js Router | Filters, pagination | ✅ (URL) |

**Rule:** NEVER cache server state in Zustand. NEVER use React Query for UI toggles.

---

## PART 5: SECURITY & TRUST ZONES

```
┌─────────────────────────────────────────────────────────────────┐
│  UNTRUSTED (Browser)           │   TRUSTED (Server)             │
│  ───────────────────────────   │   ─────────────────────────    │
│  • localStorage                │   • httpOnly cookies           │
│  • User input                  │   • JWT validation             │
│  • URL query params            │   • Casbin RBAC                │
│  • FE-computed flags           │   • Database queries           │
│                                │                                 │
│  🔴 NEVER trust for decisions  │   🟢 Source of truth           │
└─────────────────────────────────────────────────────────────────┘
```

---

## PART 6: COMPLIANCE CHECKLISTS

### ✅ Page/Component Checklist
- [ ] Renders based on backend status (not computed)?
- [ ] Buttons gated by `can_*` flags from API?
- [ ] Handles all status values (including unknown)?
- [ ] No inferred/combined states?

### ✅ Mutation Checklist
- [ ] Handles `409 Conflict`?
- [ ] `onSuccess` switches on all possible statuses?
- [ ] No assumption of synchronous completion?

### ✅ State Checklist
- [ ] All business states from server?
- [ ] No local eligibility calculations?
- [ ] No default business values (use null)?

---

## PART 7: ADR TEMPLATE

When you MUST violate a rule:

```markdown
# ADR-FE-001: [Title]

## Status
Proposed | Accepted | Deprecated

## Context
Why is the violation necessary?

## Decision
What exception we are making.

## Consequences
- Sync risk with backend?
- Maintenance burden?

## Mitigation
How will we prevent drift?
```

---

*Architecture v3.1 – Thin Client Edition with State Ownership & Contract Governance*
*Last Updated: 2026-01-09*
