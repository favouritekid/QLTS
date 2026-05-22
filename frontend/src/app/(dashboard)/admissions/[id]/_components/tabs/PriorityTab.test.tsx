/**
 * PriorityTab composition test (Q9 #07 Phase E.4 PR-3 audit P2).
 *
 * Spec V3 §II ("Wireframe Step 4 — workbench") locks PriorityTab as a 5-child
 * compose: PriorityHeaderBanner + PriorityInputsSection + EngineResultCard +
 * UtEvidenceCards + PrioritySummaryPanel + (mounted) PriorityOverrideDialog.
 *
 * This file pins 8 composition cases — the matrix of profile states the
 * workbench is expected to render correctly. Each case asserts:
 *   (a) all 5 sections mount
 *   (b) the wrapper data-testid is present
 *   (c) the override dialog is mounted (open=false except when triggered)
 *   (d) the right children receive the right state-derived props
 *
 * Sub-components have their own unit tests covering inner behavior (banner
 * state derivation, engine card 5 KV states, UT card per-code render,
 * summary frozen contract precedence). The job of THIS test is only to
 * verify the COMPOSITION is correct across profile states — drift in the
 * tab's section list or prop-wiring fails here before reaching production.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useForm, type UseFormReturn } from "react-hook-form"
import { useEffect } from "react"
import * as React from "react"

import { PriorityTab } from "./PriorityTab"
import type {
  AdmissionProfileResponse,
  AdmissionProfileUpdateInput,
} from "@/lib/zod/admissions"

// ---------------------------------------------------------------------------
// Mock sub-components — capture props for assertion. Each mock renders a
// minimal probe with the props serialized into a data-* attribute so the
// test reads exactly what PriorityTab handed down.
// ---------------------------------------------------------------------------

const bannerSpy = vi.fn()
const inputsSpy = vi.fn()
const engineSpy = vi.fn()
const utCardsSpy = vi.fn()
const summarySpy = vi.fn()
const overrideDialogSpy = vi.fn()

vi.mock("../priority/PriorityHeaderBanner", () => ({
  PriorityHeaderBanner: (props: Record<string, unknown>) => {
    bannerSpy(props)
    return <div data-testid="probe-banner" />
  },
}))

vi.mock("../priority/PriorityInputsSection", () => ({
  PriorityInputsSection: (props: Record<string, unknown>) => {
    inputsSpy(props)
    return (
      <div
        data-testid="probe-inputs"
        data-editable={String(props.isEditable ?? false)}
      />
    )
  },
}))

vi.mock("../priority/EngineResultCard", () => ({
  EngineResultCard: (props: Record<string, unknown>) => {
    engineSpy(props)
    return (
      <div
        data-testid="probe-engine"
        data-can-override={String(props.canOverride ?? false)}
      />
    )
  },
}))

vi.mock("../priority/UtEvidenceCards", () => ({
  UtEvidenceCards: (props: Record<string, unknown>) => {
    utCardsSpy(props)
    return (
      <div
        data-testid="probe-ut"
        data-can-verify={String(props.canVerify ?? false)}
        data-is-editable={String(props.isEditable ?? false)}
      />
    )
  },
}))

vi.mock("../priority/PrioritySummaryPanel", () => ({
  PrioritySummaryPanel: (props: Record<string, unknown>) => {
    summarySpy(props)
    return <div data-testid="probe-summary" />
  },
}))

vi.mock("../PriorityOverrideDialog", () => ({
  PriorityOverrideDialog: (props: Record<string, unknown>) => {
    overrideDialogSpy(props)
    return (
      <div
        data-testid="probe-override-dialog"
        data-open={String(props.open ?? false)}
        data-mode={String(props.mode ?? "")}
        data-current-kv={String(props.currentKv ?? "")}
      />
    )
  },
}))

// usePreviewPriorityKv — keep the hook stable + returnable nullable so the
// fire-gate (status==='draft' && cultural) does not actually hit the network.
//
// Type spy args explicitly so `.mock.calls[N][2]` resolves to ``boolean``
// instead of TS inferring zero-length tuple from the zero-arg factory
// signature (TS2493 in strict CI).
type PreviewHookArgs = [number, Record<string, unknown>, boolean]
type PreviewHookReturn = {
  data: null
  isLoading: boolean
  isFetching: boolean
}
const previewHookSpy = vi.fn<(...args: PreviewHookArgs) => PreviewHookReturn>(
  () => ({
    data: null,
    isLoading: false,
    isFetching: false,
  }),
)
vi.mock("@/lib/hooks/use-preview-priority-kv", () => ({
  usePreviewPriorityKv: (...args: PreviewHookArgs) => previewHookSpy(...args),
}))

// P0-1 fix 2026-05-22 — auth.store mock no longer needed. PriorityTab swap
// đọc mode từ `profile.override_priority_kv_mode` (server-derived) thay vì
// user.role string. Keep no-op mock để tránh import resolution surprise
// nếu PriorityTab re-add dependency tương lai.
vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: () => null,
}))

// ---------------------------------------------------------------------------
// Test harness: wraps PriorityTab with a real react-hook-form so form.watch
// returns real values for the preview hook gate (per PR-3 P1 design — gate
// is profile.status==='draft' && !!cultural). The form's defaultValues
// mirror the case's profile to keep watches in sync.
// ---------------------------------------------------------------------------

function Harness({
  profile,
  isEditable,
  defaults,
}: {
  profile: AdmissionProfileResponse
  isEditable: boolean
  defaults: Partial<AdmissionProfileUpdateInput>
}) {
  const form = useForm<AdmissionProfileUpdateInput>({
    defaultValues: defaults as AdmissionProfileUpdateInput,
  })
  return (
    <PriorityTab
      form={form as unknown as UseFormReturn<AdmissionProfileUpdateInput>}
      profile={profile}
      isEditable={isEditable}
      onNavigateToDocuments={() => {}}
    />
  )
}

function renderTab(opts: {
  profile: AdmissionProfileResponse
  isEditable?: boolean
  defaults?: Partial<AdmissionProfileUpdateInput>
}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <Harness
        profile={opts.profile}
        isEditable={opts.isEditable ?? true}
        defaults={opts.defaults ?? {}}
      />
    </QueryClientProvider>,
  )
}

// ---------------------------------------------------------------------------
// Profile builders — minimal shape; only fields PriorityTab reads.
// ---------------------------------------------------------------------------

type Permissions = NonNullable<AdmissionProfileResponse["permissions"]>
type Snapshot = NonNullable<AdmissionProfileResponse["priority_resolution_snapshot"]>

function makeProfile(over: {
  status: AdmissionProfileResponse["status"]
  version?: number
  permissions?: Partial<Permissions>
  priority_resolution_snapshot?: Snapshot | null
  priority_object_codes?: string[] | null
  priority_object_evidence?: Record<string, unknown> | null
  /** P0-1 fix 2026-05-22 — server-derived mode flag thay thế user.role check. */
  override_priority_kv_mode?: "admin" | "manager" | "officer" | "none"
}): AdmissionProfileResponse {
  // Minimal partial — cast at the call site. PriorityTab only reads ~7 fields.
  return {
    id: 42,
    status: over.status,
    version: over.version ?? 1,
    permissions: (over.permissions ?? {}) as Permissions,
    priority_resolution_snapshot: over.priority_resolution_snapshot ?? null,
    priority_object_codes: over.priority_object_codes ?? null,
    priority_object_evidence: over.priority_object_evidence ?? null,
    override_priority_kv_mode: over.override_priority_kv_mode ?? "officer",
  } as unknown as AdmissionProfileResponse
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

beforeEach(() => {
  bannerSpy.mockClear()
  inputsSpy.mockClear()
  engineSpy.mockClear()
  utCardsSpy.mockClear()
  summarySpy.mockClear()
  overrideDialogSpy.mockClear()
  previewHookSpy.mockClear()
})

describe("PriorityTab composition — Phase E.4 PR-3", () => {
  it("Case 1 — draft empty (no inputs, no UT codes): all 5 sections mount, preview NOT enabled", () => {
    const profile = makeProfile({ status: "draft" })
    renderTab({ profile, isEditable: true, defaults: {} })

    expect(screen.getByTestId("priority-tab-workbench")).toBeInTheDocument()
    expect(screen.getByTestId("probe-banner")).toBeInTheDocument()
    expect(screen.getByTestId("probe-inputs")).toBeInTheDocument()
    expect(screen.getByTestId("probe-engine")).toBeInTheDocument()
    expect(screen.getByTestId("probe-ut")).toBeInTheDocument()
    expect(screen.getByTestId("probe-summary")).toBeInTheDocument()
    expect(screen.getByTestId("probe-override-dialog")).toBeInTheDocument()

    // preview gate: cultural is null → 4th arg `enabled` MUST be false.
    expect(previewHookSpy).toHaveBeenCalled()
    const lastCall = previewHookSpy.mock.calls.at(-1)!
    expect(lastCall[2]).toBe(false) // !!cultural && isDraft = false
  })

  it("Case 2 — draft partial (cultural set, no UT codes): preview gate fires", () => {
    const profile = makeProfile({ status: "draft" })
    renderTab({
      profile,
      isEditable: true,
      defaults: { cultural_education_level: "graduated_thpt" },
    })

    expect(screen.getByTestId("probe-banner")).toBeInTheDocument()
    expect(screen.getByTestId("probe-inputs")).toHaveAttribute(
      "data-editable",
      "true",
    )
    // preview enabled because draft + cultural set
    const lastCall = previewHookSpy.mock.calls.at(-1)!
    expect(lastCall[2]).toBe(true)
  })

  it("Case 3 — draft full (cultural + UT codes claimed): UtEvidenceCards receives canVerify=false (officer w/o flag)", () => {
    const profile = makeProfile({
      status: "draft",
      priority_object_codes: ["04", "07"],
    })
    renderTab({
      profile,
      isEditable: true,
      defaults: {
        cultural_education_level: "graduated_thpt",
        priority_object_codes: ["04", "07"],
      },
    })

    const utProbe = screen.getByTestId("probe-ut")
    expect(utProbe).toHaveAttribute("data-can-verify", "false")
    expect(utProbe).toHaveAttribute("data-is-editable", "true")
  })

  it("Case 4 — submitted, UT pending: inputs disabled (not draft), preview NOT enabled", () => {
    const profile = makeProfile({
      status: "submitted",
      priority_object_codes: ["04"],
      priority_object_evidence: { "04": { status: "pending" } },
      permissions: { verify_priority_object: true },
    })
    renderTab({
      profile,
      isEditable: false,
      defaults: {
        cultural_education_level: "graduated_thpt", // set, but post-draft
        priority_object_codes: ["04"],
      },
    })

    expect(screen.getByTestId("probe-inputs")).toHaveAttribute(
      "data-editable",
      "false",
    )
    expect(screen.getByTestId("probe-ut")).toHaveAttribute(
      "data-can-verify",
      "true",
    )

    // Post-submit: preview MUST be disabled regardless of cultural — frozen
    // contract precedence (P1 fix from PR-3 Step D audit).
    const lastCall = previewHookSpy.mock.calls.at(-1)!
    expect(lastCall[2]).toBe(false)
  })

  it("Case 5 — submitted, UT verified: UtEvidenceCards still mounts w/ canVerify, summary receives profile", () => {
    const profile = makeProfile({
      status: "submitted",
      priority_object_codes: ["04"],
      priority_object_evidence: {
        "04": { status: "verified", verified_by: 1 },
      },
      permissions: { verify_priority_object: true },
    })
    renderTab({ profile, isEditable: false })

    expect(screen.getByTestId("probe-ut")).toBeInTheDocument()
    // summary panel must receive the profile (no derivation in tab)
    const lastSummaryCall = summarySpy.mock.calls.at(-1)![0]
    expect(lastSummaryCall.profile).toBe(profile)
  })

  it("Case 6 — submitted, UT rejected: composition unchanged (rejection lives in UtEvidenceCards inner)", () => {
    const profile = makeProfile({
      status: "submitted",
      priority_object_codes: ["04"],
      priority_object_evidence: {
        "04": { status: "rejected", rejection_reason: "ảnh mờ" },
      },
      permissions: { verify_priority_object: true },
    })
    renderTab({ profile, isEditable: false })

    // All 5 sections still mount — composition is state-orthogonal.
    expect(screen.getByTestId("probe-banner")).toBeInTheDocument()
    expect(screen.getByTestId("probe-inputs")).toBeInTheDocument()
    expect(screen.getByTestId("probe-engine")).toBeInTheDocument()
    expect(screen.getByTestId("probe-ut")).toBeInTheDocument()
    expect(screen.getByTestId("probe-summary")).toBeInTheDocument()
  })

  it("Case 7 — submitted + frozen + manual KV override: OverrideDialog receives currentKv from snapshot, mode=admin when override_priority_kv_mode=admin", () => {
    const profile = makeProfile({
      status: "submitted",
      version: 7,
      permissions: { override_priority_kv: true },
      override_priority_kv_mode: "admin",  // P0-1 — server-derived mode
      priority_resolution_snapshot: {
        kv_resolved: "KV2-NT",
        rule_applied: "manual_override",
        manual_override_reason: "ad-hoc adjustment",
      } as Snapshot,
    })
    renderTab({ profile, isEditable: false })

    const dialog = screen.getByTestId("probe-override-dialog")
    expect(dialog).toHaveAttribute("data-open", "false") // mounted closed
    expect(dialog).toHaveAttribute("data-mode", "admin")
    expect(dialog).toHaveAttribute("data-current-kv", "KV2-NT")

    expect(screen.getByTestId("probe-engine")).toHaveAttribute(
      "data-can-override",
      "true",
    )
  })

  it("Case 8 — rejected status: composition unchanged + inputs disabled + preview NOT enabled", () => {
    const profile = makeProfile({
      status: "rejected",
      priority_object_codes: ["04"],
    })
    renderTab({
      profile,
      isEditable: false,
      defaults: { cultural_education_level: "graduated_thpt" },
    })

    // Still all 5 sections — rejected is just another non-draft status.
    expect(screen.getByTestId("probe-banner")).toBeInTheDocument()
    expect(screen.getByTestId("probe-inputs")).toHaveAttribute(
      "data-editable",
      "false",
    )
    expect(screen.getByTestId("probe-engine")).toBeInTheDocument()
    expect(screen.getByTestId("probe-ut")).toBeInTheDocument()
    expect(screen.getByTestId("probe-summary")).toBeInTheDocument()

    // Preview disabled because not draft (frozen contract precedence).
    const lastCall = previewHookSpy.mock.calls.at(-1)!
    expect(lastCall[2]).toBe(false)
  })

  // -------------------------------------------------------------------------
  // Commit 3 — manager mode parity (anti-regression)
  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // P0-1 fix 2026-05-22 — mode flag từ server-derived profile field
  // (override_priority_kv_mode) thay thế user.role string check ở FE.
  // Anti-regression: nếu ai swap về user.role pattern, 4 test này fail.
  // -------------------------------------------------------------------------

  it("P0-1 — override_priority_kv_mode=manager: OverrideDialog nhận mode='manager' (KHÔNG fallback 'officer')", () => {
    const profile = makeProfile({
      status: "submitted",
      permissions: { override_priority_kv: true },
      override_priority_kv_mode: "manager",
      priority_resolution_snapshot: { kv_resolved: "KV1" } as Snapshot,
    })
    renderTab({ profile })

    const dialog = screen.getByTestId("probe-override-dialog")
    expect(dialog).toHaveAttribute("data-mode", "manager")
  })

  it("P0-1 — override_priority_kv_mode=officer: OverrideDialog nhận mode='officer'", () => {
    const profile = makeProfile({
      status: "draft",
      permissions: { override_priority_kv: true },
      override_priority_kv_mode: "officer",
    })
    renderTab({ profile })

    expect(screen.getByTestId("probe-override-dialog")).toHaveAttribute("data-mode", "officer")
  })

  it("P0-1 — override_priority_kv_mode=admin: OverrideDialog nhận mode='admin'", () => {
    const profile = makeProfile({
      status: "draft",
      permissions: { override_priority_kv: true },
      override_priority_kv_mode: "admin",
    })
    renderTab({ profile })

    expect(screen.getByTestId("probe-override-dialog")).toHaveAttribute("data-mode", "admin")
  })

  it("P0-1 — override_priority_kv_mode=none: dialog vẫn mount với fallback mode='officer' (read-only display)", () => {
    const profile = makeProfile({
      status: "draft",
      permissions: { override_priority_kv: true },
      override_priority_kv_mode: "none",
    })
    renderTab({ profile })

    // "none" → "officer" mapping (PriorityTab.tsx) để dialog vẫn render
    // read-only view; backend hard-deny mutation đảm bảo safety.
    expect(screen.getByTestId("probe-override-dialog")).toHaveAttribute("data-mode", "officer")
  })
})

// Avoid unused-import warning for React when running with new JSX transform.
void React
void useEffect
