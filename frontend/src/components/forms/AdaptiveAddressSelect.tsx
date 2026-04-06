// src/components/forms/AdaptiveAddressSelect.tsx
/**
 * Address Select Component with explicit mode toggle.
 *
 * Two modes:
 * - "current":  34 provinces, 2-level (province → ward), no district
 * - "legacy":   63 provinces, 3-level (province → district → ward)
 *
 * Mode is chosen by the user via a radio toggle at the top.
 * Switching mode resets province/district/ward selections.
 */

"use client"

import { useMemo } from "react"

import type { AddressMode } from "@/lib/api/administrative"
import { useDistricts, useProvinces, useWards } from "@/lib/hooks/useAdministrative"

import { Label } from "@/components/ui/label"
import { Combobox } from "@/components/ui/combobox"
import { Input } from "@/components/ui/input"

interface AdaptiveAddressSelectProps {
  provinceValue: string
  districtValue: string | null
  wardValue: string
  /** Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text. */
  residentialGroupValue?: string
  /** Số nhà, tên đường — street address line, free-text. */
  streetAddressValue?: string
  onProvinceChange: (province: string) => void
  onDistrictChange: (district: string | null) => void
  onWardChange: (ward: string) => void
  onResidentialGroupChange?: (residentialGroup: string) => void
  onStreetAddressChange?: (streetAddress: string) => void
  /** Address mode: "current" (2-level) or "legacy" (3-level) */
  mode: AddressMode
  onModeChange: (mode: AddressMode) => void
  label?: string
  disabled?: boolean
}

export function AdaptiveAddressSelect({
  provinceValue,
  districtValue,
  wardValue,
  residentialGroupValue,
  streetAddressValue,
  onProvinceChange,
  onDistrictChange,
  onWardChange,
  onResidentialGroupChange,
  onStreetAddressChange,
  mode,
  onModeChange,
  label = "Hộ khẩu thường trú",
  disabled = false,
}: AdaptiveAddressSelectProps) {
  const isLegacy = mode === "legacy"

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

  const wardOptions = useMemo(
    () => wards.map((w) => ({ value: w.name, label: w.name })),
    [wards],
  )

  // ---- Handlers ----
  const handleModeChange = (newMode: AddressMode) => {
    onModeChange(newMode)
    onProvinceChange("")
    onDistrictChange(null)
    onWardChange("")
  }

  const handleProvinceChange = (name: string) => {
    onProvinceChange(name)
    onDistrictChange(null)
    onWardChange("")
  }

  const handleDistrictChange = (name: string) => {
    onDistrictChange(name || null)
    onWardChange("")
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
              searchPlaceholder="Tìm quận/huyện..."
              emptyText={loadingDistricts ? "Đang tải..." : "Không tìm thấy"}
              disabled={disabled || !selectedProvinceCode || loadingDistricts}
            />
          </div>
        ) : null}

        {/* Ward */}
        <div>
          <Combobox
            value={wardValue || ""}
            onChange={onWardChange}
            options={wardOptions}
            placeholder="Phường/Xã"
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
                disabled={disabled}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
