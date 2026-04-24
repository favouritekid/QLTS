import type { LeadListParams } from "@/types/lead.types";

type SearchParamsRecord = Record<string, string | string[] | undefined>;

// =============================================================================
// SHARED CONSTANTS (SSR + client parity)
// =============================================================================

export const LEADS_DEFAULT_PAGE_SIZE = 50;
export const LEADS_DEFAULT_SORT_BY: NonNullable<LeadListParams["sort_by"]> = "created_at";
export const LEADS_DEFAULT_SORT_ORDER: NonNullable<LeadListParams["order"]> = "desc";

// =============================================================================
// SHARED DATE FORMATTERS
// =============================================================================

/**
 * Convert a YYYY-MM-DD date string to the lead API's `date_from` bound.
 * Uses fixed `+07:00` offset (Vietnam timezone) so the string is identical
 * on both the SSR parser and the client hook — prevents React Query from
 * treating semantically-equivalent timestamps as different query keys.
 */
export function formatLeadsDateFromApiParam(yyyyMmDd: string): string {
  return `${yyyyMmDd}T00:00:00+07:00`;
}

/**
 * Convert a YYYY-MM-DD date string to the lead API's `date_to` bound.
 * Returns end-of-day in VN timezone (same fixed offset as `_from`).
 */
export function formatLeadsDateToApiParam(yyyyMmDd: string): string {
  return `${yyyyMmDd}T23:59:59.999+07:00`;
}

// =============================================================================
// SSR PARSER — App Router searchParams -> LeadListParams
// =============================================================================

/**
 * Parse App Router searchParams into LeadListParams for the SSR fetch.
 * Keep this in sync with useLeadsFilter's URL -> apiFilters mapping.
 */
export function parseSearchParamsToApiParams(
  searchParams: SearchParamsRecord,
): LeadListParams {
  const get = (key: string): string | undefined => {
    const value = searchParams[key];
    return typeof value === "string" ? value : Array.isArray(value) ? value[0] : undefined;
  };

  const params: LeadListParams = {
    page: parseInt(get("page") || "1", 10),
    page_size: LEADS_DEFAULT_PAGE_SIZE,
    sort_by: (get("sort_by") as LeadListParams["sort_by"]) || LEADS_DEFAULT_SORT_BY,
    order: (get("order") as LeadListParams["order"]) || LEADS_DEFAULT_SORT_ORDER,
  };

  if (get("status")) params.status = get("status");
  if (get("officer")) params.assigned_officer_id = get("officer");
  if (get("unit_id")) params.unit_id = parseInt(get("unit_id")!, 10);
  if (get("offering")) params.offering_id = get("offering");
  if (get("source")) params.source = get("source");
  if (get("q")) params.search = get("q");
  if (get("stage")) params.pipeline_stage_id = get("stage");
  if (get("from")) params.date_from = formatLeadsDateFromApiParam(get("from")!);
  if (get("to")) params.date_to = formatLeadsDateToApiParam(get("to")!);
  if (get("date_field")) {
    params.date_field = get("date_field") as LeadListParams["date_field"];
  }
  if (get("score_min")) params.score_min = parseInt(get("score_min")!, 10);
  if (get("score_max")) params.score_max = parseInt(get("score_max")!, 10);
  if (get("validity")) params.validity_status = get("validity");

  if (get("nav_source")) params.nav_source = get("nav_source");
  if (get("scope")) {
    params.scope = get("scope") === "team" ? "unit" : (get("scope") as LeadListParams["scope"]);
  }
  if (get("scope_officer_id")) params.scope_officer_id = parseInt(get("scope_officer_id")!, 10);
  if (get("scope_unit_id")) params.scope_unit_id = parseInt(get("scope_unit_id")!, 10);
  if (get("include_descendants") === "1" || get("include_descendants") === "true") {
    params.include_descendants = true;
  }
  if (get("loss_reason")) params.loss_reason = get("loss_reason");

  if (get("is_final") === "true") params.is_final = true;
  else if (get("is_final") === "false") params.is_final = false;

  if (get("counts_for_funnel") === "true") params.counts_for_funnel = true;
  else if (get("counts_for_funnel") === "false") params.counts_for_funnel = false;

  return params;
}

// =============================================================================
// SSR vs CLIENT QUERY EQUALITY
// =============================================================================

/**
 * Keys that `parseSearchParamsToApiParams` and `useLeadsFilter.apiFilters`
 * are expected to produce in parity. Kept as a tuple to keep the equality
 * check explicit — add a new field here whenever the shared shape grows.
 */
const LEADS_LIST_PARAM_KEYS = [
  "page",
  "page_size",
  "sort_by",
  "order",
  "status",
  "source",
  "validity_status",
  "offering_id",
  "pipeline_stage_id",
  "assigned_officer_id",
  "unit_id",
  "search",
  "date_from",
  "date_to",
  "date_field",
  "score_min",
  "score_max",
  "nav_source",
  "scope",
  "scope_officer_id",
  "scope_unit_id",
  "include_descendants",
  "loss_reason",
  "is_final",
  "counts_for_funnel",
] as const satisfies readonly (keyof LeadListParams)[];

function normalizeValue(value: unknown): unknown {
  // Explicit undefined and missing key should collapse to the same bucket so
  // `{ search: undefined }` equals `{}`. React Query treats them as different
  // otherwise, which defeats the guard.
  if (value === undefined || value === null || value === "") return undefined;
  return value;
}

/**
 * Returns true when the caller's apiFilters shape matches the SSR
 * prefetch query shape — used as the React Query `initialData` attach
 * guard. Any drift (filters from localStorage, user edits, dashboard
 * context, etc.) short-circuits initialData and forces a fresh fetch.
 */
export function areLeadsListParamsEqual(
  a: LeadListParams | Record<string, unknown> | undefined,
  b: LeadListParams | Record<string, unknown> | undefined,
): boolean {
  if (!a || !b) return !a && !b;
  for (const key of LEADS_LIST_PARAM_KEYS) {
    const av = normalizeValue((a as Record<string, unknown>)[key]);
    const bv = normalizeValue((b as Record<string, unknown>)[key]);
    if (av !== bv) return false;
  }
  return true;
}
