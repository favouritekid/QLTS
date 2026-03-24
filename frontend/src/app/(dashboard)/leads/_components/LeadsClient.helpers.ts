import type { LeadListParams } from "@/types/lead.types";

export interface InitialDataGuardState {
  page: number;
  search: string;
  statusFilters: unknown[];
  offeringFilters: unknown[];
  sourceFilters: unknown[];
  validityFilters: unknown[];
  stageFilters: unknown[];
  officerFilters: unknown[];
  unitId: string;
  dateFrom: string;
  dateTo: string;
  scoreRange: [number, number];
  sortBy: string;
  sortOrder: string;
}

export function shouldUseInitialLeadsData(
  filterState: InitialDataGuardState,
  apiFilters: Pick<LeadListParams, "is_final" | "counts_for_funnel">,
): boolean {
  const hasUntrackedSnapshotFilter =
    apiFilters.is_final !== undefined || apiFilters.counts_for_funnel !== undefined;

  return (
    filterState.page === 1 &&
    !filterState.search &&
    filterState.statusFilters.length === 0 &&
    filterState.offeringFilters.length === 0 &&
    filterState.sourceFilters.length === 0 &&
    filterState.validityFilters.length === 0 &&
    filterState.stageFilters.length === 0 &&
    filterState.officerFilters.length === 0 &&
    !filterState.unitId &&
    !filterState.dateFrom &&
    !filterState.dateTo &&
    filterState.scoreRange[0] === 0 &&
    filterState.scoreRange[1] === 100 &&
    filterState.sortBy === "created_at" &&
    filterState.sortOrder === "desc" &&
    !hasUntrackedSnapshotFilter
  );
}
