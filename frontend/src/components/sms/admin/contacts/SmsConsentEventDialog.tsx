// src/components/sms/admin/contacts/SmsConsentEventDialog.tsx
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
import { useAppendConsentEvent } from "@/hooks/useSmsContacts"
import {
  smsConsentEventCreateSchema,
  type SmsConsentEventCreateInput,
} from "@/lib/zod/sms"

import { CONSENT_BASIS_OPTIONS, REVOKE_SOURCE_OPTIONS } from "../labels"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  contactId: number
}

const DEFAULTS: SmsConsentEventCreateInput = {
  event_type: "granted",
  occurred_at: "",
  basis: undefined,
  disclosure_version: "",
  proof_reference: "",
  revoke_source: undefined,
}

export function SmsConsentEventDialog({
  open,
  onOpenChange,
  contactId,
}: Props) {
  const mutation = useAppendConsentEvent()
  const form = useForm<SmsConsentEventCreateInput>({
    resolver: zodResolver(smsConsentEventCreateSchema),
    defaultValues: DEFAULTS,
  })
  const eventType = form.watch("event_type")

  useEffect(() => {
    if (open) form.reset(DEFAULTS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function onSubmit(values: SmsConsentEventCreateInput) {
    // occurred_at từ datetime-local (naive) → ISO tz-aware (Z). Chỉ gửi field
    // hợp lệ theo event_type để khớp ràng buộc BE (no grant-data khi revoke).
    const parsed = new Date(values.occurred_at)
    if (Number.isNaN(parsed.getTime())) {
      form.setError("occurred_at", { message: "Thời điểm không hợp lệ" })
      return
    }
    const occurredIso = parsed.toISOString()
    const data: SmsConsentEventCreateInput =
      values.event_type === "granted"
        ? {
            event_type: "granted",
            occurred_at: occurredIso,
            basis: values.basis,
            disclosure_version: values.disclosure_version?.trim(),
            proof_reference: values.proof_reference?.trim(),
          }
        : {
            event_type: "revoked",
            occurred_at: occurredIso,
            revoke_source: values.revoke_source,
          }
    mutation.mutate(
      { contactId, data },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Ghi sự kiện consent</DialogTitle>
          <DialogDescription>
            Ledger consent là append-only. GRANT cần đủ căn cứ + công bố + bằng
            chứng; REVOKE cần nguồn từ chối.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="event_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Loại sự kiện *</FormLabel>
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
                      <SelectItem value="granted">Đồng ý (grant)</SelectItem>
                      <SelectItem value="revoked">Từ chối (revoke)</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="occurred_at"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Thời điểm xảy ra *</FormLabel>
                  <FormControl>
                    <Input
                      type="datetime-local"
                      disabled={mutation.isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {eventType === "granted" ? (
              <>
                <FormField
                  control={form.control}
                  name="basis"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Căn cứ *</FormLabel>
                      <Select
                        value={field.value ?? ""}
                        onValueChange={field.onChange}
                        disabled={mutation.isPending}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="— Chọn căn cứ —" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {CONSENT_BASIS_OPTIONS.map((o) => (
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
                  name="disclosure_version"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Phiên bản công bố *</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="VD: v2026.1"
                          maxLength={50}
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
                  name="proof_reference"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tham chiếu bằng chứng *</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="VD: link scan, mã hồ sơ"
                          maxLength={512}
                          disabled={mutation.isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            ) : (
              <FormField
                control={form.control}
                name="revoke_source"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Nguồn từ chối *</FormLabel>
                    <Select
                      value={field.value ?? ""}
                      onValueChange={field.onChange}
                      disabled={mutation.isPending}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="— Chọn nguồn —" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {REVOKE_SOURCE_OPTIONS.map((o) => (
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
            )}

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
