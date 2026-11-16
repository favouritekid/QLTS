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
import { canBuildFromList, useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments"
import { useCouncilSelectionStore } from "@/lib/stores/council-selection.store"

export const BUILD_DOCUMENT_PATH = "/admin/council-documents/moi"

/** Một hồ sơ đang chọn: id + NĂM HỌC thật của hồ sơ (`academic_year` của dòng danh sách — máy chủ `083a428d`). */
export interface SelectedProfile {
  id: number
  academic_year?: number | null
}

interface Props {
  /** hồ sơ đang chọn Ở TRANG NÀY (màn này cố ý xoá lựa chọn khi đổi trang / bộ lọc) */
  profile: readonly SelectedProfile[]
  disabled?: boolean
}

/**
 * Năm học CHUNG của các hồ sơ đang chọn, đọc từ chính các dòng (không suy từ bộ lọc): đúng một năm ⇒ dùng; có dòng chưa
 * biết năm, hoặc nhiều năm khác nhau ⇒ KHÔNG dựng (không đoán, không lấy năm của dòng đầu).
 */
export type CommonYear =
  | { kind: "trong" }
  | { kind: "chua_ro" }
  | { kind: "nhieu_nam" }
  | { kind: "chung"; year: number }

export function commonYearOf(profile: readonly SelectedProfile[]): CommonYear {
  if (profile.length === 0) return { kind: "trong" }
  const year = new Set<number>()
  for (const h of profile) {
    if (typeof h.academic_year !== "number") return { kind: "chua_ro" }
    year.add(h.academic_year)
  }
  if (year.size > 1) return { kind: "nhieu_nam" }
  return { kind: "chung", year: [...year][0] }
}

const LOCK_REASONS: Record<"chua_ro" | "nhieu_nam", string> = {
  chua_ro: "Chưa biết năm học của một số hồ sơ đang chọn",
  nhieu_nam: "Các hồ sơ đang chọn thuộc nhiều năm học — chọn lại cho cùng một năm học",
}

/**
 * Nút "Dựng văn bản Hội đồng" ở thanh thao tác hàng loạt của "Hồ sơ tuyển sinh" (đặc tả 5.1, bản 2 mục 5.1).
 *
 * Chỉ ĐẨY id hồ sơ + năm học sang store RIÊNG của trang Hội đồng rồi chuyển trang; KHÔNG giữ lựa chọn qua trang trên
 * màn này (chốt xoá lựa chọn ở `AdmissionsClient` giữ nguyên — màn này có Duyệt / Từ chối hàng loạt).
 *
 * Hiện theo CỜ máy chủ (`tao_bo` + `kiem_truoc` + `tim_ho_so` — `canBuildFromList`), không theo vai.
 *
 * Năm học chung = `academic_year` của CÁC DÒNG đang chọn (máy chủ `083a428d` thêm cột này vào dòng danh sách — đúng đặc
 * 5.1); nhiều năm khác nhau hoặc có dòng chưa rõ năm ⇒ nút khoá, nói lý do.
 */
export function CouncilHandoffButton({ profile, disabled = false }: Props) {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const replace = useCouncilSelectionStore((s) => s.replace)
  const [asking, setAsking] = useState(false)

  if (vm.state !== "ready" || !canBuildFromList(vm.permissions)) return null

  const common = commonYearOf(profile)
  const academicYear = common.kind === "chung" ? common.year : undefined
  const profileId = profile.map((h) => h.id)
  const locked = disabled || academicYear === undefined
  const lockReason = common.kind === "chua_ro" || common.kind === "nhieu_nam" ? LOCK_REASONS[common.kind] : undefined

  const handOff = () => {
    if (academicYear === undefined) return
    replace(academicYear, profileId)
    router.push(BUILD_DOCUMENT_PATH)
  }

  const pressed = () => {
    // Trang Hội đồng đang giữ một danh sách KHÁC ⇒ hỏi trước khi ghi đè.
    const holding = useCouncilSelectionStore.getState()
    const other =
      holding.profileId.length > 0 &&
      (holding.academicYear !== academicYear ||
        holding.profileId.length !== profileId.length ||
        holding.profileId.some((id) => !profileId.includes(id)))
    if (other) setAsking(true)
    else handOff()
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={pressed}
        disabled={locked}
        aria-label="Dựng văn bản Hội đồng"
        title={lockReason}
        className="h-10 touch-manipulation gap-1.5 md:h-8"
        data-testid="dung-van-ban-hoi-dong"
      >
        <FileText className="h-4 w-4" aria-hidden="true" />
        <span className="hidden sm:inline">Dựng văn bản Hội đồng →</span>
      </Button>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent data-testid="thay-danh-sach-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Thay danh sách đang chọn?</AlertDialogTitle>
            <AlertDialogDescription>
              Trang Hội đồng đang giữ một danh sách hồ sơ khác. Tiếp tục sẽ thay bằng {profileId.length} hồ sơ đang chọn ở đây
              (năm học {academicYear}).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ danh sách cũ</AlertDialogCancel>
            <AlertDialogAction
              data-testid="thay-danh-sach-dong-y"
              onClick={() => {
                setAsking(false)
                handOff()
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
