// src/components/forms/AdaptiveAddressSelect.tsx
/**
 * Adaptive Address Select Component
 * 
 * Automatically adapts between 2-level and 3-level administrative structures.
 * 
 * UX Flow:
 * 1. User selects Province (required)
 * 2. If user selects District → Load 3-level wards under district
 * 3. If user skips District → Load 2-level wards directly under province
 * 
 * The system auto-detects the structure based on user's selection flow.
 */

"use client"

import { useState, useEffect, useMemo } from "react"
import { Combobox } from "@/components/ui/combobox"
import { Label } from "@/components/ui/label"
import { useProvinces, useDistricts, useWards } from "@/lib/hooks/useAdministrative"

interface AdaptiveAddressSelectProps {
  /** Current province name value */
  provinceValue: string;
  /** Current district name value (nullable for 2-level) */
  districtValue: string | null;
  /** Current ward name value */
  wardValue: string;
  /** Province change handler */
  onProvinceChange: (province: string) => void;
  /** District change handler (null to skip) */
  onDistrictChange: (district: string | null) => void;
  /** Ward change handler */
  onWardChange: (ward: string) => void;
  /** Label for the group */
  label?: string;
  /** Disable all fields */
  disabled?: boolean;
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
  // Track selected codes for API calls
  const [selectedProvinceCode, setSelectedProvinceCode] = useState<string | undefined>();
  const [selectedDistrictCode, setSelectedDistrictCode] = useState<string | null>(null);

  // Fetch data
  const { data: provinces = [], isLoading: loadingProvinces, error: provincesError } = useProvinces();
  const { data: districts = [], isLoading: loadingDistricts } = useDistricts(selectedProvinceCode);
  const { data: wards = [], isLoading: loadingWards } = useWards(
    selectedProvinceCode, 
    selectedDistrictCode  // NULL = 2-level, code = 3-level
  );

  // Create options for comboboxes
  const provinceOptions = useMemo(() => 
    provinces.map(p => ({ value: p.name, label: p.name, code: p.code })),
    [provinces]
  );

  const districtOptions = useMemo(() => 
    districts.map(d => ({ value: d.name, label: d.name, code: d.code })),
    [districts]
  );

  const wardOptions = useMemo(() => 
    wards.map(w => ({ value: w.name, label: w.name })),
    [wards]
  );

  // Handle province change
  const handleProvinceChange = (name: string) => {
    const province = provinces.find(p => p.name === name);
    setSelectedProvinceCode(province?.code);
    setSelectedDistrictCode(null); // Reset district
    onProvinceChange(name);
    onDistrictChange(null); // Clear district
    onWardChange(""); // Clear ward
  };

  // Handle district change
  const handleDistrictChange = (name: string | null) => {
    if (name) {
      const district = districts.find(d => d.name === name);
      setSelectedDistrictCode(district?.code ?? null);
    } else {
      setSelectedDistrictCode(null);
    }
    onDistrictChange(name);
    onWardChange(""); // Clear ward when district changes
  };

  // Handle ward change
  const handleWardChange = (name: string) => {
    onWardChange(name);
  };

  // Initialize codes from existing values (for edit mode)
  useEffect(() => {
    if (provinceValue && provinces.length > 0) {
      const province = provinces.find(p => p.name === provinceValue);
      if (province && selectedProvinceCode !== province.code) {
        setSelectedProvinceCode(province.code);
      }
    }
  }, [provinceValue, provinces, selectedProvinceCode]);

  useEffect(() => {
    if (districtValue && districts.length > 0) {
      const district = districts.find(d => d.name === districtValue);
      if (district && selectedDistrictCode !== district.code) {
        setSelectedDistrictCode(district.code);
      }
    }
  }, [districtValue, districts, selectedDistrictCode]);

  // Check if province has districts (determines if we show hint)
  const hasDistricts = districts.length > 0;

  return (
    <div className="col-span-2">
      <Label className="mb-2 block">{label}</Label>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Province Select */}
        <div>
          <Combobox
            value={provinceValue || ""}
            onChange={handleProvinceChange}
            options={provinceOptions}
            placeholder="Tỉnh/Thành phố"
            searchPlaceholder="Tìm tỉnh/thành phố..."
            emptyText="Không tìm thấy"
            disabled={disabled || loadingProvinces}
          />
        </div>

        {/* District Select (Optional) */}
        <div>
          <Combobox
            value={districtValue || ""}
            onChange={handleDistrictChange}
            options={[
              { value: "", label: "-- Bỏ qua (mô hình 2 cấp) --" },
              ...districtOptions
            ]}
            placeholder="Quận/Huyện"
            searchPlaceholder="Tìm quận/huyện..."
            emptyText={loadingDistricts ? "Đang tải..." : "Không tìm thấy"}
            disabled={disabled || !selectedProvinceCode || loadingDistricts}
          />
          {selectedProvinceCode && hasDistricts && (
            <p className="text-xs text-muted-foreground mt-1">
              Áp dụng với hộ khẩu mô hình cũ (trước 01/07/2025)
            </p>
          )}
        </div>

        {/* Ward Select */}
        <div>
          <Combobox
            value={wardValue || ""}
            onChange={handleWardChange}
            options={wardOptions}
            placeholder="Phường/Xã"
            searchPlaceholder="Tìm phường/xã..."
            emptyText={loadingWards ? "Đang tải..." : "Không tìm thấy"}
            disabled={disabled || !selectedProvinceCode || loadingWards}
          />
        </div>
      </div>
    </div>
  );
}
