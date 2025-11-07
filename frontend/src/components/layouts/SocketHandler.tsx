// components/layouts/SocketHandler.tsx
"use client";

import { useEffect, useRef } from "react";
import { useAuthStore } from "@/lib/stores/auth.store";
import { socketService } from "@/lib/socket/client";
import { getRefreshJtiFromToken } from "@/lib/utils/jwt";
import { toast } from "sonner";
import { useAddNotification } from "@/hooks/useNotifications";
import type { Notification } from "@/types/api.types";

/**
 * Component "vô hình" (không render)
 * Quản lý kết nối Socket.IO và lắng nghe các sự kiện auth toàn cục.
 */
export function SocketHandler() {
  const { token, logout } = useAuthStore();
  const addNotification = useAddNotification();

  // Lưu trữ JTI của trình duyệt hiện tại
  const myJti = useRef<string | null>(null);

  // ✅ CẢI TIẾN: Dùng ref cho hàm logout để tránh "stale closure"
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  // 1. Quản lý Kết nối / Ngắt kết nối
  useEffect(() => {
    if (token) {
      // Khi có token (đăng nhập)
      myJti.current = getRefreshJtiFromToken(token);
      console.log("[SocketHandler] My JTI:", myJti.current);
      socketService.connect();
    } else {
      // Khi không có token (đăng xuất)
      socketService.disconnect();
      myJti.current = null;
    }

    // Cleanup khi component unmount
    return () => {
      socketService.disconnect();
    };
  }, [token]); // Chỉ chạy lại khi `token` thay đổi

  // 2. Lắng nghe sự kiện
  useEffect(() => {
    const socket = socketService.getSocket();
    if (!socket) {
      // Socket chưa sẵn sàng (ví dụ: token đến chậm),
      // effect [token] ở trên sẽ chạy và kích hoạt lại effect này
      return;
    }

    // ✅ CẢI TIẾN: Vấn đề #6 - Dùng event `logout_confirmed`
    // Lắng nghe sự kiện "thu hồi batch"
    const handleForceLogoutBatch = (data: { revoked_jtis: string[] }) => {
      console.log("[SocketHandler] Received 'force_logout_batch'", data);

      if (myJti.current && data.revoked_jtis.includes(myJti.current)) {
        toast.error("Phiên của bạn đã bị thu hồi", {
          description: "Đăng xuất tự động...",
          duration: 5000,
        });

        // Gửi xác nhận về server
        socket.emit("logout_confirmed", { jti: myJti.current });

        logoutRef.current(); // Dùng ref để gọi logout
      }
    };

    // Lắng nghe sự kiện "thu hồi tất cả" (ví dụ: đổi mật khẩu)
    const handleForceLogoutAll = (data: { reason: string }) => {
      console.log("[SocketHandler] Received 'force_logout_all'", data);
      toast.error("Tất cả các phiên đã bị vô hiệu hóa", {
        description: `Lý do: ${data.reason}. Đăng xuất tự động...`,
        duration: 5000,
      });

      // Gửi xác nhận về server
      socket.emit("logout_confirmed", { jti: myJti.current, reason: data.reason });

      logoutRef.current(); // Dùng ref
    };

    // Lắng nghe sự kiện notification (real-time notifications)
    const handleNewNotification = (notification: Notification) => {
      console.log("[SocketHandler] Received new notification:", notification);

      // Add notification to the query cache
      addNotification(notification);

      // Show toast notification
      toast.info(notification.title, {
        description: notification.message,
        duration: 5000,
      });
    };

    // Đăng ký listeners
    socket.on("force_logout_batch", handleForceLogoutBatch);
    socket.on("force_logout_all", handleForceLogoutAll);
    socket.on("notification", handleNewNotification);

    // Cleanup listeners khi effect này chạy lại hoặc component unmount
    return () => {
      socket.off("force_logout_batch", handleForceLogoutBatch);
      socket.off("force_logout_all", handleForceLogoutAll);
      socket.off("notification", handleNewNotification);
    };
  }, [token, addNotification]); // Chạy lại nếu `token` hoặc `addNotification` thay đổi

  return null; // Không render gì cả
}
