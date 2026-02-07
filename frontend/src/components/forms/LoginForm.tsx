// src/components/forms/LoginForm.tsx
"use client";

import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import Link from "next/link";
import { AlertCircle, Clock } from "lucide-react";

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
import { useCountdown } from "@/hooks/useCountdown";
import { MfaVerifyForm } from "./MfaVerifyForm";
import type { LoginRequest } from "@/types/api.types";

const loginSchema = z.object({
  username: z.string().min(1, { message: "Tên đăng nhập là bắt buộc" }),
  password: z.string().min(6, { message: "Mật khẩu phải có ít nhất 6 ký tự" }),
});

type LoginFormValues = z.infer<typeof loginSchema>;

function getLoginErrorMessage(
  error: unknown,
  isRateLimited: boolean,
): string | undefined {
  if (!error) return undefined;

  if (isRateLimited) {
    return "Quá nhiều lần thử đăng nhập. Vui lòng đợi trước khi thử lại.";
  }

  const axiosError = error as { response?: { status?: number; data?: { detail?: unknown } } };
  const status = axiosError.response?.status;

  if (status === 429) {
    return "Quá nhiều lần thử đăng nhập. Vui lòng đợi trước khi thử lại.";
  }
  if (status === 401) {
    return "Tên đăng nhập hoặc mật khẩu không đúng.";
  }

  return "Đã xảy ra lỗi. Vui lòng thử lại.";
}

function getMfaErrorMessage(error: unknown): string | undefined {
  if (!error) return undefined;

  const axiosError = error as { response?: { status?: number } };
  const status = axiosError.response?.status;

  if (status === 429) {
    return "Bạn đã nhập sai quá nhiều lần. Vui lòng đợi trước khi thử lại.";
  }
  if (status === 401) {
    return "Mã xác thực không đúng. Vui lòng kiểm tra và thử lại.";
  }

  return "Đã xảy ra lỗi. Vui lòng thử lại.";
}

export function LoginForm() {
  const {
    login,
    verifyMfa,
    verifyMfaError,
    resetVerifyMfa,
    loginError,
    resetLogin,
    isLoading,
  } = useAuth();
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaToken, setMfaToken] = useState<string | null>(null);

  const loginCountdown = useCountdown(60);
  const mfaCountdown = useCountdown(60);

  // Start countdown when login gets rate limited
  useEffect(() => {
    if (!loginError) return;
    const axiosError = loginError as { response?: { status?: number; headers?: Record<string, string> } };
    if (axiosError.response?.status === 429) {
      const retryAfter = axiosError.response.headers?.["retry-after"];
      loginCountdown.start(retryAfter);
    }
  }, [loginError]); // eslint-disable-line react-hooks/exhaustive-deps

  // Start countdown when MFA gets rate limited
  useEffect(() => {
    if (!verifyMfaError) return;
    const axiosError = verifyMfaError as { response?: { status?: number; headers?: Record<string, string> } };
    if (axiosError.response?.status === 429) {
      const retryAfter = axiosError.response.headers?.["retry-after"];
      mfaCountdown.start(retryAfter);
    }
  }, [verifyMfaError]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-clear login error when countdown finishes
  useEffect(() => {
    if (!loginCountdown.isActive && loginError) {
      const axiosError = loginError as { response?: { status?: number } };
      if (axiosError.response?.status === 429) {
        resetLogin();
      }
    }
  }, [loginCountdown.isActive]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-clear MFA error when countdown finishes
  useEffect(() => {
    if (!mfaCountdown.isActive && verifyMfaError) {
      const axiosError = verifyMfaError as { response?: { status?: number } };
      if (axiosError.response?.status === 429) {
        resetVerifyMfa();
      }
    }
  }, [mfaCountdown.isActive]); // eslint-disable-line react-hooks/exhaustive-deps

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      username: "",
      password: "",
    },
  });

  function onSubmit(values: LoginFormValues) {
    resetLogin();
    login(values as LoginRequest, {
      onSuccess: (response) => {
        if (response?.mfa_required && response?.mfa_token) {
          setMfaRequired(true);
          setMfaToken(response.mfa_token);
        }
      },
    });
  }

  function handleMfaSubmit(code: string) {
    if (mfaToken) {
      resetVerifyMfa();
      verifyMfa({ mfa_token: mfaToken, code });
    }
  }

  function handleMfaCancel() {
    setMfaRequired(false);
    setMfaToken(null);
    resetVerifyMfa();
    mfaCountdown.reset();
  }

  // Show MFA verification form
  if (mfaRequired && mfaToken) {
    const isMfaRateLimited =
      verifyMfaError?.response?.status === 429 || mfaCountdown.isActive;

    return (
      <MfaVerifyForm
        onSubmit={handleMfaSubmit}
        onCancel={handleMfaCancel}
        isLoading={isLoading}
        errorMessage={
          mfaCountdown.isActive
            ? `Bạn đã nhập sai quá nhiều lần. Thử lại sau ${mfaCountdown.seconds}s.`
            : getMfaErrorMessage(verifyMfaError)
        }
        isRateLimited={isMfaRateLimited}
      />
    );
  }

  const isLoginRateLimited =
    (loginError as { response?: { status?: number } })?.response?.status === 429 ||
    loginCountdown.isActive;
  const loginErrorMessage = getLoginErrorMessage(loginError, loginCountdown.isActive);

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold font-display">Chào mừng trở lại</h1>
        <p className="text-muted-foreground">
          Nhập thông tin đăng nhập để truy cập tài khoản của bạn
        </p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
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
                    disabled={isLoading || isLoginRateLimited}
                    {...field}
                    onChange={(e) => {
                      field.onChange(e);
                      if (loginError) resetLogin();
                    }}
                  />
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
                <div className="flex items-center justify-between">
                  <FormLabel>Mật khẩu</FormLabel>
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
                    disabled={isLoading || isLoginRateLimited}
                    {...field}
                    onChange={(e) => {
                      field.onChange(e);
                      if (loginError) resetLogin();
                    }}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Inline error message */}
          {loginErrorMessage && (
            <div
              role="alert"
              className={`flex items-center gap-2 rounded-md px-3 py-2.5 text-sm ${
                isLoginRateLimited
                  ? "bg-orange-50 text-orange-700 dark:bg-orange-950 dark:text-orange-300"
                  : "bg-destructive/10 text-destructive"
              }`}
            >
              {isLoginRateLimited ? (
                <Clock className="h-4 w-4 shrink-0" aria-hidden="true" />
              ) : (
                <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
              )}
              <span>
                {isLoginRateLimited && loginCountdown.isActive
                  ? `Quá nhiều lần thử đăng nhập. Thử lại sau ${loginCountdown.seconds}s.`
                  : loginErrorMessage}
              </span>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={isLoading || isLoginRateLimited}
          >
            {isLoading ? "Đang đăng nhập…" : "Đăng nhập"}
          </Button>
        </form>
      </Form>

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
