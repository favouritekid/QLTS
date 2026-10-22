/**
 * V3 — Đổi thông tư áp dụng của hồ sơ (manager/admin).
 *
 * Wraps `POST /api/v2/admissions/{profile_id}/applicable-circular`. Backend
 * (`applicable_circular_service`) giữ toàn bộ luật: version (409), vai trò +
 * trạng thái theo đúng ma trận ấn định KV (403/400), lý do 20–500, xác nhận
 * sau công bố (chỉ admin). FE chỉ hiện nút theo
 * `profile.permissions.change_applicable_circular`.
 *
 * Response: full `AdmissionProfileResponse` (router chạy
 * `_populate_response_fields` sau commit).
 */
import { api } from "@/lib/api/client"
import type {
  AdmissionProfileResponse,
  ApplicableCircularChangeRequest,
} from "@/lib/zod/admissions"

export const applicableCircularApi = {
  async change(
    profileId: number,
    body: ApplicableCircularChangeRequest,
  ): Promise<AdmissionProfileResponse> {
    const { data } = await api.post<AdmissionProfileResponse>(
      `/api/v2/admissions/${profileId}/applicable-circular`,
      body,
    )
    return data
  },
}
