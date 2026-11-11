"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { ArrowLeft, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useCouncilDocumentPermissions, useCouncilSetPreview } from "@/hooks/admin/useCouncilDocuments"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

import { CouncilBuildStep } from "./CouncilBuildStep"
import { CouncilCheckStep } from "./CouncilCheckStep"
import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilParamsStep } from "./CouncilParamsStep"
import { CouncilPickStep } from "./CouncilPickStep"
import { CouncilPreviewSummary } from "./CouncilPreviewSummary"
import { CouncilStepper } from "./CouncilStepper"

/** Chờ sau lần đổi danh sách cuối rồi mới gọi lại kiểm trước (đặc tả 5.1). */
export const CHO_KIEM_LAI_MS = 600

type BuocMoi = 1 | 2 | 3 | 4

/**
 * Trang `/admin/council-documents/moi` — bước 1–3 và phần dựng của bước 4. Danh sách chọn + tham số chỉ ở store bộ nhớ
 * (không persist); tải lại trang ⇒ mất, nên có cảnh báo `beforeunload` khi đang có danh sách. URL KHÔNG mang gì
 * (chưa có bộ); dựng xong chuyển sang `/admin/council-documents/{id}?buoc=tai`.
 */
export function CouncilNewSetClient() {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const namHoc = useCouncilSelectionStore((s) => s.namHoc)
  const idHoSo = useCouncilSelectionStore((s) => s.idHoSo)
  const boTatCa = useCouncilSelectionStore((s) => s.boTatCa)
  const [buoc, setBuoc] = useState<BuocMoi>(1)
  // Danh sách rỗng ⇒ không còn gì để chốt: về bước 1. Đặt lại NGAY trong lúc render (mẫu "điều chỉnh state theo dữ liệu
  // đổi" của React) — không dùng effect, và bước cũ không "sống lại" khi người dùng chọn lại từ đầu.
  if (idHoSo.length === 0 && buoc !== 1) setBuoc(1)

  // Kiểm trước theo danh sách ĐÃ yên 600 ms. Trong lúc chờ / đang gọi: "đang kiểm…", không hiện số cũ như còn đúng.
  const idTre = useDebouncedValue(idHoSo, CHO_KIEM_LAI_MS)
  const dangCho = idTre !== idHoSo
  const dauVao = namHoc !== null && idTre.length > 0 ? { academic_year: namHoc, profile_ids: idTre } : null
  const kt = useCouncilSetPreview(dauVao, vm.state === "ready" && vm.permissions.kiem_truoc)
  const dangKiem = idHoSo.length > 0 && (dangCho || kt.isFetching)
  const xemTruoc = dauVao !== null && !dangCho ? kt.data : undefined
  const loiKiem = !dangKiem && kt.isError ? kt.error : undefined

  // Cảnh báo khi rời / tải lại trang lúc đang có danh sách (không đọc / ghi URL).
  useEffect(() => {
    if (idHoSo.length === 0) return
    const chan = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ""
    }
    window.addEventListener("beforeunload", chan)
    return () => window.removeEventListener("beforeunload", chan)
  }, [idHoSo.length])

  const quayLai = (
    <Link href="/admin/council-documents" className="inline-flex items-center gap-1 text-sm hover:underline">
      <ArrowLeft className="h-4 w-4" /> Danh sách bộ văn bản
    </Link>
  )

  if (vm.state === "loading") {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải quyền…
      </div>
    )
  }
  if (vm.state === "error") return <CouncilErrorAlert error={vm.error} testId="moi-quyen-loi" />
  if (vm.state === "forbidden" || !vm.permissions.tao_bo) {
    return (
      <div className="space-y-3">
        {quayLai}
        <p className="text-muted-foreground" data-testid="council-forbidden">
          Bạn không có quyền dựng bộ văn bản Hội đồng.
        </p>
      </div>
    )
  }
  if (!vm.permissions.kiem_truoc) {
    // ⏳ máy chủ chưa trả cờ `kiem_truoc` (đặc tả 3.10): luồng chọn → kiểm trước chưa dùng được.
    return (
      <div className="space-y-3">
        {quayLai}
        <p className="text-muted-foreground" data-testid="moi-chua-san-sang">
          Luồng dựng bộ theo danh sách chọn chưa sẵn sàng trên máy chủ này (chưa có tính năng kiểm trước). Dùng tab “Tạo bộ”
          (dán danh sách mã) trong lúc chờ.
        </p>
      </div>
    )
  }

  const choPhep: number[] = idHoSo.length > 0 ? [1, 2, 3, 4].filter((b) => b <= buoc) : [1]
  const idDaGui = idTre

  return (
    <div className="space-y-4" data-testid="moi-client">
      {quayLai}
      <CouncilStepper hienTai={buoc} choPhepChon={choPhep} onChon={(so) => so <= 4 && setBuoc(so as BuocMoi)} />

      {buoc === 1 ? (
        <>
          <CouncilPickStep xemTruoc={xemTruoc} dangKiem={dangKiem} />
          <div className="space-y-3 rounded border p-3">
            <CouncilPreviewSummary soDangChon={idHoSo.length} xemTruoc={xemTruoc} dangKiem={dangKiem} loi={loiKiem} />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => setBuoc(2)} disabled={idHoSo.length === 0} data-testid="tiep-kiem-tra">
                Tiếp: Kiểm tra & chốt danh sách →
              </Button>
              <Button type="button" variant="outline" onClick={boTatCa} disabled={idHoSo.length === 0} data-testid="bo-tat-ca">
                Bỏ chọn tất cả
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Giai đoạn 2 (chưa làm): máy tự chia hồ sơ thành 4 nhóm — Đạt · Cần Ban thư ký quyết · Chưa đạt, chờ lần sau · Chưa
              đủ điều kiện — và tự trừ chỉ tiêu. Ở giai đoạn 1 cán bộ chọn tay như màn này.
            </p>
          </div>
        </>
      ) : null}

      {buoc === 2 ? (
        <CouncilCheckStep
          xemTruoc={xemTruoc}
          dangKiem={dangKiem}
          loi={loiKiem}
          idDaGui={idDaGui}
          onKiemLai={() => void kt.refetch()}
          onQuayLai={() => setBuoc(1)}
          onTiep={() => setBuoc(3)}
        />
      ) : null}

      {buoc === 3 && namHoc !== null ? (
        <CouncilParamsStep namHoc={namHoc} xemTruoc={xemTruoc} onQuayLai={() => setBuoc(2)} onTiep={() => setBuoc(4)} />
      ) : null}

      {buoc === 4 && namHoc !== null ? (
        xemTruoc && !dangKiem ? (
          <CouncilBuildStep
            namHoc={namHoc}
            xemTruoc={xemTruoc}
            onQuayLai={() => setBuoc(3)}
            onDuLieuDoi={() => {
              void kt.refetch()
              setBuoc(2)
            }}
            onDungXong={(bo) => {
              toast.success(`Đã dựng bộ văn bản #${bo.id}: ${bo.so_ho_so} hồ sơ, ${bo.so_tep} tệp.`)
              router.push(`/admin/council-documents/${bo.id}?buoc=tai`)
            }}
          />
        ) : (
          <div className="space-y-2" data-testid="dung-cho-kiem">
            <p className="text-sm text-muted-foreground">
              {dangKiem ? "Đang kiểm lại danh sách…" : "Chưa có kết quả kiểm trước — quay lại bước kiểm tra."}
            </p>
            <Button type="button" variant="outline" onClick={() => setBuoc(2)}>
              ← Về bước kiểm tra
            </Button>
          </div>
        )
      ) : null}
    </div>
  )
}
