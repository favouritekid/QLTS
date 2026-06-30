// src/components/sms/SmsLandingClient.tsx
"use client"

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { BellOff, CheckCircle2, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { getSmsLanding, postSmsOptOut } from "@/lib/api/sms"

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-card mt-8 w-full max-w-md space-y-4 rounded border p-6 shadow-md md:p-8">
      {children}
    </div>
  )
}

/**
 * Trang landing công khai cho SMS marketing (§19). Thin-client: render ĐÚNG
 * những gì BE trả (KHÔNG suy luận); body là plain text (whitespace-pre-line,
 * KHÔNG render HTML → chống XSS). Opt-out idempotent qua AlertDialog xác nhận.
 */
export function SmsLandingClient({ code }: { code: string }) {
  const [optedOut, setOptedOut] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["sms-landing", code],
    queryFn: () => getSmsLanding(code),
    retry: false,
  })

  const optOut = useMutation({
    mutationFn: () => postSmsOptOut(code),
    onSuccess: () => setOptedOut(true),
  })

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

  if (isError || !data) {
    return (
      <Shell>
        <h1 className="text-lg font-semibold">
          Liên kết không hợp lệ hoặc đã hết hạn
        </h1>
        <p className="text-muted-foreground text-sm">
          Vui lòng kiểm tra lại đường liên kết trong tin nhắn.
        </p>
      </Shell>
    )
  }

  const isOptedOut = optedOut || data.already_opted_out

  return (
    <Shell>
      <header className="text-center">
        <p className="text-primary text-base font-semibold">
          {data.school_name}
        </p>
      </header>

      {data.headline && (
        <h1 className="text-xl font-bold">{data.headline}</h1>
      )}
      {data.body && (
        <p className="text-sm leading-relaxed whitespace-pre-line">
          {data.body}
        </p>
      )}

      {data.cta_label && data.cta_url && (
        <a href={data.cta_url} rel="noreferrer" target="_blank">
          <Button className="w-full">{data.cta_label}</Button>
        </a>
      )}

      <hr className="border-border" />

      <section className="space-y-3">
        <p className="text-muted-foreground text-xs">{data.consent_notice}</p>

        {isOptedOut ? (
          <p className="flex items-center gap-2 text-sm font-medium text-green-700">
            <CheckCircle2 className="h-4 w-4" /> Đã hủy nhận tin. Bạn sẽ không
            nhận tin quảng cáo từ {data.school_name} nữa.
          </p>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="outline"
                className="w-full"
                disabled={optOut.isPending}
              >
                <BellOff className="mr-2 h-4 w-4" /> Hủy nhận tin
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Hủy nhận tin?</AlertDialogTitle>
                <AlertDialogDescription>
                  Bạn chắc chắn muốn ngừng nhận tin quảng cáo tuyển sinh từ{" "}
                  {data.school_name}?
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Không</AlertDialogCancel>
                <AlertDialogAction onClick={() => optOut.mutate()}>
                  Hủy nhận tin
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}

        {optOut.isError && (
          <p className="text-destructive text-xs">
            Không thể hủy lúc này. Vui lòng thử lại.
          </p>
        )}
      </section>
    </Shell>
  )
}
