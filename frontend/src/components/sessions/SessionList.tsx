// frontend/src/components/sessions/SessionList.tsx
/**
 * Component to display list of active user sessions.
 */

"use client";

import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { Monitor, Smartphone, Tablet, MapPin, Clock, AlertTriangle } from "lucide-react";
import type { UserSession } from "@/types/session";
import { formatDeviceInfo, formatLocation, getRelativeTime, getDeviceIcon } from "@/types/session";
import { cn } from "@/lib/utils"; // ✅ 1. Import CN utility

interface SessionListProps {
  sessions: UserSession[];
  onRevokeSession: (sessionId: number) => Promise<void>;
  onRevokeAllOthers: () => Promise<void>;
  isLoading?: boolean;
}

export function SessionList({
  sessions,
  onRevokeSession,
  onRevokeAllOthers,
  isLoading = false,
}: SessionListProps) {
  // ✅ 2. Thêm state cho dialog revoke đơn lẻ
  const [sessionToRevoke, setSessionToRevoke] = useState<UserSession | null>(null);
  const [isRevokingSingle, setIsRevokingSingle] = useState(false);

  // (State cho revoke all giữ nguyên)
  const [showRevokeAllDialog, setShowRevokeAllDialog] = useState(false);
  const [isRevokingAll, setIsRevokingAll] = useState(false);

  // ✅ 3. Tạo hàm handler mới cho dialog
  const handleConfirmRevokeSingle = async () => {
    if (!sessionToRevoke) return;

    setIsRevokingSingle(true);
    try {
      await onRevokeSession(sessionToRevoke.id);
    } finally {
      setIsRevokingSingle(false);
      setSessionToRevoke(null); // Đóng dialog
    }
  };

  // (Handler cho revoke all giữ nguyên)
  const handleRevokeAllOthers = async () => {
    setIsRevokingAll(true);
    try {
      await onRevokeAllOthers();
      setShowRevokeAllDialog(false);
    } finally {
      setIsRevokingAll(false);
    }
  };

  const getDeviceIconComponent = (session: UserSession) => {
    const iconName = getDeviceIcon(session);
    const className = "h-5 w-5 text-muted-foreground";

    switch (iconName) {
      case "smartphone":
        return <Smartphone className={className} />;
      case "tablet":
        return <Tablet className={className} />;
      case "monitor":
      default:
        return <Monitor className={className} />;
    }
  };

  const currentSession = sessions.find((s) => s.is_current);
  const otherSessions = sessions.filter((s) => !s.is_current);

  // ✅ 4. Hàm render icon với status dot
  const renderIconWithStatus = (session: UserSession) => {
    const isCurrent = session.is_current;

    return (
      <span className="relative flex h-5 w-5">
        {getDeviceIconComponent(session)}
        <span
          className={cn(
            "ring-card absolute right-0 bottom-0 block h-2 w-2 rounded-full ring-2",
            isCurrent ? "bg-green-500" : "bg-gray-400"
          )}
        />
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header (giữ nguyên) */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Active Sessions</h2>
          <p className="text-muted-foreground">Manage your active login sessions across devices</p>
        </div>
        {otherSessions.length > 0 && (
          <Button
            variant="destructive"
            onClick={() => setShowRevokeAllDialog(true)}
            disabled={isLoading}
          >
            Revoke All Other Sessions
          </Button>
        )}
      </div>

      {/* Current Session */}
      {currentSession && (
        <Card className="border-primary">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {/* ✅ 5. Sử dụng hàm render icon mới */}
                {renderIconWithStatus(currentSession)}
                <div>
                  <CardTitle className="text-lg">Current Session</CardTitle>
                  <CardDescription>{formatDeviceInfo(currentSession)}</CardDescription>
                </div>
              </div>
              <Badge variant="default">Active Now</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <SessionDetails session={currentSession} />
          </CardContent>
        </Card>
      )}

      {/* Other Sessions */}
      {otherSessions.length > 0 ? (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Other Sessions</h3>
          {otherSessions.map((session) => (
            <Card key={session.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {/* ✅ 6. Sử dụng hàm render icon mới */}
                    {renderIconWithStatus(session)}
                    <div>
                      <CardTitle className="text-lg">{formatDeviceInfo(session)}</CardTitle>
                      <CardDescription>
                        Last active {getRelativeTime(session.last_activity_at)}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {session.is_suspicious && (
                      <Badge variant="destructive" className="gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Suspicious
                      </Badge>
                    )}
                    {/* ✅ DEFENSE IN DEPTH: Disable revoke button for current session */}
                    <Button
                      variant={session.is_current ? "outline" : "destructive"}
                      size="sm"
                      onClick={() => setSessionToRevoke(session)}
                      disabled={isLoading || session.is_current}
                      title={session.is_current ? "This is your current session" : "Revoke this session"}
                    >
                      {session.is_current ? "Current" : "Revoke"}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <SessionDetails session={session} />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="text-muted-foreground py-8 text-center">
            No other active sessions
          </CardContent>
        </Card>
      )}

      {/* ✅ 8. Thêm Dialog cho Revoke đơn lẻ */}
      <AlertDialog
        open={!!sessionToRevoke}
        onOpenChange={(open) => !open && setSessionToRevoke(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke this session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will log out the session on{" "}
              <strong>{sessionToRevoke ? formatDeviceInfo(sessionToRevoke) : "this device"}</strong>
              . This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingSingle}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRevokeSingle}
              disabled={isRevokingSingle}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingSingle ? "Revoking..." : "Revoke Session"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Dialog cho Revoke All (giữ nguyên) */}
      <AlertDialog open={showRevokeAllDialog} onOpenChange={setShowRevokeAllDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke all other sessions?</AlertDialogTitle>
            <AlertDialogDescription>
              This will log you out from all other devices. You will remain logged in on this
              device. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingAll}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeAllOthers}
              disabled={isRevokingAll}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingAll ? "Revoking..." : "Revoke All"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// Session details component
function SessionDetails({ session }: { session: UserSession }) {
  return (
    <div className="grid gap-3 text-sm">
      <div className="text-muted-foreground flex items-center gap-2">
        <MapPin className="h-4 w-4" />
        <span>{formatLocation(session)}</span>
      </div>
      <div className="text-muted-foreground flex items-center gap-2">
        <Clock className="h-4 w-4" />
        <span>
          Created {getRelativeTime(session.created_at)} • Expires{" "}
          {getRelativeTime(session.expires_at)}
        </span>
      </div>
      {session.ip_address && (
        <div className="text-muted-foreground text-xs">IP: {session.ip_address}</div>
      )}
    </div>
  );
}
