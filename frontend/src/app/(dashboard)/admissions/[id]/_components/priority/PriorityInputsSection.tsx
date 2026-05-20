/**
 * Q9 #07 Phase E.4 — § 1 Inputs section (officer-friendly UX refactor).
 *
 * Linear 1-column layout:
 *   Trình độ:
 *     Văn hóa:  [select]      ← Tab 1
 *     Nghề:     [select]      ← Tab 2
 *   Cách xác định khu vực:
 *     ( ) Theo trường học           area_resolution_basis = null
 *     ( ) Theo nơi thường trú        area_resolution_basis = "permanent_address_special"
 *       ↳ Xã/phường thường trú: [input]  (conditional reveal)
 *
 * UX rationale: replaces the previous "Bật trường hợp đặc biệt" switch +
 * raw commune-code input which read as bypass-control + jargon-heavy
 * helper text. The new radio framing surfaces the OFFICER DECISION
 * ("which basis are we using") instead of a binary edge-case toggle,
 * and the helper text on the commune field stays short — officers
 * tra cứu mã hành chính separately, không tự đoán.
 *
 * Mapping to BE contract is UNCHANGED:
 *   - Theo trường học           → area_resolution_basis = null
 *   - Theo nơi thường trú        → area_resolution_basis = "permanent_address_special"
 *   - permanent_commune_code field shape unchanged
 *
 * No business logic on FE — area resolution still computed by BE engine.
 */
"use client"

import { UseFormReturn } from "react-hook-form"
import {
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
  FormDescription,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import {
  RadioGroup,
  RadioGroupItem,
} from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

// Mirror BE app/services/priority_service.py _derive_kv_basis_level enum.
const CULTURAL_OPTIONS = [
  { value: "completed_thcs",  label: "Hoàn thành chương trình THCS (chưa tốt nghiệp)" },
  { value: "graduated_thcs",  label: "Tốt nghiệp THCS" },
  { value: "completed_thpt",  label: "Hoàn thành chương trình THPT (chưa tốt nghiệp)" },
  { value: "graduated_thpt",  label: "Tốt nghiệp THPT" },
  { value: "graduated_gdtx",  label: "Tốt nghiệp GDTX (Giáo dục thường xuyên cấp 3)" },
]

const VOCATIONAL_OPTIONS = [
  { value: "none",       label: "Chưa có bằng nghề" },
  { value: "so_cap",     label: "Sơ cấp nghề" },
  { value: "trung_cap",  label: "Trung cấp" },
  { value: "cao_dang",   label: "Cao đẳng" },
]

// Internal radio values — distinct from BE enum to avoid colliding với
// the optional/nullable shape. ``null`` (school basis) is not a valid
// HTML radio value, so we map UI strings ↔ BE field locally.
const BASIS_BY_SCHOOL = "by_school"
const BASIS_BY_PERMANENT_ADDRESS = "permanent_address_special"

export interface PriorityInputsSectionProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

export function PriorityInputsSection({
  form,
  isEditable,
}: PriorityInputsSectionProps) {
  const areaBasis = form.watch("area_resolution_basis")
  const isPermanentAddress = areaBasis === BASIS_BY_PERMANENT_ADDRESS

  return (
    <section
      data-testid="priority-inputs-section"
      className="space-y-4 rounded-lg border border-border bg-card p-4"
    >
      <h3 className="text-base font-semibold">Trình độ &amp; Khu vực</h3>

      {/* Trình độ — văn hóa + nghề */}
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          control={form.control}
          name="cultural_education_level"
          render={({ field }) => (
            <FormItem>
              <FormLabel htmlFor="cultural_education_level">Trình độ văn hóa</FormLabel>
              <Select
                value={field.value ?? ""}
                onValueChange={(v) => field.onChange(v || null)}
                disabled={!isEditable}
              >
                <FormControl>
                  <SelectTrigger
                    id="cultural_education_level"
                    data-testid="cultural-education-level-select"
                  >
                    <SelectValue placeholder="Chọn trình độ văn hóa…" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {CULTURAL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="vocational_qualification"
          render={({ field }) => (
            <FormItem>
              <FormLabel htmlFor="vocational_qualification">Trình độ nghề</FormLabel>
              <Select
                value={field.value ?? ""}
                onValueChange={(v) => field.onChange(v || null)}
                disabled={!isEditable}
              >
                <FormControl>
                  <SelectTrigger
                    id="vocational_qualification"
                    data-testid="vocational-qualification-select"
                  >
                    <SelectValue placeholder="Chọn trình độ nghề…" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {VOCATIONAL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      {/* Cách xác định khu vực — replaces the prior "Bật trường hợp đặc biệt"
          switch. Officer chooses the resolution basis explicitly. */}
      <FormField
        control={form.control}
        name="area_resolution_basis"
        render={({ field }) => {
          const radioValue = isPermanentAddress
            ? BASIS_BY_PERMANENT_ADDRESS
            : BASIS_BY_SCHOOL
          return (
            <FormItem className="space-y-2 rounded-md border border-dashed border-border p-3">
              <FormLabel className="text-sm font-medium">
                Cách xác định khu vực
              </FormLabel>
              <FormControl>
                <RadioGroup
                  value={radioValue}
                  onValueChange={(v) => {
                    // Map UI → BE field: school basis writes null.
                    field.onChange(
                      v === BASIS_BY_PERMANENT_ADDRESS
                        ? BASIS_BY_PERMANENT_ADDRESS
                        : null,
                    )
                  }}
                  disabled={!isEditable}
                  className="gap-2"
                  data-testid="area-resolution-basis-radio"
                >
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem
                      value={BASIS_BY_SCHOOL}
                      id="area-basis-by-school"
                      data-testid="area-basis-by-school"
                    />
                    <label
                      htmlFor="area-basis-by-school"
                      className="text-sm cursor-pointer"
                    >
                      Theo trường học
                    </label>
                  </div>
                  <div className="flex items-center space-x-2">
                    <RadioGroupItem
                      value={BASIS_BY_PERMANENT_ADDRESS}
                      id="area-basis-by-permanent-address"
                      data-testid="area-basis-by-permanent-address"
                    />
                    <label
                      htmlFor="area-basis-by-permanent-address"
                      className="text-sm cursor-pointer"
                    >
                      Theo nơi thường trú
                    </label>
                  </div>
                </RadioGroup>
              </FormControl>
              <FormMessage />
            </FormItem>
          )
        }}
      />

      {/* Commune code (conditional reveal). Short helper text — no
          MOET cardinality copy, no "trường hợp đặc biệt" wording. */}
      {isPermanentAddress && (
        <FormField
          control={form.control}
          name="permanent_commune_code"
          render={({ field }) => (
            <FormItem data-testid="commune-code-field">
              <FormLabel htmlFor="permanent_commune_code">
                Xã/phường thường trú
              </FormLabel>
              <FormControl>
                <Input
                  id="permanent_commune_code"
                  data-testid="permanent-commune-code-input"
                  placeholder="VD: 01_00025"
                  value={field.value ?? ""}
                  onChange={(e) => field.onChange(e.target.value || null)}
                  disabled={!isEditable}
                />
              </FormControl>
              <FormDescription className="text-xs">
                Nhập mã xã/phường nếu hồ sơ thuộc diện tính khu vực theo
                thường trú.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
    </section>
  )
}
