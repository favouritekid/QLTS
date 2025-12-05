// src/components/forms/LoginForm.tsx
"use client"; // Cần thiết vì sử dụng hooks (useForm, useAuth)

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
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth"; // Import hook useAuth
import type { LoginRequest } from "@/types/api.types"; // Import kiểu LoginRequest

// Định nghĩa Zod schema khớp với LoginRequest và yêu cầu backend
const loginSchema = z.object({
  username: z.string().min(1, { message: "Tên đăng nhập là bắt buộc" }),
  password: z.string().min(6, { message: "Mật khẩu phải có ít nhất 6 ký tự" }),
});

// Suy luận kiểu TypeScript từ Zod schema
type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { login, isLoading } = useAuth(); // Lấy hàm login và trạng thái loading từ hook

  // 1. Định nghĩa form với react-hook-form
  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema), // Sử dụng Zod để validation
    defaultValues: {
      username: "",
      password: "",
    },
  });

  // 2. Định nghĩa hàm xử lý submit
  function onSubmit(values: LoginFormValues) {
    // Gọi hàm login từ useAuth hook với dữ liệu form đã validate
    // Lưu ý: Backend dùng username, nên values.username là đúng
    console.log("Form Values on Submit:", values);
    login(values as LoginRequest); // Ép kiểu sang LoginRequest nếu cần
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold">Chào mừng trở lại</h1>
        <p className="text-muted-foreground">Nhập thông tin đăng nhập để truy cập tài khoản của bạn</p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Trường Username */}
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Tên đăng nhập</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Tên đăng nhập"
                    autoComplete="username"
                    disabled={isLoading} // Vô hiệu hóa khi đang loading
                    {...field} // Kết nối input với react-hook-form
                  />
                </FormControl>
                <FormMessage /> {/* Hiển thị lỗi validation */}
              </FormItem>
            )}
          />

          {/* Trường Password */}
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Mật khẩu</FormLabel>
                  {/* Link Forgot Password */}
                  <Link
                    href="/forgot-password"
                    className="text-primary text-sm hover:underline"
                  >
                    Quên mật khẩu?
                  </Link>
                </div>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoComplete="current-password"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Nút Submit */}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Đang đăng nhập..." : "Đăng nhập"}
          </Button>
        </form>
      </Form>

      {/* Link Sign Up */}
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Chưa có tài khoản?{" "}
        <Link
          href="/register"
          className="text-primary font-medium hover:underline"
        >
          Đăng ký
        </Link>
      </p>
    </div>
  );
}
