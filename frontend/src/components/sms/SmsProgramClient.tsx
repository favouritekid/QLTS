// src/components/sms/SmsProgramClient.tsx
"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, GraduationCap, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { getSmsLanding } from "@/lib/api/sms"
import { useSmsDwellTracker } from "@/hooks/useSmsDwellTracker"

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-card mt-8 w-full max-w-md space-y-4 rounded border p-6 shadow-md md:p-8">
      {children}
    </div>
  )
}

/**
 * Trang 1 ngành (§16.1) — nơi ĐO CHÍNH dwell. Tái dùng landing response để lấy
 * tên trường + thông tin ngành (id/tên/mã/trình độ), KHÔNG gọi thêm endpoint.
 * `useSmsDwellTracker` tự mở session/program-view + heartbeat khi xem trang.
 * Thin-client: chỉ render + gửi tín hiệu, KHÔNG suy luận nghiệp vụ.
 */
export function SmsProgramClient({
  code,
  majorProgramId,
}: {
  code: string
  majorProgramId: number
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["sms-landing", code],
    queryFn: () => getSmsLanding(code),
    retry: false,
  })

  const program = data?.programs.find((p) => p.id === majorProgramId)

  // Chỉ bắt đầu đo khi ngành hợp lệ (có trong danh mục landing).
  useSmsDwellTracker(code, program ? majorProgramId : 0)

  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="text-muted-foreground mt-16 flex items-center gap-2"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải…
      </div>
    )
  }

  if (isError || !data || !program) {
    return (
      <Shell>
        <h1 className="text-lg font-semibold">
          Không tìm thấy ngành hoặc liên kết đã hết hạn
        </h1>
        <Link href={`/lp/${encodeURIComponent(code)}`}>
          <Button variant="outline" className="w-full">
            <ArrowLeft className="mr-2 h-4 w-4" /> Về danh mục ngành
          </Button>
        </Link>
      </Shell>
    )
  }

  return (
    <Shell>
      <header className="text-center">
        <p className="text-primary text-sm font-semibold">{data.school_name}</p>
      </header>

      <div className="flex items-start gap-3">
        <GraduationCap className="text-primary mt-1 h-6 w-6 shrink-0" />
        <div className="space-y-1">
          <h1 className="text-xl font-bold">{program.name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{program.degree_level}</Badge>
            <span className="text-muted-foreground text-xs">
              Mã ngành: {program.code}
            </span>
          </div>
        </div>
      </div>

      <p className="text-muted-foreground text-sm leading-relaxed">
        Bạn đang xem thông tin ngành <strong>{program.name}</strong>. Để được tư
        vấn chi tiết về chương trình, học phí và hồ sơ, vui lòng liên hệ{" "}
        {data.school_name} hoặc để lại thông tin đăng ký.
      </p>

      <hr className="border-border" />

      <Link href={`/lp/${encodeURIComponent(code)}`}>
        <Button variant="outline" className="w-full">
          <ArrowLeft className="mr-2 h-4 w-4" /> Xem ngành khác
        </Button>
      </Link>

      <p className="text-muted-foreground text-center text-xs">
        {data.consent_notice}
      </p>
    </Shell>
  )
}
