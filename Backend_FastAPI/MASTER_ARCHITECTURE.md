# QLTS MASTER BACKEND ARCHITECTURE & FRAMEWORK (V3.0)

> **ABSTRACT**
> This document is the **Single Source of Truth** for the QLTS Backend. It combines strict architectural mandates (`Security Gateway`) with practical implementation guidelines (`Patterns`, `Checklists`).
> **COMPLIANCE LEVEL: MANDATORY.**

---

## PART 0: CORE PHILOSOPHY & META-RULES

### 0.1. The "Security First" Mindset
The architecture is designed to make **insecurity impossible** by default. We do not rely on developer discipline to check permissions; we rely on the **Architecture** to enforce them.

*   **Secure by Design:** You cannot write a secure Router if you handle logic inside it. Logic belongs in a protected layer.
*   **Defense in Depth:** Security checks happen at multiple layers (Edge -> Dependency -> Service -> Query).
*   **Separation of Concerns:**
    *   **Router:** Dumb HTTP IO.
    *   **Dependency:** Intelligent Gatekeeper (Auth, RBAC, Context).
    *   **Service:** Pure Business Logic (No HTTP, No SQL).
    *   **Repository:** Pure Data Access (SQLAlchemy).

### 0.2. The 4 Golden Rules
1.  **Smart Dependency, Dumb Router:** If you are writing an `if` statement in a Router to check a permission or role, **YOU ARE WRONG**. This logic belongs in `deps.py`.
2.  **Service Isolation:** Services must never know they are running in a Web Server. No `Import Request`, No `HTTPException`.
3.  **Explicit Data Flow:** Data flows DOWN (`Router` -> `Service` -> `Repository`). Errors flow UP (Exceptions).
4.  **Transaction Responsibility:** The **Router** owns the transaction. The Service only behaves within it.

---

## PART 1: THE FOUR LAYERS (DETAILED)

### 1.1. LAYER 1: ROUTERS (THE DUMB COORDINATOR)

**Role:** The Router is merely a translator between HTTP (JSON) and Python Domain Objects.

#### FORBIDDEN ACTIONS IN ROUTER:
*   **No Business Logic:** `if amount > 1000:` -> Move to Service.
*   **No Authorization Logic:** `if user.role == 'admin':` -> Move to Dependency.
*   **No Direct DB Access:** `db.execute(select(...))` -> Use Repository.
*   **No Manual Instantiation:** `repo = UserRepo(db)` -> Use Dependency Injection.
*   **No Exception Logic:** `try...except` blocks should be minimal.
*   **No Generic Catch:** `except Exception:` -> Hides bugs, makes debugging impossible.
*   **No Exception Swallowing:** Catching Domain Exception without raising HTTP Error.

#### MANDATORY PATTERNS:
*   **Dependency Injection:** Everything (User, DB, Repo, Service) must come from `Depends()`.
*   **Response Models:** Every endpoint must have `response_model=Schema`.
*   **Transaction Commits:** The Router calls `await db.commit()`.

#### CODE EXAMPLE:
```python
@router.post("/items", response_model=ItemResponse)
async def create_item(
    item_in: ItemCreate,
    # ----------------------------------------
    # INPUT: Dependencies handle ALL context
    # ----------------------------------------
    current_user: User = Depends(get_current_active_user),
    repo: ItemRepo = Depends(get_item_repo),
    db: AsyncSession = Depends(get_db),
):
    # 1. DELEGATE to Service
    item, post_commit_callback = await item_service.create(db, repo, item_in, current_user)

    # 2. COMMIT Transaction
    await db.commit()

    # 3. SIDE EFFECTS (After commit success)
    await post_commit_callback()

    # 4. RETURN Pydantic Model
    return item
```

---

### 1.2. LAYER 2: SECURITY GATEWAY (DEPENDENCIES)

**Role:** The "Firewall" of the application. It ensures **Clean Input** and **Authorized Context** before code execution reaches the Router logic.

#### THE 4-STAGE DEFENSE SYSTEM:

1.  **Identity Layer (`get_current_active_user`)**:
    *   Validates JWT Signature.
    *   Checks Redis Blacklist (Logout).
    *   Checks `is_active` DB flag.
    *   *Result:* We know WHO they are.

2.  **Gatekeeping Layer (`require_roles`)**:
    *   Checks high-level static permissions only.
    *   Example: "Only Admins can enter this zone".
    *   *Result:* We know they are ALLOWED here.

3.  **Resource Access Layer (IDOR Protection)**:
    *   **CRITICAL:** Fetches the TARGET resource and checks OWNERSHIP.
    *   If user requests `/leads/100` but owns `/leads/99`: **RAISE 404 (Not 403)**.
    *   *Reason:* 403 reveals that ID 100 exists. 404 hides it.
    *   *Result:* Router receives a **Safe Object**.

4.  **Context Filtering Layer (`get_config_filter`)**:
    *   Modifies query parameters based on Role.
    *   Example: Student requests `?active_only=false`. Dependency converts to `True`.
    *   *Result:* Router receives **Sanitized Parameters**.

#### CODE EXAMPLE (IDOR PROTECTION):
```python
# deps.py
async def get_lead_access(
    lead_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Lead:
    repo = LeadRepository(db)
    lead = await repo.get(lead_id)

    # THE CHECK IS HERE, NOT IN ROUTER
    if not lead:
        raise ResourceNotFoundError()
    if user.role != 'admin' and lead.owner_id != user.id:
        raise ResourceNotFoundError() # Fake 404 for security

    return lead
```

---

### 1.3. LAYER 3: SERVICE (PURE LOGIC)

**Role:** The brain. It implements the business rules, state transitions, and calculations.

#### RULES:
*   **Pure Python:** Input is Pydantic/Model. Output is Model/Tuple.
*   **Context Safety:** MAY receive `User` domain object. **MUST NOT** receive `Request`, `Headers`, or `Tokens`.
*   **Repo Only:** Only talks to DB via Repositories.
*   **No Commits:** ideally does NOT call `db.commit()`. It prepares the state change.
*   **Return Callback:** Returns a closure `async def post_commit()` for tasks that must happen *after* DB success (Sending emails, Queueing jobs).

#### TRANSACTIONS & CALLBACK PATTERN:
Why return a callback? Because sending an email *before* the DB transaction commits is dangerous. If the commit fails, the email was sent falsely.

```python
async def update_status(db: AsyncSession, lead: Lead, new_status: str):
    # 1. Validation Logic
    if lead.status == 'closed':
        raise BusinessRuleError("Cannot reopen closed lead")

    # 2. State Change
    lead.status = new_status
    await db.flush() # Send to DB, but don't commit

    # 3. Prepare Side Effect
    async def post_commit():
        await send_notification(lead.owner_id, "Status Updated")

    return lead, post_commit
```

---

### 1.4. LAYER 4: REPOSITORY (DATA ACCESS)

**Role:** The Librarian. It efficiently retrieves and stores data.

#### RULES:
*   **Inherit Base:** Must inherit `BaseRepository[Model]`.
*   **Session Slave:** Operates strictly within the provided `AsyncSession`. **NEVER** creates or closes sessions.
*   **Eager Loading:** MUST use `selectinload` for relationships to avoid N+1 problems.
*   **No Logic:** `get_by_email` means "Get by Email", not "Get by Email and check if active".
*   **Return None:** Do not raise exceptions if not found. Return `None`.

---

## PART 2: CODING STANDARDS & BEST PRACTICES

### 2.1. Naming Conventions
*   **Routing:** `plural_nouns` (e.g., `users.py`, `leads.py`).
*   **Services:** `singular_service.py` (e.g., `user_service.py`).
*   **Repos:** `singular_repository.py` (e.g., `user_repository.py`).
*   **Variables:** `snake_case`.
*   **Classes:** `PascalCase`.

### 2.2. Error Handling (Domain Exceptions)
We Map Domain Exceptions to HTTP Codes in the Router or Exception Handler.

| Domain Exception (Service) | HTTP Code (Router) | Meaning |
|----------------------------|--------------------|---------|
| `ResourceNotFoundError` | 404 Not Found | Item missing or hidden (IDOR) |
| `DuplicateResourceError` | 409 Conflict | Unique constraint violation |
| `BusinessRuleViolation` | 400 Bad Request | Invalid state transition |
| `PermissionDeniedError` | 403 Forbidden | Valid user, invalid action |
| `AuthenticationError` | 401 Unauthorized | Invalid credential |

### 2.3. Type Hinting
**STRICT ENFORCEMENT.** Every function signature must be fully typed.
*   `def process(data):` -> WRONG
*   `def process(data: LeadCreateSchema) -> Tuple[Lead, Callable]:` -> CORRECT

---

## PART 3: COMPLIANCE CHECKLISTS

### ROUTER CHECKLIST
1.  [ ] Does it have `response_model`?
2.  [ ] Are ALL dependencies injected via `Depends`?
3.  [ ] Is there ZERO business logic (`if/else`)?
4.  [ ] Is there ZERO direct SQL access?
5.  [ ] Does it call `await db.commit()`?
6.  [ ] Does it rely on `deps.py` for permission checks?

### SERVICE CHECKLIST
1.  [ ] Is it free of `HTTPException` imports?
2.  [ ] Does it use Repositories instead of direct DB queries?
3.  [ ] Does it return a `post_commit_callback` for side effects?
4.  [ ] Does it raise specific Domain Exceptions?
5.  [ ] Are complex queries optimized with eager loading?

### SECURITY CHECKLIST
1.  [ ] **IDOR Check**: Do resource endpoints use a `get_resource_access` dependency?
2.  [ ] **RBAC Check**: Are `require_roles` or Casbin policies applied?
3.  [ ] **Visibility Check**: Are list endpoints filtered (e.g., `active_only`) inside the dependency layer?
4.  [ ] **Leak Check**: Are we raising 404 instead of 403 for missing/unauthorized resources?

---

## PART 4: MIGRATION & EXCEPTIONS

### 4.1. Allowed Exceptions
*   **Internal Tasks:** Celery tasks may bypass the Router layer and use Services directly.
*   **Health Checks:** `monitoring.py` may execute raw SQL for connectivity definition.
*   **Performance Hotspots:** In *extreme* cases (Batch Insert 1M rows), raw SQL might be used in Repository, but never in Router.

### 4.2. Migration Path
When touching legacy code:
1.  **Stop the bleeding:** Do not add new logic to a bad Router.
2.  **Refactor on touch:** If you edit a function, move its logic to Service/Repo.
3.  **Strict New Code:** New modules must follow V3.0 rules 100%.

---

## PART 5: ADDENDUM - AGENT STRICT COMPLIANCE RULES

### A. TRANSACTION & CONSISTENCY MODEL (CRITICAL)

#### A.1. Transaction Boundary Rules

##### A.1.1. Single-Service Transaction (Default)
*   **Structure:** 1 Router → 1 Service → 1 Commit.
*   **Rule:** Service **NEVER** commits. Router **ALWAYS** commits (or rollbacks).
*   **Service Knowledge:** The Service does not know if a transaction is committed. It only flushes.

```text
Router (Controller)
 └── Service (Logic)
      └── Repo (Data)
 └── COMMIT (Router)
```

##### A.1.2. Multi-Service Transaction (Orchestration Pattern)
**PERMITTED ONLY WHEN:**
*   A business action requires multiple distinct steps that must succeed or fail together.

**MANDATORY STRUCTURE:**
*   Use an **Orchestrator Service** (application-level service).
*   No individual service may commit. The Orchestrator returns a callback; the Router commits.

```text
Router
 └── AdmissionOrchestratorService
      ├── LeadService (Flush only)
      ├── ScoringService (Flush only)
      └── PaymentIntentService (Flush only)
 └── COMMIT (Router)
```
*   **FORBIDDEN:** Service A commits, then calls Service B.
*   **FORBIDDEN:** Router calls Service A, commits, then calls Service B.

---

#### A.2. Post-Commit Callback Rules

##### A.2.1. Allowed Actions in Callback
- Send email / notification.
- Push message to Queue / Event Bus.
- Write to Audit Log (if separate DB/Table).
- Invalidate external Caches.

##### A.2.2. STRICTLY FORBIDDEN
- Writing to the Application Database (Transaction is already closed).
- Calling another Service that requires a DB transaction.
- Raising exceptions that disrupt the main success flow.

> **Principle:** A Callback failure (e.g., email failed) does **NOT** mean the Request failed. Log the error, maybe retry via background job, but return 200 OK to the user.

---

### B. SERVICE DESIGN TAXONOMY

#### B.1. Pure Domain Service
*   **Scope:** Manages 1 single entity or aggregate root.
*   **Responsibility:** Enforce business rules, validation, state changes.
*   **Examples:** `LeadService`, `ApplicationService`.

#### B.2. Orchestrator Service
*   **Scope:** Does not own data. Coordinates other services.
*   **Responsibility:** Flow control, sequential execution of domain steps.
*   **Rule:** `Orchestrator = Flow Controller`. `Service = Rule Owner`.
*   **FORBIDDEN:** Putting core business rules (e.g., status validation) in the Orchestrator.
*   **FORBIDDEN:** Calling an Orchestrator from a Repository.

---

### C. REPOSITORY QUERY RULES (ANTI-N+1)

#### C.1. Query Shape Rule
| Use Case | REQUIRED Pattern |
| :--- | :--- |
| **List + Relations** | Must use `selectinload` for expected relationships. |
| **Detail View** | Explicit eager loading (load necessary children). |
| **Count** | Use `select(func.count())` - do not fetch objects to count them. |
| **Existence Check** | Use `select(exists())` - do not fetch the object. |

*   **FORBIDDEN:** Lazy loading relationships implicitely in Service loops.
*   **FORBIDDEN:** Accessing `.relationship` properties that were not preloaded.

#### C.2. Raw SQL – WHEN & HOW
**PERMITTED ONLY IF:**
1.  Batch operation > 100,000 rows.
2.  Complex Analytical Query (Reporting).
3.  Database Migration logic.

**MANDATORY:**
*   Must be encapsulated inside a specific Repository method.
*   Must have a comment explaining WHY raw SQL is needed.
*   Must have test coverage.

---

### D. SECURITY THREAT MODEL

#### D.1. IDOR Threat (Insecure Direct Object Reference)
*   **Attack:** User guesses ID increment (e.g., `/leads/100` -> `/leads/101`).
*   **Defense:** **Dependency Injection Resource Access**.
*   **Mechanism:** `get_resource_access` dependency fetches AND checks ownership. If fail, raises 404.

#### D.2. Inference Attack
*   **Attack:** User distinguishes between "Access Denied" (403) and "Not Found" (404) to map existing IDs.
*   **Defense:** **Always raise 404** for resources the user does not own, even if they exist.

#### D.3. Privilege Escalation
*   **Attack:** User manually sends `?role=admin` or `?active_only=false`.
*   **Defense:** **Context Filtering Dependency**. The code ignores user input for sensitive flags and relies on trusted dependencies (`get_config_filter`) to enforce values based on the authenticated user's role.

---

### E. ANTI-PATTERN CATALOG

#### Fat Router
*   **Symptoms:** Router function > 30 lines. Contains `if/else` business logic.
*   **Fix:** Move logic to Service. Move checks to Dependency.

#### Smart Repository
*   **Symptoms:** Repository checks user permissions. Repository raises `HTTPException`.
*   **Fix:** Repository should only return Data or None. Logic belongs in Service. Authorization belongs in Dependency.

#### Leaky Service
*   **Symptoms:** Service imports `fastapi` (Request, Response, HTTPException). Service takes `user_id` from a Request object.
*   **Fix:** Service signatures should use Pydantic models, Primitives, or Domain Objects only.

---

### F. AGENT HARD RULES (PARSE-FRIENDLY)

```yaml
ALWAYS:
  - Inject all dependencies (User, DB, Repo) via `Depends()` in Router.
  - Check permissions inside `deps.py` dependencies, NEVER in Router body.
  - Raise defined `Domain Exceptions` in Service layer.
  - Catch Domain Exceptions and map to `HTTPException` in Router (or global handler).
  - Call `await db.commit()` ONLY in the Router (Presentation Layer).

NEVER:
  - Write `if user.role == ...` inside a Router function.
  - Call `db.commit()` inside a Service function.
  - Raise `HTTPException` inside a Service or Repository.
  - Return ORM Models directly without a Pydantic `response_model`.
  - Import `Request` or `Response` inside logic layers (Service/Repo).
```

---

## PART 6: META-ENFORCEMENT

### ARCHITECTURAL ENFORCEMENT NOTE
These rules are designed to be enforced by:
1.  **Code Review** (Human).
2.  **Static Analysis** (Linter/CI).
3.  **Agent Instruction Validation**.

**Any code violating these rules MUST be rejected, even if it "works".**
"It runs" is not an excuse for "It violates architecture".
