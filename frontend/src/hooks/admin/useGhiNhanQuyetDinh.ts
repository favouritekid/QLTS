/**
 * Văn bản Hội đồng — bộ điều khiển bước 6 "Ghi nhận" (đặc tả 5.6 + bản 2 mục 3.7.5, 5.6.1).
 *
 * Bất biến (test `useGhiNhanQuyetDinh.test.tsx` khoá từng điều):
 *   • Lượt gửi được mở NGAY trước khi gửi, không mở khi vào bước 6 (vào rồi bỏ đi sẽ để lại lượt treo).
 *   • Mã lượt CHỈ nằm trong bộ nhớ (`useRef`) — không storage, không URL, không log. Tải lại trang ⇒ lấy lại qua
 *     `GET /sets/{id}/luot-ghi-nhan` (`khoiPhuc`).
 *   • Bị từ chối dứt khoát (4xx đã định) ⇒ mở khoá biểu mẫu, gửi lại CÙNG mã (lượt vẫn `cho_gui`).
 *   • Mất mạng / hết giờ / 5xx / 404 / 2xx không đọc được ⇒ "Chưa xác định". KHÔNG bao giờ suy "chưa ghi", và KHÔNG
 *     có đường "gửi lại" từ trạng thái này — chỉ có "Kiểm tra trên máy chủ" (phân xử).
 *   • Phân xử cũng có thể mất phản hồi, hoặc bị đóng băng tuyển sinh chặn (503) ⇒ vẫn "Chưa xác định" (gọi lại được: máy chủ
 *     luỹ đẳng) — không bao giờ suy "chưa ghi".
 *   • Mã của lượt đã `da_ghi` chỉ bị bỏ SAU KHI máy chủ xác nhận huỷ ghi nhận (`batDauLuotMoiSauHuy`); lỗi nghiệp vụ khi gửi
 *     KHÔNG bỏ mã (lượt vẫn `cho_gui`) — F276.
 *   • Chống bấm đúp bằng cờ đồng bộ (không chờ React render).
 *
 * ⚠️ KHÔNG dùng `useMutation`: biến số (scan, số hồ sơ gõ lại, ghi chú) không được nằm trong MutationCache.
 */
import { useCallback, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import {
  createCouncilDecision,
  councilErrorCode,
  listCouncilSubmissions,
  openCouncilSubmission,
  resolveCouncilSubmission,
  type CreateCouncilDecisionInput,
} from "@/lib/api/council-documents"
import {
  giaiNghiaPhanXu,
  huongXuLyLoiGui,
  luotDangCho,
  phanLoaiLoiGui,
  type HuongXuLyLoiGui,
} from "@/lib/council-submission"
import { readApiError } from "@/lib/error-handler"
import type { CouncilDecisionWrite, CouncilSubmission } from "@/lib/zod/council-documents"

import { councilDocumentKeys } from "./useCouncilDocuments"

/** Vì sao đang "chưa xác định" — chỉ để chọn câu hướng dẫn, không đổi nghĩa. */
export type LyDoChuaRo =
  | "gui" // mất phản hồi / lỗi lúc gửi
  | "mo_luot" // đã có lượt `cho_gui` (mở trùng, hoặc mất phản hồi lúc mở)
  | "tai_lai_trang" // khôi phục từ `GET /sets/{id}/luot-ghi-nhan`
  | "dang_xu_ly" // phân xử: giao dịch ghi còn giữ lượt
  | "phan_xu_loi" // phân xử mất phản hồi
  | "dong_bang" // phân xử bị đóng băng tuyển sinh chặn (503 ADMISSION_FROZEN): vẫn chưa rõ, đợi hết đóng băng
  | "van_chua_ro" // phân xử trả `ket_qua` lạ

export type TrangThaiGhiNhan =
  | { kieu: "nhap" }
  | { kieu: "dang_gui" }
  /** máy chủ TỪ CHỐI dứt khoát; `huong` cho biết bước tiếp theo hợp lệ */
  | { kieu: "bi_tu_choi"; loi: unknown; huong: HuongXuLyLoiGui }
  /** không mở được lượt — CHƯA gửi gì, thử lại an toàn */
  | { kieu: "loi_mo_luot"; loi: unknown }
  /** bộ không còn (404 khi mở lượt) */
  | { kieu: "bo_khong_con" }
  | { kieu: "chua_xac_dinh"; ma: string; luc: string; lyDo: LyDoChuaRo }
  | { kieu: "dang_phan_xu"; ma: string; luc: string }
  /** `quyetDinh` null = máy chủ báo ĐÃ ghi mà không kèm chi tiết */
  | { kieu: "da_ghi"; quyetDinh: CouncilDecisionWrite | null }
  /** lượt đã bị chặn: chắc chắn CHƯA có văn bản */
  | { kieu: "chua_ghi_da_chan" }

export type DuLieuGuiGhiNhan = Omit<CreateCouncilDecisionInput, "set_id" | "ma_luot_gui">

type KetQuaMoLuot =
  | { kieu: "ok"; ma: string }
  | { kieu: "chua_xac_dinh"; ma: string }
  | { kieu: "bo_khong_con" }
  | { kieu: "loi"; loi: unknown }

export function useGhiNhanQuyetDinh(setId: number) {
  const qc = useQueryClient()
  const [trangThai, setTrangThai] = useState<TrangThaiGhiNhan>({ kieu: "nhap" })
  const maRef = useRef<string | null>(null)
  const dangChay = useRef(false)

  const lamMoiSauGhi = useCallback(() => {
    void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    void qc.invalidateQueries({ queryKey: councilDocumentKeys.decisions() })
  }, [qc])

  const moLuot = useCallback(async (): Promise<KetQuaMoLuot> => {
    try {
      const r = await openCouncilSubmission(setId)
      return { kieu: "ok", ma: r.ma }
    } catch (loi) {
      const c = councilErrorCode(loi)
      const status = readApiError(loi).status
      if (status === 409 && c.maLoi === "luot_dang_cho" && c.ma) return { kieu: "chua_xac_dinh", ma: c.ma }
      if (status === 404) return { kieu: "bo_khong_con" }
      // `luot_dang_thay_doi` hoặc mất phản hồi / 5xx lúc mở: lượt có thể ĐÃ được tạo mà ta chưa biết mã ⇒ đọc lại.
      try {
        const cho = luotDangCho(await listCouncilSubmissions(setId))
        if (cho) return { kieu: "chua_xac_dinh", ma: cho.ma }
      } catch {
        /* không đọc lại được: CHƯA gửi gì, báo lỗi mở lượt (thử lại an toàn) */
      }
      return { kieu: "loi", loi }
    }
  }, [setId])

  const gui = useCallback(
    async (du_lieu: DuLieuGuiGhiNhan) => {
      if (dangChay.current) return
      dangChay.current = true
      setTrangThai({ kieu: "dang_gui" })
      try {
        let ma = maRef.current
        if (ma === null) {
          const r = await moLuot()
          if (r.kieu === "chua_xac_dinh") {
            maRef.current = r.ma
            setTrangThai({ kieu: "chua_xac_dinh", ma: r.ma, luc: new Date().toISOString(), lyDo: "mo_luot" })
            return
          }
          if (r.kieu === "bo_khong_con") {
            setTrangThai({ kieu: "bo_khong_con" })
            return
          }
          if (r.kieu === "loi") {
            setTrangThai({ kieu: "loi_mo_luot", loi: r.loi })
            return
          }
          ma = r.ma
          maRef.current = ma
        }
        try {
          const qd = await createCouncilDecision({ ...du_lieu, set_id: setId, ma_luot_gui: ma })
          setTrangThai({ kieu: "da_ghi", quyetDinh: qd })
          lamMoiSauGhi()
        } catch (loi) {
          if (phanLoaiLoiGui(loi) === "bi_tu_choi") {
            const huong = huongXuLyLoiGui(loi)
            if (huong === "mo_luot_moi") maRef.current = null
            setTrangThai({ kieu: "bi_tu_choi", loi, huong })
          } else {
            setTrangThai({ kieu: "chua_xac_dinh", ma, luc: new Date().toISOString(), lyDo: "gui" })
          }
        }
      } finally {
        dangChay.current = false
      }
    },
    [moLuot, setId, lamMoiSauGhi],
  )

  const phanXu = useCallback(async () => {
    const ma = maRef.current
    if (ma === null || dangChay.current) return
    dangChay.current = true
    const luc = new Date().toISOString()
    setTrangThai({ kieu: "dang_phan_xu", ma, luc })
    try {
      const kq = giaiNghiaPhanXu(await resolveCouncilSubmission(ma))
      switch (kq.kieu) {
        case "da_ghi":
          setTrangThai({ kieu: "da_ghi", quyetDinh: kq.quyetDinh })
          lamMoiSauGhi()
          break
        case "da_ghi_thieu_chi_tiet":
          setTrangThai({ kieu: "da_ghi", quyetDinh: null })
          lamMoiSauGhi()
          break
        case "chua_ghi_da_chan":
          maRef.current = null
          setTrangThai({ kieu: "chua_ghi_da_chan" })
          break
        case "dang_xu_ly":
          setTrangThai({ kieu: "chua_xac_dinh", ma, luc, lyDo: "dang_xu_ly" })
          break
        default:
          setTrangThai({ kieu: "chua_xac_dinh", ma, luc, lyDo: "van_chua_ro" })
      }
    } catch (loi) {
      // mất mạng / hết giờ / 404 / 5xx / phản hồi không đọc được: KHÔNG kết luận gì. Đóng băng tuyển sinh (503 ADMISSION_FROZEN)
      // chặn CẢ việc phân xử: máy chủ vẫn trả lời nên không phải "mất mạng" — nói riêng để người dùng biết đợi hết đóng băng.
      setTrangThai({ kieu: "chua_xac_dinh", ma, luc, lyDo: readApiError(loi).frozen ? "dong_bang" : "phan_xu_loi" })
    } finally {
      dangChay.current = false
    }
  }, [lamMoiSauGhi])

  /** Tải lại trang: thấy lượt `cho_gui` ⇒ vào thẳng "Chưa xác định" (chỉ khi đang ở `nhap`). */
  const khoiPhuc = useCallback((ds: readonly CouncilSubmission[]) => {
    const cho = luotDangCho(ds)
    if (!cho) return
    setTrangThai((cu) => {
      if (cu.kieu !== "nhap") return cu
      maRef.current = cho.ma
      return { kieu: "chua_xac_dinh", ma: cho.ma, luc: cho.tao_luc, lyDo: "tai_lai_trang" }
    })
  }, [])

  /**
   * Về biểu mẫu sau khi lượt đã bị CHẶN (`chua_ghi_da_chan`, mã đã bỏ lúc phân xử). CHỈ đổi trạng thái: KHÔNG đụng mã, nên
   * KHÔNG dùng sau khi huỷ ghi nhận (xem `batDauLuotMoiSauHuy`).
   */
  const veBieuMau = useCallback(() => setTrangThai({ kieu: "nhap" }), [])

  /**
   * Gọi CHỈ SAU KHI máy chủ đã xác nhận huỷ ghi nhận văn bản của lượt này (`CouncilCancelDialog.onXong`: huỷ thành công, hoặc
   * đọc lại thấy văn bản đã huỷ). Lượt cũ đã `da_ghi` — mã của nó đã "dùng hết": gửi lại cùng mã thì máy chủ (luỹ đẳng) trả lại
   * đúng văn bản ĐÃ HUỶ, khác nội dung thì 409 (F276). Bỏ mã cũ để lần gửi kế tiếp mở lượt MỚI, và về biểu mẫu.
   *
   * KHÔNG mở lượt ngay ở đây (lượt chỉ mở NGAY trước khi gửi — vào bước rồi bỏ đi sẽ để lại lượt treo). KHÔNG gọi khi huỷ
   * chưa được xác nhận, và KHÔNG gọi ở nhánh lỗi nghiệp vụ khi gửi (lượt vẫn `cho_gui`, gửi lại CÙNG mã).
   */
  const batDauLuotMoiSauHuy = useCallback(() => {
    maRef.current = null
    setTrangThai({ kieu: "nhap" })
  }, [])

  return { trangThai, gui, phanXu, khoiPhuc, veBieuMau, batDauLuotMoiSauHuy }
}
