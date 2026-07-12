import type { AdmissionListParams } from "@/lib/zod/admissions"

export type AdmissionsSearchParamsRecord = Record<string, string | string[] | undefined>

/**
 * Status tabs for the admissions list — the SINGLE source for both the tab UI
 * (AdmissionsClient renders `label`) and the tab→status filter mapping
 * (useAdmissionsFilter.handleTabClick reads `statuses`). Keeping ONE constant
 * prevents the drift that previously broke the "Đã xác nhận" filter (the hook's
 * copy lacked a `confirmed` tab → handleTabClick("confirmed") set an empty filter
 * → showed ALL profiles) and made the "Đã duyệt" count disagree with its result
 * (the hook folded `confirmed` into `approved` while the UI counted it separately).
 *
 * 14-state grouping (phase1_11 #184): pending = submitted/resubmitted/reviewing/
 * revision_requested; approved = approved/admitted/overridden (admin-driven,
 * awaiting enroll); confirmed has its OWN tab (applicant tapped the magic link);
 * waitlisted its own; rejected = rejected/withdrawn. `result_published` is in no
 * tab (broadcast marker, reachable only via "Tất cả" / the status drop-down).
 */
export const ADMISSION_STATUS_TABS: ReadonlyArray<{
  key: string
  label: string
  statuses: readonly string[]
}> = [
  { key: "all", label: "Tất cả", statuses: [] },
  { key: "draft", label: "Nháp", statuses: ["draft"] },
  {
    key: "pending",
    label: "Chờ duyệt",
    statuses: ["submitted", "resubmitted", "reviewing", "revision_requested"],
  },
  { key: "approved", label: "Đã duyệt", statuses: ["approved", "admitted", "overridden"] },
  { key: "waitlisted", label: "Chờ ghế", statuses: ["waitlisted"] },
  { key: "confirmed", label: "Đã xác nhận", statuses: ["confirmed"] },
  { key: "enrolled", label: "Đã nhập học", statuses: ["enrolled"] },
  { key: "rejected", label: "Từ chối", statuses: ["rejected", "withdrawn", "withdrawal_pending"] },
]

export const ADMISSIONS_DEFAULT_PAGE_SIZE = 20
export const ADMISSIONS_DEFAULT_SORT_BY: NonNullable<AdmissionListParams["sort_by"]> = "created_at"
export const ADMISSIONS_DEFAULT_SORT_ORDER: NonNullable<AdmissionListParams["order"]> = "desc"
export const CURRENT_ADMISSIONS_YEAR = new Date().getFullYear()

/**
 * Postgres int4 upper bound. `unit_id` / officer / reviewer ids are compared
 * against int4 columns; SQLAlchemy binds the value with the COLUMN's type, so a
 * value beyond int4 makes asyncpg raise "integer out of range" → 500 (the #437
 * incident class the backend `_parse_id_csv` guards). A plain `Number.isFinite`
 * check passes 99999999999, so any int forwarded to the wire must clamp here.
 */
export const ADMISSIONS_INT4_MAX = 2147483647

const ADMISSIONS_LIST_PARAM_KEYS = [
  "page",
  "page_size",
  "status",
  "search",
  "major_id",
  "academic_year",
  "degree_level",
  "payment_status",
  "date_from",
  "date_to",
  "sort_by",
  "order",
  // Coordination filters (Admission List v2) — MUST be here so the SSR/initialData
  // equality check detects them; else a ?officer=5 deep-link reuses unfiltered SSR.
  "assigned_officer_id",
  "unit_id",
  "assigned_reviewer_id",
  "unassigned",
] as const satisfies readonly (keyof AdmissionListParams)[]

function getFirstParam(
  searchParams: AdmissionsSearchParamsRecord,
  key: string,
): string | undefined {
  const value = searchParams[key]
  return typeof value === "string" ? value : Array.isArray(value) ? value[0] : undefined
}

function parseIntegerParam(value: string | undefined): number | undefined {
  if (!value) return undefined
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : undefined
}

/**
 * Parse a `unit_id` (URL/state string) → number, dropping anything outside the
 * int4 range. Unlike {@link parseIntegerParam}, an out-of-int4 value (e.g.
 * `?unit_id=99999999999`) is DROPPED rather than forwarded, so it never reaches
 * `Lead.unit_id == <huge>` and 500s the backend. Mirrors `_parse_id_csv`.
 */
export function parseUnitId(value: string | undefined): number | undefined {
  const parsed = parseIntegerParam(value)
  if (parsed === undefined) return undefined
  if (parsed < 1 || parsed > ADMISSIONS_INT4_MAX) return undefined
  return parsed
}

/** Coordination-filter state (officer / unit / reviewer / unassigned). */
export interface AdmissionsCoordinationState {
  officerFilters: string[]
  unitId: string
  reviewerFilters: string[]
  unassigned: boolean
}

export type AdmissionsCoordinationParams = Pick<
  AdmissionListParams,
  "assigned_officer_id" | "unit_id" | "assigned_reviewer_id" | "unassigned"
>

/**
 * Map coordination-filter state → wire params. SINGLE source shared by
 * `useAdmissionsFilter` (apiFilters + countFilters) and the CSV export, so the
 * three never drift — the exact class of SSR/list/count divergence this list
 * already had to patch. Encodes the two invariants once:
 *  - officer XOR unassigned: an active "unassigned" DROPS the officer-IN list
 *    (else `IS NULL AND IN(...)` = ∅, an always-empty result).
 *  - `unit_id` int4-guarded (see {@link parseUnitId}) so a huge value never 500s.
 */
export function buildCoordinationParams(
  state: AdmissionsCoordinationState,
): AdmissionsCoordinationParams {
  const params: AdmissionsCoordinationParams = {}
  if (state.officerFilters.length > 0 && !state.unassigned) {
    params.assigned_officer_id = state.officerFilters.join(",")
  }
  if (state.unassigned) params.unassigned = true
  const unitId = parseUnitId(state.unitId)
  if (unitId !== undefined) params.unit_id = unitId
  if (state.reviewerFilters.length > 0) {
    params.assigned_reviewer_id = state.reviewerFilters.join(",")
  }
  return params
}

export function getDefaultAdmissionsListParams(
  pageSize: number = ADMISSIONS_DEFAULT_PAGE_SIZE,
): AdmissionListParams {
  return {
    page: 1,
    page_size: pageSize,
    academic_year: CURRENT_ADMISSIONS_YEAR,
    sort_by: ADMISSIONS_DEFAULT_SORT_BY,
    order: ADMISSIONS_DEFAULT_SORT_ORDER,
  }
}

export function parseAdmissionsSearchParamsToApiParams(
  searchParams: AdmissionsSearchParamsRecord,
  pageSize: number = ADMISSIONS_DEFAULT_PAGE_SIZE,
): AdmissionListParams {
  const params = getDefaultAdmissionsListParams(pageSize)

  const page = parseIntegerParam(getFirstParam(searchParams, "page"))
  if (page !== undefined && page > 0) params.page = page

  const year = parseIntegerParam(getFirstParam(searchParams, "year"))
  if (year !== undefined) params.academic_year = year

  const status = getFirstParam(searchParams, "status")
  if (status) params.status = status

  const search = getFirstParam(searchParams, "q")
  if (search) params.search = search

  const major = getFirstParam(searchParams, "major")
  if (major) params.major_id = major

  const degree = getFirstParam(searchParams, "degree")
  if (degree) params.degree_level = degree

  const payment = getFirstParam(searchParams, "payment")
  if (payment) params.payment_status = payment

  const from = getFirstParam(searchParams, "from")
  if (from) params.date_from = from

  const to = getFirstParam(searchParams, "to")
  if (to) params.date_to = to

  // Coordination filters (Admission List v2) — URL keys mirror useAdmissionsFilter's
  // URL-write (officer / unit_id / reviewer / unassigned). Must match the client
  // apiFilters shape (assigned_officer_id / unit_id / assigned_reviewer_id /
  // unassigned) so areAdmissionsListParamsEqual sees the SSR + client as equal.
  // officer XOR unassigned (the hook never writes both), so no conflict here.
  const officer = getFirstParam(searchParams, "officer")
  if (officer) params.assigned_officer_id = officer

  // int4-guard: a deep-link ?unit_id=99999999999 must not reach the SSR list
  // fetch (→ Lead.unit_id == <huge> → asyncpg int4 overflow → SSR 500).
  const unitId = parseUnitId(getFirstParam(searchParams, "unit_id"))
  if (unitId !== undefined) params.unit_id = unitId

  const reviewer = getFirstParam(searchParams, "reviewer")
  if (reviewer) params.assigned_reviewer_id = reviewer

  const unassigned = getFirstParam(searchParams, "unassigned")
  if (unassigned === "1" || unassigned === "true") params.unassigned = true

  return params
}

export function normalizeAdmissionsListParams(
  params: AdmissionListParams = {},
): AdmissionListParams {
  return {
    ...getDefaultAdmissionsListParams(params.page_size),
    ...params,
  }
}

export function areAdmissionsListParamsEqual(
  a: AdmissionListParams | undefined,
  b: AdmissionListParams | undefined,
): boolean {
  const normalizedA = normalizeAdmissionsListParams(a)
  const normalizedB = normalizeAdmissionsListParams(b)

  return ADMISSIONS_LIST_PARAM_KEYS.every((key) => normalizedA[key] === normalizedB[key])
}
