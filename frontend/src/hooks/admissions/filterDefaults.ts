import type { AdmissionListParams } from "@/lib/zod/admissions"

export type AdmissionsSearchParamsRecord = Record<string, string | string[] | undefined>

export const ADMISSIONS_DEFAULT_PAGE_SIZE = 20
export const ADMISSIONS_DEFAULT_SORT_BY: NonNullable<AdmissionListParams["sort_by"]> = "created_at"
export const ADMISSIONS_DEFAULT_SORT_ORDER: NonNullable<AdmissionListParams["order"]> = "desc"
export const CURRENT_ADMISSIONS_YEAR = new Date().getFullYear()

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
