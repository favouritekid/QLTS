"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
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
  useCouncilDocumentPermissions,
  useCouncilSet,
  useCouncilSetInputCodes,
  useDeleteCouncilSet,
  useDownloadCouncilSetFile,
} from "@/hooks/admin/useCouncilDocuments"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import type { TenBuoc } from "./buoc"
import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilDownloadLogPanel } from "./CouncilLogPanels"
import { kichThuoc, ngay, nguoi, shaRutGon, thoiDiem } from "./hien-thi"

const NHAN_THAM_SO: Record<string, string> = {
  so_quyet_dinh: "Số Quyết định",
  ngay_quyet_dinh: "Ngày Quyết định",
  dot_so: "Đợt số",
  dot_thang: "Tháng của đợt",
  so_bien_ban: "Số Biên bản",
  ngay_bien_ban: "Ngày Biên bản",
}

/** Chi tiết một bộ: metadata + tệp (tải bytes đã lưu) + phần CHỈ admin theo cờ. */
export function CouncilSetDetailClient({
  setId,
  buocBanDau: _buocBanDau = null,
}: {
  setId: number
  /** tên bước từ `?buoc=` (trang máy chủ đã kiểm theo danh sách đóng); `null` = mặc định. ⏳ chưa dùng — lát bước 4–6. */
  buocBanDau?: TenBuoc | null
}) {
  const vm = useCouncilDocumentPermissions()
  const q = useCouncilSet(setId, vm.state === "ready" && vm.permissions.xem_chi_tiet_bo)

  const quayLai = (
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
        {quayLai}
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
        {quayLai}
        <CouncilErrorAlert error={q.error} testId="set-detail-error" />
      </div>
    )
  }
  const bo = q.data
  const quyen = vm.permissions
  return (
    <div className="space-y-6" data-testid="set-detail">
      {quayLai}
      <ThongTinBo bo={bo} />
      <DanhSachTep bo={bo} canDownload={quyen.tai_tep} />
      {quyen.xem_ma_ho_so ? <MaHoSoDauVao setId={bo.id} soHoSo={bo.so_ho_so} /> : null}
      {quyen.xem_nhat_ky_tai ? (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Nhật ký tải tệp của bộ này</h2>
          <CouncilDownloadLogPanel setId={bo.id} />
        </section>
      ) : null}
      {quyen.xoa_bo ? <XoaBo bo={bo} /> : null}
    </div>
  )
}

function ThongTinBo({ bo }: { bo: CouncilSetDetail }) {
  const ts = bo.tham_so_quyet_dinh ?? {}
  const dongTs = Object.entries(ts).filter(([, v]) => v !== null && v !== undefined)
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-bold font-display">Bộ văn bản #{bo.id}</h1>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-muted-foreground">Tạo lúc: </dt><dd className="inline">{thoiDiem(bo.tao_luc)}</dd></div>
        <div><dt className="inline text-muted-foreground">Mốc chụp dữ liệu: </dt><dd className="inline">{thoiDiem(bo.moc_chup)}</dd></div>
        <div><dt className="inline text-muted-foreground">Người tạo: </dt><dd className="inline">{nguoi(bo.nguoi_tao_id)}</dd></div>
        <div><dt className="inline text-muted-foreground">Đơn vị: </dt><dd className="inline">{bo.unit_id === null ? "Nhiều / chưa gán (chỉ Admin thấy)" : `#${bo.unit_id}`}</dd></div>
        <div><dt className="inline text-muted-foreground">Năm học: </dt><dd className="inline">{bo.nam_hoc ?? "—"}</dd></div>
        <div><dt className="inline text-muted-foreground">Trình độ: </dt><dd className="inline">{bo.trinh_do}</dd></div>
        <div><dt className="inline text-muted-foreground">Số hồ sơ: </dt><dd className="inline">{bo.so_ho_so}</dd></div>
        <div><dt className="inline text-muted-foreground">Số tệp · dung lượng: </dt><dd className="inline">{bo.so_tep} · {kichThuoc(bo.kich_thuoc_tong)}</dd></div>
      </dl>
      <div className="text-sm">
        <span className="text-muted-foreground">Tham số Quyết định: </span>
        {dongTs.length === 0 ? (
          "không (chỗ trống trên văn bản để người ký điền)"
        ) : (
          <span>
            {dongTs
              .map(([k, v]) => `${NHAN_THAM_SO[k] ?? k}: ${typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? ngay(v) : String(v)}`)
              .join(" · ")}
          </span>
        )}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Thông tin dựng (kỹ thuật)</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-2 text-xs" data-testid="thong-tin-dung">
          {JSON.stringify(bo.thong_tin_dung, null, 2)}
        </pre>
      </details>
    </section>
  )
}

function DanhSachTep({ bo, canDownload }: { bo: CouncilSetDetail; canDownload: boolean }) {
  const tai = useDownloadCouncilSetFile()
  const [dangTai, setDangTai] = useState<number | null>(null)
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">Tệp của bộ ({bo.tep.length})</h2>
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
          {bo.tep.map((t) => (
            <TableRow key={t.thu_tu} data-testid={`set-file-${t.thu_tu}`}>
              <TableCell>{t.thu_tu}</TableCell>
              <TableCell className="break-all">{t.path}</TableCell>
              <TableCell className="font-mono text-xs" title={t.sha256}>{shaRutGon(t.sha256)}</TableCell>
              <TableCell className="text-right">{kichThuoc(t.kich_thuoc)}</TableCell>
              {canDownload ? (
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={tai.isPending}
                    data-testid={`download-file-${t.thu_tu}`}
                    onClick={() => {
                      setDangTai(t.thu_tu)
                      tai.mutate(
                        { setId: bo.id, thuTu: t.thu_tu },
                        { onSettled: () => setDangTai(null) },
                      )
                    }}
                  >
                    {dangTai === t.thu_tu ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    <span className="ml-1">Tải</span>
                  </Button>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <CouncilErrorAlert error={tai.error} testId="download-file-error" />
    </section>
  )
}

/**
 * Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN. Chỉ tải khi bấm "Hiện"; bấm
 * "Ẩn" (hoặc rời trang) ⇒ component con unmount ⇒ dữ liệu gỡ khỏi cache.
 */
function MaHoSoDauVao({ setId, soHoSo }: { setId: number; soHoSo: number }) {
  const [hien, setHien] = useState(false)
  return (
    <section className="space-y-2" data-testid="input-codes-section">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">Danh sách mã hồ sơ đầu vào ({soHoSo})</h2>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setHien((h) => !h)}
          data-testid="input-codes-toggle"
        >
          {hien ? "Ẩn" : "Hiện"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Dữ liệu cá nhân (số CCCD) — chỉ Admin xem được; không lưu trên trình duyệt, ẩn đi là xoá khỏi bộ nhớ trang.
      </p>
      {hien ? <BangMaHoSo setId={setId} /> : null}
    </section>
  )
}

function BangMaHoSo({ setId }: { setId: number }) {
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

function XoaBo({ bo }: { bo: CouncilSetDetail }) {
  const router = useRouter()
  const xoa = useDeleteCouncilSet()
  const [mo, setMo] = useState(false)
  const [lyDo, setLyDo] = useState("")
  const xacNhanDuoc = lyDo.trim() !== "" && !xoa.isPending
  return (
    <section className="space-y-2 rounded-md border border-destructive/40 p-4">
      <h2 className="text-lg font-semibold text-destructive">Xoá bộ văn bản</h2>
      <p className="text-sm text-muted-foreground">
        Xoá khỏi phần mềm (bắt buộc lý do, ghi vết). Bản sao lưu CSDL đã có KHÔNG bị xoá.
      </p>
      <Button
        variant="destructive"
        onClick={() => {
          xoa.reset()
          setMo(true)
        }}
        data-testid="delete-set-open"
      >
        Xoá bộ #{bo.id}
      </Button>
      <AlertDialog open={mo} onOpenChange={(o) => !xoa.isPending && setMo(o)}>
        <AlertDialogContent data-testid="delete-set-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá bộ văn bản #{bo.id}?</AlertDialogTitle>
            <AlertDialogDescription data-testid="delete-set-summary">
              Bộ gồm {bo.so_ho_so} hồ sơ, {bo.so_tep} tệp. Sau khi xoá không tải lại được tệp; nhật ký tải và vết xoá vẫn giữ.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1">
            <Label htmlFor="ly-do-xoa">Lý do xoá (bắt buộc)</Label>
            <Textarea
              id="ly-do-xoa"
              data-testid="delete-set-reason"
              value={lyDo}
              disabled={xoa.isPending}
              onChange={(e) => setLyDo(e.target.value)}
            />
          </div>
          <CouncilErrorAlert error={xoa.error} testId="delete-set-error" />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={xoa.isPending}>Huỷ</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={!xacNhanDuoc}
              data-testid="delete-set-confirm"
              onClick={() =>
                xoa.mutate(
                  { setId: bo.id, lyDo },
                  {
                    onSuccess: (vet) => {
                      setMo(false)
                      toast.success(`Đã xoá bộ #${vet.set_id} (vết xoá #${vet.id}).`)
                      router.push("/admin/council-documents")
                    },
                  },
                )
              }
            >
              {xoa.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Xoá
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
