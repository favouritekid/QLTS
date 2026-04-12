"use client";

import { useState } from "react";
import { Plus, Trash2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CurrencyInput } from "@/components/ui/currency-input";
import type { SemesterTuitionBulkUpsertItem } from "@/types/organization.types";

interface SemesterTuitionEditorProps {
  value: SemesterTuitionBulkUpsertItem[];
  onChange: (items: SemesterTuitionBulkUpsertItem[]) => void;
  durationSemesters?: number | null;
  disabled?: boolean;
}

export function SemesterTuitionEditor({
  value,
  onChange,
  durationSemesters,
  disabled = false,
}: SemesterTuitionEditorProps) {
  const [errors, setErrors] = useState<Record<number, string>>({});

  const nextSemesterNo = () => {
    if (value.length === 0) return 1;
    return Math.max(...value.map((v) => v.semester_no)) + 1;
  };

  const addRow = () => {
    const next = nextSemesterNo();
    onChange([...value, { semester_no: next, amount: 0 }]);
  };

  const removeRow = (index: number) => {
    const updated = value.filter((_, i) => i !== index);
    onChange(updated);
    setErrors((prev) => {
      const copy = { ...prev };
      delete copy[index];
      return copy;
    });
  };

  const updateRow = (
    index: number,
    field: keyof SemesterTuitionBulkUpsertItem,
    val: number | string | null
  ) => {
    const updated = value.map((item, i) => {
      if (i !== index) return item;
      return { ...item, [field]: val };
    });

    const newErrors: Record<number, string> = {};
    const semNos = updated.map((r) => r.semester_no);
    const seen = new Set<number>();
    for (let i = 0; i < semNos.length; i++) {
      if (semNos[i] < 1) {
        newErrors[i] = "Phải >= 1";
      } else if (seen.has(semNos[i])) {
        newErrors[i] = "Trùng lặp";
      }
      seen.add(semNos[i]);
    }
    setErrors(newErrors);
    onChange(updated);
  };

  const autoPopulate = () => {
    if (!durationSemesters || durationSemesters < 1) return;
    const existingSemesters = new Set(value.map((v) => v.semester_no));
    const newItems: SemesterTuitionBulkUpsertItem[] = [...value];
    for (let i = 1; i <= durationSemesters; i++) {
      if (!existingSemesters.has(i)) {
        newItems.push({ semester_no: i, amount: 0 });
      }
    }
    newItems.sort((a, b) => a.semester_no - b.semester_no);
    onChange(newItems);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">
          Bảng học phí theo học kỳ
        </h4>
        <div className="flex gap-2">
          {durationSemesters && durationSemesters > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={autoPopulate}
              disabled={disabled}
            >
              <Wand2 className="mr-1.5 h-3.5 w-3.5" />
              Tạo nhanh ({durationSemesters} HK)
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addRow}
            disabled={disabled}
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Thêm học kỳ
          </Button>
        </div>
      </div>

      {value.length === 0 ? (
        <p className="text-muted-foreground text-sm italic">
          Chưa có học phí theo học kỳ. Nhấn &quot;Thêm học kỳ&quot; hoặc
          &quot;Tạo nhanh&quot; để bắt đầu.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-[80px_1fr_1fr_40px] gap-2 text-xs font-medium text-muted-foreground px-1">
            <span>Học kỳ</span>
            <span>Học phí (VND)</span>
            <span>Ghi chú</span>
            <span />
          </div>
          {value.map((item, index) => (
            <div
              key={index}
              className="grid grid-cols-[80px_1fr_1fr_40px] gap-2 items-start"
            >
              <div>
                <Input
                  type="number"
                  min={1}
                  value={item.semester_no}
                  onChange={(e) =>
                    updateRow(index, "semester_no", parseInt(e.target.value) || 1)
                  }
                  disabled={disabled}
                  className={errors[index] ? "border-destructive" : ""}
                />
                {errors[index] && (
                  <p className="text-destructive text-xs mt-0.5">
                    {errors[index]}
                  </p>
                )}
              </div>
              <CurrencyInput
                value={item.amount}
                onChange={(val) => updateRow(index, "amount", val ?? 0)}
                disabled={disabled}
                currency="VND"
                locale="vi-VN"
                placeholder="0"
              />
              <Input
                value={item.notes ?? ""}
                onChange={(e) =>
                  updateRow(index, "notes", e.target.value || null)
                }
                disabled={disabled}
                placeholder="Ghi chú (tùy chọn)"
                maxLength={500}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeRow(index)}
                disabled={disabled}
                className="h-9 w-9 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {Object.keys(errors).length > 0 && (
        <p className="text-destructive text-xs">
          Vui lòng sửa lỗi ở các hàng được đánh dấu trước khi lưu.
        </p>
      )}
    </div>
  );
}
