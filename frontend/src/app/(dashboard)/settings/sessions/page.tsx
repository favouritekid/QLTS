// frontend/src/app/(dashboard)/settings/sessions/page.tsx
/**
 * Session management page.
 * Allows users to view and manage their active sessions.
 */

"use client";

import React, { useEffect, useState } from "react";
import { SessionList } from "@/components/sessions/SessionList";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import {
  getActiveSessions,
  revokeSession,
  revokeAllOtherSessions,
} from "@/lib/api/sessions";
import type { UserSession } from "@/types/session";

export default function SessionsPage() {
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Fetch sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getActiveSessions();
      setSessions(response.sessions);
    } catch (err) {
      setError("Failed to load sessions. Please try again.");
      console.error("Error loading sessions:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRevokeSession = async (sessionId: number) => {
    try {
      await revokeSession(sessionId);
      setSuccessMessage("Session revoked successfully");
      
      // Remove from local state
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Failed to revoke session. Please try again.");
      console.error("Error revoking session:", err);
    }
  };

  const handleRevokeAllOthers = async () => {
    try {
      // Find current session ID
      const currentSession = sessions.find((s) => s.is_current);
      
      await revokeAllOtherSessions(currentSession?.id);
      setSuccessMessage("All other sessions revoked successfully");
      
      // Keep only current session in local state
      if (currentSession) {
        setSessions([currentSession]);
      } else {
        setSessions([]);
      }
      
      // Clear success message after 3 seconds
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError("Failed to revoke sessions. Please try again.");
      console.error("Error revoking all sessions:", err);
    }
  };

  return (
    <div className="container max-w-4xl py-8">
      {/* Success Message */}
      {successMessage && (
        <Alert className="mb-6 border-green-500 bg-green-50">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertTitle className="text-green-800">Success</AlertTitle>
          <AlertDescription className="text-green-700">
            {successMessage}
          </AlertDescription>
        </Alert>
      )}

      {/* Error Message */}
      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Loading State */}
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <SessionList
          sessions={sessions}
          onRevokeSession={handleRevokeSession}
          onRevokeAllOthers={handleRevokeAllOthers}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}

