// src/components/forms/ResetPasswordForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useSearchParams, useRouter } from "next/navigation"; // Import hooks
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
import { useAuth } from "@/hooks/useAuth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Terminal } from "lucide-react";
import { PasswordStrengthIndicator } from "@/components/admin/PasswordStrengthIndicator";
// Tạm định nghĩa
interface ResetPasswordSchema {
  token: string;
  new_password: string;
}

// Schema validation (khớp ResetPasswordSchema backend và thêm confirm password)
const resetPasswordSchema = z
  .object({
    new_password: z
      .string()
      .min(8, { message: "Mật khẩu phải có ít nhất 8 ký tự" })
      .regex(/[A-Z]/, { message: "Phải chứa chữ cái viết hoa" })
      .regex(/[a-z]/, { message: "Phải chứa chữ cái viết thường" })
      .regex(/[0-9]/, { message: "Phải chứa số" })
      .regex(/[^A-Za-z0-9]/, { message: "Phải chứa ký tự đặc biệt" }),
    confirm_new_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "Mật khẩu không khớp",
    path: ["confirm_new_password"],
  });

type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

export function ResetPasswordForm() {
  const { resetPassword, isLoading } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token"); // Lấy token từ URL query param

  const form = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: "", confirm_new_password: "" },
    mode: "onChange", // ✅ FIX: Realtime validation
  });

  // Watch new_password for strength indicator
  const newPassword = form.watch("new_password");

  function onSubmit(values: ResetPasswordFormValues) {
    if (!token) return; // Không submit nếu không có token
    // Gửi cả token và password mới (bao gồm confirm để zod refine kiểm tra)
    const apiData: ResetPasswordSchema & { confirm_new_password: string } = {
      token,
      new_password: values.new_password,
      confirm_new_password: values.confirm_new_password,
    };
    resetPassword(apiData);
  }

  // Hiển thị lỗi nếu không có token trong URL
  if (!token) {
    return (
      <div className="mx-auto w-full max-w-md space-y-4">
        <Alert variant="destructive">
          <Terminal className="h-4 w-4" />
          <AlertTitle>Lỗi</AlertTitle>
          <AlertDescription>
            Token đặt lại mật khẩu không hợp lệ hoặc thiếu. Vui lòng yêu cầu liên kết mới.
          </AlertDescription>
        </Alert>
        <Button onClick={() => router.push("/forgot-password")} variant="outline">
          Yêu cầu Liên kết Mới
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold font-display">Đặt Lại Mật Khẩu</h1>
        <p className="text-muted-foreground">Nhập mật khẩu mới của bạn dưới đây.</p>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Mật khẩu mới</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" autoComplete="new-password" disabled={isLoading} {...field} />
                </FormControl>
                {/* ✅ UX FIX: Show password strength indicator */}
                {newPassword && <PasswordStrengthIndicator password={newPassword} />}
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Xác nhận mật khẩu mới</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" autoComplete="new-password" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Đang đặt lại…" : "Đặt Lại Mật Khẩu"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Đã nhớ mật khẩu?{" "}
        <Link href="/login" className="text-primary font-medium hover:underline">
          Đăng nhập
        </Link>
      </p>
    </div>
  );
}
