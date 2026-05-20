/**
 * Q9 #07 Phase E.4 — § 1 Inputs section (cultural + vocational + special-case).
 *
 * Linear 1-column layout per spec Section II:
 *   Trình độ:
 *     Văn hóa:  [select]      ← Tab 1
 *     Nghề:     [select]      ← Tab 2
 *   Trường hợp đặc biệt:
 *     ☐ Bật trường hợp đặc biệt  ← Tab 3
 *        ↳ Mã xã/phường: [input]  ← Tab 4 (conditional reveal)
 *
 * Special-case label per spec: "PTDT nội trú, dự bị ĐH, lớp tạo nguồn,
 * quân nhân/CAND" — same paradigm as KvDecisionPanel.tsx (which this
 * component supersedes per PR-3 cleanup).
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import type { AdmissionProfileUpdateInput } from "@/lib/zod/admissions"

// Mirror BE app/services/priority_service.py _derive_kv_basis_level enum +
// existing KvDecisionPanel constants (kept verbatim cho consistency).
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

export interface PriorityInputsSectionProps {
  form: UseFormReturn<AdmissionProfileUpdateInput>
  isEditable: boolean
}

export function PriorityInputsSection({
  form,
  isEditable,
}: PriorityInputsSectionProps) {
  const areaBasis = form.watch("area_resolution_basis")
  const isSpecialCase = areaBasis === "permanent_address_special"

  return (
    <section
      data-testid="priority-inputs-section"
      className="space-y-4 rounded-lg border border-border bg-card p-4"
    >
      <h3 className="text-base font-semibold">§ 1. Trình độ + Trường hợp đặc biệt</h3>

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

      {/* Trường hợp đặc biệt — switch + commune conditional */}
      <FormField
        control={form.control}
        name="area_resolution_basis"
        render={({ field }) => (
          <FormItem className="space-y-2 rounded-md border border-dashed border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <FormLabel htmlFor="special-case-switch" className="text-sm font-medium">
                  Bật trường hợp đặc biệt
                </FormLabel>
                <FormDescription className="text-xs">
                  PTDT nội trú, dự bị ĐH, lớp tạo nguồn, quân nhân/CAND — KV theo
                  thường trú thay vì trường.
                </FormDescription>
              </div>
              <FormControl>
                <Switch
                  id="special-case-switch"
                  data-testid="special-case-switch"
                  checked={isSpecialCase}
                  onCheckedChange={(checked) =>
                    field.onChange(checked ? "permanent_address_special" : null)
                  }
                  disabled={!isEditable}
                />
              </FormControl>
            </div>
            <FormMessage />
          </FormItem>
        )}
      />

      {/* Commune code (conditional reveal) */}
      {isSpecialCase && (
        <FormField
          control={form.control}
          name="permanent_commune_code"
          render={({ field }) => (
            <FormItem data-testid="commune-code-field">
              <FormLabel htmlFor="permanent_commune_code">
                Mã xã/phường thường trú
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
                Tra cứu trên danh bạ MOET 2025 (893 quận/huyện × 7,453 xã/phường).
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
    </section>
  )
}
