export type PublicAdmissionsSearchParams = Promise<Record<string, string | string[] | undefined>>

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value
}

export function publicAdmissionsCatalogParams(
  searchParams: Record<string, string | string[] | undefined>,
): { admission_round_id?: number; audience?: string } | undefined {
  const rawRound = firstValue(searchParams.admission_round_id) ?? firstValue(searchParams.round)
  const roundId = rawRound ? Number.parseInt(rawRound, 10) : undefined
  const audience = firstValue(searchParams.audience)

  const params: { admission_round_id?: number; audience?: string } = {}
  if (roundId !== undefined && Number.isInteger(roundId) && roundId > 0) {
    params.admission_round_id = roundId
  }
  if (audience) {
    params.audience = audience
  }

  return Object.keys(params).length > 0 ? params : undefined
}
