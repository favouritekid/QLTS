# Phase 3 UI Design Contract v0.6 LOCKED

**Date**: 2026-05-11 Day 1.5 v0.1 → v0.2 → v0.3 → v0.4 → v0.5 → v0.6 (7 review rounds incl round-7 deep verify)
**Plan ref**: `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md` v0.6 LOCKED
**Status**: ✅ LOCKED v0.6 — UI scope unchanged round-6/7 (UI patches stable). Round-6 round-7 deep verify đa số mới gaps BE-side absorbed vào plan tổng (GAP-11..34 + BONUS-35/36/37). Filename renamed `V0.1.md` → `.md`.
**Scope**: 9 UI patches (P-UI-01..09) + TS polish + BE contract + nav refactor + 5 minor refinements logged + Section 1.5/1.6 final

## v0.4 → v0.5 changelog (2026-05-11)

User round-5 hard-check phát hiện 3 P1 cross-source drift + 2 P2 wording:

**P1-new gaps**:

- **P-UI-07** (P1 NEW): Backfill queue contract DRIFT vs DB thật
  - Exception type name: em viết `AMBIGUOUS_SUBJECT_GROUP_SELECTION` SAI — DB code thật dùng `AMBIGUOUS_SELECTED_GROUP` ([phase1_12_backfill_selected_subject_group_id.py:212](Backend_FastAPI/alembic/versions/phase1_12_backfill_selected_subject_group_id.py#L212))
  - Schema columns: em invent `status: 'pending' | 'approved' | 'rejected' | 'deferred'` — DB thật chỉ có `resolved_at`, `resolved_by_user_id`, `resolution_notes` ([phase1_07b_create_backfill_exceptions_table.py:100-114](Backend_FastAPI/alembic/versions/phase1_07b_create_backfill_exceptions_table.py#L100))
  - DB UNIQUE: `(profile_id, exception_type)` partial ([line 115-118](Backend_FastAPI/alembic/versions/phase1_07b_create_backfill_exceptions_table.py#L115))
  - **Drift**: 3 docs sai: noble-launching-cocoa.md:137 + PHASE3_UI_DESIGN.md:513 + phase3-backfill-dryrun.py:15

- **P-UI-08** (P1 NEW): `available_actions` typed shape sẽ PHÁ 3+ consumers existing
  - BE schema hiện `available_actions: list[str]` ([admission.py:779](Backend_FastAPI/app/schemas/admission.py#L779))
  - FE Zod hiện `z.array(z.string())` ([admissions.ts:579](frontend/src/lib/zod/admissions.ts#L579))
  - Consumers `.includes(...)`:
    - `useAdmissionViewModel.ts:255`
    - `columns.tsx:295`
    - `TuitionTab.tsx:55`
  - Em propose Wave A "replace `list[str]` → `list[{action,target,endpoint}]`" PHÁ tất cả consumers → big-bang breaking change, KHÔNG có soft cutoff path

- **P-UI-09** (P1 NEW): Magic-link token issuance KHÔNG action-aware
  - Model có `action_type` ENUM + partial UNIQUE `(profile_id, action_type)` ([admission.py:615](Backend_FastAPI/app/models/admission.py#L615))
  - Repository `create_confirmation_token(profile_id, token, expires_at)` thiếu `action_type` param ([admission_repository.py:1098](Backend_FastAPI/app/repositories/admission_repository.py#L1098))
  - Reuse lookup chỉ filter `profile_id` ([line 1131](Backend_FastAPI/app/repositories/admission_repository.py#L1131)) → 4 actions concurrent impossible
  - Service URL generate `/confirm/{token}` KHÔNG `?action=` ([admission_service.py:7678](Backend_FastAPI/app/services/admission_service.py#L7678))

**P2 wording drift**:
- UI doc Section 1.1 vẫn còn "Step 4.5" reference (Net effect bullets)
- UI doc `DecisionBadge` file path ambiguity (`components/common/status/DecisionBadge.tsx` NEW vs `StatusBadge.tsx` extend variants — conflict)
- Wave A scope "extend 14-state Zod" stale — đã có ([admissions.ts:520](frontend/src/lib/zod/admissions.ts#L520) + [status-badge.config.ts:40](frontend/src/lib/ui-config/status-badge.config.ts#L40))

**v0.5 status**: D-UI-01..03 = A/A/A. P-UI-01..06 confirmed. P-UI-07/08/09 NEW. P2 wording fixes.

## v0.3 → v0.4 changelog (2026-05-11)

User round-4 review flag:

**P1 cross-module gap**:
- **P-UI-06** (P1 NEW): Magic-link route mới `/api/v2/admissions/magic-link/{action}/{token}` POST public KHÔNG có CSRF exemption. CSRF middleware `EXEMPT_PATHS` ([csrf.py:50-66](Backend_FastAPI/app/middleware/csrf.py#L50)) chỉ có `/api/admissions/confirm/` legacy ([line 58](Backend_FastAPI/app/middleware/csrf.py#L58)). Protected methods include POST ([line 46](Backend_FastAPI/app/middleware/csrf.py#L45)). Phase 3 magic-link public flow (mobile candidate, không có authenticated dashboard session) sẽ fail CSRF check.

**P2 wording cleanup**:
- Section 7 vẫn ghi "v0.2 patches summary" — đổi thành v0.4 + fold P-UI-04/05/06 vào table

**M1-M5 minor refinements** (logged trong Section 8, KHÔNG block lock — implementation polish trong PR):
- M1: AdmissionActions refactor 4 lines (133/141/149/157), không chỉ line 133
- M2: P-UI-05 'choices' step status compute dynamic (success/warning/locked theo choices count)
- M3: DecisionBadge discriminated union type-safer (compiler-enforced context-decision pairing)
- M4: BackfillExceptionType runtime widening — BE endpoint `/types` cần define HOẶC FE Zod widen
- M5: MagicLinkActionForm `expiresAt` source — BE preview endpoint vs fallback render

**v0.4 status**: D-UI-01..03 = A/A/A unchanged. P-UI-04/05 confirmed by user. P-UI-06 NEW. M1-M5 logged. Section 7 cleanup.

## v0.2 → v0.3 changelog (2026-05-11)

User round-3 review flag 2 P1 blockers + minor issues:

**P1 blockers**:
- **P-UI-04** (P1): Dynamic steps spec v0.2 dùng `currentStep === step.id` raw numeric ID → bug khi visible IDs không contiguous. Legacy `uses_choice_engine=false` → visible IDs `[1,2,3,4,6,7,8]` skip 5; user click Next từ step 4 → `currentStep=5` → render NOTHING (no visibleStep id=5). Phải dùng **index/key-based navigation**, KHÔNG raw ID. Patch include `AdmissionActions.tsx` ([line 133](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionActions.tsx#L133)) hardcode `currentStep > 1 && currentStep < 7` — KHÔNG chỉ AdmissionDetailClient + PipelineSidebar.
- **P-UI-05** (P1): Backend `step_status` hardcode 1-7 trong `_compute_completion_percent` ([admission_service.py:1113](Backend_FastAPI/app/services/admission_service.py#L1113)) + `_compute_frontend_fields` ([line 1677](Backend_FastAPI/app/services/admission_service.py#L1677)) + `next_action` ([line 1996](Backend_FastAPI/app/services/admission_service.py#L1996)) hardcode step 1/4/5 keys. Nếu FE thêm Step 5 "Nguyện vọng", BE vẫn trả step_status với key=5 nghĩa "Documents" → sidebar/badges lệch. Phải đổi sang **key-based step status** hoặc explicit FE remap.

**Minor issues TS/Contract/Nav**:
- TS-01: Step type missing `displayId` field (runtime add, type không declare)
- TS-02: ChoiceScoreCard `errors` key ambiguous (subject_id number vs subject_code string)
- TS-03: EligibilityResultViewer `rule_label_vi` redundant với FE i18n 25 keys (Q8 inline) — pick 1 source-of-truth
- TS-04: BackfillExceptionRow `exception_type` incomplete enum (em viết `... | ...` invalid syntax)
- TS-05: DecisionBadge 7-value union ambiguous (5 từ choice.decision DB + 2 từ EligibilityResult JSONB)
- Contract-06: `AdmissionProfileChoice.display_path_name/display_subject_group_name/scores` chưa spec BE side (computed fields qua Pydantic field_validator)
- Nav-07: `PipelineSidebar.tsx:55-58` increment `currentStep + 1` không scale với non-contiguous visible IDs

**v0.3 status**: D-UI-01..03 = A/A/A unchanged. Patches v0.3 fix spec depth — KHÔNG đổi product decisions.

## v0.1 → v0.2 changelog (2026-05-11)

User hard-check code-truth phát hiện 3 gap em đã miss:
- **P-UI-01**: `AdmissionDetailClient` hardcode `currentStep` 1-7 ([line 125](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionDetailClient.tsx#L125)) + render hardcode ([line 429](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionDetailClient.tsx#L429)) + `PipelineSidebar.STEPS` hardcode 7 items ([line 28](frontend/src/app/(dashboard)/admissions/[id]/_components/layout/PipelineSidebar.tsx#L28)). Em propose "Step 4.5" KHÔNG khả thi — phải refactor sang dynamic steps array.
- **P-UI-02**: `uses_choice_engine` field có ở BE model ([admission.py:455](Backend_FastAPI/app/models/admission.py#L455)) nhưng KHÔNG expose qua `AdmissionProfileResponse` schema FE ([admissions.ts:468](frontend/src/lib/zod/admissions.ts#L468)). Conditional gate `profile.uses_choice_engine === true` em propose CHƯA implement được — phải patch BE schema + FE Zod.
- **P-UI-03**: Magic-link Phase 1 chỉ pass token, KHÔNG đọc query param `?action=` ([confirm/[token]/page.tsx:19](frontend/src/app/confirm/[token]/page.tsx#L19)). `ConfirmAdmissionForm` chỉ nhận `{ token }` ([line 107](frontend/src/components/forms/ConfirmAdmissionForm.tsx#L107)). FE API gọi `/api/admissions/confirm/{token}` ([admissions.ts:467](frontend/src/lib/api/admissions.ts#L467)). BE router chỉ có legacy `/admissions/confirm/{token}` ([admissions.py:2073](Backend_FastAPI/app/routers/admissions.py#L2073)). Model có `action_type` ENUM ([admission.py:615](Backend_FastAPI/app/models/admission.py#L615)) NHƯNG action-aware handler CHƯA TỒN TẠI. Em propose `?action=...` decision OK nhưng phải spec rõ Phase 3 ship 6 items (FE page + form + API client + BE router + service + tests), KHÔNG ghi "backend route ready".

**v0.2 status decisions**: D-UI-01 A / D-UI-02 A / D-UI-03 A vẫn confirm. KHÔNG lock plan v0.4 ngay — apply 3 patches trước.

---

## 1. Mount points (Gap 1 HIGH) — v0.2 PATCHED

### 1.1 Admission Profile Detail — Phase 3 integration (P-UI-01 patch)

**Existing structure code-verified** (`frontend/src/app/(dashboard)/admissions/[id]/`):
- 7-step linear nav HARDCODED:
  - `currentStep` state `useState(1)` ([AdmissionDetailClient.tsx:125](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionDetailClient.tsx#L125))
  - Render `{currentStep === 1 && <PersonalInfoTab>}` ... `{currentStep === 7 && <FinalizeTab>}` hardcoded ([line 429-447](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionDetailClient.tsx#L429))
  - `PipelineSidebar.STEPS` hardcode `[{id:1,...}, ..., {id:7,...}]` ([PipelineSidebar.tsx:28](frontend/src/app/(dashboard)/admissions/[id]/_components/layout/PipelineSidebar.tsx#L28))

**P-UI-01 + P-UI-04 patch**: refactor sang **key-based step state** + **index-based navigation** — KHÔNG dùng raw numeric ID.

**TS-01 fix**: Step type include `displayId` optional + tách `VisibleStep` type:

```typescript
// AdmissionDetailClient.tsx — v0.3 spec
type StepKey = 'personal' | 'family' | 'academic' | 'scores' | 'choices' | 'documents' | 'tuition' | 'finalize'

type Step = {
  key: StepKey                              // ← primary identifier (NOT id)
  legacyId: number                          // ← BE step_status compat (1-7 for legacy)
  label: string
  icon: LucideIcon
  component: React.FC<TabProps>
  conditional?: (profile: AdmissionProfileResponse) => boolean
}

type VisibleStep = Step & { displayId: number }  // TS-01 fix: displayId only on visible

const ALL_STEPS: Step[] = [
  { key: 'personal',   legacyId: 1, label: 'Thông tin cá nhân', icon: User,           component: PersonalInfoTab },
  { key: 'family',     legacyId: 2, label: 'Gia đình / Giám hộ', icon: Users,          component: FamilyTab },
  { key: 'academic',   legacyId: 3, label: 'Học tập',           icon: GraduationCap,  component: AcademicHistoryTab },
  { key: 'scores',     legacyId: 4, label: 'Điểm & Điều kiện',  icon: Calculator,     component: ScoresTab },
  { key: 'choices',    legacyId: 0, label: 'Nguyện vọng',       icon: ListOrdered,    component: ChoicesTab,
    conditional: (p) => p.uses_choice_engine === true },                           // legacyId=0 = Phase 3 only
  { key: 'documents',  legacyId: 5, label: 'Tài liệu pháp lý',  icon: FileText,       component: DocumentsTab },
  { key: 'tuition',    legacyId: 6, label: 'Học phí',           icon: Wallet,         component: TuitionTab },
  { key: 'finalize',   legacyId: 7, label: 'Hoàn tất & Nộp',    icon: CheckSquare,    component: FinalizeTab },
]

const visibleSteps: VisibleStep[] = useMemo(
  () => ALL_STEPS
    .filter(s => !s.conditional || s.conditional(profile))
    .map((s, idx) => ({ ...s, displayId: idx + 1 })),
  [profile?.uses_choice_engine]
)

// P-UI-04: state là KEY, không phải numeric ID
const [currentStepKey, setCurrentStepKey] = useState<StepKey>('personal')

// Render qua visibleSteps loop với key match (KHÔNG numeric === id)
{visibleSteps.map(step =>
  currentStepKey === step.key && <step.component key={step.key} {...tabProps} />
)}

// Nav-07: navigation qua index trong visibleSteps array, KHÔNG raw +/- 1
const currentVisibleIdx = visibleSteps.findIndex(s => s.key === currentStepKey)
const goToNextStep = () => {
  const next = visibleSteps[currentVisibleIdx + 1]
  if (next) setCurrentStepKey(next.key)
}
const goToPrevStep = () => {
  const prev = visibleSteps[currentVisibleIdx - 1]
  if (prev) setCurrentStepKey(prev.key)
}
const isFirstStep = currentVisibleIdx === 0
const isLastStep = currentVisibleIdx === visibleSteps.length - 1
```

**Net effect** (P2 wording v0.5 cleanup — KHÔNG còn "Step 4.5"):
- Profile có `uses_choice_engine=false` (legacy): visible array 7 keys `[personal, family, academic, scores, documents, tuition, finalize]` → displayId 1-7
- Profile có `uses_choice_engine=true` (Phase 3): visible array 8 keys `[personal, family, academic, scores, choices, documents, tuition, finalize]` → displayId 1-8 ("Nguyện vọng" displayId=5)

**Files cần touch trong PR-3D-A Wave A (P-UI-04 expand scope)**:
- `AdmissionDetailClient.tsx` — refactor `currentStep: number` → `currentStepKey: StepKey` + nav functions
- `PipelineSidebar.tsx` — refactor `STEPS` constant → accept `visibleSteps` prop; replace `currentStep ± 1` (line 55-58) với `goToNext/goToPrev` callbacks; `focusedSteps` recompute từ `currentVisibleIdx`
- `AdmissionActions.tsx` — replace hardcoded `currentStep < 7` ([line 133](frontend/src/app/(dashboard)/admissions/[id]/_components/AdmissionActions.tsx#L133)) với `!isLastStep`; `currentStep > 1 && currentStep < 7` → `!isFirstStep && !isLastStep`
- `ChoicesTab.tsx` — NEW (key='choices' component, conditional render)

**Anchor tests** (PR-3D-A Wave A):
- `test_visible_steps_7_when_uses_choice_engine_false` — legacy preserved, displayId 1-7
- `test_visible_steps_8_renumbered_when_uses_choice_engine_true` — Phase 3 enabled, choices=displayId 5
- `test_nav_next_from_scores_legacy_skips_to_documents` — legacy `[1,2,3,4,_,5,6,7]` Next-from-scores → documents (NOT blank screen)
- `test_nav_next_from_scores_phase3_goes_to_choices` — Phase 3 Next-from-scores → choices
- `test_admission_actions_back_button_visible_legacy_step_4` — backward compat AdmissionActions không break
- `test_admission_actions_save_button_hidden_finalize_step` — `!isLastStep` parity với old `currentStep < 7`

**Mount file**: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/ChoicesTab.tsx` (NEW)
- Wrap `<ChoiceListEditor>` + `<ChoiceScoreCard>` cho candidate-facing
- Reuse pattern existing tabs (props `form`, `isEditable`, `profile`)

### 1.1.x Conditional gate — P-UI-02 patch (`uses_choice_engine` expose)

**Backend ([admission.py:455](Backend_FastAPI/app/models/admission.py#L455))** đã có:
```python
uses_choice_engine: Mapped[bool] = mapped_column(
    Boolean, nullable=False, server_default='false', ...
)
```

**Gap**: schema response Pydantic + Zod FE CHƯA expose field — verified:
- `AdmissionProfileResponse` ([admissions.ts:468](frontend/src/lib/zod/admissions.ts#L468)) KHÔNG có `uses_choice_engine`
- `rg uses_choice_engine frontend/src Backend_FastAPI/app/schemas` zero hits

**P-UI-02 patch — required trong PR-3A Day 2-3** (NOT defer Wave A):
1. **BE**: `Backend_FastAPI/app/schemas/admission.py` — add `uses_choice_engine: bool` vào `AdmissionProfileResponse` schema
2. **FE Zod**: `frontend/src/lib/zod/admissions.ts:468` — add `uses_choice_engine: z.boolean()` vào response schema
3. **ViewModel passthrough**: nếu có ViewModel transform layer giữa Zod + UI, ensure field passthrough (check `frontend/src/lib/admissions/viewmodel.ts` hoặc tương tự)
4. **Conditional gate test**: anchor test trong PR-3A `test_uses_choice_engine_visible_for_phase3_profile` verify FE Zod parse OK + ViewModel exposes correct value

**Migration risk**: existing profiles có `uses_choice_engine=false` (Phase 1 default) → Phase 3 Wave B flip per-round via `offering_admission_round.allow_multi_nv` (Q-P3-02). Profile-level flag chỉ thay đổi khi admin manual hoặc system migrate post Wave B+0.

### 1.1.y BE step_status contract — P-UI-05 patch

**Code-verified BE hardcode 1-7**:
- `_compute_completion_percent` ([admission_service.py:1113](Backend_FastAPI/app/services/admission_service.py#L1113)): `step_status = {1: ..., 2: ..., ..., 7: ...}` integer keys
- `step_weights = {1: 14, 2: 14, 3: 14, 4: 15, 5: 15, 6: 14, 7: 14}` ([line 1123](Backend_FastAPI/app/services/admission_service.py#L1123))
- `_compute_frontend_fields` ([line 1677](Backend_FastAPI/app/services/admission_service.py#L1677)) hardcode keys
- `next_action` ([line 1996](Backend_FastAPI/app/services/admission_service.py#L1996)) hardcode `step 1/4/5` references

**Problem**: nếu FE thêm Step 5 "Nguyện vọng" (Phase 3), BE vẫn trả `step_status[5] = "documents status"` → FE sidebar lookup `step_status_by_visible_step_5` (Choices) sẽ lệch (lấy nhầm Documents status).

**P-UI-05 patch — Em recommend Option B (FE remap legacy keys)**:

**Option A — BE refactor sang key-based** (~0.5d BE work):
```python
# admission_service.py refactor
step_status = {
    "personal":  ...,
    "family":    ...,
    "academic":  ...,
    "scores":    ...,
    "documents": ...,
    "tuition":   ...,
    "finalize":  ...,
}
# Phase 3 Wave B adds "choices" key when uses_choice_engine=true
if profile.uses_choice_engine:
    step_status["choices"] = ...
```

**Option B — FE remap legacy keys** ← **em recommend** (~0d BE, ~0.1d FE work):
```typescript
// frontend/src/lib/admissions/step-status-remap.ts (NEW)
const LEGACY_ID_TO_KEY: Record<number, StepKey> = {
  1: 'personal', 2: 'family', 3: 'academic', 4: 'scores',
  5: 'documents', 6: 'tuition', 7: 'finalize',
}

function getStepStatus(stepKey: StepKey, beStepStatus: Record<number, string>): string {
  const step = ALL_STEPS.find(s => s.key === stepKey)
  if (!step) return 'locked'
  if (step.legacyId === 0) {
    // Phase 3 'choices' step — BE chưa expose; compute FE-side hoặc default
    return profile.uses_choice_engine ? 'warning' : 'locked'
  }
  return beStepStatus[step.legacyId] ?? 'locked'
}
```

**Em recommend B** vì:
- BE Phase 3 KHÔNG có "choices" step_status logic (engine result render ở EligibilityResultViewer drawer, KHÔNG cần step badge)
- BE refactor key-based affects existing legacy API consumers — breaking change risk
- FE remap 1 file (~50 lines) + 1 test isolated, an toàn hơn

**Anchor tests** (PR-3D-A Wave A):
- `test_step_status_remap_legacy_7_keys` — BE `{1:"success",...,7:"locked"}` → FE remap đúng keys
- `test_step_status_choices_warning_when_phase3_no_choices_yet` — Phase 3 enabled + 0 choices → 'warning'
- `test_step_status_documents_unaffected_when_phase3_enabled` — Documents BE key=5 vẫn render đúng dù FE displayId=6

**Effort impact**: BE 0d (no refactor), FE +0.1d (1 file remap + 3 tests). Total P-UI-05 = +0.1d.

### 1.2 Bảng file path cho 8 components (unchanged)

### 1.2 Component → file path matrix

| Component | File path (NEW) | Parent / mount | Reuse pattern |
|---|---|---|---|
| `ChoicesTab` | `app/(dashboard)/admissions/[id]/_components/tabs/ChoicesTab.tsx` | Step 4.5 trong AdmissionDetailClient | Existing tab props pattern |
| `ChoiceListEditor` | `components/admission/choices/ChoiceListEditor.tsx` | Embedded trong ChoicesTab | react-hook-form FieldArray |
| `ChoiceScoreCard` | `components/admission/choices/ChoiceScoreCard.tsx` | Nested trong ChoiceListEditor per choice | useWatch + zodResolver (ScoresTab pattern) |
| `EligibilityResultViewer` | `components/admission/choices/EligibilityResultViewer.tsx` | Sheet drawer triggered từ "Xem kết quả" button trong ChoicesTab | PathDetailDrawer Sheet pattern reuse |
| `DecisionBadge` | **NO new file** — extend `components/common/status/StatusBadge.tsx` variants object | Render trong ChoiceListEditor + EligibilityResultViewer | StatusBadge variants extension (P2 wording v0.5 cleanup — KHÔNG tạo file riêng) |
| `AuditReasonDialog` | `components/admission/audit/AuditReasonDialog.tsx` | Triggered từ T10/T11/T12/T17 action buttons (officer/admin UI) | Existing ConfirmDialog wrapper |
| `Backfill admin queue` | `app/(dashboard)/admin/admission-backfill-queue/page.tsx` | Sidebar Organization group | TanStack DataTable reuse |
| `Magic-link 4-action UI` | `app/confirm/[token]/page.tsx` extend với `?action=...` query param | Existing Phase 1 route | Reuse `ConfirmAdmissionForm` extend |

### 1.3 Sidebar nav insertion

**Verified `frontend/src/lib/config/navigation.ts`** — Organization group line 229-232:
```
Organization:
├─ Units & Programs (/admin/organization)
├─ Cấu hình Tuyển sinh (/admin/admission-config)
└─ NEW: Hàng đợi backfill tuyển sinh (/admin/admission-backfill-queue)  ← Phase 3 add
```

**Role gate**: `["admin", "manager"]`. Icon: `Database` từ lucide-react.

### 1.4 Magic-link route decision — P-UI-03 patch

**Current state code-verified (Phase 1 LIVE, Phase 3 ZERO implementation)**:

| Layer | File | Current state | Phase 3 work |
|---|---|---|---|
| FE page | [confirm/[token]/page.tsx:19](frontend/src/app/confirm/[token]/page.tsx#L19) | Chỉ pass `token`, KHÔNG đọc `searchParams.action` | ADD `useSearchParams().get('action')` |
| FE component | [ConfirmAdmissionForm.tsx:107](frontend/src/components/forms/ConfirmAdmissionForm.tsx#L107) | Props `{ token }` only | RENAME → `MagicLinkActionForm` + `action` prop |
| FE API client | [admissions.ts:467](frontend/src/lib/api/admissions.ts#L467) | 1 endpoint `/api/admissions/confirm/{token}` | ADD 4 action-specific clients |
| BE router | [admissions.py:2073](Backend_FastAPI/app/routers/admissions.py#L2073) | 1 endpoint legacy | ADD `/api/v2/admissions/magic-link/{action}/{token}` 4 handlers |
| BE model | [admission.py:615](Backend_FastAPI/app/models/admission.py#L615) | `action_type` ENUM ready ✅ (Phase 1 M-1-18) | — |
| BE service | — | KHÔNG có `MagicLinkService` | NEW (G2 spec: atomic UPDATE + Redis rate limit) |

**Decision D-UI-03 = A query param extend** ✅ confirmed. NHƯNG **Phase 3 ship 6 items mới**, KHÔNG phải "backend route OK" như em viết v0.1.

**Final route structure** (Phase 3 Wave B):
```
/confirm/[token]                          ← legacy Phase 1 default action=confirm (backward compat)
/confirm/[token]?action=submit            ← Phase 3 Wave B NEW
/confirm/[token]?action=resubmit          ← Phase 3 Wave B NEW
/confirm/[token]?action=confirm           ← Phase 3 Wave B NEW (parity legacy)
/confirm/[token]?action=withdraw          ← Phase 3 Wave B NEW
```

**Phase 3 PR-3E scope explicit (~1.5d) — 6 items**:
1. **BE router**: 4 endpoints `/api/v2/admissions/magic-link/{action}/{token}` POST handlers
2. **BE service**: `MagicLinkService.consume_token(token, cccd, action)` — atomic UPDATE + CCCD verify + Redis rate limit 5/60s (G2)
3. **FE API client**: 4 wrapper `submitViaMagicLink/resubmitViaMagicLink/confirmViaMagicLink/withdrawViaMagicLink`
4. **FE page**: refactor `confirm/[token]/page.tsx` đọc `useSearchParams().get('action')` + branch render
5. **FE component**: rename `ConfirmAdmissionForm` → `MagicLinkActionForm` + `action` prop + 4-handler switch
6. **Backward compat**: default `action='confirm'` khi query param vắng → emails Phase 1 cũ (KHÔNG có `?action=`) vẫn work với legacy logic

**Anchor tests** (PR-3E):
- `test_default_action_confirm_when_no_query_param` — backward compat emails Phase 1
- `test_token_consume_atomic_under_concurrent_requests` × 4 actions (P1 fix #4 v2.13.1)
- `test_cccd_mismatch_rollback_token` × 4 actions
- `test_rate_limit_5_per_60s_lockout` Redis

### 1.4.x P-UI-06 CSRF exemption — Magic-link public route

**Code-verified ([csrf.py:50-66](Backend_FastAPI/app/middleware/csrf.py#L50))**:
```python
EXEMPT_PATHS: List[str] = [
    "/api/auth/login", ..., "/api/auth/verify-mfa",
    "/api/ctv-register",
    "/api/admissions/confirm/",  # ← Phase 1 magic-link exempt
    "/api/public/", "/api/webhooks/", ...
]
PROTECTED_METHODS: Set[str] = {"POST", "PUT", "DELETE", "PATCH"}
```

**Problem**: Phase 3 route mới `/api/v2/admissions/magic-link/{action}/{token}` POST KHÔNG match exempt prefix. Candidate public flow (mobile, không authenticated dashboard) sẽ fail CSRF check vì:
- Không có `csrf_token` cookie (chưa login)
- Không có `X-CSRF-Token` header
- POST method trong PROTECTED_METHODS

**3 options** em consider:

| Option | Pros | Cons |
|---|---|---|
| **A** Add CSRF exemption prefix `/api/v2/admissions/magic-link/` | Giữ contract v0.3 + Phase 3 RESTful path semantics | +1 line CSRF middleware + 2 tests |
| **B** Reuse legacy prefix `/api/admissions/confirm/{token}` với `?action=` | Reuse existing exemption — 0 middleware change | Phá REST convention (POST `/confirm/` cho withdraw không semantic); contract v0.3 inconsistent |
| **C** Require FE CSRF token on candidate page | Defense-in-depth | Candidate KHÔNG có session, phải fetch token qua public endpoint → 2 round-trips + edge cases |

**Em recommend Option A** ✅ — giữ contract v0.3, add CSRF exemption + tests.

**P-UI-06 patch — PR-3E scope thêm**:

```python
# Backend_FastAPI/app/middleware/csrf.py:58 — add 1 line
EXEMPT_PATHS: List[str] = [
    ...
    "/api/admissions/confirm/",            # Phase 1 legacy
    "/api/v2/admissions/magic-link/",      # ← Phase 3 NEW (P-UI-06)
    ...
]
```

**Anchor tests** (PR-3E):
- `test_magic_link_post_exempt_from_csrf` — POST `/api/v2/admissions/magic-link/confirm/{token}` không header `X-CSRF-Token` → 200/201 (NOT 403 CSRF fail)
- `test_other_v2_admissions_post_still_require_csrf` — POST `/api/v2/admissions/{id}/choices` vẫn require CSRF (verify exemption prefix exact match, không quá broad)
- `test_magic_link_prefix_partial_match_blocked` — POST `/api/v2/admissions/magic-link-fake/...` (malicious typosquat) → blocked CSRF (Python `startswith` strict)

**Effort impact**: +0.1d trong PR-3E (1 file middleware + 3 anchor tests). Total PR-3E 1.5d → 1.6d.

**GAP-01 v0.5 anti-abuse rate limit** (P2 security hardening, KHÔNG block lock):
- Nginx-level rate limit `/api/v2/admissions/magic-link/*` (30/min per IP)
- Defense-in-depth pre-CCCD-consume probe protection (G2 CCCD limit 5/60s áp dụng SAU consume)
- Log probe attempts (status code 4xx) cho audit trail
- Reuse existing rate limit middleware nếu có; nếu không có → nginx config update

**GAP-02 v0.5 action query param validation** (P2 security, +0.05d trong PR-3E):
- FE Zod enum validate `?action=` trước fetch
- BE Pydantic enum validate trong router param
- Throw 400 ngay với invalid action (KHÔNG silent fallback to confirm)
- Anchor test `test_invalid_action_query_param_rejected_400` — `?action=DROP_TABLE` → 400; `?action=admin` → 400; `?action=` empty → fallback intentional confirm OK

### 1.5 P-UI-08 `available_actions` migration — NEW additive field (no breaking change)

**Problem v0.4**: em propose Wave A replace `available_actions: list[str]` → `list[{action,target,endpoint}]` BIG-BANG breaking change. PHÁ 3+ consumers:
- `useAdmissionViewModel.ts:255` — `.includes("...")`
- `columns.tsx:295` — `.includes("...")`
- `TuitionTab.tsx:55` — `.includes("...")`

**P-UI-08 v0.5 fix — Additive + adapter pattern, KHÔNG replace**:

```python
# Backend_FastAPI/app/schemas/admission.py
class AdmissionProfileResponse(BaseModel):
    # ... existing fields ...
    available_actions: list[str]                # ← KEEP legacy field, KHÔNG breaking
    available_actions_v2: list[AvailableActionDetail]  # ← NEW Phase 3 typed (additive)

class AvailableActionDetail(BaseModel):
    action: str
    target: str  # 'self' | 'profile' | 'choice'
    endpoint: str  # vd '/api/v2/admissions/{id}/choices'
```

```typescript
// frontend/src/lib/admissions/has-action.ts (NEW helper)
export function hasAction(
  profile: AdmissionProfileResponse,
  action: string
): boolean {
  // Prefer v2 typed if exists (Phase 3 profiles), fallback v1 list[str]
  if (profile.available_actions_v2 && profile.available_actions_v2.length > 0) {
    return profile.available_actions_v2.some(a => a.action === action)
  }
  return profile.available_actions.includes(action)
}
```

**Migration path 3-step soft cutoff** (GAP-04 fix v0.5: B+N đếm từ **Wave B boundary 2026-08-13** per Q4 chốt v2.13.1, KHÔNG từ ship date 2026-06-15):
- **Wave B boundary = 2026-08-13** (Q4 chốt). Ship target sớm 2026-06-15 là bonus 6w soak slack, KHÔNG phải B+0 reference point.
- B+0 = 2026-08-13: BE ship cả 2 fields. FE ship `hasAction()` helper. Consumers `.includes()` migrate sang `hasAction()` per-file. (Code đã merged + soaking từ 2026-06-15.)
- B+30 = 2026-09-13: BE response header `X-API-Deprecation: available_actions string list deprecated, use available_actions_v2`. Track usage logs.
- B+90 = 2026-11-13 → **shifted 2026-12-15** (G6 buffer post-mùa): IF 0 consumers still use `.includes()` directly → BE drop `available_actions`. ELSE defer Q1/2027.

**Effort impact**: Wave A scope unchanged (legacy field intact). Wave B PR-3D-B thêm:
- BE schema additive field (+0.1d)
- `hasAction()` helper + migrate 3 consumers (+0.2d)
- Total PR-3D-B 10d → 10.3d (within slip-able buffer)

**Anchor tests**:
- `test_available_actions_v2_additive_legacy_preserved` — both fields populated
- `test_has_action_helper_prefers_v2_when_available`
- `test_has_action_helper_fallback_legacy_string_list`

### 1.6 P-UI-09 Magic-link token issuance action-aware

**Problem v0.4**: em propose magic-link consume per action_type NHƯNG repository tạo token chỉ profile-only — 4 actions concurrent impossible.

**Code-verified gap**:
- Model partial UNIQUE `(profile_id, action_type)` ([admission.py:615](Backend_FastAPI/app/models/admission.py#L615))
- Repository `create_confirmation_token(profile_id, token, expires_at)` ([admission_repository.py:1098](Backend_FastAPI/app/repositories/admission_repository.py#L1098)) thiếu `action_type` param
- Reuse lookup `.where(profile_id == profile_id)` only ([line 1131](Backend_FastAPI/app/repositories/admission_repository.py#L1131))
- Service `_generate_magic_link_url` build `/confirm/{token}` ([admission_service.py:7678](Backend_FastAPI/app/services/admission_service.py#L7678)) — KHÔNG `?action=`

**P-UI-09 v0.5 fix — PR-3E scope thêm**:

```python
# admission_repository.py refactor (PR-3E)
async def create_confirmation_token(
    self,
    profile_id: int,
    token: str,
    expires_at,
    action_type: str = "confirm",  # ← NEW param, default backward compat
) -> models.AdmissionConfirmationToken:
    # Reuse lookup filter by (profile_id, action_type) — partial UNIQUE aware
    existing = await self.db.execute(
        select(AdmissionConfirmationToken)
        .where(
            AdmissionConfirmationToken.profile_id == profile_id,
            AdmissionConfirmationToken.action_type == action_type,  # ← NEW filter
        )
    ).scalar_one_or_none()
    # ... rest unchanged
```

```python
# admission_service.py URL generation refactor (PR-3E)
def _generate_magic_link_url(
    base_url: str,
    token: str,
    action_type: str = "confirm",  # ← NEW param
) -> str:
    if action_type == "confirm":
        return f"{base_url}/confirm/{token}"  # ← legacy backward compat (KHÔNG ?action=)
    return f"{base_url}/confirm/{token}?action={action_type}"  # ← Phase 3 new
```

**Anchor tests**:
- `test_4_actions_concurrent_token_per_profile` — submit + resubmit + confirm + withdraw tokens cùng profile_id coexist
- `test_create_token_default_action_confirm_backward_compat` — legacy callers (no action_type param) → action_type='confirm'
- `test_url_legacy_format_when_action_confirm` — `/confirm/{token}` không `?action=` cho backward compat email cũ
- `test_url_phase3_format_when_action_other` — `?action=submit/resubmit/withdraw` correctly appended

**Effort impact**: PR-3E 1.6d (P-UI-06 absorbed) + repository refactor + URL refactor (+0.2d) = **1.8d**. Within slip-able buffer.

---

## 2. Props API contracts (Gap 2 HIGH)

## 2. Props API contracts (Gap 2 HIGH) — v0.3 PATCHED

### TS Fixes v0.3 summary

- **TS-01** (fixed Section 1.1): `Step` type không declare `displayId`; tách `VisibleStep extends Step { displayId: number }`
- **TS-02** (Section 2.2): `ChoiceScoreCard.errors` key ambiguous → spec rõ key format
- **TS-03** (Section 2.3): `rule_label_vi` BE redundant với FE i18n 25 keys → pick FE i18n source-of-truth
- **TS-04** (Section 2.6): `BackfillExceptionRow.exception_type` complete enum, KHÔNG `...`
- **TS-05** (Section 2.4): DecisionBadge tách 2 types `ChoiceDecision | EligibilityResult` union

### 2.1 ChoiceListEditor

```typescript
interface ChoiceListEditorProps {
  // Data
  choices: AdmissionProfileChoice[]  // BE response array
  maxChoices: number                  // từ system_config.max_choices_per_profile

  // Permissions (thin client — KHÔNG check role)
  isEditable: boolean                 // profile.can_edit
  canAddChoice: boolean               // available_actions.includes('add_choice')

  // Callbacks
  onAdd: () => Promise<void>          // POST /api/v2/admissions/{id}/choices
  onRemove: (choiceId: number) => Promise<void>
  onReorder: (newOrder: { id: number; display_order: number }[]) => Promise<void>

  // UI state
  loading?: boolean
  className?: string
}

interface AdmissionProfileChoice {
  id: number
  admission_path_id: number
  path_subject_group_config_id: number
  display_order: number
  decision: 'pending' | 'admitted' | 'waitlisted' | 'rejected' | 'skip'
  waitlist_rank: number | null
  eligibility_check_result: EligibilityResultJSONB | null
  bonus_rule_snapshot: BonusRuleJSONB | null
  // Display fields denormalized từ BE — Contract-06 spec
  display_path_name: string           // vd "CNTT - Học bạ - DOT_1"
  display_subject_group_name: string  // vd "Toán-Lý-Hoá"
  scores: ChoiceScoreSummary[]
}

// Contract-06: BE Pydantic schema phải spec computed fields
// Backend_FastAPI/app/schemas/admission_profile_choice.py:
// class AdmissionProfileChoiceResponse(BaseModel):
//     ... (DB fields)
//     # Computed fields via field_validator or joined query in repository
//     display_path_name: str  # join admission_path → academic_info.program_name + admission_method.method_name + offering_admission_round.round_code
//     display_subject_group_name: str  # join path_subject_group_config → subject_group.name
//     scores: list[ChoiceScoreSummary]  # nested profile_choice_score rows

interface ChoiceScoreSummary {
  subject_id: number
  subject_code: string                // vd "TOAN", "LY", "DGNL_DHQGHN"
  subject_name: string                // vd "Toán"
  score: number                        // NUMERIC(8,2)
  max_score_snapshot: number
  weight_snapshot: number
}
```

### 2.2 ChoiceScoreCard

```typescript
interface ChoiceScoreCardProps {
  choiceId: number
  subjects: SubjectScoreInput[]       // path_subject_group_config.subjects với min/max snapshot
  isEditable: boolean
  onSave: (scores: ChoiceScore[]) => Promise<void>  // PATCH /api/v2/admissions/{id}/choices/{choiceId}/scores
  // TS-02 fix: errors keyed by subject_code (string) — Pydantic ValidationError loc serializes to "scores.{subject_code}.score"
  errors?: Record<string, string>     // key = subject_code, value = error message
}

interface SubjectScoreInput {
  subject_id: number
  subject_name: string
  subject_code: string                // vd "TOAN", "LY", "DGNL_DHQGHN"
  min_possible_score: number          // snapshot (NUMERIC(8,2))
  max_score: number                   // snapshot (NUMERIC(8,2))
  weight: number                      // snapshot NUMERIC(5,2)
  current_score: number | null
}

interface ChoiceScore {
  subject_id: number
  score: number  // 0 to max_score range
}
```

### 2.3 EligibilityResultViewer

```typescript
interface EligibilityResultViewerProps {
  choice: AdmissionProfileChoice      // contains eligibility_check_result JSONB
  open: boolean
  onOpenChange: (open: boolean) => void  // Sheet wrapper
}

interface EligibilityResultJSONB {
  overall_decision: 'eligible' | 'ineligible' | 'pending'
  total_score: number
  rule_results: Array<{
    rule_code: 'SUBJECT_COMPLETENESS' | 'MIN_GPA' | 'GRAD_YEAR' | 'MIN_SUBJECT_SCORE' | 'TOTAL_SCORE_THRESHOLD' | 'BONUS_RULE'
    // TS-03 fix: rule_label_vi REMOVED — FE inline i18n keys (Q8 chốt) là source-of-truth
    // FE lookup: t(`admission.engine.rule.${rule_code}`) cho label
    passed: boolean
    reason_code: string | null  // i18n key cho fail reason: t(`admission.engine.reason.${reason_code}`)
    details: Record<string, unknown>  // raw data per rule (debug info, KHÔNG render UI)
  }>
  evaluated_at: string  // ISO timestamp
}
```

### 2.4 DecisionBadge

```typescript
// TS-05 fix: tách 2 types vì DecisionBadge dùng cho 2 contexts khác nhau
type ChoiceDecision = 'pending' | 'admitted' | 'waitlisted' | 'rejected' | 'skip'  // từ DB choice.decision enum
type EligibilityResult = 'pending' | 'eligible' | 'ineligible'                       // từ EligibilityResultJSONB.overall_decision
type DecisionBadgeValue = ChoiceDecision | EligibilityResult  // union 7 unique values

interface DecisionBadgeProps {
  decision: DecisionBadgeValue
  context: 'choice' | 'eligibility'   // ← FE pick variant theo context
  size?: 'sm' | 'md' | 'lg'
  showIcon?: boolean
  className?: string
}
```

**Variant extension trong StatusBadge.tsx**: thêm `admission-decision-{admitted|waitlisted|rejected|eligible|ineligible|skip|pending}` vào variants map. Reuse infrastructure existing — KHÔNG tạo file mới.

**Context discrimination**:
- `<DecisionBadge decision={choice.decision} context="choice" />` — render trong ChoiceListEditor
- `<DecisionBadge decision={eligibilityResult.overall_decision} context="eligibility" />` — render trong EligibilityResultViewer

### 2.5 AuditReasonDialog

```typescript
interface AuditReasonDialogProps {
  action: 'promote_waitlist' | 'reject_waitlist' | 'confirm_admission' | 'rollback_status'  // T10/T11/T12/T17
  profileId: number
  choiceId?: number  // optional for T10/T11
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (reason: string) => Promise<void>
}

// Internal: load reason templates from system_config (Q-P3 future) hoặc hardcoded constants
const REASON_TEMPLATES: Record<AuditReasonDialogProps['action'], string[]> = {
  promote_waitlist: ['Slot freed do candidate withdraw', 'Đặc cách xét tuyển bổ sung', ...],
  reject_waitlist: ['Chỉ tiêu đã đầy', 'Hết thời gian xét', ...],
  confirm_admission: ['Officer assist confirm', 'Admin override per request', ...],
  rollback_status: ['Engine sai', 'Data mismatch', 'Compliance audit', ...],
}
```

### 2.6 Backfill admin queue page

```typescript
// Page-level state, không phải component props
// P-UI-07 v0.5 fix + GAP-05/06 v0.5 final: align với DB schema thật + lock Phase 3 types
// DB code thật: phase1_12_backfill_selected_subject_group_id.py:212 → AMBIGUOUS_SELECTED_GROUP
// DB schema: phase1_07b_create_backfill_exceptions_table.py:100-114 → resolved_at + resolved_by_user_id + resolution_notes, KHÔNG có status column
// DB column type: exception_type VARCHAR(64) — runtime string, KHÔNG hardcoded enum trong DB

// GAP-05 + GAP-06 final list 6 known production exception_types (pre-PR-3A lock):
// Phase 1 production:
//   - AMBIGUOUS_SELECTED_GROUP (phase1_12)
//   - INVALID_GPA_VALUE (phase1_09a M-1-09a)
//   - MISSING_GPA_OVERALL (phase1_09a)
//   - INVALID_GRADUATION_YEAR (phase1_09a)
//   - MISSING_GRADUATION_YEAR (phase1_09a)
// Phase 3 NEW (locked pre-PR-3A 2026-05-12):
//   - INSUFFICIENT_DATA_FOR_CHOICE_CREATION (no path/score data cho engine xét tuyển)
//   - MULTI_PATH_AMBIGUITY (profile scores match >1 path → admin manual disambiguate)
//
// FE Zod runtime widening (GAP-06):
//   - schema: z.string()  // ← accept ANY string, KHÔNG hardcode enum
//   - render: i18n lookup `t(\`admission.backfill.exception.${type}\`)`
//   - fallback "Khác" cho unknown types (defensive cho future Phase 4+ types)
//   - filter UI: fetch enum list runtime từ `/api/v2/admin/admission-backfill-exceptions/types`

type BackfillExceptionTypeKnown =
  // Phase 1 production
  | 'AMBIGUOUS_SELECTED_GROUP'
  | 'INVALID_GPA_VALUE'
  | 'MISSING_GPA_OVERALL'
  | 'INVALID_GRADUATION_YEAR'
  | 'MISSING_GRADUATION_YEAR'
  // Phase 3 NEW
  | 'INSUFFICIENT_DATA_FOR_CHOICE_CREATION'
  | 'MULTI_PATH_AMBIGUITY'

// FE type used trong app:
type BackfillExceptionType = string  // ← runtime string, validate qua known list display logic

interface BackfillExceptionRow {
  id: number
  profile_id: number
  profile_lead_name: string                 // FE joined via lead.full_name
  exception_type: BackfillExceptionType      // string runtime, narrow via BackfillExceptionTypeKnown display
  details: Record<string, unknown>           // JSONB (DB column: "details", NOT "exception_details")
  resolved_at: string | null
  resolved_by_user_id: number | null
  resolution_notes: string | null            // ← DB column thật
  created_at: string
  // NOTE: KHÔNG có column "status" trên DB. FE derived state từ resolved_at:
  // - resolved_at IS NULL → derived_status = "pending"
  // - resolved_at IS NOT NULL → derived_status = "resolved"
  // Plus resolution_notes có thể chứa free-text "approved" / "rejected" / "deferred" — admin convention
}

// GAP-06 anchor test:
// test_unknown_exception_type_falls_back_to_other_filter_option
//   — BE return exception_type="FUTURE_PHASE_4_TYPE" → FE renders "Khác" label + filter dropdown vẫn show option

// FE filter UI: derived `pending` vs `resolved` từ resolved_at NULL/NOT NULL
// Batch action "Approve/Reject/Defer" → PATCH resolution_notes + resolved_at + resolved_by_user_id

// API endpoints expected (v0.5 corrected):
// GET    /api/v2/admin/admission-backfill-exceptions?filter=...&page=...
// PATCH  /api/v2/admin/admission-backfill-exceptions/{id}/resolve  (body: { resolution_notes })
// POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve  (body: { ids: [...], resolution_notes })
// GET    /api/v2/admin/admission-backfill-exceptions/export.csv

interface BackfillQueueFilters {
  exception_type?: string
  status?: 'pending' | 'approved' | 'rejected' | 'deferred'
  date_from?: string
  date_to?: string
  search?: string  // profile name / lead phone
}

// API endpoints expected:
// GET    /api/v2/admin/admission-backfill-exceptions?filters=...&page=...
// PATCH  /api/v2/admin/admission-backfill-exceptions/{id}/resolve  (approve/reject/defer)
// POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve  (batch)
// GET    /api/v2/admin/admission-backfill-exceptions/export.csv
```

### 2.7 MagicLinkActionForm (rename ConfirmAdmissionForm)

```typescript
interface MagicLinkActionFormProps {
  token: string
  action: 'submit' | 'resubmit' | 'confirm' | 'withdraw'  // từ useSearchParams
  expiresAt: string  // ISO timestamp, BE return từ token lookup
}

// Internal:
// - CCCD input mandatory all 4 actions
// - Per-action handler:
//   - submit:    POST /api/v2/admissions/magic-link/submit/{token}    body { cccd, ...form_data }
//   - resubmit:  POST /api/v2/admissions/magic-link/resubmit/{token}  body { cccd, ...form_data }
//   - confirm:   POST /api/v2/admissions/magic-link/confirm/{token}   body { cccd }
//   - withdraw:  POST /api/v2/admissions/magic-link/withdraw/{token}  body { cccd, reason }
```

---

## 3. Mobile responsive policy (Gap 6 HIGH)

### 3.1 Three-tier zone classification

| Zone | Components | Mobile policy |
|---|---|---|
| **A — Candidate-facing mobile-first** | ChoicesTab, ChoiceListEditor, ChoiceScoreCard, EligibilityResultViewer, MagicLinkActionForm, DecisionBadge | Full mobile support 320px-640px viewport |
| **B — Admin desktop-only acceptable** | Backfill admin queue, AuditReasonDialog (officer/admin context) | Mobile may render OK nhưng KHÔNG ưu tiên optimize. `md:` breakpoint OK |
| **C — Shared components** | DecisionBadge | Same as StatusBadge existing (sm/md/lg sizes all work mobile) |

### 3.2 Zone A specific policies

**ChoiceListEditor drag-drop mobile fallback**:
- `@dnd-kit/core` v6.3.1 supports `PointerSensor` (touch + mouse unified)
- Mobile (< 768px): show explicit "↑ ↓" arrow buttons next to each choice item như fallback
- Desktop (≥ 768px): drag-drop primary, arrows hidden
- Implementation: `useMediaQuery('(min-width: 768px)')` toggle

**ChoiceScoreCard mobile layout**:
- Mobile (< 640px): 1-column grid `grid-cols-1`, full-width score inputs
- Tablet (≥ 640px): 2-column grid `sm:grid-cols-2`
- Desktop (≥ 1024px): 3-column grid `lg:grid-cols-3`

**EligibilityResultViewer Sheet mobile**:
- Mobile (< 640px): fullscreen `<SheetContent className="w-full h-full max-w-full">` (override Phase 2 `sm:max-w-3xl`)
- Desktop (≥ 640px): `sm:max-w-2xl` slide-in từ right
- 6 rule cards: stack vertical mobile, không thay đổi layout

**MagicLinkActionForm**:
- Mobile-first design — candidate dùng phone là use case chính
- Form fields stack vertical
- CCCD input numeric keyboard `inputMode="numeric"`
- Submit button sticky bottom mobile (`fixed bottom-0` < 640px)

### 3.3 Zone B specific policies

**Backfill queue table**:
- Desktop primary (admin context)
- Mobile fallback: TanStack DataTable mặc định scroll horizontal `overflow-x-auto`
- KHÔNG optimize column collapse hoặc card-view mobile (admin chấp nhận desktop)

**AuditReasonDialog**:
- Modal `<Dialog>` Radix primitive mặc định mobile responsive
- Textarea full-width, dropdown native render
- KHÔNG custom mobile layout

---

## 4. Reuse decisions summary

| Existing pattern | Phase 3 reuse | Decision |
|---|---|---|
| `StatusBadge` variants | DecisionBadge | ✅ EXTEND variants object — KHÔNG file mới |
| `Sheet` + `Tabs` URL sync (PathDetailDrawer) | EligibilityResultViewer drawer | ✅ REUSE pattern — same URL param `?eligibility=<choiceId>` |
| `useForm` + `zodResolver` + `mode: "onBlur"` | ChoicesTab, ChoiceScoreCard | ✅ REUSE existing form lib (react-hook-form) |
| `useWatch` real-time validation | ChoiceScoreCard | ✅ REUSE ScoresTab.tsx:74-92 pattern |
| TanStack DataTable | Backfill queue | ✅ REUSE common/table/DataTable.tsx |
| `@dnd-kit` from PipelineClient | ChoiceListEditor | ✅ REUSE library (đã installed) + SSR `{ ssr: false }` dynamic import |
| `/confirm/[token]` route | Magic-link 4-action | ✅ EXTEND với `?action=` query param |
| AdmissionDetailClient step nav | ChoicesTab | ✅ EXTEND step state (Step 4.5 conditional render) |

**0 new dependency** required. Phase 3 FE pure leverage Phase 1+2 infrastructure.

---

## 5. User decisions confirmed (D-UI-01..03) — v0.2 status

### D-UI-01: Tab integration approach → ✅ **(A) Step 5 dynamic conditional**

User confirm A — NHƯNG v0.1 mô tả sai "Step 4.5". v0.2 patch P-UI-01 refactor sang **dynamic steps array với renumber sequential**. Khi `uses_choice_engine=true`, "Nguyện vọng" = Step 5 (Documents push → 6, Tuition → 7, Finalize → 8). Khi false: 7 steps cũ giữ nguyên.

### D-UI-02: AuditReasonDialog templates source → ✅ **(A) Hardcoded constants**

User confirm A — KHÔNG thêm DB schema cho v0.4. `REASON_TEMPLATES` constant trong `frontend/src/components/admission/audit/reason-templates.ts` mới (NEW file). 4 actions × 4-6 templates mỗi action = ~20 strings.

### D-UI-03: Magic-link route final → ✅ **(A) Query param extend**

User confirm A — NHƯNG v0.1 ghi sai "backend route ready". v0.2 patch P-UI-03 spec rõ Phase 3 ship 6 items mới (4 BE endpoints + BE service + 4 FE API clients + FE page refactor + component rename + backward compat).

---

## 6. Day 1.5 design session output checklist

- [x] 8 components mount points chốt (Section 1)
- [x] Props API TypeScript interfaces 7 components (Section 2)
- [x] Mobile responsive 3-zone policy (Section 3)
- [x] Reuse pattern decisions table (Section 4)
- [x] User D-UI-01..03 confirm A/A/A
- [x] v0.2 patches P-UI-01/02/03 applied (code-truth gaps fix)
- [x] User round-3 review flag 2 P1 + 5 TS + 1 Contract + 1 Nav
- [x] v0.3 patches P-UI-04/05 + TS-01..05 + Contract-06 + Nav-07 applied
- [x] User round-4 review accept P-UI-04/05; flag P-UI-06 CSRF + M1-M5 minor
- [x] v0.4 patch P-UI-06 + Section 7 cleanup + Section 8 M1-M5 log applied
- [x] User round-5 review accept P-UI-06; flag 3 P1 NEW (backfill DB drift + available_actions breaking + token action-aware) + 2 P2 wording
- [x] v0.5 patches P-UI-07/08/09 + P2 wording cleanup + dry-run script fix applied
- [x] User round-6 hard gap hunt 10 gaps (P0/P1/P2/P3 mixed)
- [x] v0.5 final patches: GAP-01 rate limit + GAP-02 action validate + GAP-03/08 6 fixtures + GAP-04 timeline B+N from boundary + GAP-05 Phase 3 types lock + GAP-06 FE widen string + GAP-09 cascade 21.4d + GAP-10 R14 buffer math (GAP-07 N/A no drift detected)
- [x] Lock plan v0.5 ready (em apply cascade sync below)

## 7. v0.4 patches summary cho plan v0.4 absorb

Khi lock plan v0.4, cần add các điểm sau từ UI design v0.4 (cumulative v0.2 + v0.3 + v0.4):

### P-UI-01 (PR-3D-A Wave A scope expand)

PR-3D-A scope thêm:
- Refactor `AdmissionDetailClient.tsx` state `currentStep` + render loop sang dynamic `visibleSteps` array
- Refactor `PipelineSidebar.tsx` `STEPS` constant sang accept `steps` prop
- 2 anchor tests:
  - `test_visible_steps_7_when_uses_choice_engine_false` (legacy preserved)
  - `test_visible_steps_8_renumbered_when_uses_choice_engine_true` (Phase 3 enabled)

**Effort impact**: PR-3D-A 1.5d → **2d** (+0.5d refactor existing 2 files)

### P-UI-02 (PR-3A bundle thêm)

PR-3A `phase3_01` migration bundle G1 hiện đã có 4 ALTER + 1 INSERT + 1 UPDATE. Thêm:
- **BE schema**: `Backend_FastAPI/app/schemas/admission.py` `AdmissionProfileResponse` add `uses_choice_engine: bool` field
- **FE Zod**: `frontend/src/lib/zod/admissions.ts:468` add `uses_choice_engine: z.boolean()`
- **ViewModel passthrough**: nếu có transform layer
- **Anchor test**: `test_uses_choice_engine_visible_in_profile_response` (BE pytest) + Zod parse test (FE Vitest)

**Effort impact**: PR-3A 1.5d → **1.75d** (+0.25d schema + Zod + 2 anchor tests). KHÔNG migration change — chỉ schema/Zod refactor.

### P-UI-03 (PR-3E scope expand — 6 items)

PR-3E hiện estimate 1.5d. v0.2 break down 6 items với scope rõ:
1. BE router 4 endpoints (~0.3d)
2. BE service `MagicLinkService` consume + atomic + Redis rate limit (~0.5d)
3. FE API client 4 wrappers (~0.15d)
4. FE page `confirm/[token]/page.tsx` refactor `useSearchParams` (~0.15d)
5. FE component rename + extend (~0.25d)
6. Backward compat default action='confirm' + tests (~0.15d)

Tổng ~1.55d → keep estimate **1.5d** (rounding OK, em đã calibrate đúng v0.3).

### Plan v0.5 final effort table (cumulative all patches)

| Patch | Effort delta | PR ảnh hưởng | Scope |
|---|---|---|---|
| P-UI-01 dynamic steps refactor | +0.5d | PR-3D-A 1.5d → 2d | FE refactor 3 files |
| P-UI-02 `uses_choice_engine` expose | +0.25d | PR-3A 1.5d → 1.75d | BE schema + FE Zod + 2 anchor tests |
| P-UI-03 magic-link 6 items spec rõ | 0d (within 1.5d) | PR-3E unchanged | Documentation only |
| P-UI-04 key-based nav + AdmissionActions | +0.25d | PR-3D-A 2d → 2.25d | 4 files + 6 anchor tests |
| P-UI-05 FE step_status remap Option B | +0.1d | PR-3D-A 2.25d → 2.35d | 1 file remap + 3 tests |
| Contract-06 BE Pydantic computed fields | +0.1d | PR-3A 1.75d → 1.85d | 1 schema + field_validator |
| P-UI-06 CSRF exemption magic-link prefix | +0.1d | PR-3E 1.5d → 1.6d | csrf.py middleware + 3 anchor tests |
| **P-UI-07 v0.5 backfill DB contract align** | **0d** | **PR-3D-B documentation polish** | **Schema corrected; FE filter UI derived state từ resolved_at** |
| **P-UI-08 v0.5 `available_actions` additive (no breaking change)** | **+0.3d** | **PR-3D-B 10d → 10.3d** | **BE additive field + hasAction() helper + migrate 3 consumers** |
| **GAP-03/08 v0.5 6 test fixture files migrate** | **+0.1d** | **PR-3D-B 10.3d → 10.4d** | **AdmissionActions.test + PersonalInfoTab.test + TuitionTab.test + useAdmissionPaths.test + useAdmissionViewModel.test + AdmissionsBulkActionsBar.test — add `available_actions_v2: []` mock** |
| **P-UI-09 v0.5 token issuance action-aware** | **+0.2d** | **PR-3E 1.6d → 1.8d** | **Repository + URL gen action_type param + 4 tests** |
| TS-01..05 spec polish | 0d | — | Type definitions only |
| **Total Phase 3** | **+1.9d** | **19.5d → 21.4d active dev** | — |

Buffer 4w W6-W9 (~20d available) absorb 1.9d slip OK (room ~18.1d remaining buffer post-absorb).

**GAP-10 risk register R14 NEW**: Cumulative absorbing eats buffer 1.9d. Nếu Phase 2 PR-2D.1 hard-review pass lặp pattern (4 iter × ~0.5-1d each = 2-4d), buffer thực sự còn 14-16d. Fallback: shift Wave B+0 boundary từ 2026-08-13 → **2026-09-13 (last-resort slip)** trong khi Wave A 2026-07-23 hard commit vẫn hold. Mùa 2026-08-01 mở với Wave A single-NV minimum, Wave B features deploy late tháng 9 nếu cần.

**Note Wave A scope cleanup** (P2 wording v0.5):
- "Zod strict enum 14 states extend" → **parity test** (đã có ở [admissions.ts:520](frontend/src/lib/zod/admissions.ts#L520))
- "Status badge config 4 decision badges" → **parity test + variants extension** (đã có 14 admission states ở [status-badge.config.ts:40](frontend/src/lib/ui-config/status-badge.config.ts#L40))
- Net Wave A nhỏ hơn estimate v0.4 nhưng em giữ 2.35d budget cho refactor work + anchor tests (parity tests count cùng).

---

## 8. Minor refinements logged (M1-M5) — implementation polish trong PR, KHÔNG block lock

| # | Section ref | Refinement | Apply trong PR |
|---|---|---|---|
| **M1** | Section 1.1 P-UI-04 | AdmissionActions.tsx refactor **4 lines** (133/141/149/157), không chỉ line 133. Anchor test thêm `test_admission_actions_4_currentStep_refs_removed` post-refactor. | PR-3D-A |
| **M2** | Section 1.1.y P-UI-05 | 'choices' step status hard-coded `profile.uses_choice_engine ? 'warning' : 'locked'` → refine dynamic: `success` nếu all choices có scores, `warning` nếu partial, `locked` nếu 0 choices. | PR-3D-A |
| **M3** | Section 2.4 DecisionBadge | Discriminated union type-safer:<br>`type DecisionBadgeProps = { context: 'choice'; decision: ChoiceDecision; ... } \| { context: 'eligibility'; decision: EligibilityResult; ... }`<br>Compiler-enforced context-decision pairing. | PR-3D-B |
| **M4** | Section 2.6 BackfillExceptionType | Phase 1 #07b có thể có thêm types (INVALID_GPA_VALUE, INVALID_GRADUATION_YEAR từ M-1-09a). FE Zod 2-value enum sẽ parse fail nếu BE returns others. Options: (a) define BE endpoint `/api/v2/admin/admission-backfill-exceptions/types` runtime + FE Zod widen `z.string()`, hoặc (b) FE Zod hardcode 4-value union với fallback "unknown". | PR-3D-B |
| **M5** | Section 2.7 MagicLinkActionForm | `expiresAt` source ambiguous — Phase 1 chưa có preview endpoint. Options: (a) NEW BE endpoint `GET /api/v2/admissions/magic-link/{token}/preview` return `{ expires_at, action_type }` cho FE fetch trước CCCD input, hoặc (b) fallback render expiry banner sau consume fail với BE error message. | PR-3E |

---

---

## Reference

- Memory `phase3-plan-locked` (v0.3)
- Memory `pattern-change-impact-audit` (anchor test mandate)
- Memory `audit-before-fix` (verify existing patterns trước design)
- Plan `noble-launching-cocoa.md` v0.3
- Audit report Day 1.5: FE patterns extraction 2026-05-11 (Explore agent)
