/**
 * Bulk clone admission paths Q6 deep-copy (Phase 2 v8.2 PR-2D BE).
 *
 * Endpoint: POST /api/v2/admin/rounds/{target_round_id}/clone-paths-from/{source_round_id}
 * BE schema source: app/schemas/path_subject_group.py:78-111.
 */

import { api } from "./client"

export interface ClonePathsRequest {
  /** Filter — clone chỉ paths thuộc các academic_info này. NULL = clone all. */
  academic_info_ids?: number[] | null
  /** Template cho cloned criteria.code, e.g. "{source_code}_{round_code}". NULL = auto fallback. */
  criteria_code_template?: string | null
}

export interface ClonePathsResponseItem {
  source_path_id: number
  cloned_path_id: number
  source_criteria_code: string
  cloned_criteria_code: string
}

export interface ClonePathsResponse {
  source_round_id: number
  target_round_id: number
  cloned_count: number
  /** Paths skipped (already exist trong target round per 3-col UNIQUE). */
  skipped_count: number
  items: ClonePathsResponseItem[]
}

export async function clonePathsFromRound(
  targetRoundId: number,
  sourceRoundId: number,
  payload: ClonePathsRequest,
): Promise<ClonePathsResponse> {
  const response = await api.post<ClonePathsResponse>(
    `/api/v2/admin/rounds/${targetRoundId}/clone-paths-from/${sourceRoundId}`,
    payload,
  )
  return response.data
}
