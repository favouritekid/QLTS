# Test Coverage Matrix — QLTS

## Legend
- ✅ Covered (test exists + passes)
- 🟡 Partial (test exists but doesn't cover all cases)
- ❌ Missing (no test)
- 📍 Suite ref: file#line

---

## 1. UNIFIED INTEGRATION (cross-module)

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| U1 | Lead create → consultation → admission → approve → enroll | lead-to-admission-workflow | ✅ | |
| U2 | Rejection → resubmit → revision → resubmit → approve recovery | lead-to-admission-workflow | ✅ | |
| U3 | UI: lead list shows status + stage badge after consultation | lead-to-admission-workflow#372 | ✅ | |
| U4 | UI: admission list shows "Chờ duyệt" after submit | lead-to-admission-workflow#547 | ✅ | |
| U5 | UI: all 6 action buttons locked after enrolled | lead-to-admission-workflow#662 | ✅ | |
| U6 | UI: "Yêu cầu bổ sung" + "Đã nộp lại" badges in recovery | lead-to-admission-workflow#856 | ✅ | |
| U7 | Lead assign → reassign → assign lại lifecycle | — | ❌ | Add to unified flow Phase 1 |
| U8 | Finance gate: fee → invoice → payment → verify → enroll | finance-lifecycle | ✅ (separate suite) | Not in unified; by design |

## 2. LEAD DOMAIN

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| L1 | CRUD: create + update + read | lead-workflow | ✅ | |
| L2 | Consultation: add + status transition | lead-workflow, lead-to-admission-workflow | ✅ | |
| L3 | Assignment: admin assign to officer | lead-workflow#451 | ✅ | |
| L4 | Bulk assign | lead-workflow#451 | ✅ | |
| L5 | Delete / restore | lead-workflow#612 | ✅ | |
| L6 | FSM validation: allowed transitions | lead-workflow#612 | ✅ | |
| L7 | IDOR: officer cannot access unassigned lead | lead-workflow#728 | ✅ | |
| L8 | Officer action + audit logs | lead-workflow#728 | ✅ | |
| L9 | Validity status + bulk delete | lead-workflow#1152 | ✅ | |
| L10 | CSV import | lead-workflow (test 6) | ✅ | |
| L11 | List filters + pagination + role-based visibility | lead-workflow#1152 | ✅ | |
| L12 | Optimistic locking | lead-workflow#1309 | ✅ | |
| L13 | Loss reason on terminal status | lead-workflow#1309 | ✅ | |
| L14 | Terminal block guard | lead-workflow#1309 | ✅ | |
| L15 | Reassign quota: officer capped, admin uncapped | lead-workflow#1473 | ✅ | |
| L16 | Manager IDOR: unit-scoped visibility | lead-workflow (test 10) | ✅ | |
| L17 | Duplicate check | lead-workflow (test 1) | ✅ | |
| L18 | Distribution preview | lead-workflow#1152 | ✅ | |
| L19 | LeadsTable row identity (not array index) | LeadsTable.test.tsx | ✅ | |
| L20 | LeadsTable selection reset on page/sort change | LeadsTable.test.tsx | ✅ | |
| L21 | LeadsTable badge rendering (stage + status columns) | — | ❌ | Add to LeadsTable.test.tsx |
| L22 | LeadsTable assignment column rendering | — | ❌ | Add to LeadsTable.test.tsx |

## 3. ADMISSION DOMAIN

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| A1 | Happy path: draft → submitted → approved → overridden → enrolled | admission-lifecycle#382 | ✅ | |
| A2 | Rejection: submitted → rejected → resubmitted → approved | admission-lifecycle#599 | ✅ | |
| A3 | Magic link: approved → confirmed → enrolled | admission-lifecycle#726 | ✅ | |
| A4 | Document upload / verify / reject / reset / re-upload / delete | admission-lifecycle#949 | ✅ | |
| A5 | Request revision: submitted → revision_requested → resubmitted | admission-lifecycle#1092 | ✅ | |
| A6 | Auth boundary + IDOR + optimistic locking | admission-lifecycle#1185 | ✅ | |
| A7 | Drop flow: enrolled → dropped (side-channel) | admission-lifecycle#1319 | ✅ | |
| A8 | UI smoke: list page + filter tabs | admission-ui-smoke | ✅ | |
| A9 | UI smoke: detail page tabs | admission-ui-smoke | ✅ | |
| A10 | UI smoke: unsaved changes dialog | admission-ui-smoke | ✅ | |
| A11 | Bulk approve / reject / assign | admission-bulk | ✅ | |
| A12 | AdmissionActions visibility matrix by status/permission | — | ❌ | Add AdmissionActions.test.tsx |
| A13 | PersonalInfoTab version-resync after form.reset | — | ❌ | Add PersonalInfoTab.test.tsx |

## 4. FINANCE DOMAIN

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| F1 | Fee calculation (tuition + application) | finance-lifecycle#334 | ✅ | |
| F2 | Fee recalculate | finance-lifecycle | ✅ | |
| F3 | Fee waive (partial) | finance-lifecycle | ✅ | |
| F4 | Fee waive excessive amount → fail | finance-lifecycle | ✅ | |
| F5 | Fee cancel | finance-lifecycle | ✅ | |
| F6 | Invoice issue | finance-lifecycle | ✅ | |
| F7 | Payment record (manual) | finance-lifecycle | ✅ | |
| F8 | Payment verify (maker-checker) | finance-lifecycle | ✅ | |
| F9 | Self-verify block (maker-checker enforcement) | finance-lifecycle#528 | ✅ | |
| F10 | Payment rejection | finance-lifecycle | ✅ | |
| F11 | Installment plans list | finance-lifecycle | ✅ | |
| F12 | Finance dashboard | finance-lifecycle | ✅ | |
| F13 | Recalculate with pending payment | finance-lifecycle | ✅ | |

## 5. CTV / COMMISSION

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| C1 | CTV self-register | ctv-commission-workflow | ✅ | |
| C2 | Admin approve CTV | ctv-commission-workflow | ✅ | |
| C3 | CTV submit lead + claim | ctv-commission-workflow | ✅ | |
| C4 | Admin approve/reject claim | ctv-commission-workflow | ✅ | |
| C5 | Commission trigger on status progression | ctv-commission-workflow | ✅ | |
| C6 | Commission approve + pay | ctv-commission-workflow | ✅ | |
| C7 | Commission rejection | ctv-commission-workflow | ✅ | |
| C8 | Regression cancellation (status regress → auto-cancel) | ctv-commission-workflow | ✅ | |
| C9 | CTV dashboard + stats | ctv-commission-workflow | ✅ | |

## 6. REGRESSION / BUGFIX

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| R1 | Bulk action targets correct IDs | bugfix-regression#107 | ✅ | |
| R2 | Stage bulk update | bugfix-regression | ✅ | |
| R3 | Export filter params (assigned_officer_id) | bugfix-regression | ✅ | |
| R4 | Reassign quota contract | bugfix-regression | ✅ | |
| R5 | No stale fields in quota response | bugfix-regression | ✅ | |
| R6 | Date range end-of-day inclusive | bugfix-regression | ✅ | |
| R7 | Lead detail 404 for non-existent ID | bugfix-regression | ✅ | |

## 7. UI COMPONENT CONTRACT

| # | Behavior | Suite | Status | Missing |
|---|----------|-------|--------|---------|
| UI1 | AdaptiveAddressSelect: current mode (provinces, no districts, wards) | AdaptiveAddressSelect.test.tsx | ✅ | |
| UI2 | AdaptiveAddressSelect: legacy mode (provinces + districts + wards) | AdaptiveAddressSelect.test.tsx | ✅ | |
| UI3 | AdaptiveAddressSelect: mode switching resets fields | AdaptiveAddressSelect.test.tsx | ✅ | |
| UI4 | AdaptiveAddressSelect: province selection clears district+ward | AdaptiveAddressSelect.test.tsx | ✅ | |
| UI5 | PersonalInfoTab: addressMode re-derives on version change | — | ❌ | New: PersonalInfoTab.test.tsx |
| UI6 | AdmissionActions: button visibility by status × permission | — | ❌ | New: AdmissionActions.test.tsx |
| UI7 | LeadsTable: stage badge column rendering | — | ❌ | Extend LeadsTable.test.tsx |
| UI8 | LeadsTable: consultation status badge rendering | — | ❌ | Extend LeadsTable.test.tsx |

---

## SUMMARY

| Category | Total | ✅ Covered | ❌ Missing |
|----------|-------|-----------|-----------|
| Unified integration | 8 | 7 | 1 (U7: assign lifecycle) |
| Lead domain | 22 | 20 | 2 (L21-L22: table badge rendering) |
| Admission domain | 13 | 11 | 2 (A12-A13: actions matrix, version resync) |
| Finance domain | 13 | 13 | 0 |
| CTV/Commission | 9 | 9 | 0 |
| Regression | 7 | 7 | 0 |
| UI component | 8 | 4 | 4 (UI5-UI8) |
| **TOTAL** | **80** | **71 (89%)** | **9 (11%)** |

---

## BACKLOG: Missing Tests (Priority Order)

| Priority | ID | What to add | Where | Est. effort |
|----------|-----|-------------|-------|-------------|
| P1 | U7 | Lead assign → reassign → re-assign lifecycle in unified flow | lead-to-admission-workflow.spec.ts | Small (extend Phase 1) |
| P1 | A13 | PersonalInfoTab version-resync after form.reset | New: PersonalInfoTab.test.tsx | Medium |
| P1 | A12 | AdmissionActions visibility matrix (status × can()) | New: AdmissionActions.test.tsx | Medium |
| P2 | UI5 | PersonalInfoTab addressMode re-derive on profile.version change | PersonalInfoTab.test.tsx (same as A13) | — (merged) |
| P2 | UI6 | AdmissionActions button visibility unit test | AdmissionActions.test.tsx (same as A12) | — (merged) |
| P3 | L21 | LeadsTable stage badge column rendering | Extend LeadsTable.test.tsx | Small |
| P3 | L22 | LeadsTable assignment column rendering | Extend LeadsTable.test.tsx | Small |
| P3 | UI7 | LeadsTable stage badge (same as L21) | — (merged) | — |
| P3 | UI8 | LeadsTable consultation status badge (same as L21) | — (merged) | — |

**Unique missing items: 5** (after merging overlaps)
1. U7: Unified assign lifecycle
2. A12/UI6: AdmissionActions.test.tsx
3. A13/UI5: PersonalInfoTab.test.tsx
4. L21/UI7: LeadsTable badge rendering
5. L22/UI8: LeadsTable assignment rendering
