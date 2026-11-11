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
  useCouncilDocumentPermissions,
  useCouncilSet,
  useCouncilSetInputCodes,
  useCouncilSetSubmissions,
  useDeleteCouncilSet,
  useDownloadCouncilSetFile,
  useDownloadCouncilSetZip,
} from "@/hooks/admin/useCouncilDocuments"
import { useGhiNhanQuyetDinh } from "@/hooks/admin/useGhiNhanQuyetDinh"
import { NHAN_CHUA_XAC_DINH, luotDangCho } from "@/lib/council-submission"
import type { CouncilSetDetail } from "@/lib/zod/council-documents"

import type { TenBuoc } from "./buoc"
import { CouncilCompareStep } from "./CouncilCompareStep"
import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilDownloadLogPanel } from "./CouncilLogPanels"
import { CouncilRecordStep } from "./CouncilRecordStep"
import { CouncilStepper } from "./CouncilStepper"
import {
  CHU_THICH_CHUA_GHI_NHAN,
  kichThuoc,
  ngay,
  nguoiHienThi,
  nhanLoaiQuyetDinh,
  nhanTinhTrangBo,
  shaRutGon,
  thoiDiem,
  tomTatQuyetDinh,
} from "./hien-thi"

const NHAN_THAM_SO: Record<string, string> = {
  so_quyet_dinh: "Số Quyết định",
  ngay_quyet_dinh: "Ngày Quyết định",
  dot_so: "Đợt số",
  dot_thang: "Tháng của đợt",
  so_bien_ban: "Số Biên bản",
  ngay_bien_ban: "Ngày Biên bản",
}

/** Tên bước ↔ số bước trên thanh sáu bước (bước 1–3 đã qua khi bộ đã dựng). */
const SO_BUOC: Record<TenBuoc, number> = { tai: 4, "doi-chieu": 5, "ghi-nhan": 6 }
const TEN_BUOC: Record<number, TenBuoc> = { 4: "tai", 5: "doi-chieu", 6: "ghi-nhan" }

/**
 * Chi tiết một bộ: bước 4 (tệp + tải) · 5 (đối chiếu bản ký) · 6 (ghi nhận) + phần CHỈ admin theo cờ.
 * Bước nào mở được do CỜ máy chủ quyết. URL chỉ mang `setId` và `?buoc=` (kiểm theo danh sách đóng ở trang máy chủ);
 * không có `?buoc=` mà bộ có lượt gửi chưa rõ ⇒ vào thẳng bước 6 ("Chưa xác định").
 */
export function CouncilSetDetailClient({
  setId,
  buocBanDau = null,
}: {
  setId: number
  /** tên bước từ `?buoc=` (trang máy chủ đã kiểm theo danh sách đóng); `null` = mặc định */
  buocBanDau?: TenBuoc | null
}) {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const q = useCouncilSet(setId, vm.state === "ready" && vm.permissions.xem_chi_tiet_bo)
  const quyenSan = vm.state === "ready" ? vm.permissions : NO_COUNCIL_PERMISSIONS
  // Bộ điều khiển ghi nhận dùng CHUNG: mọi chỗ trên màn nói "Chưa xác định" khi lượt chưa rõ (đặc tả 5.6.1).
  const gn = useGhiNhanQuyetDinh(setId)
  const ds = useCouncilSetSubmissions(setId, vm.state === "ready" && quyenSan.xem_luot_gui)
  const { khoiPhuc } = gn
  useEffect(() => {
    if (ds.data) khoiPhuc(ds.data)
  }, [ds.data, khoiPhuc])
  const [buocChon, setBuocChon] = useState<TenBuoc | null>(buocBanDau)

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

  const buocMo: Record<TenBuoc, boolean> = {
    tai: true,
    "doi-chieu": quyen.so_bo_voi_hien_tai,
    "ghi-nhan": quyen.ghi_nhan_qd && quyen.mo_luot_gui,
  }
  const coLuotCho = ds.data !== undefined && luotDangCho(ds.data) !== undefined
  const macDinh: TenBuoc = coLuotCho && buocMo["ghi-nhan"] ? "ghi-nhan" : "tai"
  const buoc: TenBuoc = buocChon !== null && buocMo[buocChon] ? buocChon : macDinh
  const chonBuoc = (b: TenBuoc) => {
    setBuocChon(b)
    router.replace(`/admin/council-documents/${setId}?buoc=${b}`, { scroll: false })
  }
  const chuaRo = gn.trangThai.kieu === "chua_xac_dinh" || gn.trangThai.kieu === "dang_phan_xu"
  const choPhepChon = (Object.keys(buocMo) as TenBuoc[]).filter((b) => buocMo[b]).map((b) => SO_BUOC[b])

  return (
    <div className="space-y-6" data-testid="set-detail">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {quayLai}
        {quyen.tao_bo && quyen.kiem_truoc ? (
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/council-documents/moi" data-testid="dung-bo-moi-tu-bo">
              + Dựng bộ mới
            </Link>
          </Button>
        ) : null}
      </div>
      <ThongTinBo bo={bo} chuaRo={chuaRo} />
      <CouncilStepper
        hienTai={SO_BUOC[buoc]}
        choPhepChon={choPhepChon}
        onChon={(so) => {
          const b = TEN_BUOC[so]
          if (b) chonBuoc(b)
        }}
      />
      {buoc === "tai" ? (
        <>
          <DanhSachTep bo={bo} canDownload={quyen.tai_tep} canZip={quyen.tai_ca_bo} />
          {buocMo["doi-chieu"] || buocMo["ghi-nhan"] ? (
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm" data-testid="huong-tiep-sau-tai">
              <span className="text-muted-foreground">In, trình ký. Khi giấy đã ký về:</span>
              <Button type="button" onClick={() => chonBuoc(buocMo["doi-chieu"] ? "doi-chieu" : "ghi-nhan")} data-testid="tiep-sau-tai">
                {buocMo["doi-chieu"] ? "Tiếp: Đối chiếu bản ký →" : "Tiếp: Ghi nhận →"}
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
      {buoc === "doi-chieu" ? (
        <CouncilCompareStep
          bo={bo}
          onQuayLai={() => chonBuoc("tai")}
          onTiep={buocMo["ghi-nhan"] ? () => chonBuoc("ghi-nhan") : null}
        />
      ) : null}
      {buoc === "ghi-nhan" ? (
        <CouncilRecordStep
          bo={bo}
          quyen={quyen}
          gn={gn}
          onQuayLai={() => chonBuoc(buocMo["doi-chieu"] ? "doi-chieu" : "tai")}
          onDaHuy={() => {
            void q.refetch()
            void ds.refetch()
          }}
        />
      ) : null}
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

function ThongTinBo({ bo, chuaRo }: { bo: CouncilSetDetail; chuaRo: boolean }) {
  const ts = bo.tham_so_quyet_dinh ?? {}
  const dongTs = Object.entries(ts).filter(([, v]) => v !== null && v !== undefined)
  const qd = tomTatQuyetDinh(bo.quyet_dinh)
  // Khi lượt gửi chưa rõ (phía này đang chờ phân xử, hoặc máy chủ nói `chua_xac_dinh`): CHỈ "Chưa xác định".
  const khongRo = chuaRo || bo.tinh_trang === "chua_xac_dinh"
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-bold font-display">Bộ văn bản #{bo.id}</h1>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-muted-foreground">Tạo lúc: </dt><dd className="inline">{thoiDiem(bo.tao_luc)}</dd></div>
        <div><dt className="inline text-muted-foreground">Mốc chụp dữ liệu: </dt><dd className="inline">{thoiDiem(bo.moc_chup)}</dd></div>
        <div><dt className="inline text-muted-foreground">Người tạo: </dt><dd className="inline">{nguoiHienThi(bo.nguoi_tao_ten, bo.nguoi_tao_id)}</dd></div>
        <div><dt className="inline text-muted-foreground">Đơn vị: </dt><dd className="inline">{bo.unit_id === null ? "Nhiều / chưa gán (chỉ Admin thấy)" : `#${bo.unit_id}`}</dd></div>
        <div><dt className="inline text-muted-foreground">Năm học: </dt><dd className="inline">{bo.nam_hoc ?? "—"}</dd></div>
        <div><dt className="inline text-muted-foreground">Trình độ: </dt><dd className="inline">{bo.trinh_do}</dd></div>
        <div><dt className="inline text-muted-foreground">Số hồ sơ: </dt><dd className="inline">{bo.so_ho_so}</dd></div>
        <div><dt className="inline text-muted-foreground">Số tệp · dung lượng: </dt><dd className="inline">{bo.so_tep} · {kichThuoc(bo.kich_thuoc_tong)}</dd></div>
      </dl>
      {khongRo || bo.tinh_trang !== undefined ? (
        <div className="text-sm" data-testid="tinh-trang">
          <span className="text-muted-foreground">Tình trạng: </span>
          <span className="font-medium">{khongRo ? NHAN_CHUA_XAC_DINH : nhanTinhTrangBo(bo.tinh_trang ?? "")}</span>
          {!khongRo && bo.tinh_trang === "chua_ghi_nhan" ? (
            <span className="ml-2 text-xs text-muted-foreground" data-testid="chu-thich-chua-ghi-nhan">
              “Chưa ghi nhận” = {CHU_THICH_CHUA_GHI_NHAN}.
            </span>
          ) : null}
        </div>
      ) : null}
      {qd && (qd.so || qd.ngay) ? (
        <div className="text-sm" data-testid="qd-cua-bo">
          <span className="text-muted-foreground">Quyết định đã ghi: </span>
          {[qd.loai ? nhanLoaiQuyetDinh(qd.loai) : null, qd.so ? `số ${qd.so}` : null, qd.ngay ? `ngày ${ngay(qd.ngay)}` : null, typeof qd.soHoSo === "number" ? `${qd.soHoSo} hồ sơ` : null]
            .filter(Boolean)
            .join(" · ")}
        </div>
      ) : null}
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

function DanhSachTep({ bo, canDownload, canZip }: { bo: CouncilSetDetail; canDownload: boolean; canZip: boolean }) {
  const tai = useDownloadCouncilSetFile()
  const taiZip = useDownloadCouncilSetZip()
  const [dangTai, setDangTai] = useState<number | null>(null)
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Tệp của bộ ({bo.tep.length})</h2>
        {canZip ? (
          <Button
            type="button"
            size="sm"
            disabled={taiZip.isPending}
            data-testid="tai-ca-bo"
            onClick={() => taiZip.mutate({ setId: bo.id })}
          >
            {taiZip.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Download className="mr-1 h-4 w-4" />}
            Tải cả bộ (.zip · {bo.so_tep} tệp · khoảng {Math.max(1, Math.round(bo.kich_thuoc_tong / 1024))} KB)
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
      <CouncilErrorAlert error={taiZip.error} testId="download-zip-error" />
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
