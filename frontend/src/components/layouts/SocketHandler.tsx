// components/layouts/SocketHandler.tsx
"use client";

import { useEffect, useRef } from "react";
import { useAuthStore } from "@/lib/stores/auth.store";
import { socketService } from "@/lib/socket/client";
import { toast } from "sonner";
import { useAddNotification } from "@/hooks/useNotifications";
import { useNotificationPreferences } from "@/hooks/useNotificationPreferences";
import { playNotificationSound, showBrowserNotification } from "@/lib/sound";
import type { Notification } from "@/types/api.types";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Component "vô hình" (không render)
 * Quản lý kết nối Socket.IO và lắng nghe các sự kiện auth toàn cục.
 */
export function SocketHandler() {
  const { isAuthenticated, logout } = useAuthStore();
  const addNotification = useAddNotification();
  const { data: preferences } = useNotificationPreferences();
  const queryClient = useQueryClient();

  // ✅ CẢI TIẾN: Dùng ref cho hàm logout để tránh "stale closure"
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  // ✅ SECURITY FIX: Manage Socket.io connection based on authentication state
  // No longer tracks JTI or token - backend reads auth from httpOnly cookies
  useEffect(() => {
    if (isAuthenticated) {
      // When authenticated, connect Socket.io (cookies sent automatically)
      console.log("[SocketHandler] User authenticated, connecting Socket.io...");
      socketService.connect();
    } else {
      // When not authenticated, disconnect
      console.log("[SocketHandler] User not authenticated, disconnecting Socket.io...");
      socketService.disconnect();
    }

    // Cleanup khi component unmount
    return () => {
      socketService.disconnect();
    };
  }, [isAuthenticated]); // Chạy lại khi `isAuthenticated` thay đổi

  // 2. Lắng nghe sự kiện
  useEffect(() => {
    const socket = socketService.getSocket();
    if (!socket) {
      // Socket chưa sẵn sàng
      // effect [isAuthenticated] ở trên sẽ chạy và kích hoạt lại effect này
      return;
    }

    // ✅ SECURITY FIX: Simplified force logout handlers
    // Backend emits to user_room_{user_id}, so all sessions receive the event
    // No need to track JTI client-side - backend manages session invalidation

    // Lắng nghe sự kiện "thu hồi batch" (specific sessions revoked)
    const handleForceLogoutBatch = (data: { revoked_jtis: string[] }) => {
      console.log("[SocketHandler] Received 'force_logout_batch'", data);

      toast.error("Phiên của bạn đã bị thu hồi", {
        description: "Đăng xuất tự động...",
        duration: 5000,
      });

      // Gửi xác nhận về server
      socket.emit("logout_confirmed", {});

      logoutRef.current(); // Dùng ref để gọi logout
    };

    // Lắng nghe sự kiện "thu hồi tất cả" (ví dụ: đổi mật khẩu)
    const handleForceLogoutAll = (data: { reason: string }) => {
      console.log("[SocketHandler] Received 'force_logout_all'", data);
      toast.error("Tất cả các phiên đã bị vô hiệu hóa", {
        description: `Lý do: ${data.reason}. Đăng xuất tự động...`,
        duration: 5000,
      });

      // Gửi xác nhận về server
      socket.emit("logout_confirmed", { reason: data.reason });

      logoutRef.current(); // Dùng ref
    };

    // Lắng nghe sự kiện notification (real-time notifications)
    const handleNewNotification = (notification: Notification) => {
      console.log("[SocketHandler] Received new notification:", notification);

      // Add notification to the query cache
      addNotification(notification);

      // Get type-specific preferences
      const typePrefs = preferences?.type_preferences?.[notification.type];
      const soundAllowed = typePrefs?.sound ?? true;
      const browserAllowed = typePrefs?.browser ?? true;

      // Play sound if enabled globally and for this type
      if (preferences?.sound_enabled && soundAllowed) {
        playNotificationSound();
      }

      // Show browser notification if enabled
      if (preferences?.browser_enabled && browserAllowed) {
        showBrowserNotification(notification.title, {
          body: notification.message,
          icon: "/favicon.ico",
          tag: `notification-${notification.id}`,
        });
      }

      // Always show toast notification (this is in-app, separate from browser notifications)
      toast.info(notification.title, {
        description: notification.message,
        duration: 5000,
      });
    };

    // ✅ REAL-TIME DATA SYNC (v16): Lắng nghe sự kiện data_updated
    const handleDataUpdated = (data: {
      resource_type: string;
      operation: "create" | "update" | "delete";
      resource_id: number;
      data?: Record<string, unknown>;
      timestamp: string;
    }) => {
      console.log("[SocketHandler] Received data_updated event:", data);

      // Invalidate queries based on resource_type
      switch (data.resource_type) {
        case "user":
          // Invalidate all user-related queries
          queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
          queryClient.invalidateQueries({ queryKey: ["admin", "users", "list"] });
          queryClient.invalidateQueries({ queryKey: ["admin", "statistics"] });

          // Show subtle toast for real-time updates
          const operationText =
            data.operation === "create" ? "created" :
            data.operation === "update" ? "updated" :
            "deleted";

          toast.info(`User ${operationText}`, {
            description: `Data refreshed automatically`,
            duration: 3000,
          });
          break;

        case "lead":
          queryClient.invalidateQueries({ queryKey: ["leads"] });
          break;

        case "organization":
          // Invalidate all organization-related queries
          queryClient.invalidateQueries({ queryKey: ["organization"] });

          // Show toast for organization updates
          const orgOperation =
            data.operation === "create" ? "đã tạo" :
            data.operation === "update" ? "đã cập nhật" :
            "đã xóa";

          toast.info(`Đơn vị tổ chức ${orgOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "major":
          // Invalidate all major-related queries
          queryClient.invalidateQueries({ queryKey: ["organization", "majors"] });
          queryClient.invalidateQueries({ queryKey: ["organization", "list"] });

          // Show toast for major updates
          const majorOperation =
            data.operation === "create" ? "đã tạo" :
            data.operation === "update" ? "đã cập nhật" :
            "đã xóa";

          toast.info(`Ngành học ${majorOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "policy":
          queryClient.invalidateQueries({ queryKey: ["policies"] });
          queryClient.invalidateQueries({ queryKey: ["admin", "roles"] });
          break;

        default:
          console.warn("[SocketHandler] Unknown resource_type:", data.resource_type);
      }
    };

    // Đăng ký listeners
    socket.on("force_logout_batch", handleForceLogoutBatch);
    socket.on("force_logout_all", handleForceLogoutAll);
    socket.on("notification", handleNewNotification);
    socket.on("data_updated", handleDataUpdated);

    // Cleanup listeners khi effect này chạy lại hoặc component unmount
    return () => {
      socket.off("force_logout_batch", handleForceLogoutBatch);
      socket.off("force_logout_all", handleForceLogoutAll);
      socket.off("notification", handleNewNotification);
      socket.off("data_updated", handleDataUpdated);
    };
    // ✅ SECURITY FIX: Removed 'token' from dependencies, now use 'isAuthenticated'
  }, [isAuthenticated, addNotification, preferences, queryClient]);

  return null; // Không render gì cả
}
