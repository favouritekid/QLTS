"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCouncilDecisions } from "@/hooks/admin/useCouncilDocuments"
import type { RecordSubmissionData, useRecordDecision } from "@/hooks/admin/useRecordDecision"
import { councilBlockedRowsFromError, councilConfirmNeededFromError } from "@/lib/api/council-documents"
import { UNDETERMINED_LABEL } from "@/lib/council-submission"
import type { CouncilDecision, CouncilDocumentPermissions, CouncilSetDetail } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilRecordResult } from "./CouncilRecordResult"
import { ngay, decisionKindLabel, statusLabel, formatTime } from "./display"

export type RecordController = ReturnType<typeof useRecordDecision>

interface Props {
  docSet: CouncilSetDetail
  permissions: CouncilDocumentPermissions
  /** bộ điều khiển dùng CHUNG với cha (để mọi chỗ trên màn đều nói "Chưa xác định" khi lượt chưa rõ) */
  gn: RecordController
  onBack: () => void
  /** sau khi huỷ ghi nhận xong: cha làm mới dữ liệu bộ */
  onCancelled: () => void
}

/** Giá trị ô ĐÃ in trên bộ (`tham_so_quyet_dinh`) ⇒ chuỗi để khoá; chưa in ⇒ null (người dùng gõ theo giấy). */
function printedValue(ts: Record<string, unknown> | null, k: string): string | null {
  const v = ts?.[k]
  return typeof v === "string" || typeof v === "number" ? String(v) : null
}

const POSITIVE_INTEGER_RE = /^[0-9]+$/
const ONE_TO_SIX_DIGITS_RE = /^[0-9]{1,6}$/

/**
 * Bước 6 — Ghi nhận Quyết định đã ký (đặc tả 5.6, 5.6.1). Biểu mẫu nhập theo giấy đã ký kèm scan PDF; ô đã in trên bộ
 * khoá đúng giá trị in. Gửi / mất phản hồi / phân xử đi qua `useRecordDecision` (giao thức đã có test). Khi lượt chưa
 * rõ: MỌI chỗ chỉ hiện "Chưa xác định", biểu mẫu khoá, KHÔNG có nút "Gửi lại" — chỉ "Kiểm tra trên máy chủ".
 */
export function CouncilRecordStep({ docSet, permissions, gn, onBack, onCancelled }: Props) {
  const t = gn.status
  const ts = docSet.tham_so_quyet_dinh
  const lockDecisionNumber = printedValue(ts, "so_quyet_dinh")
  const lockDecisionDate = printedValue(ts, "ngay_quyet_dinh")
  const lockMinutes = printedValue(ts, "so_bien_ban")
  const lockMinutesDate = printedValue(ts, "ngay_bien_ban")
  const lockBatchNumber = printedValue(ts, "dot_so")
  const lockBatchMonth = printedValue(ts, "dot_thang")

  const [loai, setKind] = useState<"trung_tuyen" | "bo_sung">("trung_tuyen")
  const [goc, setRoot] = useState("")
  const [decisionNumber, setDecisionNumber] = useState("")
  const [signingDate, setSigningDate] = useState("")
  const [minutesNumber, setMinutesNumber] = useState("")
  const [minutesDate, setMinutesDate] = useState("")
  const [batchNumber, setBatchNumber] = useState("")
  const [batchMonth, setBatchMonth] = useState("")
  const [scan, setScan] = useState<File | null>(null)
  const [removeAgainNumber, setRemoveAgainNumber] = useState("")
  const [matches, setMatches] = useState(false)
  const [typedConfirm, setTypedConfirm] = useState<Record<string, string>>({})

  // Danh sách Quyết định đã ghi của bộ (hiện kết quả khi tải lại trang) và danh sách gốc cho Quyết định bổ sung.
  const cua_bo = useCouncilDecisions({ set_id: docSet.id, limit: 50, offset: 0 }, permissions.xem_danh_sach_qd)
  // Máy chủ `083a428d` LỌC `loai` + `trang_thai` (giá trị lạ ⇒ 422): chỉ Quyết định trúng tuyển còn hiệu lực làm "gốc" cho
  // Quyết định bổ sung. Giao diện KHÔNG lọc lại (máy chủ kiểm lại khi ghi).
  const all = useCouncilDecisions(
    { limit: 200, offset: 0, loai: "trung_tuyen", trang_thai: "hieu_luc" },
    permissions.xem_danh_sach_qd && loai === "bo_sung",
  )

  // Văn bản CÒN tính của bộ — theo định nghĩa của chính máy chủ (`van_ban_song_cua_bo`: chưa huỷ ghi nhận), mới nhất.
  // Máy chủ `083a428d`: `bo.quyet_dinh.id` = văn bản CHƯA huỷ ghi nhận mới nhất của bộ (một nguồn với cột "Tình trạng"). Giao
  // diện chọn ĐÚNG văn bản ấy trong danh sách; `null` ⇒ bộ chưa có văn bản còn tính — KHÔNG tự chọn "mới nhất" theo giờ.
  const decisionId = docSet.quyet_dinh?.id
  const existing: CouncilDecision | undefined = useMemo(
    () => (decisionId === undefined ? undefined : (cua_bo.data ?? []).find((d) => d.id === decisionId)),
    [cua_bo.data, decisionId],
  )

  const allCandidates = all.data ?? []

  const confirmNeeded = t.kieu === "bi_tu_choi" ? councilConfirmNeededFromError(t.loi) : undefined
  const blockedRows = t.kieu === "bi_tu_choi" ? councilBlockedRowsFromError(t.loi) : undefined
  const confirmMatches =
    confirmNeeded === undefined ||
    Object.entries(confirmNeeded.so_ho_so_theo_loai).every(([k, n]) => (typedConfirm[k] ?? "").trim() === String(n))

  const value = {
    decisionNumber: lockDecisionNumber ?? decisionNumber,
    signingDate: lockDecisionDate ?? signingDate,
  }
  const locking = t.kieu === "dang_gui" || t.kieu === "dang_phan_xu" || t.kieu === "chua_xac_dinh"
  const valid =
    ONE_TO_SIX_DIGITS_RE.test(value.decisionNumber.trim()) &&
    value.signingDate !== "" &&
    scan !== null &&
    scan.size > 0 &&
    POSITIVE_INTEGER_RE.test(removeAgainNumber.trim()) &&
    Number(removeAgainNumber.trim()) >= 1 &&
    matches &&
    (loai === "trung_tuyen" || goc !== "") &&
    confirmMatches

  const gui = () => {
    if (!scan) return
    const dl: RecordSubmissionData = {
      loai,
      ...(loai === "bo_sung" && goc !== "" ? { goc_id: Number(goc) } : {}),
      so_quyet_dinh: value.decisionNumber.trim(),
      ngay_ky: value.signingDate,
      ...((lockMinutes ?? minutesNumber) ? { so_bien_ban: (lockMinutes ?? minutesNumber).trim() } : {}),
      ...((lockMinutesDate ?? minutesDate) ? { ngay_bien_ban: lockMinutesDate ?? minutesDate } : {}),
      ...((lockBatchNumber ?? batchNumber) ? { dot_so: (lockBatchNumber ?? batchNumber).trim() } : {}),
      ...((lockBatchMonth ?? batchMonth) ? { dot_thang: Number((lockBatchMonth ?? batchMonth).trim()) } : {}),
      xac_nhan_so_ho_so: Number(removeAgainNumber.trim()),
      xac_nhan_khop_ban_in: matches,
      ...(confirmNeeded ? { xac_nhan_trang_thai: confirmNeeded.so_ho_so_theo_loai } : {}),
      scan,
    }
    void gn.gui(dl)
  }

  // ── 1. kết quả (từ DTO máy chủ) ───────────────────────────────────────────
  if (t.kieu === "da_ghi" && t.decision) {
    return (
      <div className="space-y-4" data-testid="buoc-ghi-nhan">
        <CouncilRecordResult decision={t.decision} setId={docSet.id} permissions={permissions} onCancelled={() => { onCancelled(); gn.startNewSubmissionAfterCancel() }} />
      </div>
    )
  }
  if (t.kieu === "da_ghi") {
    return (
      <div className="space-y-3" data-testid="buoc-ghi-nhan">
        <div className="rounded border p-4 text-sm" data-testid="da-ghi-thieu-chi-tiet">
          Máy chủ báo ĐÃ ghi nhận nhưng không trả chi tiết văn bản. Mở “Danh sách bộ” để xem.
        </div>
      </div>
    )
  }
  if (t.kieu === "nhap" && existing) {
    return (
      <div className="space-y-4" data-testid="buoc-ghi-nhan">
        <p className="text-sm text-muted-foreground">Bước 6 — bộ #{docSet.id} đã có Quyết định đã ghi nhận.</p>
        <CouncilRecordResult decision={existing} setId={docSet.id} permissions={permissions} onCancelled={() => { onCancelled(); gn.startNewSubmissionAfterCancel() }} />
      </div>
    )
  }

  // ── 2. biểu mẫu + các trạng thái phụ ──────────────────────────────────────
  return (
    <div className="space-y-4" data-testid="buoc-ghi-nhan">
      <p className="text-sm text-muted-foreground">
        Bước 6 — nhập theo giấy đã ký, kèm bản scan. Máy chủ đối chiếu với bản in của bộ #{docSet.id}.
      </p>

      {t.kieu === "chua_xac_dinh" || t.kieu === "dang_phan_xu" ? (
        <Unspecified t={t} onCheck={() => void gn.adjudicate()} />
      ) : null}

      {t.kieu === "chua_ghi_da_chan" ? (
        <div className="space-y-2 rounded border p-4 text-sm" data-testid="da-chan">
          <p className="font-medium">Đã chặn lượt gửi cũ</p>
          <p>
            Máy chủ xác nhận lượt đó chưa tạo Quyết định nào, và lượt gửi muộn sẽ bị từ chối. Nhập lại và gửi sẽ mở một lượt MỚI.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={gn.backToForm} data-testid="nhap-lai">
            Nhập lại
          </Button>
        </div>
      ) : null}

      {t.kieu === "bo_khong_con" ? (
        <p className="text-sm text-destructive" role="alert" data-testid="bo-khong-con">
          Bộ văn bản không còn — về danh sách bộ.
        </p>
      ) : null}

      <fieldset className="space-y-4" disabled={locking} data-testid="bieu-mau-ghi-nhan">
        <div className="space-y-1">
          <Label>Loại văn bản</Label>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="loai-qd" value="trung_tuyen" checked={loai === "trung_tuyen"} onChange={() => setKind("trung_tuyen")} data-testid="loai-trung-tuyen" />
              Quyết định trúng tuyển
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="loai-qd" value="bo_sung" checked={loai === "bo_sung"} onChange={() => setKind("bo_sung")} data-testid="loai-bo-sung" />
              Quyết định bổ sung
            </label>
          </div>
        </div>

        {loai === "bo_sung" ? (
          <div className="space-y-1">
            <Label htmlFor="b6-goc">Quyết định gốc (bắt buộc với Quyết định bổ sung)</Label>
            <select
              id="b6-goc"
              data-testid="goc"
              className="h-10 w-full max-w-md rounded-md border border-border bg-card px-2 text-sm md:h-9"
              value={goc}
              onChange={(e) => setRoot(e.target.value)}
            >
              <option value="">Chưa chọn Quyết định gốc.</option>
              {allCandidates.map((d) => (
                <option key={d.id} value={d.id}>
                  {`${decisionKindLabel(d.loai)} số ${d.so_quyet_dinh} ngày ${ngay(d.ngay_ky)}`}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">Chỉ liệt kê Quyết định trúng tuyển còn hiệu lực — máy chủ kiểm lại khi ghi.</p>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id="b6-so-qd" nhan="Số Quyết định" khoa={lockDecisionNumber} value={decisionNumber} onChange={setDecisionNumber} testid="so-quyet-dinh" numeric />
          <Field id="b6-ngay-ky" nhan="Ngày ký (theo giấy)" khoa={lockDecisionDate} value={signingDate} onChange={setSigningDate} testid="ngay-ky" type="date" />
          <Field id="b6-so-bb" nhan="Số Biên bản" khoa={lockMinutes} value={minutesNumber} onChange={setMinutesNumber} testid="so-bien-ban" numeric />
          <Field id="b6-ngay-bb" nhan="Ngày Biên bản" khoa={lockMinutesDate} value={minutesDate} onChange={setMinutesDate} testid="ngay-bien-ban" type="date" />
          <Field id="b6-dot-so" nhan="Đợt số" khoa={lockBatchNumber} value={batchNumber} onChange={setBatchNumber} testid="dot-so" numeric />
          <Field id="b6-dot-thang" nhan="Tháng của đợt" khoa={lockBatchMonth} value={batchMonth} onChange={setBatchMonth} testid="dot-thang" numeric />
        </div>

        <div className="space-y-1">
          <Label htmlFor="b6-scan">Bản scan (PDF)</Label>
          <input
            id="b6-scan"
            type="file"
            accept="application/pdf,.pdf"
            data-testid="scan"
            className="block text-sm"
            onChange={(e) => setScan(e.target.files?.[0] ?? null)}
          />
          {scan ? <p className="text-xs text-muted-foreground" data-testid="scan-nhan">{scan.name} · {scan.size} byte</p> : null}
        </div>

        <div className="space-y-1">
          <Label htmlFor="b6-so-ho-so">Gõ lại số hồ sơ đếm trên giấy đã ký</Label>
          <Input
            id="b6-so-ho-so"
            data-testid="xac-nhan-so-ho-so"
            className="max-w-[8rem]"
            inputMode="numeric"
            autoComplete="off"
            value={removeAgainNumber}
            onChange={(e) => setRemoveAgainNumber(e.target.value)}
          />
        </div>

        <label className="flex items-start gap-2 text-sm">
          <Checkbox checked={matches} onCheckedChange={(v) => setMatches(v === true)} data-testid="xac-nhan-khop" aria-label="Đã đối chiếu khớp bản in" />
          <span>
            Tôi đã đối chiếu: giấy đã ký khớp bản in của bộ #{docSet.id} (danh sách, ngành, điểm từng em)
          </span>
        </label>

        {confirmNeeded ? (
          <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="khoi-xac-nhan-trang-thai">
            <div className="text-sm font-medium">Có hồ sơ đổi trạng thái từ lúc dựng</div>
            {Object.entries(confirmNeeded.so_ho_so_theo_loai).map(([k, n]) => (
              <div key={k} className="space-y-1">
                <Label htmlFor={`b6-xn-${k}`}>
                  {`“${statusLabel(k)}”: ${n} hồ sơ (dòng ${(confirmNeeded.dong_theo_loai[k] ?? []).join(", ")}). Gõ số hồ sơ để xác nhận vẫn ghi nhận theo giấy đã ký.`}
                </Label>
                <Input
                  id={`b6-xn-${k}`}
                  data-testid={`xac-nhan-tt-${k}`}
                  className="max-w-[8rem]"
                  inputMode="numeric"
                  autoComplete="off"
                  value={typedConfirm[k] ?? ""}
                  onChange={(e) => setTypedConfirm((g) => ({ ...g, [k]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        ) : null}
      </fieldset>

      {t.kieu === "bi_tu_choi" ? (
        <div className="space-y-2" data-testid="bi-tu-choi">
          <CouncilErrorAlert error={t.loi} testId="ghi-nhan-loi" />
          {blockedRows ? (
            <ul className="list-disc pl-5 text-sm" data-testid="dong-bi-chan">
              {blockedRows.map((d) => (
                <li key={d.dong}>{`Dòng ${d.dong}: ${d.ly_do}`}</li>
              ))}
            </ul>
          ) : null}
          {t.huong === "mo_luot_moi" ? (
            <p className="text-sm" data-testid="huong-mo-luot-moi">Lượt gửi cũ đã bị chặn — bấm “Ghi nhận” để mở lượt mới.</p>
          ) : null}
          {t.huong === "phan_xu" ? (
            <div className="space-y-2 text-sm" data-testid="huong-phan-xu">
              <p>Lượt này đã có văn bản ghi với nội dung khác — bấm để máy chủ cho biết văn bản đó.</p>
              <Button type="button" size="sm" variant="outline" onClick={() => void gn.adjudicate()} data-testid="kiem-tra-may-chu">
                Kiểm tra trên máy chủ
              </Button>
            </div>
          ) : null}
          {t.huong === "tai_lai_bo" ? (
            <p className="text-sm" data-testid="huong-tai-lai-bo">Lượt gửi không hợp lệ với bộ này — tải lại trang để đọc lại trạng thái bộ.</p>
          ) : null}
        </div>
      ) : null}

      {t.kieu === "loi_mo_luot" ? (
        <div className="space-y-2" data-testid="loi-mo-luot">
          <CouncilErrorAlert error={t.loi} testId="mo-luot-loi" />
          <p className="text-sm">Chưa gửi gì lên máy chủ — thử lại an toàn.</p>
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" onClick={onBack} disabled={locking} data-testid="ghi-nhan-quay-lai">
          ← Quay lại
        </Button>
        {t.kieu === "chua_xac_dinh" || t.kieu === "dang_phan_xu" ? null : (
          <Button type="button" onClick={gui} disabled={!valid || t.kieu === "dang_gui" || t.kieu === "bo_khong_con"} data-testid="ghi-nhan">
            {t.kieu === "dang_gui" ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Đang gửi ghi nhận…
              </>
            ) : (
              "Ghi nhận"
            )}
          </Button>
        )}
      </div>
    </div>
  )
}

/** Một ô nhập; ô đã in trên bộ ⇒ khoá đúng giá trị in. */
function Field({
  id,
  nhan,
  khoa,
  value,
  onChange,
  testid,
  type,
  numeric,
}: {
  id: string
  nhan: string
  khoa: string | null
  value: string
  onChange: (v: string) => void
  testid: string
  type?: "date"
  numeric?: boolean
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>
        {nhan}
        {khoa !== null ? <span className="ml-1 text-xs text-muted-foreground">(đã in trên bộ)</span> : null}
      </Label>
      <Input
        id={id}
        data-testid={testid}
        type={type}
        inputMode={numeric ? "numeric" : undefined}
        autoComplete="off"
        readOnly={khoa !== null}
        value={khoa ?? value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

/** Thẻ "Chưa xác định" — MỌI chữ ở đây đều không nói "chưa ghi nhận" (đặc tả 5.6.1). */
function Unspecified({
  t,
  onCheck,
}: {
  t: { kieu: "chua_xac_dinh"; ma: string; luc: string; reason: string } | { kieu: "dang_phan_xu"; ma: string; luc: string }
  onCheck: () => void
}) {
  const checking = t.kieu === "dang_phan_xu"
  const reason = t.kieu === "chua_xac_dinh" ? t.reason : null
  return (
    <div className="space-y-2 rounded border border-warning-500/60 bg-warning-50 p-4 text-sm" role="status" data-testid="chua-xac-dinh">
      <div className="text-base font-semibold" data-testid="nhan-chua-xac-dinh">
        {UNDETERMINED_LABEL} được kết quả ghi nhận
      </div>
      <p>
        Lượt gửi lúc {formatTime(t.luc)}, mã lượt gửi <span className="font-mono" data-testid="ma-luot">{t.ma}</span>. Quyết định CÓ THỂ
        đã được ghi. Biểu mẫu đã khoá — đừng gửi lại; bấm nút dưới để máy chủ cho biết chắc.
      </p>
      {reason === "dang_xu_ly" ? <p data-testid="tb-dang-xu-ly">Máy chủ đang xử lý — vẫn chưa rõ, thử lại sau ít giây.</p> : null}
      {reason === "phan_xu_loi" ? <p data-testid="tb-phan-xu-loi">Không kết nối được — kiểm thất bại. Thử lại.</p> : null}
      {reason === "dong_bang" ? (
        <p data-testid="tb-dong-bang">
          Tuyển sinh đang tạm đóng băng nên máy chủ chưa cho kiểm lượt này. Kết quả vẫn chưa xác định (Quyết định CÓ THỂ đã được
          ghi). Biểu mẫu vẫn khoá; đợi hết đóng băng rồi bấm kiểm lại.
        </p>
      ) : null}
      {reason === "van_chua_ro" ? <p data-testid="tb-van-chua-ro">Máy chủ trả kết quả không hiểu được — vẫn chưa rõ.</p> : null}
      <Button type="button" size="sm" onClick={onCheck} disabled={checking} data-testid="kiem-tra-may-chu">
        {checking ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Kiểm tra trên máy chủ
      </Button>
    </div>
  )
}
