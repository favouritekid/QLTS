---
trigger: always_on
---

## THIN CLIENT · STATE OWNERSHIP · HOOK SAFETY

> **STATUS:** MANDATORY
> **PURPOSE:** Enforce a **Thin Client** frontend where **Backend is the only source of business truth**.
> Frontend exists to **render, collect input, and reflect backend decisions** — nothing more.

---

## PART 0 — CORE PHILOSOPHY (NON-NEGOTIABLE)

### 0.1 Thin Client Doctrine

Frontend is a **Presentation Machine**.

It MAY:

* Render backend state
* Collect user input
* Improve UX (loading, optimistic UI, hints)

It MUST NOT:

* Decide correctness
* Calculate business outcomes
* Infer workflows or permissions

> **Immutable Law**
> **Frontend may optimize UX, but may NEVER decide correctness.**

If logic answers **“Is this correct / allowed?”** → **Backend owns it**.

---

### 0.2 Five Golden Rules

| # | Rule                       | Forbidden Example                    |
| - | -------------------------- | ------------------------------------ |
| 1 | Backend is Source of Truth | FE calculates `totalScore`           |
| 2 | Status-Driven UI           | FE shows “Approved” from local state |
| 3 | No Inferred Workflow       | FE assumes `submitted → approved`    |
| 4 | Server Permissions Only    | FE checks `user.role === "admin"`    |
| 5 | ADR for Exceptions         | Silent rule violation                |

---

## PART 1 — BUSINESS STATE OWNERSHIP (CRITICAL)

### 1.1 State Ownership Table

| State           | Owner            | FE Authority |
| --------------- | ---------------- | ------------ |
| Workflow status | Backend FSM      | READ ONLY    |
| Eligibility     | Backend service  | READ ONLY    |
| Business rules  | Backend config   | READ ONLY    |
| Computed values | Backend response | READ ONLY    |
| Permissions     | Backend (Casbin) | READ ONLY    |

> **Rule:**
> FE must render **exact backend state**.
> FE must NOT invent, merge, or predict states.

---

### 1.2 Forbidden State Inference

```tsx
// ❌ FORBIDDEN
const isPending = status === "submitted" && !approved_at;
const canEdit = status === "draft" || status === "rejected";
const nextStatus = isEligible ? "approved" : "rejected";
```

```tsx
// ✅ REQUIRED
const { status, can_edit, available_actions } = profile;
```

---

### 1.3 Backend Contract (MANDATORY)

Every business resource MUST return:

* `status` (enum, exact)
* `available_actions: string[]`
* `can_*` permission flags
* `validation_errors?: string[]`
* `computed_*` values (scores, percent, etc.)

Frontend **must not guess missing fields**.

---

## PART 2 — API & CONTRACT GOVERNANCE

### 2.1 Contract-First Workflow

1. Backend defines schema & enums
2. Backend publishes OpenAPI / contract
3. Frontend mirrors via Zod
4. FE + BE review breaking changes

**Breaking changes require deprecation. Always.**

---

### 2.2 Enum Stability Rule

* Never rename or remove enum values
* Only add new values
* No ambiguous states (`pending` is forbidden)

Frontend must handle **unknown future states gracefully**.

---

## PART 3 — FRONTEND AUTHORITY LIMITS

### 3.1 Hard Boundaries

Frontend may NEVER:

* Calculate eligibility or scores
* Infer workflow transitions
* Override server permissions
* Default business values
* Store sensitive data
* Batch business mutations

Frontend may ONLY:

* Render backend decisions
* Validate input **format** (not business rules)
* Optimize UX
* Cache for performance (not truth)

---

### 3.2 Presentation vs Decision Test

| Question                 | Owner    |
| ------------------------ | -------- |
| How to display?          | Frontend |
| What is correct/allowed? | Backend  |

---

## PART 4 — LAYER MODEL

```
Presentation (Render Only)
        ↓
Frontend Domain Service (View Model)
        ↓
State Management (React Query / RHF)
        ↓
API Client (Typed, No Logic)
        ↓
Backend (ONLY source of truth)
```

---

## PART 5 — MANDATORY PATTERNS

### 5.1 Status-Driven Rendering

```tsx
// ❌ WRONG
<Button disabled={!isEligible}>Submit</Button>

// ✅ CORRECT
<Button disabled={eligibility_status !== "eligible"}>Submit</Button>
```

---

### 5.2 Permission-Based UI

```tsx
// ❌ WRONG
user.role === "manager"

// ✅ CORRECT
profile.can_approve
```

---

### 5.3 Async-First Thinking

Never assume synchronous completion.
Always handle all returned states.

---

### 5.4 Optimistic Locking

409 Conflict MUST:

* Notify user
* Offer refresh
* Never silently override data

---

## PART 6 — FRONTEND DOMAIN SERVICE LAYER (MANDATORY)

### 6.1 Purpose

This layer exists to answer ONE question:

> **How should backend data be shaped so UI can render safely without violating Hooks rules?**

It is:

* NOT business logic
* NOT correctness
* NOT side-effect driven

---

### 6.2 Data Flow

```
Backend → React Query → Domain Service (View Model) → Component
```

Components MUST NOT derive logic themselves.

---

### 6.3 Allowed Responsibilities

* Map enums → labels / colors
* Derive UX-only flags from backend permissions
* Normalize data for rendering
* Safe optional access (no `|| {}`)

---

### 6.4 Prohibitions

* No eligibility calculation
* No workflow inference
* No side effects
* No `useEffect` for data sync (except RHF reset)

---

### 6.5 View Model Pattern

```ts
export function useAdmissionViewModel(id: number) {
  const query = useGetAdmission(id);

  const vm = useMemo(() => {
    if (!query.data) return null;
    const { status, available_actions, applied_rules, ...rest } = query.data;

    return {
      ...rest,
      status,
      status_label: STATUS_LABELS[status] ?? status,
      can_submit: available_actions.includes("submit"),
      min_gpa: applied_rules?.min_gpa,
    };
  }, [query.data]);

  return { ...query, data: vm };
}
```

---

### 6.6 Form Sync Rules

**Preferred:** `key` remount
**Allowed exception:** `form.reset()` inside `useEffect`

No other `setState-in-effect` is allowed.

---

## PART 7 — ANTI-PATTERNS (AUTO-REJECT)

* Thick Validator
* God Component
* Inferred State
* Hardcoded Business Config
* Re-render Storm from global watchers

---

## PART 8 — COMPLIANCE CHECKLIST

Before merging:

* [ ] No business logic in FE?
* [ ] Status & permissions from backend?
* [ ] No inferred states?
* [ ] Domain Service used?
* [ ] No `any`, no `|| {}`?
* [ ] Hooks rules satisfied by design?


