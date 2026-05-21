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
  onWardCodeChange,
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
  // Phase E.4 KV bridge: every transition that changes the selected ward
  // (mode switch, province/district reset, direct ward pick, or clear)
  // must mirror the ward code so callers tracking `permanent_commune_code`
  // never see a stale or orphaned code. `lookupWardCode` reads the loaded
  // wards list; returns `null` when ward is empty or not present in the
  // current province's ward set (e.g. mode switched mid-edit).
  const lookupWardCode = (wardName: string): string | null => {
    if (!wardName) return null
    const ward = wards.find((w) => w.name === wardName)
    return ward?.code ?? null
  }

  const handleModeChange = (newMode: AddressMode) => {
    onModeChange(newMode)
    onProvinceChange("")
    onDistrictChange(null)
    onWardChange("")
    onWardCodeChange?.(null)
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

  const handleWardChange = (name: string) => {
    onWardChange(name)
    onWardCodeChange?.(lookupWardCode(name))
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
            onChange={handleWardChange}
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
    </div>
  )
}
