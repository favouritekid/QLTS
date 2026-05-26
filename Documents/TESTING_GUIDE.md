# Testing Guide — QLTS

## Quick Reference

### Backend Contract Tests (Phase 3)

```bash
# Lead assignment lifecycle (1 test, ~15s)
docker compose exec backend python -m pytest \
  tests/api/test_lead_assignment_api.py::test_lead_assignment_lifecycle_end_to_end -v

# Admission workflow (13 tests, ~200s)
docker compose exec backend python -m pytest \
  tests/api/test_admission_workflow_api.py -v

# Both together
docker compose exec backend python -m pytest \
  tests/api/test_lead_assignment_api.py::test_lead_assignment_lifecycle_end_to_end \
  tests/api/test_admission_workflow_api.py -v
```

**Prerequisite**: `docker compose exec backend pip install -r requirements-dev.txt`

### Frontend UI Contract Tests (Phase 2)

```bash
# All 3 files (37 tests, ~4s)
docker compose exec frontend npx vitest run \
  "src/app/(dashboard)/admissions/[id]/_components/AdmissionActions.test.tsx" \
  "src/app/(dashboard)/admissions/[id]/_components/tabs/PersonalInfoTab.test.tsx" \
  "src/components/leads/command-center/LeadsTable.test.tsx" \
  --reporter=verbose
```

### Unified E2E Workflow (Phase 1)

```bash
# Headless (CI) — requires backend + frontend running
cd frontend && npx playwright test \
  src/test/e2e/lead-to-admission-workflow.spec.ts \
  --project=e2e-workflow --reporter=list

# Headed (local debugging) — opens visible browser
cd frontend && E2E_ADMIN_USERNAME=admin E2E_ADMIN_PASSWORD="Admin@123" \
  E2E_OFFICER_USERNAME=vothithuthuhien E2E_OFFICER_PASSWORD="Abc@123456789" \
  npx playwright test \
  src/test/e2e/lead-to-admission-workflow.spec.ts \
  --project=e2e-workflow --headed --reporter=list
```

**Prerequisite**: Docker services running + Playwright browsers installed (`npx playwright install chromium`)

---

## CI Pipeline

### PR Gate (`deploy.yml`)
Runs on every push to `main`. Blocks deploy if any step fails.

| Step | What | Runtime |
|------|------|---------|
| Backend lead contract | `test_lead_assignment_lifecycle_end_to_end` | ~15s |
| Backend admission contract | `test_admission_workflow_api.py` (13 tests) | ~200s |
| Frontend type-check | `npm run type-check` | ~30s |
| Frontend lint | `npm run lint` | ~20s |
| Frontend Vitest | 3 contract test files (37 tests) | ~4s |

### Nightly Regression (`nightly-regression.yml`)
Runs at 2:00 AM UTC daily. Non-blocking. Can be triggered manually via `workflow_dispatch`.

| Suite | File | Tests |
|-------|------|-------|
| Lead workflow | `lead-workflow.spec.ts` | ~10 |
| Admission lifecycle | `admission-lifecycle.spec.ts` | ~10 |
| Finance lifecycle | `finance-lifecycle.spec.ts` | ~15 |
| Bugfix regression | `bugfix-regression.spec.ts` | ~8 |
| Unified workflow | `lead-to-admission-workflow.spec.ts` | 21 |
| Smoke | `smoke-all-pages.spec.ts` + `admission-ui-smoke.spec.ts` | ~5 |

---

## Test Architecture

```
PR Gate (fast, blocking)
├── Backend pytest: 14 contract tests
├── Frontend Vitest: 37 UI contract tests
├── Type check + lint
└── ~5 min total

Nightly (deep, non-blocking)
├── E2E Playwright: ~70 tests across 6 suites
├── Full stack required (docker compose)
└── ~15 min total
```

E2E tests are NOT in PR gate because they require full stack (backend + frontend + postgres + redis + seed data). PR gate uses GitHub Actions service containers (postgres + redis only).

---

## Environment Variables for E2E

| Variable | Default | Description |
|----------|---------|-------------|
| `E2E_ADMIN_USERNAME` | `admin` | Admin username |
| `E2E_ADMIN_PASSWORD` | `Admin@123` | Admin password (matches xlsx 2_TaiKhoan) |
| `E2E_ADMIN_TOTP_SECRET` | (hardcoded) | TOTP secret for MFA |
| `E2E_OFFICER_USERNAME` | `vothithuthuhien` | Officer username (matches xlsx 2_TaiKhoan) |
| `E2E_OFFICER_PASSWORD` | `Abc@123456789` | Officer password (matches xlsx 2_TaiKhoan) |
| `E2E_API_URL` | `http://localhost:8000` | Backend API URL |
| `PLAYWRIGHT_BASE_URL` | `http://localhost:3000` | Frontend URL |

**Source of truth**: ``Backend_FastAPI/seed_data_template.xlsx`` sheet ``2_TaiKhoan``. Spec fallback defaults are synced to that workbook and locked by the parity guard at ``frontend/src/test/seed-credentials-parity.test.ts`` (runs in CI). If the workbook rotates a credential, update the spec defaults + this doc in the same PR — the parity guard will fail otherwise.
