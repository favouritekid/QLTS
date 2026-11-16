"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { ArrowLeft, Download, Loader2 } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  NO_COUNCIL_PERMISSIONS,
  canBuildFromList,
  useCouncilDocumentPermissions,
  useCouncilSet,
  useCouncilSetInputCodes,
  useCouncilSetSubmissions,
  useDeleteCouncilSet,
  useDownloadCouncilSetFile,
  useDownloadCouncilSetZip,
} from "@/hooks/admin/useCouncilDocuments"
import { useRecordDecision } from "@/hooks/admin/useRecordDecision"
import { UNDETERMINED_LABEL, pendingSubmission } from "@/lib/council-submission"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import type { StepName } from "./steps"
import { CouncilCompareStep } from "./CouncilCompareStep"
import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilDownloadLogPanel } from "./CouncilLogPanels"
import { CouncilRecordStep } from "./CouncilRecordStep"
import { CouncilStepper } from "./CouncilStepper"
import {
  NOT_RECORDED_NOTE,
  formatSize,
  formatDate,
  userLabel,
  decisionKindLabel,
  setStateLabel,
  shortSha,
  formatTime,
} from "./display"

const PARAM_LABELS: Record<string, string> = {
  so_quyet_dinh: "Số Quyết định",
  ngay_quyet_dinh: "Ngày Quyết định",
  dot_so: "Đợt số",
  dot_thang: "Tháng của đợt",
  so_bien_ban: "Số Biên bản",
  ngay_bien_ban: "Ngày Biên bản",
}

/** Tên bước ↔ số bước trên thanh sáu bước (bước 1–3 đã qua khi bộ đã dựng). */
const STEP_COUNT: Record<StepName, number> = { tai: 4, "doi-chieu": 5, "ghi-nhan": 6 }
const STEP_NAMES: Record<number, StepName> = { 4: "tai", 5: "doi-chieu", 6: "ghi-nhan" }

/**
 * Chi tiết một bộ: bước 4 (tệp + tải) · 5 (đối chiếu bản ký) · 6 (ghi nhận) + phần CHỈ admin theo cờ.
 * Bước nào mở được do CỜ máy chủ quyết. URL chỉ mang `setId` và `?buoc=` (kiểm theo danh sách đóng ở trang máy chủ);
 * không có `?buoc=` mà bộ có lượt gửi chưa rõ ⇒ vào thẳng bước 6 ("Chưa xác định") — quyết định ĐÚNG MỘT LẦN lúc vào trang (F281).
 */
export function CouncilSetDetailClient({
  setId,
  initialStep = null,
}: {
  setId: number
  /** tên bước từ `?buoc=` (trang máy chủ đã kiểm theo danh sách đóng); `null` = mặc định */
  initialStep?: StepName | null
}) {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const q = useCouncilSet(setId, vm.state === "ready" && vm.permissions.xem_chi_tiet_bo)
  const readyPermissions = vm.state === "ready" ? vm.permissions : NO_COUNCIL_PERMISSIONS
  // Bộ điều khiển ghi nhận dùng CHUNG: mọi chỗ trên màn nói "Chưa xác định" khi lượt chưa rõ (đặc tả 5.6.1).
  const recorder = useRecordDecision(setId)
  const submissions = useCouncilSetSubmissions(setId, vm.state === "ready" && readyPermissions.xem_luot_gui)
  const { restore: restore } = recorder
  useEffect(() => {
    if (submissions.data) restore(submissions.data)
  }, [submissions.data, restore])
  // BƯỚC ĐANG XEM tách khỏi BƯỚC MẶC ĐỊNH (F281, Codex lần 19+20):
  //   • `pickStep` — người dùng chọn (bấm thanh bước) hoặc `?buoc=` lúc vào: là bước đang xem khi nó mở được.
  //   • `buocVao` — bước mặc định, suy từ dữ liệu ĐÚNG MỘT LẦN, lúc vào trang (khi quyền và danh sách lượt đã có kết quả), rồi CHỐT.
  //     Sau đó dữ liệu lượt / bộ đổi (phân xử, ghi nhận, huỷ, làm mới) KHÔNG kéo người dùng rời bước đang xem. Trước đây bước
  //     mặc định suy lại từ `pendingSubmission(ds.data)` ở MỌI lần vẽ: vào không `?buoc=` có lượt chờ ⇒ tự vào bước 6 ⇒ phân xử xong
  //     lượt hết `cho_gui` ⇒ trang tự về bước 4, mất khung kết quả / cảnh báo vượt chỉ tiêu / khung "đã chặn".
  const [pickStep, setPickStep] = useState<StepName | null>(initialStep)
  const [entryStep, setEntryStep] = useState<StepName | null>(null)
  const hasInputData = vm.state === "ready" && (!readyPermissions.xem_luot_gui || submissions.isSuccess || submissions.isError)
  if (entryStep === null && hasInputData) {
    // chỉ chạy MỘT lần (điều kiện `buocVao === null`); cập nhật trạng thái trong lúc vẽ theo đúng cách React cho phép
    const hasPendingSubmission = submissions.data !== undefined && pendingSubmission(submissions.data) !== undefined
    setEntryStep(hasPendingSubmission && readyPermissions.ghi_nhan_qd && readyPermissions.mo_luot_gui ? "ghi-nhan" : "tai")
  }

  const back = (
    <Link href="/admin/council-documents" className="inline-flex items-center gap-1 text-sm hover:underline">
      <ArrowLeft className="h-4 w-4" /> Danh sách bộ văn bản
    </Link>
  )
  if (vm.state === "loading") {
    return <p className="text-muted-foreground">Đang tải quyền…</p>
  }
  if (vm.state === "error") return <CouncilErrorAlert error={vm.error} />
  if (vm.state === "forbidden" || !vm.permissions.xem_chi_tiet_bo) {
    return (
      <div className="space-y-3">
        {back}
        <p className="text-muted-foreground" data-testid="council-forbidden">
          Bạn không có quyền xem bộ văn bản Hội đồng.
        </p>
      </div>
    )
  }
  if (q.isPending) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải bộ văn bản…
      </div>
    )
  }
  if (q.isError) {
    return (
      <div className="space-y-3">
        {back}
        <CouncilErrorAlert error={q.error} testId="set-detail-error" />
      </div>
    )
  }
  const docSet = q.data
  const permissions = vm.permissions

  const openStep: Record<StepName, boolean> = {
    tai: true,
    "doi-chieu": permissions.so_bo_voi_hien_tai,
    "ghi-nhan": permissions.ghi_nhan_qd && permissions.mo_luot_gui,
  }
  // Bước đang xem: bước người dùng chọn (nếu mở được), không thì bước mặc định ĐÃ CHỐT lúc vào (nếu mở được), không thì bước 4.
  // Chưa chốt (còn chờ quyền / danh sách lượt) ⇒ bước 4, như trước.
  const step: StepName =
    pickStep !== null && openStep[pickStep] ? pickStep : entryStep !== null && openStep[entryStep] ? entryStep : "tai"
  const selectStep = (b: StepName) => {
    setPickStep(b)
    router.replace(`/admin/council-documents/${setId}?buoc=${b}`, { scroll: false })
  }
  const unclear = recorder.status.kind === "chua_xac_dinh" || recorder.status.kind === "dang_phan_xu"
  const canPick = (Object.keys(openStep) as StepName[]).filter((b) => openStep[b]).map((b) => STEP_COUNT[b])

  return (
    <div className="space-y-6" data-testid="set-detail">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {back}
        {canBuildFromList(permissions) ? (
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/council-documents/moi" data-testid="dung-bo-moi-tu-bo">
              + Dựng bộ mới
            </Link>
          </Button>
        ) : null}
      </div>
      <SetInfo docSet={docSet} unclear={unclear} />
      <CouncilStepper
        current={STEP_COUNT[step]}
        canPick={canPick}
        onPick={(number) => {
          const b = STEP_NAMES[number]
          if (b) selectStep(b)
        }}
      />
      {step === "tai" ? (
        <>
          <FileList docSet={docSet} canDownload={permissions.tai_tep} canZip={permissions.tai_ca_bo} />
          {openStep["doi-chieu"] || openStep["ghi-nhan"] ? (
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm" data-testid="huong-tiep-sau-tai">
              <span className="text-muted-foreground">In, trình ký. Khi giấy đã ký về:</span>
              <Button type="button" onClick={() => selectStep(openStep["doi-chieu"] ? "doi-chieu" : "ghi-nhan")} data-testid="tiep-sau-tai">
                {openStep["doi-chieu"] ? "Tiếp: Đối chiếu bản ký →" : "Tiếp: Ghi nhận →"}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
      {step === "doi-chieu" ? (
        <CouncilCompareStep
          docSet={docSet}
          onBack={() => selectStep("tai")}
          onNext={openStep["ghi-nhan"] ? () => selectStep("ghi-nhan") : null}
        />
      ) : null}
      {step === "ghi-nhan" ? (
        <CouncilRecordStep
          docSet={docSet}
          permissions={permissions}
          recorder={recorder}
          onBack={() => selectStep(openStep["doi-chieu"] ? "doi-chieu" : "tai")}
          onCancelled={() => {
            void q.refetch()
            void submissions.refetch()
          }}
        />
      ) : null}
      {permissions.xem_ma_ho_so ? <InputProfileCodes setId={docSet.id} profileCount={docSet.so_ho_so} /> : null}
      {permissions.xem_nhat_ky_tai ? (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Nhật ký tải tệp của bộ này</h2>
          <CouncilDownloadLogPanel setId={docSet.id} />
        </section>
      ) : null}
      {permissions.xoa_bo ? <DeleteSet docSet={docSet} /> : null}
    </div>
  )
}

function SetInfo({ docSet, unclear }: { docSet: CouncilSetDetail; unclear: boolean }) {
  const decisionParams = docSet.tham_so_quyet_dinh ?? {}
  const paramEntries = Object.entries(decisionParams).filter(([, v]) => v !== null && v !== undefined)
  const decision = docSet.quyet_dinh
  // Khi lượt gửi chưa rõ (phía này đang chờ phân xử, hoặc máy chủ nói `chua_xac_dinh`): CHỈ "Chưa xác định".
  const unknown = unclear || docSet.tinh_trang === "chua_xac_dinh"
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-bold font-display">Bộ văn bản #{docSet.id}</h1>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-muted-foreground">Tạo lúc: </dt><dd className="inline">{formatTime(docSet.tao_luc)}</dd></div>
        <div><dt className="inline text-muted-foreground">Mốc chụp dữ liệu: </dt><dd className="inline">{formatTime(docSet.moc_chup)}</dd></div>
        <div><dt className="inline text-muted-foreground">Người tạo: </dt><dd className="inline">{userLabel(docSet.nguoi_tao_ten, docSet.nguoi_tao_id)}</dd></div>
        <div><dt className="inline text-muted-foreground">Đơn vị: </dt><dd className="inline">{docSet.unit_id === null ? "Nhiều / chưa gán (chỉ Admin thấy)" : `#${docSet.unit_id}`}</dd></div>
        <div><dt className="inline text-muted-foreground">Năm học: </dt><dd className="inline">{docSet.nam_hoc ?? "—"}</dd></div>
        <div><dt className="inline text-muted-foreground">Trình độ: </dt><dd className="inline">{docSet.trinh_do}</dd></div>
        <div><dt className="inline text-muted-foreground">Số hồ sơ: </dt><dd className="inline">{docSet.so_ho_so}</dd></div>
        <div><dt className="inline text-muted-foreground">Số tệp · dung lượng: </dt><dd className="inline">{docSet.so_tep} · {formatSize(docSet.kich_thuoc_tong)}</dd></div>
      </dl>
      {unknown || docSet.tinh_trang !== null ? (
        <div className="text-sm" data-testid="tinh-trang">
          <span className="text-muted-foreground">Tình trạng: </span>
          <span className="font-medium">{unknown ? UNDETERMINED_LABEL : setStateLabel(docSet.tinh_trang ?? "")}</span>
          {!unknown && docSet.tinh_trang === "chua_ghi_nhan" ? (
            <span className="ml-2 text-xs text-muted-foreground" data-testid="chu-thich-chua-ghi-nhan">
              “Chưa ghi nhận” = {NOT_RECORDED_NOTE}.
            </span>
          ) : null}
        </div>
      ) : null}
      {decision ? (
        <div className="text-sm" data-testid="qd-cua-bo">
          <span className="text-muted-foreground">Quyết định đã ghi: </span>
          {[decisionKindLabel(decision.loai), `số ${decision.so_quyet_dinh}`, `ngày ${formatDate(decision.ngay_ky)}`, `${decision.so_ho_so} hồ sơ`].join(" · ")}
        </div>
      ) : null}
      <div className="text-sm">
        <span className="text-muted-foreground">Tham số Quyết định: </span>
        {paramEntries.length === 0 ? (
          "không (chỗ trống trên văn bản để người ký điền)"
        ) : (
          <span>
            {paramEntries
              .map(([k, v]) => `${PARAM_LABELS[k] ?? k}: ${typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v) : String(v)}`)
              .join(" · ")}
          </span>
        )}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Thông tin dựng (kỹ thuật)</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-2 text-xs" data-testid="thong-tin-dung">
          {JSON.stringify(docSet.thong_tin_dung, null, 2)}
        </pre>
      </details>
    </section>
  )
}

function FileList({ docSet, canDownload, canZip }: { docSet: CouncilSetDetail; canDownload: boolean; canZip: boolean }) {
  const download = useDownloadCouncilSetFile()
  const downloadZip = useDownloadCouncilSetZip()
  const [loading, setLoading] = useState<number | null>(null)
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Tệp của bộ ({docSet.tep.length})</h2>
        {canZip ? (
          <Button
            type="button"
            size="sm"
            disabled={downloadZip.isPending}
            data-testid="tai-ca-bo"
            onClick={() => downloadZip.mutate({ setId: docSet.id })}
          >
            {downloadZip.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Download className="mr-1 h-4 w-4" />}
            Tải cả bộ (.zip · {docSet.so_tep} tệp · khoảng {Math.max(1, Math.round(docSet.kich_thuoc_tong / 1024))} KB)
          </Button>
        ) : null}
      </div>
      <Table data-testid="set-files">
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Đường dẫn</TableHead>
            <TableHead>sha256</TableHead>
            <TableHead className="text-right">Kích thước</TableHead>
            {canDownload ? <TableHead /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {docSet.tep.map((t) => (
            <TableRow key={t.thu_tu} data-testid={`set-file-${t.thu_tu}`}>
              <TableCell>{t.thu_tu}</TableCell>
              <TableCell className="break-all">{t.path}</TableCell>
              <TableCell className="font-mono text-xs" title={t.sha256}>{shortSha(t.sha256)}</TableCell>
              <TableCell className="text-right">{formatSize(t.kich_thuoc)}</TableCell>
              {canDownload ? (
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={download.isPending}
                    data-testid={`download-file-${t.thu_tu}`}
                    onClick={() => {
                      setLoading(t.thu_tu)
                      download.mutate(
                        { setId: docSet.id, order: t.thu_tu },
                        { onSettled: () => setLoading(null) },
                      )
                    }}
                  >
                    {loading === t.thu_tu ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    <span className="ml-1">Tải</span>
                  </Button>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <CouncilErrorAlert error={download.error} testId="download-file-error" />
      <CouncilErrorAlert error={downloadZip.error} testId="download-zip-error" />
    </section>
  )
}

/**
 * Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN. Chỉ tải khi bấm "Hiện"; bấm
 * "Ẩn" (hoặc rời trang) ⇒ component con unmount ⇒ dữ liệu gỡ khỏi cache.
 */
function InputProfileCodes({ setId, profileCount }: { setId: number; profileCount: number }) {
  const [show, setShow] = useState(false)
  return (
    <section className="space-y-2" data-testid="input-codes-section">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">Danh sách mã hồ sơ đầu vào ({profileCount})</h2>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setShow((h) => !h)}
          data-testid="input-codes-toggle"
        >
          {show ? "Ẩn" : "Hiện"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Dữ liệu cá nhân (số CCCD) — chỉ Admin xem được; không lưu trên trình duyệt, ẩn đi là xoá khỏi bộ nhớ trang.
      </p>
      {show ? <ProfileCodeTable setId={setId} /> : null}
    </section>
  )
}

function ProfileCodeTable({ setId }: { setId: number }) {
  const q = useCouncilSetInputCodes(setId, true)
  if (q.isPending) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách mã…
      </div>
    )
  }
  if (q.isError) return <CouncilErrorAlert error={q.error} testId="input-codes-error" />
  return (
    <ol className="max-h-80 list-decimal overflow-auto rounded border py-2 pl-12 font-mono text-sm" data-testid="input-codes">
      {q.data.ma_ho_so.map((m, i) => (
        <li key={i}>{m}</li>
      ))}
    </ol>
  )
}

function DeleteSet({ docSet }: { docSet: CouncilSetDetail }) {
  const router = useRouter()
  const deleteSet = useDeleteCouncilSet()
  const [isOpen, setIsOpen] = useState(false)
  const [reason, setReason] = useState("")
  const confirmed = reason.trim() !== "" && !deleteSet.isPending
  return (
    <section className="space-y-2 rounded-md border border-destructive/40 p-4">
      <h2 className="text-lg font-semibold text-destructive">Xoá bộ văn bản</h2>
      <p className="text-sm text-muted-foreground">
        Xoá khỏi phần mềm (bắt buộc lý do, ghi vết). Bản sao lưu CSDL đã có KHÔNG bị xoá.
      </p>
      <Button
        variant="destructive"
        onClick={() => {
          deleteSet.reset()
          setIsOpen(true)
        }}
        data-testid="delete-set-open"
      >
        Xoá bộ #{docSet.id}
      </Button>
      <AlertDialog open={isOpen} onOpenChange={(o) => !deleteSet.isPending && setIsOpen(o)}>
        <AlertDialogContent data-testid="delete-set-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá bộ văn bản #{docSet.id}?</AlertDialogTitle>
            <AlertDialogDescription data-testid="delete-set-summary">
              Bộ gồm {docSet.so_ho_so} hồ sơ, {docSet.so_tep} tệp. Sau khi xoá không tải lại được tệp; nhật ký tải và vết xoá vẫn giữ.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1">
            <Label htmlFor="ly-do-xoa">Lý do xoá (bắt buộc)</Label>
            <Textarea
              id="ly-do-xoa"
              data-testid="delete-set-reason"
              value={reason}
              disabled={deleteSet.isPending}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <CouncilErrorAlert error={deleteSet.error} testId="delete-set-error" />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteSet.isPending}>Huỷ</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={!confirmed}
              data-testid="delete-set-confirm"
              onClick={() =>
                deleteSet.mutate(
                  { setId: docSet.id, reason },
                  {
                    onSuccess: (trace) => {
                      setIsOpen(false)
                      toast.success(`Đã xoá bộ #${trace.set_id} (vết xoá #${trace.id}).`)
                      router.push("/admin/council-documents")
                    },
                  },
                )
              }
            >
              {deleteSet.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Xoá
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
