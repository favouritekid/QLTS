// src/components/sms/admin/contacts/SmsContactFormDialog.tsx
"use client"

import { useEffect } from "react"
import { useForm, type Resolver } from "react-hook-form"
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
import { Textarea } from "@/components/ui/textarea"
import { useCreateContact, useUpdateContact } from "@/hooks/useSmsContacts"
import {
  smsContactCreateSchema,
  smsContactUpdateSchema,
  type SmsContact,
  type SmsContactCreateInput,
  type SmsContactUpdateInput,
} from "@/lib/zod/sms"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  contact?: SmsContact | null
}

type FormData = SmsContactCreateInput

export function SmsContactFormDialog({ open, onOpenChange, contact }: Props) {
  const isEdit = !!contact
  const createMut = useCreateContact()
  const updateMut = useUpdateContact()
  const isPending = createMut.isPending || updateMut.isPending

  const form = useForm<FormData>({
    resolver: zodResolver(
      isEdit ? smsContactUpdateSchema : smsContactCreateSchema,
    ) as unknown as Resolver<FormData>,
    defaultValues: { full_name: "", phone: "", note: "", source_label: "" },
  })

  useEffect(() => {
    if (!open) return
    if (contact) {
      form.reset({
        full_name: contact.full_name,
        phone: contact.phone_normalized,
        note: contact.note ?? "",
        source_label: contact.source_label ?? "",
      })
    } else {
      form.reset({ full_name: "", phone: "", note: "", source_label: "" })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contact?.id])

  function onSubmit(values: FormData) {
    const onDone = () => onOpenChange(false)
    if (isEdit && contact) {
      // Update: gửi "" (không phải undefined) để CHO PHÉP xoá field — BE dùng
      // exclude_unset nên undefined bị bỏ qua = không xoá được.
      const data: SmsContactUpdateInput = {
        full_name: values.full_name,
        note: (values.note ?? "").trim(),
        source_label: (values.source_label ?? "").trim(),
      }
      updateMut.mutate({ id: contact.id, data }, { onSuccess: onDone })
    } else {
      const data: SmsContactCreateInput = {
        full_name: values.full_name,
        phone: values.phone,
        note: values.note?.trim() || undefined,
        source_label: values.source_label?.trim() || undefined,
      }
      createMut.mutate(data, { onSuccess: onDone })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Sửa liên hệ" : "Tạo liên hệ"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Không đổi được số điện thoại (định danh). Consent ghi qua sự kiện riêng."
              : "Liên hệ mới mặc định trạng thái consent “chưa rõ”."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Họ tên *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Nguyễn Văn A"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                      disabled={isPending || isEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="source_label"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nhãn nguồn</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Hội thảo 06/2026"
                      maxLength={255}
                      disabled={isPending}
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
              name="note"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ghi chú</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={2}
                      maxLength={2000}
                      disabled={isPending}
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
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEdit ? "Lưu" : "Tạo"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
