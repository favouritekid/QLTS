import type { LeadListParams } from "@/types/lead.types";

type SearchParamsRecord = Record<string, string | string[] | undefined>;

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
    page_size: 50,
    sort_by: get("sort_by") || "created_at",
    order: (get("order") as LeadListParams["order"]) || "desc",
  };

  if (get("status")) params.status = get("status");
  if (get("officer")) params.assigned_officer_id = get("officer");
  if (get("unit_id")) params.unit_id = parseInt(get("unit_id")!, 10);
  if (get("offering")) params.offering_id = get("offering");
  if (get("source")) params.source = get("source");
  if (get("q")) params.search = get("q");
  if (get("stage")) params.pipeline_stage_id = get("stage");
  if (get("from")) params.date_from = `${get("from")}T00:00:00+07:00`;
  if (get("to")) params.date_to = `${get("to")}T23:59:59.999+07:00`;
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
