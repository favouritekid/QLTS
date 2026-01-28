// src/components/forms/ForgotPasswordForm.tsx
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
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// Tạm định nghĩa
interface ForgotPasswordSchema {
  email: string;
}

const forgotPasswordSchema = z.object({
  email: z.string().email({ message: "Địa chỉ email không hợp lệ" }),
});

type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

export function ForgotPasswordForm() {
  const { forgotPassword, isLoading } = useAuth();

  const form = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  function onSubmit(values: ForgotPasswordFormValues) {
    forgotPassword(values as ForgotPasswordSchema);
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold font-display">Quên Mật Khẩu</h1>
        <p className="text-muted-foreground">Nhập email để nhận liên kết đặt lại mật khẩu.</p>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
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
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Đang gửi..." : "Gửi Liên Kết Đặt Lại"}
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
