// src/components/forms/RegisterForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage, // ✅ Thêm FormMessage chuẩn từ shadcn/ui
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import type { UserCreate } from "@/types/api.types";

const registerSchema = z
  .object({
    username: z
      .string()
      .min(1, { message: "Tên đăng nhập là bắt buộc" })
      .min(3, { message: "Tên đăng nhập phải có ít nhất 3 ký tự" }),
    email: z
      .string()
      .min(1, { message: "Email là bắt buộc" })
      .email({ message: "Địa chỉ email không hợp lệ" }),
    full_name: z.string().optional(),
    password: z
      .string()
      .min(1, { message: "Mật khẩu là bắt buộc" })
      .min(8, { message: "Mật khẩu phải có ít nhất 8 ký tự" })
      .regex(/[A-Z]/, { message: "Mật khẩu phải chứa chữ cái viết hoa" })
      .regex(/[a-z]/, { message: "Mật khẩu phải chứa chữ cái viết thường" })
      .regex(/[0-9]/, { message: "Mật khẩu phải chứa số" })
      .regex(/[^A-Za-z0-9]/, { message: "Mật khẩu phải chứa ký tự đặc biệt" }),
    confirmPassword: z.string().min(1, { message: "Vui lòng xác nhận mật khẩu" }),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Mật khẩu không khớp",
    path: ["confirmPassword"],
  });

type RegisterFormValues = z.infer<typeof registerSchema>;

export function RegisterForm() {
  const { registerUser, isLoading } = useAuth(); // Đã đổi tên

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      username: "",
      email: "",
      full_name: "",
      password: "",
      confirmPassword: "",
    },
    // Cài đặt mode của bạn rất tốt cho UX
    mode: "onTouched",
    reValidateMode: "onChange",
  });

  function onSubmit(values: RegisterFormValues) {
    // Chỉ gửi các trường mà backend yêu cầu (không gửi confirmPassword)
    const apiData: UserCreate & { confirm_password: string } = {
      username: values.username,
      email: values.email,
      password: values.password,
      confirm_password: values.confirmPassword, // Chỉ để pass type check, mutation sẽ filter
      full_name: values.full_name || null,
    };
    registerUser(apiData);
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold font-display">Tạo tài khoản</h1>
        <p className="text-muted-foreground">Nhập thông tin của bạn để đăng ký</p>
      </div>
      <Form {...form}>
        {/* ❌ Đã xóa hàm onError (chỉ chứa log) khỏi handleSubmit */}
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Tên đăng nhập</FormLabel>
                <FormControl>
                  <Input placeholder="Tên đăng nhập" autoComplete="username" disabled={isLoading} {...field} />
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
                  <Input
                    type="email"
                    placeholder="email@example.com"
                    autoComplete="email"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Họ và tên (Tùy chọn)</FormLabel>
                <FormControl>
                  <Input placeholder="Nguyễn Văn A" autoComplete="name" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Mật khẩu</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" autoComplete="new-password" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="confirmPassword"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Xác nhận mật khẩu</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" autoComplete="new-password" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Đang đăng ký…" : "Đăng ký"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Đã có tài khoản?
        <Link href="/login" className="text-primary font-medium hover:underline">
          Đăng nhập
        </Link>
      </p>
    </div>
  );
}
