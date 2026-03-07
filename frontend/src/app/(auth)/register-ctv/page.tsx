"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api/client"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"

// =============================================================================
// SCHEMA
// =============================================================================

const ctvRegisterSchema = z.object({
  full_name: z.string()
    .min(1, "Họ tên không được để trống")
    .max(255)
    .trim(),
  phone: z.string()
    .min(1, "Số điện thoại không được để trống")
    .max(20)
    .trim(),
  email: z.union([
    z.string().email("Email không hợp lệ"),
    z.literal(""),
  ]).nullable().transform(v => v === "" ? null : v),
  id_card_number: z.string().max(20).nullable().transform(v => v === "" ? null : v),
  address: z.string().max(500).nullable().transform(v => v === "" ? null : v),
  notes: z.string().max(1000).nullable().transform(v => v === "" ? null : v),
  unit_id: z.number({ message: "Vui lòng nhập mã đơn vị" }),
})

type CTVRegisterFormData = z.infer<typeof ctvRegisterSchema>

// =============================================================================
// PAGE
// =============================================================================

export default function RegisterCTVPage() {
  const router = useRouter()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const form = useForm({
    resolver: zodResolver(ctvRegisterSchema),
    defaultValues: {
      full_name: "",
      phone: "",
      email: "",
      id_card_number: "",
      address: "",
      notes: "",
      unit_id: undefined,
    },
  })

  async function onSubmit(data: CTVRegisterFormData) {
    setIsSubmitting(true)
    try {
      await api.post("/api/ctv-register", data)
      router.push("/register-ctv/success")
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      const message = axiosErr?.response?.data?.detail || "Lỗi đăng ký. Vui lòng thử lại."
      toast.error(message)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Đăng ký Cộng tác viên</CardTitle>
          <CardDescription>
            Điền thông tin bên dưới để đăng ký trở thành cộng tác viên. Tài khoản sẽ được kích hoạt sau khi admin duyệt.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Họ tên <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input placeholder="Nguyễn Văn A" autoComplete="name" {...field} />
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
                    <FormLabel>Số điện thoại <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input placeholder="0901234567" autoComplete="tel" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" placeholder="email@example.com" autoComplete="email" {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="unit_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mã đơn vị <span className="text-destructive">*</span></FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        placeholder="VD: 1"
                        {...field}
                        value={field.value ?? ""}
                        onChange={(e) => field.onChange(e.target.value ? Number(e.target.value) : undefined)}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="id_card_number"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số CMND/CCCD</FormLabel>
                    <FormControl>
                      <Input placeholder="012345678901" {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="address"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Địa chỉ</FormLabel>
                    <FormControl>
                      <Input placeholder="Địa chỉ liên hệ" {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="notes"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Ghi chú</FormLabel>
                    <FormControl>
                      <Textarea placeholder="Thông tin bổ sung..." rows={3} {...field} value={field.value ?? ""} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />}
                Đăng ký
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}
