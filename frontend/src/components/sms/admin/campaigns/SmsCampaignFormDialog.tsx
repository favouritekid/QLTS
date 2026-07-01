// src/components/sms/admin/campaigns/SmsCampaignFormDialog.tsx
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
  FormDescription,
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
  useCreateSmsCampaign,
  useUpdateSmsCampaign,
} from "@/hooks/useSmsCampaigns"
import {
  smsCampaignCreateSchema,
  smsCampaignUpdateSchema,
  type SmsCampaign,
  type SmsCampaignCreateInput,
} from "@/lib/zod/sms"

import { LANDING_TYPE_OPTIONS, isoToDatetimeLocal } from "../labels"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Có giá trị → sửa (chỉ khi draft); null → tạo. */
  campaign?: SmsCampaign | null
  onCreated?: (c: SmsCampaign) => void
}

type FormData = SmsCampaignCreateInput

const DEFAULTS: FormData = {
  name: "",
  code: "",
  sms_template: "",
  landing_type: "qlts_hosted",
  landing_url: "",
  landing_headline: "",
  landing_body: "",
  landing_cta_label: "",
  landing_cta_url: "",
  frequency_cap_days: undefined,
  link_expires_at: "",
}

export function SmsCampaignFormDialog({
  open,
  onOpenChange,
  campaign,
  onCreated,
}: Props) {
  const isEdit = !!campaign
  const createMut = useCreateSmsCampaign()
  const updateMut = useUpdateSmsCampaign()
  const isPending = createMut.isPending || updateMut.isPending

  const form = useForm<FormData>({
    resolver: zodResolver(
      isEdit ? smsCampaignUpdateSchema : smsCampaignCreateSchema,
    ) as unknown as Resolver<FormData>,
    defaultValues: DEFAULTS,
  })
  const landingType = form.watch("landing_type")

  useEffect(() => {
    if (!open) return
    if (campaign) {
      form.reset({
        name: campaign.name,
        code: campaign.code,
        sms_template: campaign.sms_template,
        landing_type: campaign.landing_type as FormData["landing_type"],
        landing_url: campaign.landing_url ?? "",
        landing_headline: campaign.landing_headline ?? "",
        landing_body: campaign.landing_body ?? "",
        landing_cta_label: campaign.landing_cta_label ?? "",
        landing_cta_url: campaign.landing_cta_url ?? "",
        frequency_cap_days: campaign.frequency_cap_days ?? undefined,
        // BE trả UTC → đổi sang giờ local cho datetime-local (tránh lệch offset).
        link_expires_at: isoToDatetimeLocal(campaign.link_expires_at),
      })
    } else {
      form.reset(DEFAULTS)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campaign?.id])

  function onSubmit(values: FormData) {
    const isExternal = values.landing_type === "external"
    // Chỉ giữ field landing đúng loại (external→url; hosted→headline/body/cta);
    // field không thuộc loại → "" để không lưu dữ liệu chéo cũ (finding #3).
    const t = (v?: string | null) => (v ?? "").trim()
    const landing = {
      landing_url: isExternal ? t(values.landing_url) : "",
      landing_headline: isExternal ? "" : t(values.landing_headline),
      landing_body: isExternal ? "" : t(values.landing_body),
      landing_cta_label: isExternal ? "" : t(values.landing_cta_label),
      landing_cta_url: isExternal ? "" : t(values.landing_cta_url),
    }
    const linkIso = values.link_expires_at
      ? new Date(values.link_expires_at).toISOString()
      : null

    if (isEdit && campaign) {
      // Update: gửi "" / null (KHÔNG undefined) để CHO PHÉP xoá field — BE
      // exclude_unset bỏ qua undefined = không xoá được (finding #2).
      updateMut.mutate(
        {
          id: campaign.id,
          data: {
            name: values.name,
            sms_template: values.sms_template,
            landing_type: values.landing_type,
            ...landing,
            frequency_cap_days: values.frequency_cap_days ?? null,
            link_expires_at: linkIso,
          },
        },
        { onSuccess: () => onOpenChange(false) },
      )
    } else {
      // Create: field trống → undefined (BE default None); code tự sinh.
      createMut.mutate(
        {
          name: values.name,
          code: values.code?.trim() || undefined,
          sms_template: values.sms_template,
          landing_type: values.landing_type,
          landing_url: landing.landing_url || undefined,
          landing_headline: landing.landing_headline || undefined,
          landing_body: landing.landing_body || undefined,
          landing_cta_label: landing.landing_cta_label || undefined,
          landing_cta_url: landing.landing_cta_url || undefined,
          frequency_cap_days: values.frequency_cap_days ?? undefined,
          link_expires_at: linkIso ?? undefined,
        },
        {
          onSuccess: (c) => {
            onOpenChange(false)
            onCreated?.(c)
          },
        },
      )
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Sửa chiến dịch" : "Tạo chiến dịch SMS"}
          </DialogTitle>
          <DialogDescription>
            Nội dung tin có thể dùng biến {"{full_name}"} và {"{link}"} (link
            rút gọn). Thiếu {"{link}"} → không đo được click.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tên chiến dịch *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Tuyển sinh khối 10 — đợt 1"
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
                        placeholder="bỏ trống để tự sinh"
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
              name="sms_template"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nội dung tin *</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={4}
                      maxLength={2000}
                      placeholder="Chào {full_name}, … Xem chi tiết: {link}"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Hệ thống tự thêm tiền tố [QC] + hướng dẫn từ chối khi gửi.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="landing_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Loại trang đích</FormLabel>
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
                      {LANDING_TYPE_OPTIONS.map((o) => (
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

            {landingType === "external" ? (
              <FormField
                control={form.control}
                name="landing_url"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>URL ngoài</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="https://…"
                        disabled={isPending}
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormDescription>
                      Host phải thuộc allowlist (BE kiểm). Cần có {"{link}"}
                      trong tin.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <>
                <FormField
                  control={form.control}
                  name="landing_headline"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tiêu đề trang đích</FormLabel>
                      <FormControl>
                        <Input
                          maxLength={200}
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
                  name="landing_body"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Nội dung trang đích</FormLabel>
                      <FormControl>
                        <Textarea
                          rows={3}
                          maxLength={10000}
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="landing_cta_label"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nhãn nút CTA</FormLabel>
                        <FormControl>
                          <Input
                            maxLength={100}
                            placeholder="Đăng ký tư vấn"
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
                    name="landing_cta_url"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>URL nút CTA</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="https://…"
                            disabled={isPending}
                            {...field}
                            value={field.value ?? ""}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="frequency_cap_days"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Chặn gửi lại (ngày)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={0}
                        max={3650}
                        placeholder="vd 30"
                        disabled={isPending}
                        value={field.value ?? ""}
                        onChange={(e) =>
                          field.onChange(
                            e.target.value === ""
                              ? undefined
                              : Number(e.target.value),
                          )
                        }
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="link_expires_at"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Link hết hạn</FormLabel>
                    <FormControl>
                      <Input
                        type="datetime-local"
                        disabled={isPending}
                        {...field}
                        value={field.value ?? ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

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
