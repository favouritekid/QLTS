// src/components/forms/AdaptiveAddressSelect.tsx
/**
 * Address Select Component with explicit mode toggle.
 *
 * Two modes:
 * - "current":  34 provinces, 2-level (province → ward), no district
 * - "legacy":   63 provinces, 3-level (province → district → ward)
 *
 * Mode is chosen by the user via a radio toggle at the top.
 * Switching mode resets province/district/ward selections after confirmation
 * when the user already has hierarchical address data.
 */

"use client"

import { useMemo, useState } from "react"

import type { AddressMode } from "@/lib/api/administrative"
import { useDistricts, useProvinces, useWards } from "@/lib/hooks/useAdministrative"

import { Label } from "@/components/ui/label"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"
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

interface AdaptiveAddressSelectProps {
  provinceValue: string
  districtValue: string | null
  /**
   * Display name của xã/phường — fallback render khi `wardCodeValue` chưa
   * có (vd hồ sơ legacy chỉ lưu tên). Callers cũ chỉ cần truyền `wardValue`.
   */
  wardValue: string
  /**
   * Phase E.4 KV bridge: canonical commune/ward code (administrative_nodes.code,
   * vd "01_00025"). Là **primary key** của combobox xã/phường sau commit fix
   * Finding 1 — combobox `value` = code, options[].value = code, label = name.
   * Khi prop này có giá trị, component lookup name từ code; nếu null/undefined,
   * fall back lookup ngược từ `wardValue` (display name) để backward-compat
   * với callers chưa wire code (vd hồ sơ cũ trước cải cách).
   */
  wardCodeValue?: string | null
  /** Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text. */
  residentialGroupValue?: string
  /** Số nhà, tên đường — street address line, free-text. */
  streetAddressValue?: string
  onProvinceChange: (province: string) => void
  onDistrictChange: (district: string | null) => void
  onWardChange: (ward: string) => void
  /**
   * Phase E.4 KV bridge: canonical commune/ward code from administrative_nodes.
   * Fires alongside `onWardChange` whenever the ward selection changes. Receives
   * the ward `code` field from the administrative API (e.g. "01_00025") or
   * `null` when ward is cleared / not found in the loaded list. Callers that
   * track `permanent_commune_code` (PriorityTab KV resolution) wire this to
   * form state; callers that don't simply omit the prop.
   */
  onWardCodeChange?: (wardCode: string | null) => void
  onResidentialGroupChange?: (residentialGroup: string) => void
  onStreetAddressChange?: (streetAddress: string) => void
  /** Address mode: "current" (2-level) or "legacy" (3-level) */
  mode: AddressMode
  onModeChange: (mode: AddressMode) => void
  label?: string
  disabled?: boolean
  errorMessage?: string
}

export function AdaptiveAddressSelect({
  provinceValue,
  districtValue,
  wardValue,
  wardCodeValue,
  residentialGroupValue,
  streetAddressValue,
  onProvinceChange,
  onDistrictChange,
  onWardChange,
  onWardCodeChange,
  onResidentialGroupChange,
  onStreetAddressChange,
  mode,
  onModeChange,
  label = "Hộ khẩu thường trú",
  disabled = false,
  errorMessage,
}: AdaptiveAddressSelectProps) {
  const isLegacy = mode === "legacy"
  const [pendingMode, setPendingMode] = useState<AddressMode | null>(null)

  // ---- Data fetching ----
  const { data: provinces = [], isLoading: loadingProvinces } = useProvinces(mode)

  const selectedProvince = useMemo(
    () => provinces.find((p) => p.name === provinceValue),
    [provinces, provinceValue],
  )
  const selectedProvinceCode = selectedProvince?.code

  const { data: districts = [], isLoading: loadingDistricts } = useDistricts(
    selectedProvinceCode,
    isLegacy, // only fetch districts in legacy mode
  )

  const selectedDistrict = useMemo(
    () => districts.find((d) => d.name === districtValue),
    [districts, districtValue],
  )
  const selectedDistrictCode = selectedDistrict?.code ?? null

  const { data: wards = [], isLoading: loadingWards } = useWards(
    selectedProvinceCode,
    mode,
    isLegacy ? selectedDistrictCode : undefined,
  )

  // ---- Options ----
  const provinceOptions = useMemo(
    () => provinces.map((p) => ({ value: p.name, label: p.name })),
    [provinces],
  )

  const districtOptions = useMemo(
    () => districts.map((d) => ({ value: d.name, label: d.name })),
    [districts],
  )

  // Phase E.4 KV bridge fix Finding 1: options[].value = canonical ward.code
  // (administrative_nodes.code), label = display name. Ward.code là primary
  // key — tránh ambiguity khi 2 xã/phường trùng tên ở 2 tỉnh/quận khác.
  const wardOptions = useMemo(
    () => wards.map((w) => ({ value: w.code, label: w.name })),
    [wards],
  )

  // Derive combobox internal value (= ward.code) từ 2 nguồn theo priority:
  //   1. `wardCodeValue` prop (callers new — pass canonical code thẳng)
  //   2. Fallback: lookup `wardValue` (display name) ngược ra code từ wards
  //      list — backward-compat cho hồ sơ legacy chưa wire code.
  // Khi cả 2 đều miss (vd wards list chưa load, hoặc name không match) →
  // combobox shows placeholder; sẽ render đúng khi wards load và user re-pick.
  //
  // ⚠️ LEGACY MODE: KHÔNG dùng `wardCodeValue` để khớp option. `wardCodeValue`
  // (= permanent_commune_code) là mã xã/phường **hiện hành** mà BE canonicalize
  // khi lưu — nó KHÔNG phải key trong danh sách ward legacy, và mã GSO có thể bị
  // tái sử dụng giữa 2 thời kỳ: vd legacy "Xã Nam Bình" (24721) canonicalize sang
  // 24717, nhưng trong danh sách legacy mã 24717 lại là "Thị trấn Đức An" → field
  // "nhảy" sang xã sai sau khi lưu. Ở legacy mode PHẢI resolve theo TÊN
  // (`wardValue`, chính là permanent_ward officer đã chọn), không theo mã.
  const selectedWardCode = useMemo(() => {
    if (isLegacy) {
      if (wardValue) {
        const matched = wards.find((w) => w.name === wardValue)
        return matched?.code ?? ""
      }
      return ""
    }
    // Current mode: code là canonical primary key (tránh trùng tên 2 tỉnh).
    if (wardCodeValue) return wardCodeValue
    if (wardValue) {
      const matched = wards.find((w) => w.name === wardValue)
      return matched?.code ?? ""
    }
    return ""
  }, [isLegacy, wardCodeValue, wardValue, wards])

  // ---- Handlers ----
  // Phase E.4 KV bridge: every transition that changes the selected ward
  // (mode switch, province/district reset, direct ward pick, or clear)
  // must mirror cả name (display) lẫn code (canonical KV input) qua callbacks
  // để callers tracking `permanent_commune_code` không có stale orphan code.

  const applyModeChange = (newMode: AddressMode) => {
    onModeChange(newMode)
    onProvinceChange("")
    onDistrictChange(null)
    onWardChange("")
    onWardCodeChange?.(null)
  }

  const handleModeChange = (newMode: AddressMode) => {
    if (newMode === mode) return

    const hasHierarchicalAddress = Boolean(
      provinceValue || districtValue || wardValue || wardCodeValue,
    )
    if (hasHierarchicalAddress) {
      setPendingMode(newMode)
      return
    }

    applyModeChange(newMode)
  }

  const confirmModeChange = () => {
    if (!pendingMode) return
    applyModeChange(pendingMode)
    setPendingMode(null)
  }

  const handleProvinceChange = (name: string) => {
    onProvinceChange(name)
    onDistrictChange(null)
    onWardChange("")
    onWardCodeChange?.(null)
  }

  const handleDistrictChange = (name: string) => {
    onDistrictChange(name || null)
    onWardChange("")
    onWardCodeChange?.(null)
  }

  const handleWardChange = (code: string) => {
    // Combobox onChange giờ truyền ward.code (canonical). Lookup ward record
    // để fire onWardChange(display name) — keep public API caller cũ unchanged.
    if (!code) {
      onWardChange("")
      onWardCodeChange?.(null)
      return
    }
    const ward = wards.find((w) => w.code === code)
    onWardChange(ward?.name ?? "")
    onWardCodeChange?.(ward?.code ?? null)
  }

  // ---- Render ----
  return (
    <div className="col-span-2">
      <Label className="mb-2 block">{label}</Label>

      {/* Mode toggle */}
      <div className="mb-3 flex items-center gap-4 text-sm">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="address-mode"
            checked={mode === "current"}
            onChange={() => handleModeChange("current")}
            disabled={disabled}
            className="accent-primary"
          />
          <span>Địa giới hiện hành</span>
          <span className="text-muted-foreground">(từ 01/07/2025)</span>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="address-mode"
            checked={mode === "legacy"}
            onChange={() => handleModeChange("legacy")}
            disabled={disabled}
            className="accent-primary"
          />
          <span>Hộ khẩu cũ</span>
          <span className="text-muted-foreground">(trước 01/07/2025)</span>
        </label>
      </div>

      <AlertDialog
        open={pendingMode !== null}
        onOpenChange={(open) => {
          if (!open) setPendingMode(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Đổi chế độ địa chỉ?</AlertDialogTitle>
            <AlertDialogDescription>
              Tỉnh/Thành phố, Quận/Huyện và Phường/Xã đang chọn sẽ bị xóa.
              Tổ/Thôn và số nhà, tên đường vẫn được giữ lại. Bạn sẽ cần chọn
              lại địa chỉ trước khi lưu hoặc nộp hồ sơ.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ địa chỉ hiện tại</AlertDialogCancel>
            <AlertDialogAction onClick={confirmModeChange}>
              Đổi và xóa địa chỉ
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Address fields */}
      <div
        className={`grid grid-cols-1 gap-4 ${isLegacy ? "md:grid-cols-3" : "md:grid-cols-2"}`}
      >
        {/* Province */}
        <div>
          <Combobox
            value={provinceValue || ""}
            onChange={handleProvinceChange}
            options={provinceOptions}
            placeholder={isLegacy ? "Tỉnh/Thành phố (63 tỉnh)" : "Tỉnh/Thành phố (34 tỉnh)"}
            ariaLabel={`Chọn tỉnh/thành phố — ${label}`}
            searchPlaceholder="Tìm tỉnh/thành phố..."
            emptyText="Không tìm thấy"
            disabled={disabled || loadingProvinces}
          />
        </div>

        {/* District (legacy only) */}
        {isLegacy ? (
          <div>
            <Combobox
              value={districtValue || ""}
              onChange={handleDistrictChange}
              options={districtOptions}
              placeholder="Quận/Huyện"
              ariaLabel={`Chọn quận/huyện — ${label}`}
              searchPlaceholder="Tìm quận/huyện..."
              emptyText={loadingDistricts ? "Đang tải..." : "Không tìm thấy"}
              disabled={disabled || !selectedProvinceCode || loadingDistricts}
            />
          </div>
        ) : null}

        {/* Ward — combobox dùng ward.code làm canonical key (Phase E.4 Finding 1).
            `value` = ward.code, options[].value = ward.code. Display name resolve
            qua options[].label. */}
        <div>
          <Combobox
            value={selectedWardCode}
            onChange={handleWardChange}
            options={wardOptions}
            placeholder="Phường/Xã"
            ariaLabel={`Chọn xã/phường — ${label}`}
            searchPlaceholder="Tìm phường/xã..."
            emptyText={loadingWards ? "Đang tải..." : "Không tìm thấy"}
            disabled={
              disabled ||
              !selectedProvinceCode ||
              (isLegacy && !selectedDistrictCode) ||
              loadingWards
            }
          />
        </div>
      </div>

      {/* Sub-ward + street address — free-text rows below the selectors.
          Rendered only when the parent wires up handlers, so legacy callers
          that haven't adopted the new fields keep working unchanged. */}
      {(onResidentialGroupChange || onStreetAddressChange) && (
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
          {onResidentialGroupChange && (
            <div>
              <Input
                value={residentialGroupValue ?? ""}
                onChange={(e) => onResidentialGroupChange(e.target.value)}
                placeholder="Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố"
                aria-label="Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố"
                disabled={disabled}
              />
            </div>
          )}
          {onStreetAddressChange && (
            <div>
              <Input
                value={streetAddressValue ?? ""}
                onChange={(e) => onStreetAddressChange(e.target.value)}
                placeholder="Số nhà, tên đường"
                aria-label="Số nhà, tên đường"
                disabled={disabled}
              />
            </div>
          )}
        </div>
      )}

      {errorMessage ? (
        <p
          role="alert"
          aria-live="assertive"
          className="mt-2 whitespace-pre-line text-[0.8rem] font-medium text-destructive"
          data-testid="address-field-error"
        >
          {errorMessage}
        </p>
      ) : null}
    </div>
  )
}
