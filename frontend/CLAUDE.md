# Frontend (Next.js) Guidelines

## Core Documentation
- **Architecture**: `FRONTEND_ARCHITECTURE_V3.md`

## 🚨 MANDATORY ARCHITECTURE RULES
1.  **Thin Client Philosophy**:
    - **NO Business Logic**: Frontend never calculates eligibility, scores, or workflow transitions.
    - **Renderer Only**: Display exactly what the Backend returns.

2.  **State Ownership**:
    - **Backend = Truth**: Trust `status`, `can_edit`, `available_actions` from API response.
    - **No Inference**: Do NOT derive state (e.g., `isPending = status === 'submitted' && !approved`).
    - **No Role Checks**: Control visibility via API permission flags, NOT `user.role` strings.

3.  **Code Patterns**:
    - **Zod Schemas**: Must mirror Backend Pydantic models strictly.
    - **React Query**: Used for server state caching. NOT for local UI state.
    - **Status Handling**: Handle ALL status enum values (use `default` case for unknown states).

4.  **Breaking Changes**:
    - If an API field is missing, **STOP**. Do not hack a workaround. Request a Backend Contract update.

---

## 📁 File Conventions
| Type | Location | Naming |
|------|----------|--------|
| API Client | `src/lib/api/` | `module.ts` (e.g., `leads.ts`) |
| Zod Schemas | `src/lib/zod/` | `module.ts` (e.g., `admissions.ts`) |
| React Query Hooks | `src/lib/hooks/` | `use-module.ts` |
| Zustand Stores | `src/lib/stores/` | `module-store.ts` |
| Components | `src/components/` | `PascalCase.tsx` |

---

## 📊 State Classification
| State Type | Tool | Example |
|------------|------|---------|
| **Server State** | React Query | Lead data, Profiles | 
| **Form State** | React Hook Form | Draft inputs |
| **UI State** | Zustand | Sidebar, modals |
| **URL State** | Next.js Router | Filters, pagination |

> **RULE**: NEVER cache server state in Zustand. NEVER use React Query for UI toggles.

---

## ❌ NEVER DO (Anti-Patterns)
```tsx
// ❌ Calculate eligibility locally
const isEligible = gpa >= minGpa && docs >= requiredDocs; // WRONG

// ✅ Read from API
const { eligibility_status } = profile;
<Button disabled={eligibility_status !== "eligible"}>Submit</Button>

// ❌ Check role string
{user.role === "admin" && <ApproveButton />} // WRONG

// ✅ Check permission flag
{profile.can_approve && <ApproveButton />}

// ❌ Infer intermediate state
const isPending = status === "submitted" && !approved_at; // WRONG

// ✅ Use exact backend status
<Badge>{STATUS_CONFIG[status]?.label ?? status}</Badge>

// ❌ Default business values
const score = data.score ?? 0; // WRONG - hides missing data

// ✅ Require server to provide
const score = data.score; // Zod will fail if missing
```

---

## Common Commands (Docker)

All commands run inside the frontend container via `docker compose exec`.

```bash
docker compose exec frontend npm run dev             # Dev server (auto-started by override)
docker compose exec frontend npm run build            # Production build
docker compose exec frontend npm run type-check       # TypeScript checking
docker compose exec frontend npm run lint             # ESLint check
docker compose exec frontend npm run lint:fix         # ESLint auto-fix
docker compose exec frontend npm run test             # Vitest
docker compose exec frontend npm run test:coverage    # Coverage report
docker compose exec frontend npm install [package]    # Install package
```

