// src/app/(dashboard)/settings/sessions/_components/SessionsClient.tsx
"use client";

import { useState } from "react";
import { SessionList } from "@/components/sessions/SessionList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import {
  useSessions,
  useRevokeSession,
  useRevokeAllOtherSessions,
} from "@/hooks/useSessions";
import type { UserSessionListResponse } from "@/lib/api/sessions";

interface SessionsClientProps {
  initialData?: UserSessionListResponse;
}

export function SessionsClient({ initialData }: SessionsClientProps) {
  const { data: sessionsData } = useSessions({ initialData });
  const revokeSessionMutation = useRevokeSession();
  const revokeAllOthersMutation = useRevokeAllOtherSessions();

  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const sessions = sessionsData?.sessions || [];

  const handleRevokeSession = async (sessionId: number) => {
    try {
      setError(null);
      await revokeSessionMutation.mutateAsync(sessionId);
      setSuccessMessage("Thu hồi phiên thành công");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Không thể thu hồi phiên. Vui lòng thử lại.");
      console.error("Error revoking session:", err);
    }
  };

  const handleRevokeAllOthers = async () => {
    try {
      setError(null);
      const currentSession = sessions.find((s) => s.is_current);
      await revokeAllOthersMutation.mutateAsync({
        currentSessionId: currentSession?.id,
      });
      setSuccessMessage("Thu hồi tất cả phiên khác thành công");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Không thể thu hồi phiên. Vui lòng thử lại.");
      console.error("Error revoking all sessions:", err);
    }
  };

  const isLoading =
    revokeSessionMutation.isPending || revokeAllOthersMutation.isPending;

  return (
    <div className="container max-w-4xl py-8">
      {/* Success Message */}
      {successMessage && (
        <Alert className="mb-6 border-success-500 bg-success-50">
          <CheckCircle2 className="h-4 w-4 text-success-600" />
          <AlertTitle className="text-success-800">Thành công</AlertTitle>
          <AlertDescription className="text-success-700">
            {successMessage}
          </AlertDescription>
        </Alert>
      )}

      {/* Error Message */}
      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Lỗi</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Session List */}
      <SessionList
        sessions={sessions}
        onRevokeSession={handleRevokeSession}
        onRevokeAllOthers={handleRevokeAllOthers}
        isLoading={isLoading}
      />
    </div>
  );
}
