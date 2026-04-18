// src/components/forms/ConfirmAdmissionForm.tsx
"use client"

import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import * as z from "zod"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  CheckCircle2,
  AlertTriangle,
  Clock,
  Lock,
  Loader2,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  admissionConfirmKeys,
  useConfirmAdmission,
  useConfirmTokenInfo,
} from "@/hooks/admissions/useAdmissionConfirm"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import type { AxiosError } from "axios"

// ---------------------------------------------------------------------------
// Schema (mirrors ConfirmTokenVerifyRequestSchema in lib/zod/admissions.ts)
// ---------------------------------------------------------------------------
const formSchema = z.object({
  last_digits_citizen_id: z
    .string()
    .regex(/^\d{4}$/, "Vui lòng nhập đủ 4 chữ số"),
})
type FormValues = z.infer<typeof formSchema>

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      {children}
    </div>
  )
}

function SpinnerState() {
  return (
    <PageShell>
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center gap-3 py-8 text-muted-foreground"
      >
        <Loader2 className="h-8 w-8 animate-spin" />
        <span>Đang tải thông tin xác nhận…</span>
      </div>
    </PageShell>
  )
}

function ErrorBanner({
  icon: Icon,
  title,
  description,
  tone = "destructive",
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
  tone?: "destructive" | "default"
}) {
  return (
    <PageShell>
      <Alert variant={tone === "destructive" ? "destructive" : "default"}>
        <Icon className="h-4 w-4" />
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription>{description}</AlertDescription>
      </Alert>
      <p className="text-muted-foreground text-center text-sm">
        Nếu cần hỗ trợ, vui lòng liên hệ cán bộ tuyển sinh qua hotline của Nhà trường.
      </p>
    </PageShell>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ConfirmAdmissionForm({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const { data: info, isLoading, isError } = useConfirmTokenInfo(token)
  const confirmMutation = useConfirmAdmission(token)
  const [isConfirmed, setIsConfirmed] = useState(false)

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { last_digits_citizen_id: "" },
    mode: "onSubmit",
  })

  // --- loading / error states -------------------------------------------
  if (isLoading) return <SpinnerState />

  if (isError || !info) {
    return (
      <ErrorBanner
        icon={AlertTriangle}
        title="Không tìm thấy liên kết"
        description="Liên kết xác nhận không hợp lệ hoặc đã bị xoá. Vui lòng kiểm tra lại email hoặc liên hệ cán bộ tuyển sinh để được cấp lại."
      />
    )
  }

  // --- success (after client-side confirm) -------------------------------
  if (isConfirmed) {
    return (
      <PageShell>
        <Alert>
          <CheckCircle2 className="h-4 w-4" />
          <AlertTitle>Xác nhận nhập học thành công</AlertTitle>
          <AlertDescription>
            Cảm ơn <strong>{info.profile_name}</strong> đã xác nhận. Nhà trường sẽ liên hệ
            với bạn trong vòng <strong>3 ngày làm việc</strong> để hướng dẫn các bước tiếp theo.
          </AlertDescription>
        </Alert>
      </PageShell>
    )
  }

  // --- terminal states returned by backend -------------------------------
  if (info.already_used) {
    return (
      <ErrorBanner
        icon={CheckCircle2}
        tone="default"
        title="Đã xác nhận trước đó"
        description={`Hồ sơ của ${info.profile_name} đã được xác nhận trước đây. Bạn không cần thao tác thêm.`}
      />
    )
  }

  if (info.locked) {
    return (
      <ErrorBanner
        icon={Lock}
        title="Liên kết đã bị khoá"
        description="Bạn đã nhập sai CCCD quá số lần cho phép. Vui lòng liên hệ cán bộ tuyển sinh để được cấp lại liên kết."
      />
    )
  }

  if (info.expired) {
    return (
      <ErrorBanner
        icon={Clock}
        tone="default"
        title="Liên kết đã hết hạn"
        description="Liên kết xác nhận đã hết hạn. Vui lòng liên hệ cán bộ tuyển sinh để được cấp liên kết mới."
      />
    )
  }

  if (!info.valid) {
    return (
      <ErrorBanner
        icon={AlertTriangle}
        title="Liên kết không hợp lệ"
        description="Liên kết xác nhận không hợp lệ. Vui lòng liên hệ cán bộ tuyển sinh."
      />
    )
  }

  // --- happy path: form ---------------------------------------------------
  const onSubmit = (values: FormValues) => {
    confirmMutation.mutate(values, {
      onSuccess: () => {
        toast.success("Xác nhận nhập học thành công!")
        setIsConfirmed(true)
      },
      onError: (err) => {
        handleApiError(err as AxiosError<ApiErrorResponse>, {
          context: "xác nhận nhập học",
        })
        // Backend commits attempt_count / locked_at on 400 and 429, so the
        // cached token info is now stale. Invalidate → useQuery refetches →
        // component re-renders with the fresh attempts_remaining / locked
        // state without forcing the user to reload.
        queryClient.invalidateQueries({
          queryKey: admissionConfirmKeys.tokenInfo(token),
        })
        // Clear input so the user can re-enter cleanly.
        form.reset({ last_digits_citizen_id: "" })
      },
    })
  }

  const isPending = confirmMutation.isPending
  const attemptsRemaining = info.attempts_remaining
  const showAttemptsHint = attemptsRemaining > 0 && attemptsRemaining < 5

  return (
    <PageShell>
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold font-display">Xác nhận nhập học</h1>
        <p className="text-muted-foreground text-sm">
          Xin chào <strong>{info.profile_name}</strong>.
        </p>
        <p className="text-muted-foreground text-sm">
          Vui lòng nhập <strong>4 số cuối CCCD/CMND</strong> của bạn để xác nhận hồ sơ.
        </p>
        {showAttemptsHint && (
          <p className="text-sm text-amber-600" role="status" aria-live="polite">
            Còn <strong>{attemptsRemaining}</strong> lần thử trước khi liên kết bị khoá.
          </p>
        )}
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          <FormField
            control={form.control}
            name="last_digits_citizen_id"
            render={({ field }) => (
              <FormItem className="flex flex-col items-center">
                <FormLabel>4 số cuối CCCD/CMND</FormLabel>
                <FormControl>
                  <InputOTP
                    maxLength={4}
                    value={field.value}
                    onChange={field.onChange}
                    inputMode="numeric"
                    pattern="\d*"
                    disabled={isPending}
                  >
                    <InputOTPGroup>
                      <InputOTPSlot index={0} />
                      <InputOTPSlot index={1} />
                      <InputOTPSlot index={2} />
                      <InputOTPSlot index={3} />
                    </InputOTPGroup>
                  </InputOTP>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? "Đang xác nhận…" : "Xác nhận nhập học"}
          </Button>
        </form>
      </Form>

      <p className="text-muted-foreground text-center text-xs">
        Nếu bạn không nộp hồ sơ vào Nhà trường, vui lòng bỏ qua email và liên kết này.
      </p>
    </PageShell>
  )
}
