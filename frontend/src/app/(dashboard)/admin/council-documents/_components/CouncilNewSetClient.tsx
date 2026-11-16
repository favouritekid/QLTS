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
export const RECHECK_DELAY_MS = 600

type NewStep = 1 | 2 | 3 | 4

/**
 * Trang `/admin/council-documents/moi` — bước 1–3 và phần dựng của bước 4. Danh sách chọn + tham số chỉ ở store bộ nhớ
 * (không persist); tải lại trang ⇒ mất, nên có cảnh báo `beforeunload` khi đang có danh sách. URL KHÔNG mang gì
 * (chưa có bộ); dựng xong chuyển sang `/admin/council-documents/{id}?buoc=tai`.
 */
export function CouncilNewSetClient() {
  const router = useRouter()
  const vm = useCouncilDocumentPermissions()
  const academicYear = useCouncilSelectionStore((s) => s.academicYear)
  const profileId = useCouncilSelectionStore((s) => s.profileId)
  const clearAll = useCouncilSelectionStore((s) => s.clearAll)
  const [step, setStep] = useState<NewStep>(1)
  // Review max PR #724 (R12): đang dựng ⇒ khoá chuyển bước (xem `CouncilBuildStep.onBuildingChange`).
  const [isBuilding, setIsBuilding] = useState(false)
  // Danh sách rỗng ⇒ không còn gì để chốt: về bước 1. Đặt lại NGAY trong lúc render (mẫu "điều chỉnh state theo dữ liệu
  // đổi" của React) — không dùng effect, và bước cũ không "sống lại" khi người dùng chọn lại từ đầu.
  if (profileId.length === 0 && step !== 1) setStep(1)

  // Kiểm trước theo danh sách ĐÃ yên 600 ms. Trong lúc chờ / đang gọi: "đang kiểm…", không hiện số cũ như còn đúng.
  const idTre = useDebouncedValue(profileId, RECHECK_DELAY_MS)
  const pending = idTre !== profileId
  const input = academicYear !== null && idTre.length > 0 ? { academic_year: academicYear, profile_ids: idTre } : null
  const kt = useCouncilSetPreview(input, vm.state === "ready" && vm.permissions.kiem_truoc)
  const checking = profileId.length > 0 && (pending || kt.isFetching)
  const preview = input !== null && !pending ? kt.data : undefined
  const checkError = !checking && kt.isError ? kt.error : undefined

  // Cảnh báo khi rời / tải lại trang lúc đang có danh sách (không đọc / ghi URL).
  useEffect(() => {
    if (profileId.length === 0) return
    const chan = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ""
    }
    window.addEventListener("beforeunload", chan)
    return () => window.removeEventListener("beforeunload", chan)
  }, [profileId.length])

  const back = (
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
        {back}
        <p className="text-muted-foreground" data-testid="council-forbidden">
          Bạn không có quyền dựng bộ văn bản Hội đồng.
        </p>
      </div>
    )
  }
  if (!vm.permissions.kiem_truoc || !vm.permissions.tim_ho_so) {
    // Cờ `kiem_truoc` / `tim_ho_so` (đặc tả 3.10; mỗi route một cờ) tắt — tài khoản không được cấp quyền các route ấy, hoặc
    // máy chủ chưa hỗ trợ: luồng chọn → kiểm trước không dùng được. Giao diện không phân biệt hai nguyên nhân (không đoán).
    return (
      <div className="space-y-3">
        {back}
        <p className="text-muted-foreground" data-testid="moi-chua-san-sang">
          Luồng dựng bộ theo danh sách chọn chưa dùng được với tài khoản / máy chủ này (thiếu quyền kiểm trước hoặc tìm hồ sơ).
          Dùng tab “Tạo bộ” (dán danh sách mã) trong lúc chờ.
        </p>
      </div>
    )
  }

  const allowed: number[] = isBuilding ? [] : profileId.length > 0 ? [1, 2, 3, 4].filter((b) => b <= step) : [1]
  const submittedIds = idTre

  return (
    <div className="space-y-4" data-testid="moi-client">
      {back}
      <CouncilStepper
        current={step}
        canPick={allowed}
        onPick={(number) => !isBuilding && number <= 4 && setStep(number as NewStep)}
      />

      {step === 1 ? (
        <>
          <CouncilPickStep preview={preview} checking={checking} hasCodeChange={vm.permissions.doi_ma} />
          <div className="space-y-3 rounded border p-3">
            <CouncilPreviewSummary selectedCount={profileId.length} preview={preview} checking={checking} error={checkError} />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => setStep(2)} disabled={profileId.length === 0} data-testid="tiep-kiem-tra">
                Tiếp: Kiểm tra & chốt danh sách →
              </Button>
              <Button type="button" variant="outline" onClick={clearAll} disabled={profileId.length === 0} data-testid="bo-tat-ca">
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

      {step === 2 ? (
        <CouncilCheckStep
          preview={preview}
          checking={checking}
          error={checkError}
          submittedIds={submittedIds}
          onRecheck={() => void kt.refetch()}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      ) : null}

      {step === 3 && academicYear !== null ? (
        <CouncilParamsStep academicYear={academicYear} preview={preview} onBack={() => setStep(2)} onNext={() => setStep(4)} />
      ) : null}

      {step === 4 && academicYear !== null ? (
        preview && !checking ? (
          <CouncilBuildStep
            academicYear={academicYear}
            preview={preview}
            onBack={() => setStep(3)}
            onDataChange={() => {
              void kt.refetch()
              setStep(2)
            }}
            onBuildingChange={setIsBuilding}
            onBuildDone={(docSet) => {
              toast.success(`Đã dựng bộ văn bản #${docSet.id}: ${docSet.so_ho_so} hồ sơ, ${docSet.so_tep} tệp.`)
              router.push(`/admin/council-documents/${docSet.id}?buoc=tai`)
            }}
          />
        ) : (
          <div className="space-y-2" data-testid="dung-cho-kiem">
            <p className="text-sm text-muted-foreground">
              {checking ? "Đang kiểm lại danh sách…" : "Chưa có kết quả kiểm trước — quay lại bước kiểm tra."}
            </p>
            <Button type="button" variant="outline" onClick={() => setStep(2)}>
              ← Về bước kiểm tra
            </Button>
          </div>
        )
      ) : null}
    </div>
  )
}
