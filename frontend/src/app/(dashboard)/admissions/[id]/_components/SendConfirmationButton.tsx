// src/app/(dashboard)/admissions/[id]/_components/SendConfirmationButton.tsx
"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Copy, Mail, Loader2, Send, Check } from "lucide-react"
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
  useSendConfirmation,
  type SendConfirmationResponse,
} from "@/hooks/admissions/useSendConfirmation"
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"

interface Props {
  profileId: number
  /** Only render when profile is eligible (status=approved and up).
   *  Parent decides via permissions / status — keep this component dumb. */
}

/**
 * Officer-facing button: triggers POST /send-confirmation and opens a
 * dialog with the resulting confirm_url so the officer can copy it and
 * share via Zalo/SMS/phone when the applicant has no email.
 *
 * Even when the email was queued successfully, surfacing the URL is
 * valuable because:
 *   - SMTP may bounce (spam, invalid inbox)
 *   - Officer often needs a fallback channel (Zalo is the norm in VN)
 */
export function SendConfirmationButton({ profileId }: Props) {
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<SendConfirmationResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const mutation = useSendConfirmation()

  const handleSend = () => {
    mutation.mutate(profileId, {
      onSuccess: (data) => {
        setResult(data)
        setOpen(true)
        // No-email path: the system only minted a token, operator must
        // share the link manually. Saying "đã gửi email" here contradicts
        // the dialog's own destructive alert below.
        toast.success(
          data.sent_to_email
            ? "Đã gửi email xác nhận"
            : "Đã tạo liên kết xác nhận",
        )
      },
      onError: (err) => {
        handleApiError(err as AxiosError<ApiErrorResponse>, {
          context: "gửi liên kết xác nhận",
        })
      },
    })
  }

  const handleCopy = async () => {
    if (!result?.confirm_url) return
    try {
      await navigator.clipboard.writeText(result.confirm_url)
      setCopied(true)
      toast.success("Đã sao chép liên kết")
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Không sao chép được. Vui lòng sao thủ công.")
    }
  }

  const isPending = mutation.isPending
  const emailWasQueued = Boolean(result?.sent_to_email)

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
        Gửi liên kết xác nhận
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Liên kết xác nhận nhập học</DialogTitle>
            <DialogDescription>
              Sao chép và gửi liên kết dưới đây cho thí sinh qua Zalo, SMS hoặc
              điện thoại. Thí sinh sẽ cần 4 số cuối CCCD/CMND để xác nhận.
            </DialogDescription>
          </DialogHeader>

          {emailWasQueued ? (
            <Alert>
              <Mail className="h-4 w-4" />
              <AlertTitle>Đã gửi email</AlertTitle>
              <AlertDescription>
                Hệ thống đã gửi email đến <strong>{result?.sent_to_email}</strong>.
                Bạn vẫn có thể copy liên kết dưới đây để gửi qua kênh phụ.
              </AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive">
              <Mail className="h-4 w-4" />
              <AlertTitle>Thí sinh chưa có email</AlertTitle>
              <AlertDescription>
                Hệ thống chưa gửi email. Vui lòng sao chép liên kết và gửi thủ công qua
                Zalo, SMS, hoặc gọi điện cho thí sinh
                {result?.phone ? (
                  <>
                    {" "}
                    ({<strong>{result.phone}</strong>})
                  </>
                ) : null}
                .
              </AlertDescription>
            </Alert>
          )}

          <div className="flex items-center gap-2">
            <Input
              readOnly
              value={result?.confirm_url ?? ""}
              className="font-mono text-xs"
              aria-label="Liên kết xác nhận"
              onFocus={(e) => e.currentTarget.select()}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleCopy}
              disabled={!result?.confirm_url}
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
