// src/app/(dashboard)/admissions/[id]/_components/SendMagicLinkButton.tsx
"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Copy, Loader2, Send, Check } from "lucide-react"
import type { AxiosError } from "axios"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  useSendMagicLink,
  type MagicLinkAction,
  type SendMagicLinkResponse,
} from "@/hooks/admissions/useSendMagicLink"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"

/**
 * W2-1 fix Wave 7 (2026-05-16) — SendMagicLinkButton.
 *
 * Officer/manager generate magic-link cho 3 candidate self-service actions
 * (submit/resubmit/withdraw). Mirror SendConfirmationButton pattern —
 * dialog hiển thị URL + nút Copy cho officer share manual qua Zalo/SMS.
 *
 * Per-action button label + tooltip + dialog title. Parent caller pass
 * `action` prop + permission gate (`can('send_submit_link')` etc.) trước
 * khi mount component để Thin Client compliance.
 *
 * KHÔNG có Celery email auto-send cho Wave 7 MVP. Operator có thể wire
 * Celery task sau khi product clarify Vietnamese template per action.
 */

const ACTION_CONFIG: Record<
  MagicLinkAction,
  {
    buttonLabel: string
    dialogTitle: string
    dialogDescription: string
    successToast: string
  }
> = {
  submit: {
    buttonLabel: "Gửi link nộp hồ sơ",
    dialogTitle: "Liên kết nộp hồ sơ tuyển sinh",
    dialogDescription:
      "Sao chép và gửi liên kết dưới đây cho thí sinh qua Zalo, SMS hoặc " +
      "điện thoại. Thí sinh sẽ cần 4 số cuối CCCD/CMND để xác nhận nộp hồ sơ.",
    successToast: "Đã tạo liên kết nộp hồ sơ",
  },
  resubmit: {
    buttonLabel: "Gửi link nộp lại hồ sơ",
    dialogTitle: "Liên kết nộp lại hồ sơ (sau yêu cầu sửa)",
    dialogDescription:
      "Sao chép và gửi liên kết cho thí sinh đã chỉnh sửa hồ sơ theo yêu " +
      "cầu. Thí sinh sẽ cần 4 số cuối CCCD/CMND để xác nhận nộp lại.",
    successToast: "Đã tạo liên kết nộp lại hồ sơ",
  },
  withdraw: {
    buttonLabel: "Gửi link rút hồ sơ",
    dialogTitle: "Liên kết rút hồ sơ tuyển sinh",
    dialogDescription:
      "Sao chép và gửi liên kết cho thí sinh muốn rút hồ sơ. Thí sinh sẽ " +
      "cần 4 số cuối CCCD/CMND để xác nhận rút hồ sơ.",
    successToast: "Đã tạo liên kết rút hồ sơ",
  },
}

interface Props {
  profileId: number
  action: MagicLinkAction
}

export function SendMagicLinkButton({ profileId, action }: Props) {
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<SendMagicLinkResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const mutation = useSendMagicLink()

  const config = ACTION_CONFIG[action]

  const handleSend = () => {
    mutation.mutate(
      { profileId, action },
      {
        onSuccess: (data) => {
          setResult(data)
          setOpen(true)
          toast.success(config.successToast)
        },
        onError: (err) => {
          handleApiError(err as AxiosError<ApiErrorResponse>, {
            context: `tạo liên kết ${action}`,
          })
        },
      },
    )
  }

  const handleCopy = async () => {
    if (!result?.magic_link_url) return
    try {
      await navigator.clipboard.writeText(result.magic_link_url)
      setCopied(true)
      toast.success("Đã sao chép liên kết")
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Không sao chép được. Vui lòng sao thủ công.")
    }
  }

  const isPending = mutation.isPending

  return (
    <>
      <Button
        variant="outline"
        onClick={handleSend}
        disabled={isPending}
        className="gap-2"
      >
        {isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Send className="h-4 w-4" />
        )}
        {config.buttonLabel}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{config.dialogTitle}</DialogTitle>
            <DialogDescription>{config.dialogDescription}</DialogDescription>
          </DialogHeader>

          <Alert>
            <Send className="h-4 w-4" />
            <AlertTitle>Chia sẻ liên kết thủ công</AlertTitle>
            <AlertDescription>
              Hệ thống không tự động gửi email/SMS. Vui lòng copy URL bên dưới
              và gửi cho thí sinh qua Zalo, SMS, hoặc gọi điện
              {result?.phone ? (
                <>
                  {" "}
                  (<strong>{result.phone}</strong>)
                </>
              ) : null}
              .
            </AlertDescription>
          </Alert>

          <div className="flex items-center gap-2">
            <Input
              readOnly
              value={result?.magic_link_url ?? ""}
              className="font-mono text-xs"
              aria-label={`Liên kết ${action}`}
              onFocus={(e) => e.currentTarget.select()}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleCopy}
              disabled={!result?.magic_link_url}
              aria-label={copied ? "Đã sao chép" : "Sao chép liên kết"}
            >
              {copied ? (
                <Check className="h-4 w-4 text-success-600" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
          </div>

          <p className="text-muted-foreground text-xs">
            Liên kết hết hạn lúc:{" "}
            <strong>
              {result?.token_expires_at
                ? new Date(result.token_expires_at).toLocaleString("vi-VN", {
                    timeZone: "Asia/Ho_Chi_Minh",
                  })
                : "—"}
            </strong>
          </p>

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Đóng
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
