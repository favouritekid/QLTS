"use client"

import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

/** Sáu bước của luồng (đặc tả 1.2): tên đúng bản mẫu. */
export const BUOC_LUONG = [
  { so: 1, ten: "Chọn hồ sơ" },
  { so: 2, ten: "Kiểm tra & chốt" },
  { so: 3, ten: "Tham số" },
  { so: 4, ten: "Dựng & tải" },
  { so: 5, ten: "Đối chiếu bản ký" },
  { so: 6, ten: "Ghi nhận" },
] as const

interface Props {
  /** bước đang mở (1–6) */
  hienTai: number
  /** các bước bấm được (phần còn lại hiện mờ, không bấm) — do nơi dùng quyết (theo cờ quyền / trạng thái bộ) */
  choPhepChon: readonly number[]
  onChon: (so: number) => void
}

/** Thanh sáu bước. Chỉ trình bày: bước nào mở được do cha quyết, không tính luật ở đây. */
export function CouncilStepper({ hienTai, choPhepChon, onChon }: Props) {
  return (
    <nav aria-label="Các bước dựng văn bản Hội đồng">
      <ol className="flex flex-wrap items-center gap-2" data-testid="council-stepper">
        {BUOC_LUONG.map((b) => {
          const dangMo = b.so === hienTai
          const daQua = b.so < hienTai
          const bam = choPhepChon.includes(b.so) && !dangMo
          return (
            <li key={b.so}>
              <button
                type="button"
                disabled={!bam}
                aria-current={dangMo ? "step" : undefined}
                data-testid={`buoc-${b.so}`}
                onClick={() => onChon(b.so)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors",
                  dangMo && "border-primary bg-primary text-primary-foreground",
                  !dangMo && daQua && "border-primary/40 text-foreground",
                  !dangMo && !daQua && "border-border text-muted-foreground",
                  bam && "hover:bg-muted",
                  !bam && !dangMo && "cursor-default opacity-70",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-xs",
                    dangMo ? "bg-primary-foreground text-primary" : "bg-muted text-muted-foreground",
                  )}
                >
                  {daQua ? <Check className="h-3 w-3" /> : b.so}
                </span>
                {b.ten}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
