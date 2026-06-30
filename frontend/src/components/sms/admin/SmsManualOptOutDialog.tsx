// src/components/sms/admin/SmsManualOptOutDialog.tsx
"use client"

import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useCreateManualOptOut } from "@/hooks/useSmsAdmin"
import {
  smsManualOptOutSchema,
  type SmsManualOptOutInput,
} from "@/lib/zod/sms"

import { MANUAL_OPT_OUT_SOURCE_OPTIONS } from "./labels"

const DEFAULTS: SmsManualOptOutInput = {
  phone: "",
  source: "manual",
  source_reference: "",
  reason: "",
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Form admin ghi opt-out thủ công (số từ chối nhận tin qua đối tác / điện
 * thoại / SMS reply). BE chuẩn hóa SĐT + idempotent.
 */
export function SmsManualOptOutDialog({ open, onOpenChange }: Props) {
  const mutation = useCreateManualOptOut()

  const form = useForm<SmsManualOptOutInput>({
    resolver: zodResolver(smsManualOptOutSchema),
    defaultValues: DEFAULTS,
  })

  // Reset mỗi khi mở lại để không giữ giá trị lần trước.
  useEffect(() => {
    if (open) form.reset(DEFAULTS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function onSubmit(values: SmsManualOptOutInput) {
    mutation.mutate(
      {
        phone: values.phone,
        source: values.source,
        // "" → undefined: tránh lưu chuỗi rỗng cho field optional.
        source_reference: values.source_reference?.trim() || undefined,
        reason: values.reason?.trim() || undefined,
      },
      {
        onSuccess: () => {
          onOpenChange(false)
          form.reset(DEFAULTS)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Thêm số từ chối nhận tin</DialogTitle>
          <DialogDescription>
            Ghi nhận số điện thoại từ chối quảng cáo qua kênh ngoài trang đích
            (điện thoại, trả lời SMS, đối tác). Hệ thống sẽ chặn gửi ở các chiến
            dịch sau.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="phone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Số điện thoại *</FormLabel>
                  <FormControl>
                    <Input
                      type="tel"
                      inputMode="tel"
                      placeholder="0912345678"
                      autoComplete="off"
                      disabled={mutation.isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="source"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nguồn *</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={mutation.isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {MANUAL_OPT_OUT_SOURCE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
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
              name="source_reference"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tham chiếu nguồn</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: mã ticket, ID cuộc gọi…"
                      disabled={mutation.isPending}
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Lý do</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={3}
                      placeholder="Ghi chú lý do từ chối (không bắt buộc)."
                      disabled={mutation.isPending}
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={mutation.isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Ghi nhận
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
