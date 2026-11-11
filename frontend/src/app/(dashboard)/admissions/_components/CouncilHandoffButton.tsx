// src/app/(dashboard)/admissions/_components/CouncilHandoffButton.tsx
"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
import { FileText } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { coTheDungTuDanhSach, useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

export const DUONG_DAN_DUNG_VAN_BAN = "/admin/council-documents/moi"

interface Props {
  /** năm học của bộ lọc đang áp (lọc phía máy chủ ⇒ mọi dòng đang hiển thị đều thuộc năm này); `undefined` = "Tất cả năm" */
  namHoc: number | undefined
  /** id hồ sơ đang chọn Ở TRANG NÀY (màn này cố ý xoá lựa chọn khi đổi trang / bộ lọc) */
  idHoSo: readonly number[]
  disabled?: boolean
}

/**
 * Nút "Dựng văn bản Hội đồng" ở thanh thao tác hàng loạt của "Hồ sơ tuyển sinh" (đặc tả 5.1, bản 2 mục 5.1).
 *
 * Chỉ ĐẨY id hồ sơ + năm học sang store RIÊNG của trang Hội đồng rồi chuyển trang; KHÔNG giữ lựa chọn qua trang trên
 * màn này (chốt xoá lựa chọn ở `AdmissionsClient` giữ nguyên — màn này có Duyệt / Từ chối hàng loạt).
 *
 * Hiện theo CỜ máy chủ (`tao_bo` + `kiem_truoc` + `tim_ho_so` — `coTheDungTuDanhSach`), không theo vai.
 *
 * ⚠️ Lệch đặc tả có chủ ý: đặc tả muốn "năm học chung" đọc từ dòng đang hiển thị, nhưng DTO nhẹ của danh sách
 * (`AdmissionListItem`) KHÔNG có `academic_year`. Năm học lấy từ bộ lọc năm học (lọc phía máy chủ nên mọi dòng cùng
 * năm); "Tất cả năm" ⇒ nút khoá. Muốn đúng đặc tả cần máy chủ thêm `academic_year` vào `AdmissionProfileListItem`.
 */
export function CouncilHandoffButton({ namHoc, idHoSo, disabled = false }: Props) {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const thayThe = useCouncilSelectionStore((s) => s.thayThe)
  const [hoi, setHoi] = useState(false)

  if (vm.state !== "ready" || !coTheDungTuDanhSach(vm.permissions)) return null

  const thieuNam = namHoc === undefined
  const khoa = disabled || idHoSo.length === 0 || thieuNam

  const day = () => {
    if (namHoc === undefined) return
    thayThe(namHoc, idHoSo)
    router.push(DUONG_DAN_DUNG_VAN_BAN)
  }

  const bam = () => {
    // Trang Hội đồng đang giữ một danh sách KHÁC ⇒ hỏi trước khi ghi đè.
    const dangGiu = useCouncilSelectionStore.getState()
    const khac =
      dangGiu.idHoSo.length > 0 &&
      (dangGiu.namHoc !== namHoc ||
        dangGiu.idHoSo.length !== idHoSo.length ||
        dangGiu.idHoSo.some((id) => !idHoSo.includes(id)))
    if (khac) setHoi(true)
    else day()
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={bam}
        disabled={khoa}
        aria-label="Dựng văn bản Hội đồng"
        title={thieuNam ? "Chọn một năm học ở bộ lọc trước" : undefined}
        className="h-10 touch-manipulation gap-1.5 md:h-8"
        data-testid="dung-van-ban-hoi-dong"
      >
        <FileText className="h-4 w-4" aria-hidden="true" />
        <span className="hidden sm:inline">Dựng văn bản Hội đồng →</span>
      </Button>
      <AlertDialog open={hoi} onOpenChange={setHoi}>
        <AlertDialogContent data-testid="thay-danh-sach-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Thay danh sách đang chọn?</AlertDialogTitle>
            <AlertDialogDescription>
              Trang Hội đồng đang giữ một danh sách hồ sơ khác. Tiếp tục sẽ thay bằng {idHoSo.length} hồ sơ đang chọn ở đây
              (năm học {namHoc}).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ danh sách cũ</AlertDialogCancel>
            <AlertDialogAction
              data-testid="thay-danh-sach-dong-y"
              onClick={() => {
                setHoi(false)
                day()
              }}
            >
              Thay bằng danh sách này
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
