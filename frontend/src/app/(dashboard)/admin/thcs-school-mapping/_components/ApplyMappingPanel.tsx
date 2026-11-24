/**
 * ApplyMappingPanel — xem trước (chạy thử) lượt áp ghép tên trường THCS vào lịch
 * sử học hồ sơ, và nút áp thật.
 *
 * Nút "Áp thật" CHỈ bấm được khi BE trả `apply_enabled = true` (cờ
 * THCS_MAPPING_APPLY_ENABLED, mặc định tắt — owner chưa quyết dòng y→y). Áp thật
 * gửi kèm hai số của lượt chạy thử vừa xem; BE lệch số ⇒ 409, không ghi gì.
 *
 * Owner 23-11 (QUYET-DINH-OWNER-THCS-AP-GHEP-LIEN-CAP-VA-AN-DINH câu 2): hồ sơ KV
 * ấn định tay KHÔNG bị áp, chỉ liệt kê — ở cả chạy thử lẫn sau khi áp thật.
 * Mọi câu đánh dấu [ĐX] là câu MỚI, chỉ đề xuất — chờ owner duyệt.
 */

"use client"

import { useState } from "react"
import { toast } from "sonner"

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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { useApplyThcsMapping } from "@/lib/hooks/useThcsSchoolMapping"
import { parseApiError } from "@/lib/utils/api-errors"
import type { ThcsMappingApplyResult } from "@/lib/zod/thcs-school-mapping"

/** Danh sách hồ sơ bỏ qua vì KV ấn định tay — mỗi id mở được trang hồ sơ để cán bộ tự xem. */
function ManualKvSkippedList({ ids, testId }: { ids: number[]; testId: string }) {
  if (ids.length === 0) return null
  return (
    <span className="flex flex-wrap gap-x-2" data-testid={testId}>
      {ids.map((id) => (
        <a
          key={id}
          href={`/admissions/${id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline"
        >
          #{id}
        </a>
      ))}
    </span>
  )
}

export function ApplyMappingPanel() {
  const mutation = useApplyThcsMapping()
  const [preview, setPreview] = useState<ThcsMappingApplyResult | null>(null)
  const [appliedSkipped, setAppliedSkipped] = useState<number[] | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runPreview = async () => {
    setError(null)
    setAppliedSkipped(null)
    try {
      setPreview(await mutation.mutateAsync({ dry_run: true }))
    } catch (e) {
      setError(parseApiError(e, "Chạy thử thất bại"))
    }
  }

  const runApply = async () => {
    if (!preview) return
    setError(null)
    try {
      const res = await mutation.mutateAsync({
        dry_run: false,
        expected_rows_to_change: preview.rows_to_change,
        expected_profiles_to_change: preview.profiles_to_change,
      })
      // [ĐX] phần "bỏ qua … KV ấn định tay" của câu báo là câu mới.
      toast.success(
        `Đã áp ghép ${res.rows_to_change} dòng ở ${res.profiles_to_change} hồ sơ` +
          (res.skipped_manual_kv_override_profiles > 0
            ? `; bỏ qua ${res.skipped_manual_kv_override_profiles} hồ sơ KV ấn định tay`
            : ""),
      )
      setPreview(null)
      setAppliedSkipped(res.skipped_manual_kv_override_profile_ids)
    } catch (e) {
      setError(parseApiError(e, "Áp ghép thất bại"))
    } finally {
      setConfirmOpen(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Áp ghép vào hồ sơ</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* [ĐX] thêm "hồ sơ đã ấn định KV bằng tay" và câu "chỉ gắn mã trường…". */}
        <p className="text-muted-foreground">
          Gắn trường đã ghép vào các dòng THCS gõ tay của hồ sơ nháp và hồ sơ đang chờ
          xét (năm tuyển sinh 2026). Chỉ gắn mã trường, dòng vẫn giữ cấp THCS. Không
          chạm dòng đã chọn trường, hồ sơ đã có kết quả, đã rút, gắn Quyết định, hoặc đã
          ấn định KV bằng tay. Luôn chạy thử trước.
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={runPreview}
            disabled={mutation.isPending}
            data-testid="thcs-apply-preview"
          >
            Chạy thử
          </Button>
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={
              mutation.isPending ||
              !preview ||
              !preview.apply_enabled ||
              preview.rows_to_change === 0
            }
            data-testid="thcs-apply-real"
          >
            Áp thật
          </Button>
        </div>
        {preview && !preview.apply_enabled && (
          <p
            className="rounded-md border border-warning-300 bg-warning-50 px-3 py-2 text-xs text-warning-900"
            role="status"
          >
            Áp thật đang tạm khoá: chưa có quyết định về dòng THCS một năm (năm bắt
            đầu = năm kết thúc). Hiện chỉ xem trước được.
          </p>
        )}
        {preview && (
          <ul className="list-disc pl-5" data-testid="thcs-apply-preview-result">
            <li>
              Sẽ gắn trường: <b>{preview.rows_to_change}</b> dòng ở{" "}
              <b>{preview.profiles_to_change}</b> hồ sơ.
            </li>
            <li data-testid="thcs-apply-preview-draft">
              Trong đó hồ sơ NHÁP: {preview.draft_profiles_to_change} hồ sơ (
              {preview.draft_rows_to_change} dòng) — cán bộ đang mở form các hồ sơ này
              sẽ phải tải lại trang trước khi lưu.
            </li>
            <li>
              Trong đó dòng y→y (năm bắt đầu = năm kết thúc): {preview.same_year_rows}{" "}
              dòng ở {preview.same_year_profiles} hồ sơ.
            </li>
            {/* [ĐX] câu mới — thay câu cũ "sẽ phải duyệt lại ấn định". */}
            <li data-testid="thcs-apply-preview-manual-kv">
              Bỏ qua vì đã ấn định KV bằng tay (không đổi gì):{" "}
              {preview.skipped_manual_kv_override_profiles} hồ sơ (
              {preview.skipped_manual_kv_override_rows} dòng).{" "}
              <ManualKvSkippedList
                ids={preview.skipped_manual_kv_override_profile_ids}
                testId="thcs-apply-preview-manual-kv-ids"
              />
            </li>
            <li>
              Bỏ qua vì trạng thái hồ sơ (có kết quả):{" "}
              {preview.skipped_status_profiles} hồ sơ ({preview.skipped_status_rows}{" "}
              dòng). Bỏ qua vì khác năm {preview.academic_year}:{" "}
              {preview.skipped_year_profiles} hồ sơ ({preview.skipped_year_rows} dòng).
              Bỏ qua vì gắn Quyết định: {preview.skipped_decision_profiles} hồ sơ.
            </li>
            <li>
              Dòng ở hồ sơ chờ xét mà nhóm chưa ghép: {preview.unmapped_rows}.
              {preview.unusable_mappings > 0 &&
                ` Ghép trỏ tới trường đã ngừng / sai cấp: ${preview.unusable_mappings}.`}
            </li>
          </ul>
        )}
        {appliedSkipped && appliedSkipped.length > 0 && (
          // [ĐX] câu mới — danh sách sau khi áp thật.
          <p data-testid="thcs-apply-real-manual-kv">
            Đã áp xong. Bỏ qua {appliedSkipped.length} hồ sơ đã ấn định KV bằng tay, cán
            bộ tự xem:{" "}
            <ManualKvSkippedList ids={appliedSkipped} testId="thcs-apply-real-manual-kv-ids" />
          </p>
        )}
        {error && (
          <p className="text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Áp ghép thật?</AlertDialogTitle>
            <AlertDialogDescription>
              Gắn trường vào {preview?.rows_to_change} dòng ở{" "}
              {preview?.profiles_to_change} hồ sơ (trong đó{" "}
              {preview?.draft_profiles_to_change} hồ sơ nháp).{" "}
              {/* [ĐX] câu mới — thay câu cũ "sẽ mất hiệu lực ấn định". */}
              Bỏ qua {preview?.skipped_manual_kv_override_profiles} hồ sơ đã ấn định KV
              bằng tay. Thao tác ghi vết từng hồ sơ; muốn gỡ phải sửa tay.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Không</AlertDialogCancel>
            <AlertDialogAction onClick={runApply} disabled={mutation.isPending}>
              Áp thật
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
