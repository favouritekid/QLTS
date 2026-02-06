"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp";

interface MfaVerifyFormProps {
  onSubmit: (code: string) => void;
  onCancel: () => void;
  isLoading: boolean;
}

export function MfaVerifyForm({
  onSubmit,
  onCancel,
  isLoading,
}: MfaVerifyFormProps) {
  const [code, setCode] = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);
  const [backupCode, setBackupCode] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const value = useBackupCode ? backupCode.trim() : code;
    if (value.length >= 6) {
      onSubmit(value);
    }
  }

  return (
    <div className="bg-card mx-auto w-full max-w-md space-y-6 rounded border p-6 shadow-md md:p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold font-display">Xác thực hai yếu tố</h1>
        <p className="text-muted-foreground text-sm">
          {useBackupCode
            ? "Nhập mã backup của bạn"
            : "Nhập mã 6 chữ số từ ứng dụng xác thực"}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {useBackupCode ? (
          <div className="flex justify-center">
            <Input
              placeholder="Nhập mã backup"
              value={backupCode}
              onChange={(e) => setBackupCode(e.target.value)}
              maxLength={8}
              disabled={isLoading}
              autoComplete="one-time-code"
              className="text-center font-mono text-lg tracking-widest"
            />
          </div>
        ) : (
          <div className="flex justify-center">
            <InputOTP
              maxLength={6}
              value={code}
              onChange={setCode}
              disabled={isLoading}
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
        )}

        <Button
          type="submit"
          className="w-full"
          disabled={
            isLoading ||
            (useBackupCode ? backupCode.trim().length < 6 : code.length < 6)
          }
        >
          {isLoading ? "Đang xác thực…" : "Xác nhận"}
        </Button>
      </form>

      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setUseBackupCode(!useBackupCode);
            setCode("");
            setBackupCode("");
          }}
          className="text-primary text-sm hover:underline"
          disabled={isLoading}
        >
          {useBackupCode
            ? "Sử dụng mã từ ứng dụng xác thực"
            : "Sử dụng mã backup"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-muted-foreground text-sm hover:underline"
          disabled={isLoading}
        >
          Quay lại đăng nhập
        </button>
      </div>
    </div>
  );
}
