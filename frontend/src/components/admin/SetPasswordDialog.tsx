"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Eye, EyeOff } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PasswordStrengthIndicator } from "@/components/admin/PasswordStrengthIndicator";
import { useAdminSetPassword } from "@/hooks/useAdminUsers";
import type { User } from "@/types/api.types";

// Password validation schema
const setPasswordSchema = z.object({
  new_password: z
    .string()
    .min(12, "Mật khẩu phải có ít nhất 12 ký tự")
    .regex(/[A-Z]/, "Mật khẩu phải có ít nhất một chữ cái viết hoa")
    .regex(/[a-z]/, "Mật khẩu phải có ít nhất một chữ cái viết thường")
    .regex(/\d/, "Mật khẩu phải có ít nhất một số")
    .regex(/[@$!%*?&]/, "Mật khẩu phải có ít nhất một ký tự đặc biệt"),
  confirm_password: z.string(),
}).refine((data) => data.new_password === data.confirm_password, {
  message: "Mật khẩu không khớp",
  path: ["confirm_password"],
});

type SetPasswordFormValues = z.infer<typeof setPasswordSchema>;

interface SetPasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: User;
}

export function SetPasswordDialog({ open, onOpenChange, user }: SetPasswordDialogProps) {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const setPasswordMutation = useAdminSetPassword(user.id);

  const form = useForm<SetPasswordFormValues>({
    resolver: zodResolver(setPasswordSchema),
    defaultValues: {
      new_password: "",
      confirm_password: "",
    },
    mode: "onChange", // ✅ FIX: Realtime validation
  });

  // Derive password value from form instead of separate state
  const passwordValue = form.watch("new_password");

  // Reset form state when dialog opens/closes
  const handleOpenChange = (newOpen: boolean) => {
    if (newOpen) {
      form.reset();
      setShowPassword(false);
      setShowConfirmPassword(false);
    }
    onOpenChange(newOpen);
  };

  async function onSubmit(values: SetPasswordFormValues) {
    try {
      await setPasswordMutation.mutateAsync({
        new_password: values.new_password,
      });
      handleOpenChange(false);
    } catch {
      // Error handling is done in the mutation hook
    }
  }

  const isPending = setPasswordMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Đặt Mật Khẩu</DialogTitle>
          <DialogDescription>
            Đặt mật khẩu mới cho <span className="font-semibold">{user.username}</span>.
            Người dùng sẽ có thể đăng nhập bằng mật khẩu mới ngay lập tức.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* New Password */}
            <FormField
              control={form.control}
              name="new_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mật khẩu mới</FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showPassword ? "text" : "password"}
                        placeholder="Nhập mật khẩu mới"
                        {...field}
                        onChange={field.onChange}
                        disabled={isPending}
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        disabled={isPending}
                        aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                      >
                        {showPassword ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Password Strength Indicator */}
            {passwordValue && <PasswordStrengthIndicator password={passwordValue} />}

            {/* Confirm Password */}
            <FormField
              control={form.control}
              name="confirm_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Xác nhận mật khẩu</FormLabel>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showConfirmPassword ? "text" : "password"}
                        placeholder="Xác nhận mật khẩu mới"
                        {...field}
                        disabled={isPending}
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        disabled={isPending}
                        aria-label={showConfirmPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                      >
                        {showConfirmPassword ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Đang đặt…" : "Đặt Mật Khẩu"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
