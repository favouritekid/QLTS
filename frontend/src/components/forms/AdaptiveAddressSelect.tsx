// src/components/forms/AdaptiveAddressSelect.tsx
/**
 * Adaptive Address Select Component
 *
 * Automatically adapts between 2-level and 3-level administrative structures.
 *
 * UX Flow:
 * 1. User selects Province (required)
 * 2. If user selects District -> Load 3-level wards under district
 * 3. If user skips District -> Load 2-level wards directly under province
 *
 * The system auto-detects the structure based on user's selection flow.
 */

"use client"

import { useMemo, useState } from "react"

import type { Province } from "@/lib/api/administrative"
import { useDistricts, useProvinces, useWards } from "@/lib/hooks/useAdministrative"

import { Label } from "@/components/ui/label"
import { Combobox } from "@/components/ui/combobox"

interface AdaptiveAddressSelectProps {
  /** Current province name value */
  provinceValue: string
  /** Current district name value (nullable for 2-level) */
  districtValue: string | null
  /** Current ward name value */
  wardValue: string
  /** Province change handler */
  onProvinceChange: (province: string) => void
  /** District change handler (null to skip) */
  onDistrictChange: (district: string | null) => void
  /** Ward change handler */
  onWardChange: (ward: string) => void
  /** Label for the group */
  label?: string
  /** Disable all fields */
  disabled?: boolean
}

function formatDisplayDate(value: string): string {
  return value.split("-").reverse().join("/")
}

function buildProvinceLabel(province: Province, hasDuplicateName: boolean): string {
  if (hasDuplicateName && province.is_current) {
    return `${province.name} (hiện hành từ ${formatDisplayDate(province.valid_from)})`
  }

  if (!province.is_current && province.valid_to) {
    return `${province.name} (mô hình cũ đến ${formatDisplayDate(province.valid_to)})`
  }

  return province.name
}

function resolveProvinceCode(
  provinces: Province[],
  provinceValue: string,
  districtValue: string | null,
  wardValue: string,
  currentProvinceCode?: string
): string | undefined {
  if (!provinceValue) {
    return undefined
  }

  const matches = provinces.filter((province) => province.name === provinceValue)
  if (matches.length === 0) {
    return undefined
  }

  if (currentProvinceCode && matches.some((province) => province.code === currentProvinceCode)) {
    return currentProvinceCode
  }

  if (matches.length === 1) {
    return matches[0].code
  }

  if (districtValue) {
    return matches.find((province) => !province.is_current)?.code ?? matches[0].code
  }

  if (wardValue) {
    return matches.find((province) => province.is_current)?.code ?? matches[0].code
  }

  return matches.find((province) => province.is_current)?.code ?? matches[0].code
}

export function AdaptiveAddressSelect({
  provinceValue,
  districtValue,
  wardValue,
  onProvinceChange,
  onDistrictChange,
  onWardChange,
  label = "Hộ khẩu thường trú",
  disabled = false,
}: AdaptiveAddressSelectProps) {
  const { data: provinces = [], isLoading: loadingProvinces } = useProvinces()
  const [selectedProvinceCodeOverride, setSelectedProvinceCodeOverride] = useState<string | undefined>(undefined)

  const provinceByCode = useMemo(
    () => new Map(provinces.map((province) => [province.code, province])),
    [provinces]
  )

  const provinceNameCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const province of provinces) {
      counts.set(province.name, (counts.get(province.name) ?? 0) + 1)
    }
    return counts
  }, [provinces])

  const selectedProvinceCode = useMemo(
    () =>
      resolveProvinceCode(
        provinces,
        provinceValue,
        districtValue,
        wardValue,
        selectedProvinceCodeOverride
      ),
    [districtValue, provinceValue, provinces, selectedProvinceCodeOverride, wardValue]
  )

  const { data: districts = [], isLoading: loadingDistricts } = useDistricts(selectedProvinceCode)

  const selectedDistrict = useMemo(
    () => districts.find((district) => district.name === districtValue),
    [districtValue, districts]
  )
  const selectedDistrictCode = selectedDistrict?.code ?? null

  const { data: wards = [], isLoading: loadingWards } = useWards(
    selectedProvinceCode,
    selectedDistrictCode
  )

  const provinceOptions = useMemo(
    () =>
      provinces.map((province) => ({
        value: province.code,
        label: buildProvinceLabel(
          province,
          (provinceNameCounts.get(province.name) ?? 0) > 1
        ),
      })),
    [provinceNameCounts, provinces]
  )

  const districtOptions = useMemo(
    () => districts.map((district) => ({ value: district.name, label: district.name })),
    [districts]
  )

  const wardOptions = useMemo(
    () => wards.map((ward) => ({ value: ward.name, label: ward.name })),
    [wards]
  )

  const handleProvinceChange = (code: string) => {
    setSelectedProvinceCodeOverride(code || undefined)
    onProvinceChange(code ? provinceByCode.get(code)?.name ?? "" : "")
    onDistrictChange(null)
    onWardChange("")
  }

  const handleDistrictChange = (name: string) => {
    onDistrictChange(name || null)
    onWardChange("")
  }

  const hasDistricts = districts.length > 0

  return (
    <div className="col-span-2">
      <Label className="mb-2 block">{label}</Label>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <Combobox
            value={selectedProvinceCode || ""}
            onChange={handleProvinceChange}
            options={provinceOptions}
            placeholder="Tỉnh/Thành phố"
            searchPlaceholder="Tìm tỉnh/thành phố..."
            emptyText="Không tìm thấy"
            disabled={disabled || loadingProvinces}
          />
        </div>

        <div>
          <Combobox
            value={districtValue || ""}
            onChange={handleDistrictChange}
            options={[
              { value: "", label: "-- Bỏ qua (mô hình 2 cấp) --" },
              ...districtOptions,
            ]}
            placeholder="Quận/Huyện"
            searchPlaceholder="Tìm quận/huyện..."
            emptyText={loadingDistricts ? "Đang tải..." : "Không tìm thấy"}
            disabled={disabled || !selectedProvinceCode || loadingDistricts}
          />
          {selectedProvinceCode && hasDistricts ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Áp dụng với hộ khẩu mô hình cũ (trước 01/07/2025)
            </p>
          ) : null}
        </div>

        <div>
          <Combobox
            value={wardValue || ""}
            onChange={onWardChange}
            options={wardOptions}
            placeholder="Phường/Xã"
            searchPlaceholder="Tìm phường/xã..."
            emptyText={loadingWards ? "Đang tải..." : "Không tìm thấy"}
            disabled={disabled || !selectedProvinceCode || loadingWards}
          />
        </div>
      </div>
    </div>
  )
}
