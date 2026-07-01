// src/components/sms/admin/contacts/SmsGroupFormDialog.tsx
"use client"

import { useEffect } from "react"
import { useForm, type Resolver } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import {
  useCreateContactGroup,
  useUpdateContactGroup,
} from "@/hooks/useSmsContacts"
import {
  smsContactGroupCreateSchema,
  smsContactGroupUpdateSchema,
  type SmsContactGroup,
  type SmsContactGroupCreateInput,
  type SmsContactGroupUpdateInput,
} from "@/lib/zod/sms"

import { GROUP_TYPE_OPTIONS } from "../labels"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Có giá trị → chế độ sửa; null → tạo mới. */
  group?: SmsContactGroup | null
}

type FormData = SmsContactGroupCreateInput & { is_active?: boolean }

export function SmsGroupFormDialog({ open, onOpenChange, group }: Props) {
  const isEdit = !!group
  const createMut = useCreateContactGroup()
  const updateMut = useUpdateContactGroup()
  const isPending = createMut.isPending || updateMut.isPending

  const form = useForm<FormData>({
    resolver: zodResolver(
      isEdit ? smsContactGroupUpdateSchema : smsContactGroupCreateSchema,
    ) as Resolver<FormData>,
    defaultValues: {
      name: "",
      code: "",
      group_type: "custom",
      description: "",
      is_active: true,
    },
  })

  useEffect(() => {
    if (!open) return
    if (group) {
      form.reset({
        name: group.name,
        group_type: group.group_type as FormData["group_type"],
        description: group.description ?? "",
        is_active: group.is_active,
      })
    } else {
      form.reset({
        name: "",
        code: "",
        group_type: "custom",
        description: "",
        is_active: true,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, group?.id])

  function onSubmit(values: FormData) {
    const onDone = () => onOpenChange(false)
    if (isEdit && group) {
      // Update: gửi "" (không phải undefined) để CHO PHÉP xoá mô tả (BE
      // exclude_unset bỏ qua undefined = không xoá được).
      const data: SmsContactGroupUpdateInput = {
        name: values.name,
        group_type: values.group_type,
        description: (values.description ?? "").trim(),
        is_active: values.is_active ?? true,
      }
      updateMut.mutate({ id: group.id, data }, { onSuccess: onDone })
    } else {
      const data: SmsContactGroupCreateInput = {
        name: values.name,
        code: values.code?.trim() || undefined,
        group_type: values.group_type,
        description: values.description?.trim() || undefined,
      }
      createMut.mutate(data, { onSuccess: onDone })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Sửa nhóm liên hệ" : "Tạo nhóm liên hệ"}
          </DialogTitle>
          <DialogDescription>
            Nhóm dùng để gom liên hệ và gắn vào chiến dịch SMS.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tên nhóm *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Phụ huynh khối 10 — 2026"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {!isEdit && (
              <FormField
                control={form.control}
                name="code"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mã (slug) — tùy chọn</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="bỏ trống để tự sinh từ tên"
                        disabled={isPending}
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="group_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Loại nhóm *</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {GROUP_TYPE_OPTIONS.map((o) => (
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
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mô tả</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={2}
                      maxLength={2000}
                      placeholder="Ghi chú nội bộ (không bắt buộc)."
                      disabled={isPending}
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {isEdit && (
              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center gap-2 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={isPending}
                      />
                    </FormControl>
                    <FormLabel className="font-normal">
                      Nhóm đang hoạt động
                    </FormLabel>
                  </FormItem>
                )}
              />
            )}

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
