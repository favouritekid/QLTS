// src/lib/stores/council-selection.store.ts
/**
 * Lựa chọn hồ sơ + sáu tham số để dựng văn bản Hội đồng — CHỈ Ở BỘ NHỚ TRANG.
 *
 * ⚠️ KHÔNG `persist`, không storage, không URL (đặc tả 5, luật chung): danh sách chọn là tập id hồ sơ nội bộ nhưng đi
 * cùng bảng có tên / CCCD; tải lại trang ⇒ mất (trang `moi` có cảnh báo `beforeunload` khi đang có danh sách). Test
 * tĩnh `khong-luu-ma.static.test.ts` quét tệp này.
 *
 * ⚠️ RIÊNG của trang Hội đồng — KHÔNG dùng chung với lựa chọn (`rowSelection`) của màn "Hồ sơ tuyển sinh": màn đó cố ý
 * xoá lựa chọn khi đổi trang / bộ lọc (`AdmissionsClient.tsx`) để Duyệt / Từ chối hàng loạt không chạm hồ sơ không nhìn
 * thấy. Màn đó chỉ ĐẨY id sang đây qua `thayThe` khi bấm "Dựng văn bản Hội đồng".
 *
 * Store chỉ giữ dữ liệu người dùng đã chọn; không tính gì. Số liệu kiểm trước, thứ tự, mức chặn do MÁY CHỦ trả.
 */
import { create } from "zustand"

import { EMPTY_PARAMS, type InputParams } from "@/lib/council-params"

interface CouncilSelectionState {
  /** năm học của lần dựng (bắt buộc trước khi chọn); `null` = chưa chọn */
  academicYear: number | null
  /** id hồ sơ (số nội bộ) theo thứ tự người dùng thêm; KHÔNG trùng. Máy chủ sắp lại thứ tự khi kiểm trước. */
  profileId: number[]
  params: InputParams

  /** Đổi năm ⇒ xoá danh sách chọn (giao diện đã hỏi xác nhận trước khi gọi). */
  setAcademicYear: (year: number | null) => void
  /** Thêm id (bỏ trùng, giữ thứ tự thêm). */
  add: (ids: readonly number[]) => void
  docSet: (id: number) => void
  clearAll: () => void
  setParams: (patch: Partial<InputParams>) => void
  /** Ghi đè cả năm học lẫn danh sách (từ nút ở màn "Hồ sơ tuyển sinh"). Tham số giữ nguyên. */
  replace: (year: number, ids: readonly number[]) => void
  /** Xoá hết (sau khi dựng xong, hoặc rời luồng). */
  reset: () => void
}

function dedupe(ids: readonly number[]): number[] {
  return Array.from(new Set(ids))
}

export const useCouncilSelectionStore = create<CouncilSelectionState>()((set) => ({
  academicYear: null,
  profileId: [],
  params: EMPTY_PARAMS,

  setAcademicYear: (year) => set({ academicYear: year, profileId: [] }),
  add: (ids) => set((s) => ({ profileId: dedupe([...s.profileId, ...ids]) })),
  docSet: (id) => set((s) => ({ profileId: s.profileId.filter((x) => x !== id) })),
  clearAll: () => set({ profileId: [] }),
  setParams: (patch) => set((s) => ({ params: { ...s.params, ...patch } })),
  replace: (year, ids) => set({ academicYear: year, profileId: dedupe(ids) }),
  reset: () => set({ academicYear: null, profileId: [], params: EMPTY_PARAMS }),
}))
