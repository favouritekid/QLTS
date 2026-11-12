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

import { THAM_SO_TRONG, type ThamSoNhap } from "@/lib/council-params"

interface CouncilSelectionState {
  /** năm học của lần dựng (bắt buộc trước khi chọn); `null` = chưa chọn */
  namHoc: number | null
  /** id hồ sơ (số nội bộ) theo thứ tự người dùng thêm; KHÔNG trùng. Máy chủ sắp lại thứ tự khi kiểm trước. */
  idHoSo: number[]
  thamSo: ThamSoNhap

  /** Đổi năm ⇒ xoá danh sách chọn (giao diện đã hỏi xác nhận trước khi gọi). */
  datNamHoc: (nam: number | null) => void
  /** Thêm id (bỏ trùng, giữ thứ tự thêm). */
  them: (ids: readonly number[]) => void
  bo: (id: number) => void
  boTatCa: () => void
  datThamSo: (patch: Partial<ThamSoNhap>) => void
  /** Ghi đè cả năm học lẫn danh sách (từ nút ở màn "Hồ sơ tuyển sinh"). Tham số giữ nguyên. */
  thayThe: (nam: number, ids: readonly number[]) => void
  /** Xoá hết (sau khi dựng xong, hoặc rời luồng). */
  lamSach: () => void
}

function boTrung(ids: readonly number[]): number[] {
  return Array.from(new Set(ids))
}

export const useCouncilSelectionStore = create<CouncilSelectionState>()((set) => ({
  namHoc: null,
  idHoSo: [],
  thamSo: THAM_SO_TRONG,

  datNamHoc: (nam) => set({ namHoc: nam, idHoSo: [] }),
  them: (ids) => set((s) => ({ idHoSo: boTrung([...s.idHoSo, ...ids]) })),
  bo: (id) => set((s) => ({ idHoSo: s.idHoSo.filter((x) => x !== id) })),
  boTatCa: () => set({ idHoSo: [] }),
  datThamSo: (patch) => set((s) => ({ thamSo: { ...s.thamSo, ...patch } })),
  thayThe: (nam, ids) => set({ namHoc: nam, idHoSo: boTrung(ids) }),
  lamSach: () => set({ namHoc: null, idHoSo: [], thamSo: THAM_SO_TRONG }),
}))
