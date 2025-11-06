// src/components/forms/ChangePasswordForm.tsx
"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
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
import { FormErrorMessage } from "@/components/ui/form-error-message";
import { getActiveSessions } from "@/lib/api/sessions";
import type { ChangePasswordSchema } from "@/types/api.types";

// Schema validation
const changePasswordSchema = z
  .object({
    old_password: z.string().min(1, { message: "Current password is required" }),
    new_password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" })
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
  const { changePassword, isLoading: isChangingPassword } = useAuth();
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [pendingData, setPendingData] = useState<ChangePasswordFormValues | null>(null);

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
    mode: "onTouched",
    reValidateMode: "onChange",
  });

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
      onError: () => {
        // Keep dialog open on error so user can retry
        setShowConfirmDialog(false);
      },
    });
  }

  return (
    <div className="w-full max-w-xl space-y-4">
      <h2 className="text-xl font-semibold">Change Password</h2>

      {/* Security Warning Alert */}
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Security Notice</AlertTitle>
        <AlertDescription className="space-y-2">
          <p>
            Changing your password will <strong>log you out from all devices</strong>. You will
            need to log in again with your new password.
          </p>
          {isLoadingSessions ? (
            <Skeleton className="h-4 w-64" />
          ) : activeSessionsCount > 1 ? (
            <p className="mt-2 text-sm">
              📱 You are currently logged in on <strong>{activeSessionsCount} devices</strong>.
            </p>
          ) : null}
          {activeSessionsCount > 1 && (
            <p className="mt-2 text-sm">
              💡 Tip:{" "}
              <Link href="/settings/sessions" className="underline font-medium hover:text-destructive-foreground">
                Review your active sessions
              </Link>{" "}
              before changing your password to identify any suspicious logins.
            </p>
          )}
        </AlertDescription>
      </Alert>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="old_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Current Password</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    disabled={isChangingPassword}
                    {...field}
                  />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="new_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>New Password</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    disabled={isChangingPassword}
                    {...field}
                  />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirm_new_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>Confirm New Password</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    disabled={isChangingPassword}
                    {...field}
                  />
                </FormControl>
                <FormErrorMessage message={fieldState.error?.message} />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={isChangingPassword} className="mt-4">
            {isChangingPassword ? "Changing..." : "Change Password"}
          </Button>
        </form>
      </Form>

      {/* Confirmation Dialog */}
      <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Password Change</AlertDialogTitle>
            <AlertDialogDescription>
              You will be logged out from{" "}
              <strong>
                {activeSessionsCount === 1 ? "this device" : `all ${activeSessionsCount} devices`}
              </strong>
              . Are you sure you want to continue?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isChangingPassword}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmChange}
              disabled={isChangingPassword}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isChangingPassword ? "Changing..." : "Yes, Change Password"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
