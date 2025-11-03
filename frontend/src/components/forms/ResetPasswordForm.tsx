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
      .min(8, { message: "Password must be at least 8 characters" })
      .regex(/[A-Z]/, { message: "Must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Must contain a special character" }),
    confirm_new_password: z.string(),
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "Passwords do not match",
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
  });

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
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>
            Invalid or missing password reset token. Please request a new link.
          </AlertDescription>
        </Alert>
        <Button onClick={() => router.push("/forgot-password")} variant="outline">
          Request New Link
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold">Reset Password</h1>
        <p className="text-muted-foreground">Enter your new password below.</p>
      </div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Confirm New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Resetting..." : "Reset Password"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Remembered your password?{" "}
        <Link href="/login" className="text-primary font-medium hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
