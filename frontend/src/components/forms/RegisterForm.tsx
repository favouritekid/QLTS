// src/components/forms/RegisterForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";

import { Button } from "@/components/ui/button";
// Xóa FormMessage khỏi import vì chúng ta dùng component tùy chỉnh
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// Import component báo lỗi tùy chỉnh
import { FormErrorMessage } from "@/components/ui/form-error-message";
import type { UserCreate } from "@/types/api.types";

const registerSchema = z
  .object({
    username: z
      .string()
      .min(1, { message: "Username is required" })
      .min(3, { message: "Username must be at least 3 characters" }),
    email: z
      .string()
      .min(1, { message: "Email is required" })
      .email({ message: "Invalid email address" }),
    full_name: z.string().optional(),
    password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" })
      // ... (các regex rules)
      .regex(/[A-Z]/, { message: "Password must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Password must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Password must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Password must contain a special character" }),
    confirmPassword: z.string().min(1, { message: "Please confirm your password" }),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
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
        <h1 className="text-3xl font-bold">Create an account</h1>
        <p className="text-muted-foreground">Enter your details below to register</p>
      </div>
      <Form {...form}>
        {/* ❌ Đã xóa hàm onError (chỉ chứa log) khỏi handleSubmit */}
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="username"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Username</FormLabel>
                <FormControl>
                  <Input placeholder="your_username" disabled={isLoading} {...field} />
                </FormControl>
                {/* Sử dụng component tùy chỉnh */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="email"
            render={({ field, fieldState }) => (
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
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="full_name"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Full Name (Optional)</FormLabel>
                <FormControl>
                  <Input placeholder="Your Full Name" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="confirmPassword"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Confirm Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />

          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Registering..." : "Register"}
          </Button>
        </form>
      </Form>
      <p className="text-muted-foreground mt-4 text-center text-sm">
        Already have an account?
        <Link href="/login" className="text-primary font-medium hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
