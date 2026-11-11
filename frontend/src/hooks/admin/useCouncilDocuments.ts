/**
 * Văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1) — React Query hooks + view
 * model cờ quyền.
 *
 * Ẩn / hiện theo CỜ của máy chủ (`GET /quyen`), KHÔNG theo `user.role`
 * (FRONTEND_ARCHITECTURE_V3 §2.2). 403 ở route cờ (vai không có dòng Casbin)
 * ⇒ "không có quyền": mọi cờ tắt. Lỗi khác ⇒ trạng thái lỗi, cũng mọi cờ tắt
 * (fail-closed) — máy chủ vẫn là chốt chặn thật.
 *
 * ⚠️ DỮ LIỆU CÁ NHÂN (danh sách mã hồ sơ = CCCD):
 *   - query xem mã: `gcTime: 0`, `staleTime: 0`, không retry, không refetch
 *     khi focus ⇒ React Query gỡ khỏi cache ngay khi component dùng nó unmount
 *     (bấm "Ẩn" / rời trang);
 *   - mutation dựng bộ: `gcTime: 0` — biến số (thân yêu cầu có danh sách mã)
 *     không nằm lại trong MutationCache sau khi xong;
 *   - không persist (QueryClient của app không có persister — test khoá), không
 *     Zustand, không storage, không `console.*`, không URL.
 */
import { useMemo } from "react"
import axios from "axios"
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  cancelCouncilDecisionRecord,
  compareCouncilSet,
  createCouncilSet,
  createCouncilSetByIds,
  deleteCouncilSet,
  downloadCouncilSetFile,
  downloadCouncilSetZip,
  getCouncilDecision,
  getCouncilDocumentPermissions,
  getCouncilSet,
  getCouncilSetInputCodes,
  listCouncilDecisions,
  listCouncilDownloadLog,
  listCouncilSetDeletions,
  listCouncilSets,
  listCouncilSubmissions,
  listCouncilTemplates,
  previewCouncilSet,
  resolveCouncilCodes,
  searchCouncilProfiles,
  uploadCouncilTemplate,
  type CouncilDecisionListParams,
  type CouncilLogParams,
  type CouncilSetListParams,
  type UploadCouncilTemplateInput,
} from "@/lib/api/council-documents"
import type {
  CouncilCodesIn,
  CouncilDecisionCancel,
  CouncilDocumentPermissions,
  CouncilProfileSearchIn,
  CouncilSetCreate,
  CouncilSetCreateByIds,
  CouncilSetPreviewIn,
} from "@/lib/zod/council-documents"
import { downloadBlob } from "@/lib/utils/download-blob"

export const councilDocumentKeys = {
  all: ["council-documents"] as const,
  permissions: () => [...councilDocumentKeys.all, "quyen"] as const,
  templates: () => [...councilDocumentKeys.all, "templates"] as const,
  sets: () => [...councilDocumentKeys.all, "sets"] as const,
  setList: (p: CouncilSetListParams) => [...councilDocumentKeys.sets(), "list", p] as const,
  set: (id: number) => [...councilDocumentKeys.sets(), "detail", id] as const,
  /** lượt gửi của bộ — mã lượt KHÔNG phải dữ liệu cá nhân nhưng không lưu ngoài bộ nhớ */
  submissions: (setId: number) => [...councilDocumentKeys.sets(), "luot-gui", setId] as const,
  decisions: () => [...councilDocumentKeys.all, "decisions"] as const,
  decisionList: (p: CouncilDecisionListParams) => [...councilDocumentKeys.decisions(), "list", p] as const,
  decision: (id: number) => [...councilDocumentKeys.decisions(), "detail", id] as const,
  /** DỮ LIỆU CÁ NHÂN (ho_ten) — gcTime 0. Khoá chỉ gồm năm học + id hồ sơ (số nội bộ). */
  preview: (year: number, ids: readonly number[]) =>
    [...councilDocumentKeys.all, "kiem-truoc", year, ids] as const,
  /** DỮ LIỆU CÁ NHÂN (ho_ten, cccd) — gcTime 0. Khoá mang từ khoá tìm kiếm ⇒ gỡ ngay khi không còn quan sát. */
  profileSearch: (p: CouncilProfileSearchIn) => [...councilDocumentKeys.all, "tim-ho-so", p] as const,
  /** DỮ LIỆU CÁ NHÂN — gcTime 0, gỡ khi unmount. */
  inputCodes: (id: number) => [...councilDocumentKeys.all, "ma-ho-so", id] as const,
  downloadLog: (p: CouncilLogParams) => [...councilDocumentKeys.all, "nhat-ky-tai", p] as const,
  deletions: (p: Omit<CouncilLogParams, "set_id">) =>
    [...councilDocumentKeys.all, "nhat-ky-xoa", p] as const,
}

// ── cờ quyền ─────────────────────────────────────────────────────────────────
export const NO_COUNCIL_PERMISSIONS: CouncilDocumentPermissions = {
  xem_mau: false,
  tai_mau_len: false,
  xem_danh_sach_bo: false,
  tao_bo: false,
  xem_chi_tiet_bo: false,
  tai_tep: false,
  xoa_bo: false,
  xem_ma_ho_so: false,
  xem_nhat_ky_tai: false,
  xem_nhat_ky_xoa: false,
  ghi_nhan_qd: false,
  xem_danh_sach_qd: false,
  xem_chi_tiet_qd: false,
  tai_scan_qd: false,
  huy_ghi_nhan_qd: false,
  huy_hieu_luc_qd: false,
  tao_bo_dieu_chinh: false,
  ghi_nhan_dieu_chinh: false,
  dung_lai_ban_ky: false,
  so_bo_voi_hien_tai: false,
  xem_nhom_cho: false,
  cho_xet_lai: false,
  xem_su_kien: false,
  mo_luot_gui: false,
  xem_luot_gui: false,
  phan_xu_luot_gui: false,
  kiem_truoc: false,
  tim_ho_so: false,
  doi_ma: false,
  tai_ca_bo: false,
}

/**
 * Luồng "dựng từ danh sách chọn" dùng được: cần quyền tạo bộ + CẢ HAI route nền của luồng (kiểm trước, tìm hồ sơ) — mỗi
 * route một cờ (phiên A chốt 11-11). Một nguồn cho mọi nơi hiện lối vào luồng.
 */
export function coTheDungTuDanhSach(q: CouncilDocumentPermissions): boolean {
  return q.tao_bo && q.kiem_truoc && q.tim_ho_so
}

export type CouncilPermissionState = "loading" | "forbidden" | "error" | "ready"

export interface CouncilPermissionsViewModel {
  state: CouncilPermissionState
  /** luôn đủ khoá; chỉ có giá trị bật khi `state === "ready"` */
  permissions: CouncilDocumentPermissions
  error: unknown
}

export function useCouncilDocumentPermissions(
  { enabled = true }: { enabled?: boolean } = {},
): CouncilPermissionsViewModel {
  const q = useQuery({
    queryKey: councilDocumentKeys.permissions(),
    queryFn: getCouncilDocumentPermissions,
    staleTime: 60_000,
    retry: false,
    enabled,
  })
  return useMemo<CouncilPermissionsViewModel>(() => {
    if (q.isPending) {
      return { state: "loading", permissions: NO_COUNCIL_PERMISSIONS, error: null }
    }
    if (q.isError) {
      const forbidden = axios.isAxiosError(q.error) && q.error.response?.status === 403
      return {
        state: forbidden ? "forbidden" : "error",
        permissions: NO_COUNCIL_PERMISSIONS,
        error: q.error,
      }
    }
    return { state: "ready", permissions: q.data, error: null }
  }, [q.isPending, q.isError, q.error, q.data])
}

// ── kho mẫu ──────────────────────────────────────────────────────────────────
export function useCouncilTemplates(enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.templates(),
    queryFn: listCouncilTemplates,
    enabled,
    staleTime: 30_000,
  })
}

export function useUploadCouncilTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: UploadCouncilTemplateInput) => uploadCouncilTemplate(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.templates() })
    },
  })
}

// ── bộ văn bản ───────────────────────────────────────────────────────────────
export function useCouncilSets(params: CouncilSetListParams, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.setList(params),
    queryFn: () => listCouncilSets(params),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}

export function useCouncilSet(setId: number, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.set(setId),
    queryFn: () => getCouncilSet(setId),
    enabled: enabled && Number.isInteger(setId) && setId > 0,
    staleTime: 30_000,
  })
}

/**
 * Dựng bộ. `gcTime: 0`: biến số mutation (thân có danh sách mã) rời
 * MutationCache ngay khi không còn ai quan sát. Chống bấm đúp: nút khoá theo
 * `isPending` (máy chủ vẫn là chốt — khoá dựng ⇒ 409).
 */
export function useCreateCouncilSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CouncilSetCreate) => createCouncilSet(payload),
    gcTime: 0,
    onSuccess: (bo) => {
      qc.setQueryData(councilDocumentKeys.set(bo.id), bo)
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    },
  })
}

export function useDeleteCouncilSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ setId, lyDo }: { setId: number; lyDo: string }) =>
      deleteCouncilSet(setId, lyDo),
    gcTime: 0,
    onSuccess: (vet) => {
      qc.removeQueries({ queryKey: councilDocumentKeys.inputCodes(vet.set_id) })
      // Chi tiết bộ: đánh dấu cũ, KHÔNG tải lại ngay (trang đang chuyển đi — tải lại ⇒ 404 nháy).
      void qc.invalidateQueries({
        queryKey: councilDocumentKeys.set(vet.set_id),
        refetchType: "none",
      })
      void qc.invalidateQueries({ queryKey: [...councilDocumentKeys.sets(), "list"] })
      void qc.invalidateQueries({ queryKey: [...councilDocumentKeys.all, "nhat-ky-xoa"] })
    },
  })
}

/**
 * Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN. Chỉ tải khi `enabled`
 * (người dùng bấm "Hiện"); không giữ trong cache: `gcTime: 0` ⇒ React Query
 * gỡ query ngay khi không còn component nào dùng (bấm "Ẩn" / rời trang). Không
 * thêm `removeQueries` trong cleanup: StrictMode (dev) chạy cleanup giữa hai
 * lần mount ⇒ tải mã HAI lần.
 */
export function useCouncilSetInputCodes(setId: number, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.inputCodes(setId),
    queryFn: () => getCouncilSetInputCodes(setId),
    enabled,
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

export function useDownloadCouncilSetFile() {
  return useMutation({
    mutationFn: async ({ setId, thuTu }: { setId: number; thuTu: number }) => {
      const tep = await downloadCouncilSetFile(setId, thuTu)
      downloadBlob(tep.blob, tep.filename)
      return tep.filename
    },
    gcTime: 0,
  })
}

// ── nhật ký (CHỈ admin) ──────────────────────────────────────────────────────
export function useCouncilDownloadLog(params: CouncilLogParams, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.downloadLog(params),
    queryFn: () => listCouncilDownloadLog(params),
    enabled,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  })
}

export function useCouncilSetDeletions(
  params: Omit<CouncilLogParams, "set_id">,
  enabled: boolean,
) {
  return useQuery({
    queryKey: councilDocumentKeys.deletions(params),
    queryFn: () => listCouncilSetDeletions(params),
    enabled,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  })
}

// ═══════════════ vòng giao diện: chọn hồ sơ → kiểm trước → dựng (máy chủ có từ `5feb425d`) ═══════════════
// ⚠️ Phản hồi có `ho_ten` / `cccd`: `gcTime: 0` ⇒ React Query gỡ khỏi cache ngay khi không còn component quan sát;
// không persist (QueryClient của app không có persister — test khoá), không storage, không `console.*`, không URL.

/**
 * Kiểm trước + thứ tự. `input === null` ⇒ không gọi. Không giữ kết quả cũ khi danh sách đổi (không
 * `placeholderData`): trong lúc chờ giao diện hiện "đang kiểm…", KHÔNG hiện số của lần kiểm trước như thể còn đúng.
 */
export function useCouncilSetPreview(input: CouncilSetPreviewIn | null, enabled = true) {
  return useQuery({
    queryKey: councilDocumentKeys.preview(input?.academic_year ?? 0, input?.profile_ids ?? []),
    queryFn: () => {
      if (input === null) throw new Error("Chưa có danh sách để kiểm trước.")
      return previewCouncilSet(input)
    },
    enabled: enabled && input !== null && input.profile_ids.length > 0,
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

/** Tìm hồ sơ cho trang chọn (POST — từ khoá không vào URL). Giữ trang cũ trong lúc lật trang để bảng khỏi nháy. */
export function useCouncilProfileSearch(params: CouncilProfileSearchIn, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.profileSearch(params),
    queryFn: () => searchCouncilProfiles(params),
    enabled,
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    placeholderData: keepPreviousData,
  })
}

/** Dán danh sách mã ⇒ id hồ sơ. `gcTime: 0`: biến số (danh sách mã = CCCD) không nằm lại trong MutationCache. */
export function useResolveCouncilCodes() {
  return useMutation({
    mutationFn: (input: CouncilCodesIn) => resolveCouncilCodes(input),
    gcTime: 0,
  })
}

/** Dựng bộ theo id + dấu kiểm trước (đặc tả 3.3). */
export function useCreateCouncilSetByIds() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CouncilSetCreateByIds) => createCouncilSetByIds(payload),
    gcTime: 0,
    onSuccess: (bo) => {
      qc.setQueryData(councilDocumentKeys.set(bo.id), bo)
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    },
  })
}

/** Tải cả bộ (.zip). Máy chủ kiểm sha + ghi nhật ký TRƯỚC khi trả byte; giao diện chỉ lưu tệp. */
export function useDownloadCouncilSetZip() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ setId }: { setId: number }) => {
      const tep = await downloadCouncilSetZip(setId)
      downloadBlob(tep.blob, tep.filename)
      return tep.filename
    },
    gcTime: 0,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: [...councilDocumentKeys.all, "nhat-ky-tai"] })
    },
  })
}

/** Đối chiếu bản ký: số dòng + TÊN trường đổi. Bấm nút mới gọi (mutation), không tự chạy. */
export function useCompareCouncilSet() {
  return useMutation({
    mutationFn: ({ setId }: { setId: number }) => compareCouncilSet(setId),
    gcTime: 0,
  })
}

// ── Quyết định đã ký + lượt gửi (máy chủ có từ `dd6c725d`) ─────────────────────────────────────────────────────────
/** Các lượt gửi của bộ — để khôi phục sau tải lại trang. KHÔNG cache lâu: trạng thái lượt đổi theo từng thao tác. */
export function useCouncilSetSubmissions(setId: number, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.submissions(setId),
    queryFn: () => listCouncilSubmissions(setId),
    enabled: enabled && Number.isInteger(setId) && setId > 0,
    staleTime: 0,
  })
}

export function useCouncilDecisions(params: CouncilDecisionListParams, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.decisionList(params),
    queryFn: () => listCouncilDecisions(params),
    enabled,
    staleTime: 15_000,
  })
}

export function useCouncilDecision(decisionId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.decision(decisionId ?? 0),
    queryFn: () => {
      if (decisionId === null) throw new Error("Chưa có văn bản.")
      return getCouncilDecision(decisionId)
    },
    enabled: enabled && decisionId !== null && decisionId > 0,
    staleTime: 0,
  })
}

/** Huỷ ghi nhận (nhập SAI). Xong ⇒ làm cũ văn bản, danh sách bộ và lượt của bộ. */
export function useCancelCouncilDecisionRecord() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, payload }: { decisionId: number; payload: CouncilDecisionCancel }) =>
      cancelCouncilDecisionRecord(decisionId, payload),
    gcTime: 0,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.decisions() })
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    },
  })
}
