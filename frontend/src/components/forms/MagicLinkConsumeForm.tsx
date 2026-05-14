// src/components/forms/MagicLinkConsumeForm.tsx
"use client"

import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { toast } from "sonner"
import {
  CheckCircle2,
  AlertTriangle,
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
import { useMagicLinkConsume } from "@/hooks/admissions/useMagicLink"
import {
  magicLinkConsumeRequestSchema,
  type MagicLinkAction,
  type MagicLinkConsumeRequest,
  type MagicLinkConsumeResponse,
} from "@/lib/zod/magic-link"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"
import type { AxiosError } from "axios"

// ---------------------------------------------------------------------------
// Per-action copy. Pure config — no business logic (thin client).
// Each entry mirrors the four enum members of MagicLinkAction so the
// TypeScript exhaustiveness check covers the lot.
// ---------------------------------------------------------------------------
const ACTION_COPY: Record<
  MagicLinkAction,
  {
    title: string
    instruction: string
    submitLabel: string
    submittingLabel: string
    successTitle: string
    successDescription: (profileName: string | null) => string
  }
> = {
  confirm: {
    title: "Xác nhận nhập học",
    instruction:
      "Nhập 4 số cuối CCCD/CMND để xác nhận hồ sơ nhập học của bạn.",
    submitLabel: "Xác nhận nhập học",
    submittingLabel: "Đang xác nhận…",
    successTitle: "Xác nhận nhập học thành công",
    successDescription: (name) =>
      `Cảm ơn ${name ?? "bạn"} đã xác nhận. Nhà trường sẽ liên hệ trong vòng 3 ngày làm việc.`,
  },
  submit: {
    title: "Gửi hồ sơ tuyển sinh",
    instruction:
      "Nhập 4 số cuối CCCD/CMND để gửi hồ sơ tuyển sinh của bạn.",
    submitLabel: "Gửi hồ sơ",
    submittingLabel: "Đang gửi…",
    successTitle: "Đã gửi hồ sơ tuyển sinh",
    successDescription: () =>
      "Hồ sơ của bạn đã được gửi và đang chờ Nhà trường xét duyệt.",
  },
  resubmit: {
    title: "Nộp lại hồ sơ",
    instruction:
      "Nhập 4 số cuối CCCD/CMND để nộp lại hồ sơ sau khi đã chỉnh sửa.",
    submitLabel: "Nộp lại",
    submittingLabel: "Đang nộp lại…",
    successTitle: "Đã nộp lại hồ sơ",
    successDescription: () =>
      "Hồ sơ chỉnh sửa của bạn đã được nộp lại và đang chờ xét duyệt.",
  },
  withdraw: {
    title: "Rút hồ sơ tuyển sinh",
    instruction:
      "Nhập 4 số cuối CCCD/CMND để xác nhận rút hồ sơ tuyển sinh.",
    submitLabel: "Xác nhận rút hồ sơ",
    submittingLabel: "Đang xử lý…",
    successTitle: "Đã rút hồ sơ",
    successDescription: () =>
      "Hồ sơ tuyển sinh của bạn đã được rút theo yêu cầu.",
  },
}

// ---------------------------------------------------------------------------
// Small presentational helpers (consistent with ConfirmAdmissionForm).
// ---------------------------------------------------------------------------
function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      {children}
    </div>
  )
}

function SuccessBanner({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <PageShell>
      <Alert>
        <CheckCircle2 className="h-4 w-4" />
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription>{description}</AlertDescription>
      </Alert>
    </PageShell>
  )
}

function ActionRouteErrorBanner() {
  return (
    <PageShell>
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Liên kết không hợp lệ</AlertTitle>
        <AlertDescription>
          Đường dẫn không thuộc một trong các thao tác được hỗ trợ. Vui lòng
          kiểm tra lại email hoặc liên hệ cán bộ tuyển sinh.
        </AlertDescription>
      </Alert>
    </PageShell>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export type MagicLinkConsumeFormProps = {
  action: MagicLinkAction
  token: string
}

export function MagicLinkConsumeForm({
  action,
  token,
}: MagicLinkConsumeFormProps) {
  const copy = ACTION_COPY[action]
  const consumeMutation = useMagicLinkConsume(action, token)
  const [result, setResult] = useState<MagicLinkConsumeResponse | null>(null)

  const form = useForm<MagicLinkConsumeRequest>({
    resolver: zodResolver(magicLinkConsumeRequestSchema),
    defaultValues: { cccd: "" },
    mode: "onSubmit",
  })

  // Should never trigger at runtime — TypeScript exhaustiveness covers it,
  // but render a safe banner if a stray action value ever leaks in.
  if (!copy) {
    return <ActionRouteErrorBanner />
  }

  // Success state — BE consumed the token + returned profile snapshot.
  if (result) {
    return (
      <SuccessBanner
        title={copy.successTitle}
        description={copy.successDescription(null)}
      />
    )
  }

  const onSubmit = (values: MagicLinkConsumeRequest) => {
    consumeMutation.mutate(values, {
      onSuccess: (data) => {
        toast.success(copy.successTitle)
        setResult(data)
      },
      onError: (err) => {
        handleApiError(err as AxiosError<ApiErrorResponse>, {
          context: copy.submitLabel.toLowerCase(),
        })
        // Clear the input so the user can re-enter cleanly after a 400.
        form.reset({ cccd: "" })
      },
    })
  }

  const isPending = consumeMutation.isPending

  return (
    <PageShell>
      <div className="space-y-2 text-center">
        <h1 className="font-display text-2xl font-bold">{copy.title}</h1>
        <p className="text-muted-foreground text-sm">{copy.instruction}</p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          <FormField
            control={form.control}
            name="cccd"
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

          <Button
            type="submit"
            className="w-full"
            disabled={isPending}
            data-testid="magic-link-submit"
          >
            {isPending ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                {copy.submittingLabel}
              </span>
            ) : (
              copy.submitLabel
            )}
          </Button>
        </form>
      </Form>

      <p className="text-muted-foreground text-center text-xs">
        Nếu bạn không gửi yêu cầu này, vui lòng bỏ qua email và liên kết.
      </p>
    </PageShell>
  )
}
