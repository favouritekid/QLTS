// src/components/forms/ChangePasswordForm.tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";

import { Button } from "@/components/ui/button";
// <<< SỬA IMPORT: Xóa FormMessage >>>
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
// <<< THÊM IMPORT >>>
import { FormErrorMessage } from "@/components/ui/form-error-message";
import type { ChangePasswordSchema } from "@/types/api.types";

// Schema validation (giữ nguyên)
const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, { message: "Current password is required" }),
    new_password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" })
      // ... (regex)
      .regex(/[A-Z]/, { message: "Must contain an uppercase letter" })
      .regex(/[a-z]/, { message: "Must contain a lowercase letter" })
      .regex(/[0-9]/, { message: "Must contain a number" })
      .regex(/[^A-Za-z0-9]/, { message: "Must contain a special character" }),
    confirm_new_password: z.string().min(1, { message: "Please confirm your password" }),
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "New passwords do not match",
    path: ["confirm_new_password"],
  });

type ChangePasswordFormValues = z.infer<typeof changePasswordSchema>;

export function ChangePasswordForm() {
  const { changePassword, isLoading } = useAuth();

  const form = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { old_password: "", new_password: "", confirm_new_password: "" },
    mode: "onTouched",
    reValidateMode: "onChange",
  });
  // <<< SỬA: Không cần lấy errors ra nữa, dùng fieldState >>>

  function onSubmit(values: ChangePasswordFormValues) {
    const apiData: ChangePasswordSchema & { confirm_new_password: string } = {
      old_password: values.old_password,
      new_password: values.new_password,
      confirm_new_password: values.confirm_new_password,
    };
    changePassword(apiData, {
      onSuccess: () => {
        form.reset();
      },
    });
  }

  return (
    <div className="w-full max-w-xl space-y-4">
      <h2 className="text-xl font-semibold">Change Password</h2>
      <Form {...form}>
        {/* ❌ Xóa hàm onError (nếu có) khỏi handleSubmit */}
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="old_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Current Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="new_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            // <<< SỬA: Thêm fieldState >>>
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Confirm New Password</FormLabel>
                <FormControl>
                  <Input type="password" placeholder="••••••••" disabled={isLoading} {...field} />
                </FormControl>
                {/* <<< SỬA: Dùng FormErrorMessage >>> */}
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isLoading} className="mt-4">
            {isLoading ? "Changing..." : "Change Password"}
          </Button>
        </form>
      </Form>
    </div>
  );
}
