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
import { Monitor, Smartphone, Tablet, MapPin, Clock, AlertTriangle, Globe } from "lucide-react";
import type { UserSession } from "@/types/session";
import {
  formatDeviceInfo,
  formatLocation,
  getRelativeTime,
  getTimeUntilExpiration,
  getDeviceIcon,
} from "@/types/session";
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
            // Base styles
            "absolute right-0 bottom-0 block h-2 w-2 rounded-full",

            // ✅ SỬA LỖI UX: Luôn là màu xanh (tất cả sessions đều active)
            "bg-green-500",

            // ✅ Tinh chỉnh: Dùng viền (ring) để làm nổi bật session hiện tại
            "ring-2",
            isCurrent ? "ring-primary" : "ring-card"
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
          <h2 className="text-2xl font-bold tracking-tight">Phiên Đang Hoạt Động</h2>
          <p className="text-muted-foreground">Quản lý các phiên đăng nhập trên các thiết bị</p>
        </div>
        {otherSessions.length > 0 && (
          <Button
            variant="destructive"
            onClick={() => setShowRevokeAllDialog(true)}
            disabled={isLoading}
          >
            Thu hồi Tất cả Phiên Khác
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
                  <CardTitle className="text-lg">Phiên Hiện Tại</CardTitle>
                  <CardDescription>{formatDeviceInfo(currentSession)}</CardDescription>
                </div>
              </div>
              <Badge variant="default">Đang hoạt động</Badge>
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
          <h3 className="text-lg font-semibold">Phiên Khác</h3>
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
                        Hoạt động lần cuối {getRelativeTime(session.last_activity_at)}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {session.is_suspicious && (
                      <Badge variant="destructive" className="gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Đáng ngờ
                      </Badge>
                    )}
                    {/* ✅ DEFENSE IN DEPTH: Disable revoke button for current session */}
                    <Button
                      variant={session.is_current ? "outline" : "destructive"}
                      size="sm"
                      onClick={() => setSessionToRevoke(session)}
                      disabled={isLoading || session.is_current}
                      title={session.is_current ? "Đây là phiên hiện tại" : "Thu hồi phiên này"}
                    >
                      {session.is_current ? "Hiện tại" : "Thu hồi"}
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
            Không có phiên khác đang hoạt động
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
            <AlertDialogTitle>Thu hồi phiên này?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ đăng xuất phiên trên{" "}
              <strong>{sessionToRevoke ? formatDeviceInfo(sessionToRevoke) : "thiết bị này"}</strong>
              . Không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingSingle}>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmRevokeSingle}
              disabled={isRevokingSingle}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingSingle ? "Đang thu hồi..." : "Thu hồi Phiên"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Dialog cho Revoke All (giữ nguyên) */}
      <AlertDialog open={showRevokeAllDialog} onOpenChange={setShowRevokeAllDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Thu hồi tất cả phiên khác?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ đăng xuất bạn khỏi tất cả thiết bị khác. Bạn sẽ vẫn đăng nhập trên
              thiết bị này. Không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRevokingAll}>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevokeAllOthers}
              disabled={isRevokingAll}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isRevokingAll ? "Đang thu hồi..." : "Thu hồi Tất cả"}
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
          Tạo lúc {getRelativeTime(session.created_at)} • Hết hạn{" "}
          {getTimeUntilExpiration(session.expires_at)}
        </span>
      </div>
      {session.ip_address && (
        <div className="text-muted-foreground flex items-center gap-2">
          <Globe className="h-4 w-4" />
          <span className="text-xs">IP: {session.ip_address}</span>
        </div>
      )}
    </div>
  );
}
