/**
 * AdvancedTab — thẻ "Nâng cao" của PathDetailDrawer. Gom 4 trường governance
 * chỉ-admin của AdmissionPath:
 *   - ``applicable_to``                     (bộ lọc audience storefront)
 *   - ``method_quota``                      (trần theo phương thức — cấu hình/
 *                                            snapshot, CHƯA enforcement runtime)
 *   - ``bonus_rule_override``               (override cộng điểm theo path)
 *   - ``minor_correction_allowed_fields``   (allowlist hiệu chỉnh sau duyệt)
 *
 * Port từ wizard cũ ``PathBasicInfo`` để drawer ma trận là UI duy nhất cho 4
 * trường này. Cả thẻ chỉ render cho admin (do ``PathDetailDrawer`` gate bằng
 * ``user.role === "admin"``; máy chủ cũng chặn non-admin qua
 * ``BusinessRuleViolation``), nên các trường ở đây KHÔNG gate lại bằng
 * ``can_edit`` — đúng như wizard cũ chỉ gate governance bằng role admin.
 */
"use client"

import { Loader2, Save } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useUpdateAdmissionPath } from "@/hooks/admissions/useAdmissionPaths"
import {
  AUDIENCE_LABELS_VI,
  AUDIENCE_OPTIONS,
} from "@/lib/constants/admission-audience"
import {
  FIELD_GROUPS_VI,
  FIELD_LABELS_VI,
} from "@/lib/constants/minor-correction"
import { parseApiError } from "@/lib/utils/api-errors"
import {
  buildApplicableToPayload,
  buildBonusOverridePayload,
  buildMethodQuotaPayload,
} from "@/lib/utils/admission-path-payload"
import type {
  AdmissionAudience,
  AdmissionPathResponse,
} from "@/lib/zod/admission-path"

export function AdvancedTab({
  path,
  pathId,
  onClose,
}: {
  path: AdmissionPathResponse
  pathId: number
  onClose: () => void
}) {
  // Khởi tạo state governance từ path đã load.
  const [applicableTo, setApplicableTo] = useState<Set<AdmissionAudience>>(
    new Set(path.applicable_to ?? []),
  )
  const [methodQuotaInput, setMethodQuotaInput] = useState<string>(
    path.method_quota != null ? String(path.method_quota) : "",
  )
  const [bonusOverrideEnabled, setBonusOverrideEnabled] = useState<boolean>(
    path.bonus_rule_override != null,
  )
  const [applyAreaBonus, setApplyAreaBonus] = useState<boolean>(
    path.bonus_rule_override?.apply_area_bonus ?? false,
  )
  const [applyObjectBonus, setApplyObjectBonus] = useState<boolean>(
    path.bonus_rule_override?.apply_object_bonus ?? false,
  )
  const [maxTotalBonusInput, setMaxTotalBonusInput] = useState<string>(
    path.bonus_rule_override?.max_total_bonus != null
      ? String(path.bonus_rule_override.max_total_bonus)
      : "",
  )
  const [allowedFields, setAllowedFields] = useState<Set<string>>(
    new Set(path.minor_correction_allowed_fields ?? []),
  )

  const updateMutation = useUpdateAdmissionPath()

  const allowedFieldsArray = useMemo(
    () => Array.from(allowedFields).sort(),
    [allowedFields],
  )

  function toggleAudience(audience: AdmissionAudience) {
    setApplicableTo((prev) => {
      const next = new Set(prev)
      if (next.has(audience)) next.delete(audience)
      else next.add(audience)
      return next
    })
  }

  function toggleField(field: string) {
    setAllowedFields((prev) => {
      const next = new Set(prev)
      if (next.has(field)) next.delete(field)
      else next.add(field)
      return next
    })
  }

  const [confirmActiveSave, setConfirmActiveSave] = useState(false)

  /**
   * Cảnh báo khi sửa field tác động scoring/storefront trên path ĐANG hoạt
   * động: ``bonus_rule_override`` đổi điểm hồ sơ/NV CHƯA freeze (engine resolve
   * tại publish/evaluate) và ``applicable_to`` đổi bộ lọc hiển thị công khai
   * (plan §Business impact). ``method_quota`` (config/snapshot) +
   * ``minor_correction_allowed_fields`` không nằm trong cảnh báo này.
   */
  const highImpactChangedOnActive = (): boolean => {
    if (path.status !== "active") return false

    const audienceNow = buildApplicableToPayload(applicableTo)
    const audienceWas = path.applicable_to ?? null
    const audienceDiff =
      JSON.stringify(audienceNow ? [...audienceNow].sort() : null) !==
      JSON.stringify(audienceWas ? [...audienceWas].sort() : null)

    const bonusNow = buildBonusOverridePayload(
      bonusOverrideEnabled,
      applyAreaBonus,
      applyObjectBonus,
      maxTotalBonusInput,
    )
    const bonusWas = path.bonus_rule_override ?? null
    let bonusDiff: boolean
    if (bonusNow === null || bonusWas === null) {
      bonusDiff = bonusNow !== bonusWas
    } else {
      bonusDiff =
        bonusNow.apply_area_bonus !== bonusWas.apply_area_bonus ||
        bonusNow.apply_object_bonus !== bonusWas.apply_object_bonus ||
        (bonusNow.max_total_bonus ?? null) !== (bonusWas.max_total_bonus ?? null)
    }

    return audienceDiff || bonusDiff
  }

  const persist = async () => {
    setConfirmActiveSave(false)
    try {
      await updateMutation.mutateAsync({
        pathId,
        data: {
          minor_correction_allowed_fields: allowedFieldsArray,
          applicable_to: buildApplicableToPayload(applicableTo),
          method_quota: buildMethodQuotaPayload(methodQuotaInput),
          bonus_rule_override: buildBonusOverridePayload(
            bonusOverrideEnabled,
            applyAreaBonus,
            applyObjectBonus,
            maxTotalBonusInput,
          ),
        },
      })
      toast.success("Đã lưu cấu hình nâng cao")
      onClose()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi lưu — kiểm tra mạng và thử lại."))
    }
  }

  const handleSave = () => {
    if (highImpactChangedOnActive()) {
      setConfirmActiveSave(true)
      return
    }
    void persist()
  }

  const isSaving = updateMutation.isPending

  return (
    <div className="space-y-6">
      {/* applicable_to — lọc audience storefront. Bỏ trống = áp dụng cho mọi
          đối tượng (Phase 1+2 contract; empty Set → null trên wire). */}
      <div className="space-y-3 rounded-md border p-3">
        <div className="space-y-1">
          <Label className="text-sm font-medium">Đối tượng áp dụng</Label>
          <p className="text-xs text-muted-foreground max-w-lg">
            Chọn nhóm thí sinh có thể đăng ký phương thức này. Bỏ trống tất cả =
            áp dụng cho mọi đối tượng (mặc định mùa cũ).
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {AUDIENCE_OPTIONS.map((audience) => (
            <label
              key={audience}
              className="flex items-start gap-2 text-sm cursor-pointer"
            >
              <Checkbox
                id={`adv-audience-${audience}`}
                checked={applicableTo.has(audience)}
                onCheckedChange={() => toggleAudience(audience)}
                aria-label={AUDIENCE_LABELS_VI[audience]}
              />
              <span className="leading-tight">
                {AUDIENCE_LABELS_VI[audience]}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* method_quota — trần theo phương thức. Bỏ trống = không giới hạn ở tầng
          phương thức (kế thừa round.admit_quota / group_quota). Cấu hình thuần
          ở thời điểm hiện tại — chưa enforcement runtime. */}
      <div className="space-y-2 rounded-md border p-3">
        <div className="space-y-1">
          <Label htmlFor="adv-method-quota" className="text-sm font-medium">
            Chỉ tiêu phương thức
          </Label>
          <p className="text-xs text-muted-foreground max-w-lg">
            Số lượng tối đa thí sinh tuyển qua phương thức này. Để trống = không
            giới hạn ở tầng phương thức (kế thừa chỉ tiêu đợt tuyển sinh).
          </p>
        </div>
        <Input
          id="adv-method-quota"
          type="number"
          inputMode="numeric"
          value={methodQuotaInput}
          onChange={(e) => setMethodQuotaInput(e.target.value)}
          min={0}
          placeholder="Để trống nếu không giới hạn"
          autoComplete="off"
        />
      </div>

      {/* bonus_rule_override — typed (KHÔNG raw JSON). Tắt → null = kế thừa
          mặc định phương thức. Sửa trên path active đổi điểm hồ sơ/NV chưa
          freeze. */}
      <div className="space-y-3 rounded-md border p-3">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label className="text-sm font-medium">
              Quy tắc cộng điểm tùy chỉnh
            </Label>
            <p className="text-xs text-muted-foreground max-w-lg">
              Tắt = dùng quy tắc cộng điểm mặc định của phương thức. Bật để
              override cộng điểm khu vực / đối tượng và đặt trần tổng (0..10) —
              bỏ trống trần = không giới hạn.
            </p>
          </div>
          <Switch
            id="adv-bonus-enabled"
            checked={bonusOverrideEnabled}
            onCheckedChange={setBonusOverrideEnabled}
            aria-label="Bật quy tắc cộng điểm tùy chỉnh"
          />
        </div>
        {bonusOverrideEnabled && (
          <div className="space-y-3 pl-3 border-l-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="adv-apply-area-bonus"
                checked={applyAreaBonus}
                onCheckedChange={(v) => setApplyAreaBonus(v === true)}
                aria-label="Cộng điểm khu vực"
              />
              <Label
                htmlFor="adv-apply-area-bonus"
                className="text-sm cursor-pointer"
              >
                Cộng điểm khu vực (KV1 / KV2-NT / KV2 / KV3)
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="adv-apply-object-bonus"
                checked={applyObjectBonus}
                onCheckedChange={(v) => setApplyObjectBonus(v === true)}
                aria-label="Cộng điểm đối tượng ưu tiên"
              />
              <Label
                htmlFor="adv-apply-object-bonus"
                className="text-sm cursor-pointer"
              >
                Cộng điểm đối tượng ưu tiên (mã 01..07)
              </Label>
            </div>
            <div className="space-y-1">
              <Label
                htmlFor="adv-max-total-bonus"
                className="text-sm font-medium"
              >
                Trần tổng cộng điểm (0..10)
              </Label>
              <Input
                id="adv-max-total-bonus"
                type="number"
                inputMode="decimal"
                value={maxTotalBonusInput}
                onChange={(e) => setMaxTotalBonusInput(e.target.value)}
                min={0}
                max={10}
                step={0.25}
                placeholder="Để trống = không giới hạn"
                autoComplete="off"
              />
            </div>
          </div>
        )}
      </div>

      {/* minor_correction_allowed_fields — allowlist hiệu chỉnh sau duyệt. */}
      <div className="space-y-3 rounded-md border p-3">
        <div className="space-y-1">
          <Label className="text-sm font-medium">
            Hiệu chỉnh sau duyệt — danh sách trường được phép
          </Label>
          <p className="text-xs text-muted-foreground max-w-lg">
            Cho phép officer/manager hiệu chỉnh các trường không ảnh hưởng tiêu
            chí xét tuyển trên hồ sơ đã duyệt. Chỉ trường được tick mới hiển thị
            trong dialog hiệu chỉnh; mọi thay đổi đều bị log kèm lý do.
          </p>
        </div>
        <div className="space-y-4">
          {Object.entries(FIELD_GROUPS_VI).map(([groupName, fields]) => (
            <div key={groupName} className="space-y-2">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                {groupName}
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {fields.map((field) => (
                  <label
                    key={field}
                    className="flex items-start gap-2 text-sm cursor-pointer"
                  >
                    <Checkbox
                      id={`adv-mc-${field}`}
                      checked={allowedFields.has(field)}
                      onCheckedChange={() => toggleField(field)}
                      aria-label={FIELD_LABELS_VI[field] ?? field}
                    />
                    <span className="leading-tight">
                      {FIELD_LABELS_VI[field] ?? field}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2 border-t pt-3">
        <Button variant="outline" onClick={onClose}>
          Đóng
        </Button>
        <Button
          onClick={handleSave}
          disabled={isSaving}
          aria-busy={isSaving}
        >
          {isSaving ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4 mr-1" aria-hidden="true" />
          )}
          Lưu nâng cao
        </Button>
      </div>

      {/* Cảnh báo sửa field tác động cao trên path đang hoạt động — mẫu như
          dialog Vô hiệu hoá ở LifecycleTab (custom Dialog, không JS confirm). */}
      <Dialog open={confirmActiveSave} onOpenChange={setConfirmActiveSave}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Lưu thay đổi trên phương thức đang hoạt động?
            </DialogTitle>
            <DialogDescription>
              Phương thức này đang hoạt động. Đổi &quot;Đối tượng áp dụng&quot;
              hoặc &quot;Quy tắc cộng điểm&quot; sẽ ảnh hưởng hồ sơ / nguyện vọng
              CHƯA chốt điểm và bộ lọc hiển thị công khai. Hồ sơ đã chốt điểm
              giữ nguyên.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmActiveSave(false)}
            >
              Huỷ
            </Button>
            <Button onClick={persist} disabled={isSaving} aria-busy={isSaving}>
              {isSaving ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
              ) : (
                <Save className="h-4 w-4 mr-1" aria-hidden="true" />
              )}
              Vẫn lưu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
