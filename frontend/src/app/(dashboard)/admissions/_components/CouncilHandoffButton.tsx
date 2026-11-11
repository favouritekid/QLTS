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

/** Một hồ sơ đang chọn: id + NĂM HỌC thật của hồ sơ (`academic_year` của dòng danh sách — máy chủ `083a428d`). */
export interface HoSoDangChon {
  id: number
  academic_year?: number | null
}

interface Props {
  /** hồ sơ đang chọn Ở TRANG NÀY (màn này cố ý xoá lựa chọn khi đổi trang / bộ lọc) */
  hoSo: readonly HoSoDangChon[]
  disabled?: boolean
}

/**
 * Năm học CHUNG của các hồ sơ đang chọn, đọc từ chính các dòng (không suy từ bộ lọc): đúng một năm ⇒ dùng; có dòng chưa
 * biết năm, hoặc nhiều năm khác nhau ⇒ KHÔNG dựng (không đoán, không lấy năm của dòng đầu).
 */
export type NamChung =
  | { kieu: "trong" }
  | { kieu: "chua_ro" }
  | { kieu: "nhieu_nam" }
  | { kieu: "chung"; nam: number }

export function namChungCua(hoSo: readonly HoSoDangChon[]): NamChung {
  if (hoSo.length === 0) return { kieu: "trong" }
  const nam = new Set<number>()
  for (const h of hoSo) {
    if (typeof h.academic_year !== "number") return { kieu: "chua_ro" }
    nam.add(h.academic_year)
  }
  if (nam.size > 1) return { kieu: "nhieu_nam" }
  return { kieu: "chung", nam: [...nam][0] }
}

const LY_DO_KHOA: Record<"chua_ro" | "nhieu_nam", string> = {
  chua_ro: "Chưa biết năm học của một số hồ sơ đang chọn",
  nhieu_nam: "Các hồ sơ đang chọn thuộc nhiều năm học — chọn lại cho cùng một năm học",
}

/**
 * Nút "Dựng văn bản Hội đồng" ở thanh thao tác hàng loạt của "Hồ sơ tuyển sinh" (đặc tả 5.1, bản 2 mục 5.1).
 *
 * Chỉ ĐẨY id hồ sơ + năm học sang store RIÊNG của trang Hội đồng rồi chuyển trang; KHÔNG giữ lựa chọn qua trang trên
 * màn này (chốt xoá lựa chọn ở `AdmissionsClient` giữ nguyên — màn này có Duyệt / Từ chối hàng loạt).
 *
 * Hiện theo CỜ máy chủ (`tao_bo` + `kiem_truoc` + `tim_ho_so` — `coTheDungTuDanhSach`), không theo vai.
 *
 * Năm học chung = `academic_year` của CÁC DÒNG đang chọn (máy chủ `083a428d` thêm cột này vào dòng danh sách — đúng đặc
 * 5.1); nhiều năm khác nhau hoặc có dòng chưa rõ năm ⇒ nút khoá, nói lý do.
 */
export function CouncilHandoffButton({ hoSo, disabled = false }: Props) {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const thayThe = useCouncilSelectionStore((s) => s.thayThe)
  const [hoi, setHoi] = useState(false)

  if (vm.state !== "ready" || !coTheDungTuDanhSach(vm.permissions)) return null

  const chung = namChungCua(hoSo)
  const namHoc = chung.kieu === "chung" ? chung.nam : undefined
  const idHoSo = hoSo.map((h) => h.id)
  const khoa = disabled || namHoc === undefined
  const lyDoKhoa = chung.kieu === "chua_ro" || chung.kieu === "nhieu_nam" ? LY_DO_KHOA[chung.kieu] : undefined

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
        title={lyDoKhoa}
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
