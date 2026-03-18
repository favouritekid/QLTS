// src/app/(dashboard)/settings/security/_components/SecurityClient.tsx
"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { triggerSuspiciousLoginBanner } from "@/components/layouts/SecurityBanner";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  useSessions,
  useRevokeSession,
  useRevokeAllOtherSessions,
  sessionKeys,
} from "@/hooks/useSessions";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { UserSessionListResponse } from "@/lib/api/sessions";
import type {
  LoginHistoryResponse,
  ConfirmLoginRequest,
  ConfirmLoginResponse,
  SecureAccountResponse,
} from "@/types/security";
import { SuspiciousLoginsSection } from "./SuspiciousLoginsSection";
import { ActiveSessionsSection } from "./ActiveSessionsSection";
import { LoginHistorySection } from "./LoginHistorySection";
import { SecureAccountDialog } from "./SecureAccountDialog";

// ============================================================================
// API functions
// ============================================================================

async function fetchLoginHistory(): Promise<LoginHistoryResponse> {
  const { data } = await api.get<LoginHistoryResponse>(
    API_ENDPOINTS.SECURITY.LOGIN_HISTORY
  );
  return data;
}

async function confirmLogin(
  data: ConfirmLoginRequest
): Promise<ConfirmLoginResponse> {
  const { data: res } = await api.post<ConfirmLoginResponse>(
    API_ENDPOINTS.SECURITY.CONFIRM_LOGIN,
    data
  );
  return res;
}

async function secureAccount(loginId: number): Promise<SecureAccountResponse> {
  const { data } = await api.post<SecureAccountResponse>(
    API_ENDPOINTS.SECURITY.SECURE_ACCOUNT,
    null,
    { params: { login_id: loginId } }
  );
  return data;
}

// ============================================================================
// SecurityClient
// ============================================================================

interface SecurityClientProps {
  initialSessionsData?: UserSessionListResponse;
}

export function SecurityClient({ initialSessionsData }: SecurityClientProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // ---- Shared UI state ----
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secureDialogOpen, setSecureDialogOpen] = useState(false);
  const [selectedLoginId, setSelectedLoginId] = useState<number | null>(null);

  // ---- Data queries (parallel) ----
  const { data: sessionsData } = useSessions({
    initialData: initialSessionsData,
  });
  const { data: loginHistoryData } = useQuery({
    queryKey: ["loginHistory"],
    queryFn: fetchLoginHistory,
    staleTime: 60 * 1000,
  });

  // ---- Session mutations ----
  const revokeSessionMutation = useRevokeSession();
  const revokeAllOthersMutation = useRevokeAllOtherSessions();

  // ---- Login history mutations ----
  const confirmMutation = useMutation({
    mutationFn: confirmLogin,
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["loginHistory"] });
      queryClient.invalidateQueries({ queryKey: ["suspiciousCount"] });
      setSuccessMessage(
        response.device_trusted
          ? "Đã xác nhận đăng nhập và thêm thiết bị vào danh sách tin cậy."
          : "Đã xác nhận đăng nhập."
      );
      setTimeout(() => setSuccessMessage(null), 5000);
    },
    onError: () => {
      setError("Không thể xác nhận đăng nhập. Vui lòng thử lại.");
      setTimeout(() => setError(null), 5000);
    },
  });

  const secureMutation = useMutation({
    mutationFn: secureAccount,
    onSuccess: (response) => {
      // Cross-invalidation: secure account affects sessions, login history, and auth
      queryClient.invalidateQueries({ queryKey: ["loginHistory"] });
      queryClient.invalidateQueries({ queryKey: sessionKeys.all });
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["suspiciousCount"] });
      setSecureDialogOpen(false);
      setSuccessMessage(
        `Tài khoản đã được bảo mật. ${response.sessions_revoked} phiên đã bị thu hồi. Đang chuyển đến trang đổi mật khẩu...`
      );
      setTimeout(() => {
        setSuccessMessage(null);
        router.push("/settings");
      }, 2000);
    },
    onError: () => {
      setError("Không thể bảo mật tài khoản. Vui lòng thử lại.");
      setTimeout(() => setError(null), 5000);
    },
  });

  // ---- Handlers ----
  const sessions = sessionsData?.sessions || [];

  const handleRevokeSession = async (sessionId: number) => {
    try {
      setError(null);
      await revokeSessionMutation.mutateAsync(sessionId);
      setSuccessMessage("Thu hồi phiên thành công");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch {
      setError("Không thể thu hồi phiên. Vui lòng thử lại.");
    }
  };

  const handleRevokeAllOthers = async () => {
    try {
      setError(null);
      const currentSession = sessions.find((s) => s.is_current);
      if (!currentSession) {
        setError("Không thể xác định phiên hiện tại.");
        return;
      }
      await revokeAllOthersMutation.mutateAsync({
        currentSessionId: currentSession.id,
      });
      setSuccessMessage("Thu hồi tất cả phiên khác thành công");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch {
      setError("Không thể thu hồi phiên. Vui lòng thử lại.");
    }
  };

  const handleConfirmLogin = (loginId: number) => {
    setError(null);
    confirmMutation.mutate({ login_id: loginId, trust_device: true });
  };

  const handleSecureClick = (loginId: number) => {
    setSelectedLoginId(loginId);
    setSecureDialogOpen(true);
  };

  const handleSecureConfirm = () => {
    if (selectedLoginId !== null) {
      secureMutation.mutate(selectedLoginId);
    }
  };

  // ---- Derived data ----
  const suspiciousLogins =
    loginHistoryData?.items.filter(
      (item) => item.is_suspicious && !item.user_response
    ) || [];

  // Section 3: full audit trail (read-only, no exclusions)
  const historyItems = loginHistoryData?.items || [];

  const isSessionsLoading =
    revokeSessionMutation.isPending || revokeAllOthersMutation.isPending;

  // ---- Sync SecurityBanner with suspicious count ----
  useEffect(() => {
    triggerSuspiciousLoginBanner(suspiciousLogins.length);
  }, [suspiciousLogins.length]);

  return (
    <div className="max-w-4xl space-y-8">
      {/* Shared success/error alerts */}
      {successMessage && (
        <Alert className="border-success-500 bg-success-50">
          <CheckCircle2 className="text-success-600 h-4 w-4" />
          <AlertTitle className="text-success-800">Thành công</AlertTitle>
          <AlertDescription className="text-success-700">
            {successMessage}
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Lỗi</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Section 1: Suspicious logins (hidden if none) */}
      <SuspiciousLoginsSection
        items={suspiciousLogins}
        onConfirm={handleConfirmLogin}
        onSecure={handleSecureClick}
      />

      {/* Section 2: Active sessions */}
      <ActiveSessionsSection
        sessions={sessions}
        onRevokeSession={handleRevokeSession}
        onRevokeAllOthers={handleRevokeAllOthers}
        isLoading={isSessionsLoading}
      />

      {/* Section 3: Login history audit trail (excludes pending suspicious) */}
      <LoginHistorySection items={historyItems} />

      {/* Secure account confirmation dialog */}
      <SecureAccountDialog
        open={secureDialogOpen}
        onOpenChange={setSecureDialogOpen}
        onConfirm={handleSecureConfirm}
        isPending={secureMutation.isPending}
      />
    </div>
  );
}
