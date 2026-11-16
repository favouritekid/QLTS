"use client"

import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

/** Sáu bước của luồng (đặc tả 1.2): tên đúng bản mẫu. */
export const STEP_FLOW = [
  { step: 1, name: "Chọn hồ sơ" },
  { step: 2, name: "Kiểm tra & chốt" },
  { step: 3, name: "Tham số" },
  { step: 4, name: "Dựng & tải" },
  { step: 5, name: "Đối chiếu bản ký" },
  { step: 6, name: "Ghi nhận" },
] as const

interface Props {
  /** bước đang mở (1–6) */
  current: number
  /** các bước bấm được (phần còn lại hiện mờ, không bấm) — do nơi dùng quyết (theo cờ quyền / trạng thái bộ) */
  canPick: readonly number[]
  onPick: (number: number) => void
}

/** Thanh sáu bước. Chỉ trình bày: bước nào mở được do cha quyết, không tính luật ở đây. */
export function CouncilStepper({ current, canPick, onPick }: Props) {
  return (
    <nav aria-label="Các bước dựng văn bản Hội đồng">
      <ol className="flex flex-wrap items-center gap-2" data-testid="council-stepper">
        {STEP_FLOW.map((b) => {
          const opening = b.step === current
          const passed = b.step < current
          const pressed = canPick.includes(b.step) && !opening
          return (
            <li key={b.step}>
              <button
                type="button"
                disabled={!pressed}
                aria-current={opening ? "step" : undefined}
                data-testid={`buoc-${b.step}`}
                onClick={() => onPick(b.step)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors",
                  opening && "border-primary bg-primary text-primary-foreground",
                  !opening && passed && "border-primary/40 text-foreground",
                  !opening && !passed && "border-border text-muted-foreground",
                  pressed && "hover:bg-muted",
                  !pressed && !opening && "cursor-default opacity-70",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-xs",
                    opening ? "bg-primary-foreground text-primary" : "bg-muted text-muted-foreground",
                  )}
                >
                  {passed ? <Check className="h-3 w-3" /> : b.step}
                </span>
                {b.name}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
