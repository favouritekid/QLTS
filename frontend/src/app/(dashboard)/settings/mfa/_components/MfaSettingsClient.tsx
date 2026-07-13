"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { copyToClipboard } from "@/lib/clipboard";
import { ShieldCheck, ShieldOff, Copy, RefreshCw } from "lucide-react";

import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp";
import type { ApiErrorResponse } from "@/types/api.types";

interface MfaStatus {
  mfa_enabled: boolean;
  has_backup_codes: boolean;
}

interface MfaSetupData {
  secret: string;
  qr_code: string;
  provisioning_uri: string;
}

interface BackupCodesResponse {
  backup_codes: string[];
}

type SetupStep = "idle" | "scanning" | "backup_codes";

export function MfaSettingsClient() {
  const queryClient = useQueryClient();
  const [setupStep, setSetupStep] = useState<SetupStep>("idle");
  const [setupData, setSetupData] = useState<MfaSetupData | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [disablePassword, setDisablePassword] = useState("");
  const [regenPassword, setRegenPassword] = useState("");

  // Fetch MFA status
  const { data: mfaStatus, isLoading: isStatusLoading } = useQuery<MfaStatus>({
    queryKey: ["mfa", "status"],
    queryFn: async () => {
      const { data } = await api.get<MfaStatus>(API_ENDPOINTS.AUTH.MFA_STATUS);
      return data;
    },
  });

  // Setup MFA
  const setupMutation = useMutation<MfaSetupData, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      const { data } = await api.post<MfaSetupData>(API_ENDPOINTS.AUTH.MFA_SETUP);
      return data;
    },
    onSuccess: (data) => {
      setSetupData(data);
      setSetupStep("scanning");
    },
    onError: (error) => {
      const msg = typeof error.response?.data?.detail === "string"
        ? error.response.data.detail
        : "Không thể bắt đầu cài đặt MFA.";
      toast.error(msg);
    },
  });

  // Enable MFA
  const enableMutation = useMutation<
    BackupCodesResponse,
    AxiosError<ApiErrorResponse>,
    { code: string }
  >({
    mutationFn: async ({ code }) => {
      const { data } = await api.post<BackupCodesResponse>(
        API_ENDPOINTS.AUTH.MFA_ENABLE,
        { code }
      );
      return data;
    },
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setSetupStep("backup_codes");
      setVerifyCode("");
      queryClient.invalidateQueries({ queryKey: ["mfa", "status"] });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      toast.success("Đã bật xác thực hai lớp!");
    },
    onError: (error) => {
      const msg = typeof error.response?.data?.detail === "string"
        ? error.response.data.detail
        : "Mã không hợp lệ. Vui lòng thử lại.";
      toast.error(msg);
    },
  });

  // Disable MFA
  const disableMutation = useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { password: string }
  >({
    mutationFn: async ({ password }) => {
      await api.post(API_ENDPOINTS.AUTH.MFA_DISABLE, { password });
    },
    onSuccess: () => {
      setDisablePassword("");
      setSetupStep("idle");
      queryClient.invalidateQueries({ queryKey: ["mfa", "status"] });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      toast.success("Đã tắt xác thực hai lớp.");
    },
    onError: (error) => {
      const msg = typeof error.response?.data?.detail === "string"
        ? error.response.data.detail
        : "Không thể tắt MFA.";
      toast.error(msg);
    },
  });

  // Regenerate backup codes
  const regenMutation = useMutation<
    BackupCodesResponse,
    AxiosError<ApiErrorResponse>,
    { password: string }
  >({
    mutationFn: async ({ password }) => {
      const { data } = await api.post<BackupCodesResponse>(
        API_ENDPOINTS.AUTH.MFA_BACKUP_CODES,
        { password }
      );
      return data;
    },
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setSetupStep("backup_codes");
      setRegenPassword("");
      toast.success("Đã tạo mã dự phòng mới.");
    },
    onError: (error) => {
      const msg = typeof error.response?.data?.detail === "string"
        ? error.response.data.detail
        : "Không thể tạo lại mã dự phòng.";
      toast.error(msg);
    },
  });

  async function copyBackupCodes() {
    if (await copyToClipboard(backupCodes.join("\n"))) {
      toast.success("Đã sao chép mã dự phòng.");
    } else {
      toast.error("Không sao chép được.");
    }
  }

  if (isStatusLoading) {
    return <div className="py-8 text-center text-muted-foreground">Đang tải trạng thái MFA…</div>;
  }

  const isEnabled = mfaStatus?.mfa_enabled ?? false;

  // Backup codes display
  if (setupStep === "backup_codes" && backupCodes.length > 0) {
    return (
      <div className="space-y-6">
        <div className="rounded-lg border bg-amber-50 p-4 dark:bg-amber-950/20">
          <h3 className="font-semibold text-amber-800 dark:text-amber-200">
            Mã dự phòng
          </h3>
          <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
            Lưu các mã này ở nơi an toàn. Mỗi mã chỉ sử dụng được một lần.
            Đây là lần duy nhất bạn thấy các mã này.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2 rounded-lg border p-4">
          {backupCodes.map((code, i) => (
            <code key={i} className="rounded bg-muted px-2 py-1 text-center font-mono text-sm">
              {code}
            </code>
          ))}
        </div>

        <div className="flex gap-2">
          <Button variant="outline" onClick={copyBackupCodes}>
            <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
            Sao chép
          </Button>
          <Button onClick={() => { setSetupStep("idle"); setBackupCodes([]); setSetupData(null); }}>
            Xong
          </Button>
        </div>
      </div>
    );
  }

  // Setup/scanning step
  if (setupStep === "scanning" && setupData) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <h3 className="text-lg font-semibold">Cài đặt xác thực hai lớp</h3>
          <p className="text-sm text-muted-foreground">
            Quét mã QR bằng ứng dụng xác thực (Google Authenticator, Authy, v.v.)
          </p>
        </div>

        <div className="flex justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={setupData.qr_code}
            alt="Mã QR xác thực hai lớp"
            className="h-48 w-48 rounded border"
          />
        </div>

        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Nhập thủ công:</p>
          <code className="block rounded bg-muted p-2 text-center font-mono text-sm break-all select-all">
            {setupData.secret}
          </code>
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">Nhập mã 6 chữ số từ ứng dụng:</p>
          <div className="flex justify-center">
            <InputOTP
              maxLength={6}
              value={verifyCode}
              onChange={setVerifyCode}
              disabled={enableMutation.isPending}
              autoFocus
            >
              <InputOTPGroup>
                <InputOTPSlot index={0} />
                <InputOTPSlot index={1} />
                <InputOTPSlot index={2} />
                <InputOTPSlot index={3} />
                <InputOTPSlot index={4} />
                <InputOTPSlot index={5} />
              </InputOTPGroup>
            </InputOTP>
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => { setSetupStep("idle"); setSetupData(null); setVerifyCode(""); }}
            disabled={enableMutation.isPending}
          >
            Hủy
          </Button>
          <Button
            onClick={() => enableMutation.mutate({ code: verifyCode })}
            disabled={verifyCode.length < 6 || enableMutation.isPending}
          >
            {enableMutation.isPending ? "Đang xác minh…" : "Bật MFA"}
          </Button>
        </div>
      </div>
    );
  }

  // Main view
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        {isEnabled ? (
          <ShieldCheck className="h-8 w-8 text-green-600" aria-hidden="true" />
        ) : (
          <ShieldOff className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        )}
        <div>
          <h3 className="text-lg font-semibold">
            Xác thực hai lớp
          </h3>
          <p className="text-sm text-muted-foreground">
            {isEnabled
              ? "MFA đã bật. Tài khoản của bạn được bảo vệ bằng TOTP."
              : "MFA chưa bật. Thêm lớp bảo mật cho tài khoản của bạn."}
          </p>
        </div>
      </div>

      {isEnabled ? (
        <div className="space-y-4">
          {/* Disable MFA */}
          <div className="rounded-lg border p-4 space-y-3">
            <h4 className="font-medium">Tắt MFA</h4>
            <Input
              type="password"
              placeholder="Nhập mật khẩu của bạn"
              value={disablePassword}
              onChange={(e) => setDisablePassword(e.target.value)}
              autoComplete="current-password"
              disabled={disableMutation.isPending}
            />
            <Button
              variant="destructive"
              onClick={() => disableMutation.mutate({ password: disablePassword })}
              disabled={!disablePassword || disableMutation.isPending}
            >
              {disableMutation.isPending ? "Đang tắt…" : "Tắt MFA"}
            </Button>
          </div>

          {/* Regenerate backup codes */}
          <div className="rounded-lg border p-4 space-y-3">
            <h4 className="font-medium">Tạo lại mã dự phòng</h4>
            <p className="text-sm text-muted-foreground">
              Thao tác này sẽ vô hiệu hóa tất cả mã dự phòng hiện tại.
            </p>
            <Input
              type="password"
              placeholder="Nhập mật khẩu của bạn"
              value={regenPassword}
              onChange={(e) => setRegenPassword(e.target.value)}
              autoComplete="current-password"
              disabled={regenMutation.isPending}
            />
            <Button
              variant="outline"
              onClick={() => regenMutation.mutate({ password: regenPassword })}
              disabled={!regenPassword || regenMutation.isPending}
            >
              <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
              {regenMutation.isPending ? "Đang tạo…" : "Tạo lại mã dự phòng"}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => setupMutation.mutate()}
          disabled={setupMutation.isPending}
        >
          <ShieldCheck className="mr-2 h-4 w-4" aria-hidden="true" />
          {setupMutation.isPending ? "Đang cài đặt…" : "Bật MFA"}
        </Button>
      )}
    </div>
  );
}
