// src/components/forms/ChangePasswordForm.tsx
"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { PasswordStrengthIndicator } from "@/components/admin/PasswordStrengthIndicator";

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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/useAuth";
import { getActiveSessions } from "@/lib/api/sessions"; // architecture-allow legacy
import type { ChangePasswordSchema } from "@/types/api.types";

// Schema validation
const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, { message: "Mật khẩu hiện tại là bắt buộc" }),
    new_password: z
      .string()
      .min(1, { message: "Mật khẩu là bắt buộc" })
      .min(12, { message: "Mật khẩu phải có ít nhất 12 ký tự" })
      .regex(/[A-Z]/, { message: "Phải chứa chữ cái viết hoa" })
      .regex(/[a-z]/, { message: "Phải chứa chữ cái viết thường" })
      .regex(/[0-9]/, { message: "Phải chứa số" })
      .regex(/[@$!%*?&]/, { message: "Phải chứa ký tự đặc biệt (@$!%*?&)" }),
    confirm_new_password: z.string().min(1, { message: "Vui lòng xác nhận mật khẩu" }),
  })
  // ✅ SECURITY: Ensure new password is different from old password
  .refine((data) => data.new_password !== data.old_password, {
    message: "Mật khẩu mới phải khác mật khẩu hiện tại",
    path: ["new_password"],
  })
  .refine((data) => data.new_password === data.confirm_new_password, {
    message: "Mật khẩu mới không khớp",
    path: ["confirm_new_password"],
  });

type ChangePasswordFormValues = z.infer<typeof changePasswordSchema>;

export function ChangePasswordForm() {
  const { changePassword, isLoading: isChangingPassword } = useAuth();
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [pendingData, setPendingData] = useState<ChangePasswordFormValues | null>(null);
  
  // C2 SECURITY FIX: Check if user was forced to change password
  const searchParams = useSearchParams();
  const isForced = searchParams.get("forced") === "true";

  // Fetch active sessions count
  const { data: sessionsData, isLoading: isLoadingSessions } = useQuery({
    queryKey: ["sessions"],
    queryFn: getActiveSessions,
    retry: 1,
    staleTime: 5000, // 5 seconds - refresh faster after session changes
    refetchOnWindowFocus: true, // Refetch when user switches back to this tab
  });

  const activeSessionsCount = sessionsData?.total || 0;

  const form = useForm<ChangePasswordFormValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { old_password: "", new_password: "", confirm_new_password: "" },
    mode: "onChange", // ✅ FIX: Changed from onTouched to onChange for realtime validation
  });

  // Watch new_password for strength indicator
  const newPassword = form.watch("new_password");

  function onSubmit(values: ChangePasswordFormValues) {
    // Show confirmation dialog instead of submitting directly
    setPendingData(values);
    setShowConfirmDialog(true);
  }

  function handleConfirmChange() {
    if (!pendingData) return;

    const apiData: ChangePasswordSchema & { confirm_new_password: string } = {
      old_password: pendingData.old_password,
      new_password: pendingData.new_password,
      confirm_new_password: pendingData.confirm_new_password,
    };

    changePassword(apiData, {
      onSuccess: () => {
        form.reset();
        setShowConfirmDialog(false);
        setPendingData(null);
      },
    });
  }

  return (
    <div className="w-full max-w-xl space-y-4">
      <h2 className="text-xl font-semibold font-display">Đổi Mật Khẩu</h2>

      {/* C2 SECURITY FIX: Forced password change warning */}
      {isForced && (
        <Alert className="border-error-500 bg-error-50">
          <ShieldAlert className="h-5 w-5 text-error-600" />
          <AlertTitle className="text-error-800">Yêu cầu Đổi Mật Khẩu</AlertTitle>
          <AlertDescription className="text-error-700">
            <p>
              Tài khoản của bạn đã được đánh dấu cần <strong>đổi mật khẩu ngay lập tức</strong>.
              Điều này có thể do bạn đã báo cáo một đăng nhập đáng ngờ.
            </p>
            <p className="mt-2 text-sm">
              Vui lòng đổi mật khẩu để tiếp tục sử dụng hệ thống.
            </p>
          </AlertDescription>
        </Alert>
      )}

      {/* Security Warning Alert */}
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Lưu ý Bảo mật</AlertTitle>
        <AlertDescription className="space-y-2">
          <p>
            Đổi mật khẩu sẽ <strong>đăng xuất bạn khỏi tất cả thiết bị</strong>. Bạn sẽ
            cần đăng nhập lại với mật khẩu mới.
          </p>
          {isLoadingSessions ? (
            <Skeleton className="h-4 w-64" />
          ) : activeSessionsCount > 1 ? (
            <p className="mt-2 text-sm">
              📱 Bạn đang đăng nhập trên <strong>{activeSessionsCount} thiết bị</strong>.
            </p>
          ) : null}
          {activeSessionsCount > 1 && (
            <p className="mt-2 text-sm">
              💡 Mẹo:{" "}
              <Link href="/settings/sessions" className="underline font-medium hover:text-destructive-foreground">
                Xem các phiên đang hoạt động
              </Link>{" "}
              trước khi đổi mật khẩu để phát hiện đăng nhập đáng ngờ.
            </p>
          )}
        </AlertDescription>
      </Alert>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="old_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Mật khẩu hiện tại</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoComplete="current-password"
                    disabled={isChangingPassword}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Mật khẩu mới</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    disabled={isChangingPassword}
                    {...field}
                  />
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
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    disabled={isChangingPassword}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isChangingPassword} className="mt-4">
            {isChangingPassword ? "Đang đổi…" : "Đổi Mật Khẩu"}
          </Button>
        </form>
      </Form>

      {/* Confirmation Dialog */}
      <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận Đổi Mật Khẩu</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn sẽ bị đăng xuất khỏi{" "}
              <strong>
                {activeSessionsCount === 1 ? "thiết bị này" : `tất cả ${activeSessionsCount} thiết bị`}
              </strong>
              . Bạn có chắc chắn muốn tiếp tục?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isChangingPassword}>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmChange}
              disabled={isChangingPassword}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isChangingPassword ? "Đang đổi…" : "Có, Đổi Mật Khẩu"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
