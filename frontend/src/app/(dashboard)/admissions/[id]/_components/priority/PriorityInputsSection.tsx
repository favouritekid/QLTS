/**
 * Q9 #07 Phase E.4 — § 1 Inputs section.
 *
 * Officer chỉ nhập trình độ:
 *   Văn hóa:  [select]      ← Tab 1
 *   Nghề:     [select]      ← Tab 2
 *
 * KV resolution basis là OUTPUT của engine (cultural + vocational + lịch sử
 * học + permanent_commune_code từ tab Thông tin). Officer KHÔNG chọn basis
 * — vi phạm thin-client + nghiệp vụ "hệ thống tự suy ra basis". Display
 * basis derived hiển thị ở §2 EngineResultCard (state + reason + citation).
 *
 * Admin/manager override KV thực hiện qua PriorityOverrideDialog (output
 * bypass), KHÔNG qua field area_resolution_basis ở §1.
 *
 * History (audit cycle 2026-05-21):
 *   - v0: switch "Bật trường hợp đặc biệt" + mã xã input — UX jargon-heavy.
 *   - v1 (cycle 1): radio "Theo trường học / Theo nơi thường trú" + commune
 *     input. Vẫn vi phạm thin-client: officer ÉP basis = bypass engine.
 *   - v2 (THIS): officer chỉ khai trình độ; basis derive ở BE; commune
 *     code source-of-truth ở tab Thông tin (PersonalInfoTab wire qua
 *     AdaptiveAddressSelect).
 */
"use client"

import { UseFormReturn } from "react-hook-form"
import {
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from "@/components/ui/form"
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
  // THCS: từ NH 2025-2026 (Thông tư 10/2026) không còn cấp Bằng TN THCS, thay
  // bằng xác nhận hoàn thành chương trình trong học bạ. Nhãn tránh "(chưa tốt
  // nghiệp)" (gây hiểu nhầm là trượt) → phân biệt rõ "có bằng" vs "không cấp bằng".
  { value: "completed_thcs",  label: "Hoàn thành chương trình THCS (không cấp bằng TN)" },
  { value: "graduated_thcs",  label: "Tốt nghiệp THCS (có bằng)" },
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
  return (
    <section
      data-testid="priority-inputs-section"
      className="space-y-4 rounded-lg border border-border bg-card p-4"
    >
      <h3 className="text-base font-semibold">Trình độ</h3>

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

      {/* Thông báo derived basis — officer biết engine sẽ tự suy ra. */}
      <p
        data-testid="auto-basis-hint"
        className="text-xs text-muted-foreground"
      >
        Hệ thống tự xác định cách tính khu vực ưu tiên dựa trên trình độ +
        địa chỉ thường trú (tab Thông tin) + lịch sử học (tab Học tập).
        Kết quả hiển thị bên dưới.
      </p>
    </section>
  )
}
