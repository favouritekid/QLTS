// src/app/(dashboard)/settings/security/_components/ActiveSessionsSection.tsx
"use client";

import { SessionList } from "@/components/sessions/SessionList";
import type { UserSession } from "@/types/session";

interface ActiveSessionsSectionProps {
  sessions: UserSession[];
  onRevokeSession: (sessionId: number) => Promise<void>;
  onRevokeAllOthers: () => Promise<void>;
  isLoading: boolean;
}

export function ActiveSessionsSection({
  sessions,
  onRevokeSession,
  onRevokeAllOthers,
  isLoading,
}: ActiveSessionsSectionProps) {
  return (
    <section>
      <SessionList
        sessions={sessions}
        onRevokeSession={onRevokeSession}
        onRevokeAllOthers={onRevokeAllOthers}
        isLoading={isLoading}
      />
    </section>
  );
}
