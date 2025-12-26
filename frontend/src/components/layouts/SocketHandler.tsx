// components/layouts/SocketHandler.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/lib/stores/auth.store";
import { socketService } from "@/lib/socket/client";
import { toast } from "sonner";
import { useAddNotification } from "@/hooks/useNotifications";
import { useNotificationPreferences } from "@/hooks/useNotificationPreferences";
import { playNotificationSound, showBrowserNotification } from "@/lib/sound";
import type { Notification } from "@/types/api.types";
import { useQueryClient } from "@tanstack/react-query";
import { leadsKeys } from "@/hooks/useLeads";

/**
 * Component "vô hình" (không render)
 * Quản lý kết nối Socket.IO và lắng nghe các sự kiện auth toàn cục.
 */
export function SocketHandler() {
  const { isAuthenticated, logout, user } = useAuthStore();
  const addNotification = useAddNotification();
  const { data: preferences } = useNotificationPreferences();
  const queryClient = useQueryClient();

  // ✅ CẢI TIẾN: Dùng ref cho hàm logout để tránh "stale closure"
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  // ✅ FIX: Track socket connection state to trigger listener setup
  const [isSocketConnected, setIsSocketConnected] = useState(false);

  // ✅ SECURITY FIX: Manage Socket.io connection based on authentication state
  // No longer tracks JTI or token - backend reads auth from httpOnly cookies
  // ✅ PHASE 1.1.3: Staggered reconnection with random delay (Thundering Herd protection)
  useEffect(() => {
    if (isAuthenticated) {
      // ✅ PHASE 1.1.3: Add random delay 0-5000ms before connecting
      // This prevents Thundering Herd when backend restarts and all users reconnect simultaneously
      // Connections are spread over 5 seconds instead of all at once
      const delay = Math.random() * 5000;

      console.log(
        `[SocketHandler] User authenticated, connecting Socket.io in ${Math.round(delay)}ms...`
      );

      const timeoutId = setTimeout(() => {
        socketService.connect();
        console.log("[SocketHandler] Socket.io connection initiated after delay");
      }, delay);

      // Cleanup: clear timeout if effect re-runs before connection
      return () => {
        clearTimeout(timeoutId);
        socketService.disconnect();
        setIsSocketConnected(false);
      };
    } else {
      // When not authenticated, disconnect immediately (no delay needed)
      console.log("[SocketHandler] User not authenticated, disconnecting Socket.io...");
      socketService.disconnect();
      // Use queueMicrotask to avoid synchronous setState in effect
      queueMicrotask(() => setIsSocketConnected(false));
      return undefined;
    }
  }, [isAuthenticated]); // Chạy lại khi `isAuthenticated` thay đổi

  // ✅ FIX: Listen for socket connection to trigger listener setup
  useEffect(() => {
    const checkConnection = () => {
      const socket = socketService.getSocket();
      if (socket?.connected && !isSocketConnected) {
        console.log("[SocketHandler] Socket connected, setting up listeners...");
        setIsSocketConnected(true);
      }
    };

    // Check immediately
    checkConnection();

    // Also check when socket emits 'connect' event
    const socket = socketService.getSocket();
    if (socket) {
      const handleConnect = () => {
        console.log("[SocketHandler] Socket 'connect' event received");
        setIsSocketConnected(true);
      };
      socket.on("connect", handleConnect);
      return () => {
        socket.off("connect", handleConnect);
      };
    }

    // Polling fallback for connection state
    const intervalId = setInterval(checkConnection, 500);
    return () => clearInterval(intervalId);
  }, [isAuthenticated, isSocketConnected]);

  // 2. Lắng nghe sự kiện - NOW DEPENDS ON isSocketConnected
  useEffect(() => {
    const socket = socketService.getSocket();
    if (!socket || !isSocketConnected) {
      // Socket chưa sẵn sàng - effect sẽ chạy lại khi isSocketConnected thay đổi
      console.log("[SocketHandler] Socket not ready, waiting...", {
        hasSocket: !!socket,
        isSocketConnected,
      });
      return;
    }

    console.log("[SocketHandler] ✅ Registering event listeners (socket connected)");

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

      logoutRef.current(); // Clear auth state
      
      // ✅ FIX: Redirect to login page after clearing state
      // logout() only clears state, doesn't redirect
      setTimeout(() => {
        window.location.href = "/login";
      }, 1500); // Short delay to show toast
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

      logoutRef.current(); // Clear auth state
      
      // ✅ FIX: Redirect to login page after clearing state
      setTimeout(() => {
        window.location.href = "/login";
      }, 1500);
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
      // Use different toast style for reminders
      if (notification.type === "reminder") {
        toast.warning(notification.title, {
          description: notification.message,
          duration: 15000, // 15 seconds for reminders - more prominent
          action: notification.link
            ? {
                label: "Xem Lead",
                onClick: () => {
                  window.location.href = notification.link!;
                },
              }
            : undefined,
        });
      } else {
        toast.info(notification.title, {
          description: notification.message,
          duration: 5000,
        });
      }
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
            data.operation === "create"
              ? "created"
              : data.operation === "update"
                ? "updated"
                : "deleted";

          toast.info(`User ${operationText}`, {
            description: `Data refreshed automatically`,
            duration: 3000,
          });
          break;

        case "lead":
          queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
          break;

        case "organization":
          // Invalidate all organization-related queries
          queryClient.invalidateQueries({ queryKey: ["organization"] });

          // Show toast for organization updates
          const orgOperation =
            data.operation === "create"
              ? "đã tạo"
              : data.operation === "update"
                ? "đã cập nhật"
                : "đã xóa";

          toast.info(`Đơn vị tổ chức ${orgOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "program":
          // Invalidate all major program queries (3-tier Tier 1)
          queryClient.invalidateQueries({ queryKey: ["organization"] });
          queryClient.invalidateQueries({ queryKey: ["organization", "major-programs"] });

          const programOperation =
            data.operation === "create"
              ? "đã tạo"
              : data.operation === "update"
                ? "đã cập nhật"
                : "đã xóa";

          toast.info(`Chương trình đào tạo ${programOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "offering":
          // Invalidate program offering queries (3-tier Tier 2)
          queryClient.invalidateQueries({ queryKey: ["organization"] });
          queryClient.invalidateQueries({ queryKey: ["organization", "offerings"] });

          const offeringOperation =
            data.operation === "create"
              ? "đã tạo"
              : data.operation === "update"
                ? "đã cập nhật"
                : "đã xóa";

          toast.info(`Loại hình đào tạo ${offeringOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "academic_info":
          // Invalidate academic info queries (3-tier Tier 3)
          queryClient.invalidateQueries({ queryKey: ["organization"] });
          queryClient.invalidateQueries({ queryKey: ["organization", "academic-info"] });

          const academicOperation =
            data.operation === "create"
              ? "đã tạo"
              : data.operation === "update"
                ? "đã cập nhật"
                : "đã xóa";

          toast.info(`Thông tin tuyển sinh ${academicOperation}`, {
            description: "Dữ liệu đã được làm mới tự động",
            duration: 3000,
          });
          break;

        case "major":
          // Legacy support - Invalidate all major-related queries
          queryClient.invalidateQueries({ queryKey: ["organization", "majors"] });
          queryClient.invalidateQueries({ queryKey: ["organization", "list"] });

          // Show toast for major updates
          const majorOperation =
            data.operation === "create"
              ? "đã tạo"
              : data.operation === "update"
                ? "đã cập nhật"
                : "đã xóa";

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

    // ✅ REAL-TIME LEAD ASSIGNMENT (Week 1): Lắng nghe sự kiện lead_assigned
    const handleLeadAssigned = (data: {
      lead_id: number;
      lead_name: string;
      lead_phone: string;
      lead_email: string;
      offering_name: string;
      unit_name: string;
      assigned_at: string;
      assignment_type: "automatic" | "manual";
      priority: string;
      message: string;
    }) => {
      console.log("[SocketHandler] lead_assigned → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh officer's lead list
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.insights(data.lead_id) });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME APPLICATION EVENTS (Week 2): Lắng nghe sự kiện application_created
    const handleApplicationCreated = (data: {
      application_id: number;
      lead_id: number;
      lead_name: string;
      officer_id: number;
      major_program_name: string;
      status: string;
      created_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] application_created → invalidating queries (silent sync)");

      // Invalidate application-related queries
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["officer", "applications"] });
      queryClient.invalidateQueries({ queryKey: ["lead", data.lead_id] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME APPLICATION EVENTS (Week 2): Lắng nghe sự kiện application_status_changed
    const handleApplicationStatusChanged = (data: {
      application_id: number;
      lead_id: number;
      old_status: string;
      new_status: string;
      changed_by: string;
      changed_at: string;
      message: string;
    }) => {
      console.log(
        "[SocketHandler] application_status_changed → invalidating queries (silent sync)"
      );

      // Invalidate application-related queries
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["application", data.application_id] });
      queryClient.invalidateQueries({ queryKey: ["officer", "applications"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME APPLICATION EVENTS (Week 2): Lắng nghe sự kiện application_documents_updated
    const handleApplicationDocumentsUpdated = (data: {
      application_id: number;
      lead_id: number;
      updated_by: string;
      updated_at: string;
      documents_summary: string;
      message: string;
    }) => {
      console.log("[SocketHandler] Received application_documents_updated event:", data);

      // Invalidate application-related queries
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["application", data.application_id] });
      queryClient.invalidateQueries({ queryKey: ["officer", "applications"] });

      // Show subtle toast notification
      toast.info(data.message, {
        description: `${data.documents_summary} by ${data.updated_by}`,
        duration: 4000,
      });
    };

    // ✅ REAL-TIME PIPELINE CONFIG (Week 3): Lắng nghe sự kiện pipeline_config_updated
    const handlePipelineConfigUpdated = (data: {
      config_type: "pipeline_stage" | "consultation_status" | "allowed_transition";
      operation: "create" | "update" | "delete";
      resource_id: string | number;
      resource_data: Record<string, unknown>;
      updated_by: string;
      updated_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] pipeline_config_updated → invalidating queries (silent sync)");

      // Invalidate pipeline-related queries for auto-refresh
      queryClient.invalidateQueries({ queryKey: ["pipeline-stages"] });
      queryClient.invalidateQueries({ queryKey: ["consultation-statuses"] });
      queryClient.invalidateQueries({ queryKey: ["allowed-transitions"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "pipeline"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME CONSULTATION MANAGEMENT: Lắng nghe sự kiện consultation_created
    const handleConsultationCreated = (data: {
      lead_id: number;
      consultation_id: number;
      consultation_status_id: string;
      created_by: string;
      created_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] consultation_created → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh timeline and status
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME CONSULTATION MANAGEMENT: Lắng nghe sự kiện consultation_deleted
    const handleConsultationDeleted = (data: {
      lead_id: number;
      consultation_id: number;
      new_lead_status_id: string | null;
      deleted_by: string;
      deleted_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] consultation_deleted → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh timeline and status
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME CONSULTATION MANAGEMENT: Lắng nghe sự kiện consultation_updated
    const handleConsultationUpdated = (data: {
      lead_id: number;
      consultation_id: number;
      consultation_status_id: string;
      updated_by: string;
      updated_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] consultation_updated → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh timeline and status
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME LEAD MANAGEMENT: Lắng nghe sự kiện lead_updated
    const handleLeadUpdated = (data: {
      lead_id: number;
      updated_fields: string[];
      status_changed: boolean;
      updated_by: string;
      updated_at: string;
      message: string;
    }) => {
      console.log("[SocketHandler] Received lead_updated event:", data);

      // Invalidate lead-related queries to refresh all views
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(data.lead_id) });

      // If status changed, also invalidate pipeline queries
      if (data.status_changed) {
        queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      }

      // ✅ FIX: Only show toast for human updates, not system updates
      // System updates (like Celery updating next_activity_at) should be silent
      // if (data.updated_by !== "system") {
      //   const fieldsText = data.updated_fields.slice(0, 3).join(", ");
      //   const moreFields =
      //     data.updated_fields.length > 3 ? ` +${data.updated_fields.length - 3} more` : "";
      //   toast.info("📝 Lead updated", {
      //     description: `${fieldsText}${moreFields} by ${data.updated_by}`,
      //     duration: 4000,
      //   });
      // }
      // ✅ REFACTOR: Removed frontend-generated toast. 
      // We now rely on the 'notification' event from backend (handleNewNotification)
      // which allows for template customization and unified logic.
    };

    // ✅ REAL-TIME LEAD DELETION: Lắng nghe sự kiện lead_deleted
    const handleLeadDeleted = (data: {
      lead_id: number;
      lead_name: string;
      unit_id: number;
      officer_id: number;
      actor_id: number;
    }) => {
      console.log("[SocketHandler] lead_deleted → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh all views
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.removeQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.removeQueries({ queryKey: leadsKeys.timeline(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };
    const handleLeadCreated = (data: {
      lead_id: number;
      lead_name: string;
      lead_phone: string;
      lead_email: string;
      offering_name: string;
      unit_id: number;
      unit_name: string;
      created_by: string;
      created_at: string;
      assignment_status: string;
      message: string;
    }) => {
      console.log("[SocketHandler] lead_created → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh dashboard
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME ASSIGNMENT FAILURE: Lắng nghe sự kiện lead_assignment_failed
    const handleLeadAssignmentFailed = (data: {
      lead_id: number;
      unit_id: number;
      reason: string;
      reason_display: string;
      lead_name: string;
      failed_at: string;
      assignment_status: string;
      message: string;
    }) => {
      console.log("[SocketHandler] lead_assignment_failed → invalidating queries (silent sync)");

      // Invalidate lead-related queries to refresh dashboard
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME OFFICER STATUS: Lắng nghe sự kiện officer_availability_changed
    const handleOfficerAvailabilityChanged = (data: {
      officer_id: number;
      new_status: string;
      old_status?: string;
      username: string;
      unit_id?: number;
    }) => {
      console.log(
        "[SocketHandler] officer_availability_changed → invalidating queries (silent sync)"
      );

      // Invalidate officer-related queries for admin dashboard
      queryClient.invalidateQueries({ queryKey: ["admin", "officers"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      queryClient.invalidateQueries({ queryKey: ["officer", "stats"] });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME LEAD STATUS: Lắng nghe sự kiện lead_status_changed
    const handleLeadStatusChanged = (data: {
      lead_id: number;
      officer_id?: number;
      old_status: string;
      new_status: string;
    }) => {
      console.log("[SocketHandler] Received lead_status_changed event:", data);

      // Invalidate lead-related queries
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });

      // Show toast notification
      toast.info("📊 Lead Status Changed", {
        description: `Lead #${data.lead_id}: ${data.old_status || "N/A"} → ${data.new_status || "N/A"}`,
        duration: 4000,
      });
    };

    // ✅ REAL-TIME USER ROLE: Lắng nghe sự kiện user_role_changed
    const handleUserRoleChanged = (data: {
      user_id: number;
      old_role: string;
      new_role: string;
    }) => {
      console.log("[SocketHandler] Received user_role_changed event:", data);

      // Important: User's role changed, should refresh permissions
      queryClient.invalidateQueries({ queryKey: ["me"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });

      // Show prominent toast
      toast.warning("🔔 Your role has been changed", {
        description: `${data.old_role} → ${data.new_role}. Please refresh the page.`,
        duration: 10000,
        action: {
          label: "Refresh",
          onClick: () => window.location.reload(),
        },
      });
    };

    // ✅ REAL-TIME SYSTEM ALERTS: Lắng nghe sự kiện system_alert
    const handleSystemAlert = (data: {
      severity: "info" | "warning" | "error";
      message: string;
      action_url?: string;
    }) => {
      console.log("[SocketHandler] Received system_alert event:", data);

      // Show toast based on severity
      const toastFn =
        data.severity === "error"
          ? toast.error
          : data.severity === "warning"
            ? toast.warning
            : toast.info;

      toastFn(`🚨 System Alert`, {
        description: data.message,
        duration: 10000,
        action: data.action_url
          ? {
              label: "View",
              onClick: () => (window.location.href = data.action_url!),
            }
          : undefined,
      });

      // Play sound for important alerts
      if (preferences?.sound_enabled && data.severity !== "info") {
        playNotificationSound();
      }
    };

    // ✅ REAL-TIME SYSTEM ANNOUNCEMENTS: Lắng nghe sự kiện system_announcement
    const handleSystemAnnouncement = (data: {
      title: string;
      message: string;
      priority?: string;
    }) => {
      console.log("[SocketHandler] Received system_announcement event:", data);

      // Show prominent toast for announcements
      toast.info(`📢 ${data.title}`, {
        description: data.message,
        duration: 15000, // Long duration for announcements
      });

      // Show browser notification
      if (preferences?.browser_enabled) {
        showBrowserNotification(data.title, {
          body: data.message,
          icon: "/favicon.ico",
          tag: `system-announcement-${Date.now()}`,
        });
      }
    };

    // ✅ REAL-TIME LEAD REASSIGNMENT: Lắng nghe sự kiện lead_reassigned
    const handleLeadReassigned = (data: {
      lead_id: number;
      old_officer_id: number | null;
      new_officer_id: number | null;
      old_unit_id: number;
      new_unit_id: number;
      actor_id: number;
      reason: string;
    }) => {
      console.log("[SocketHandler] lead_reassigned → invalidating queries (silent sync)");

      // Invalidate lead-related queries for both old and new assignments
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      // ✅ NO TOAST - Per-user notification will show toast via "notification" event
    };

    // ✅ REAL-TIME CONSULTATION REMINDER: Lắng nghe sự kiện consultation_reminder
    const handleConsultationReminder = (data: {
      consultation_id: number;
      lead_id: number;
      lead_name: string;
      lead_phone: string;
      officer_id: number;
      scheduled_at: string;
      minutes_until: number;
    }) => {
      // ✅ FIX: Only show toast if current user is the target officer
      // Domain events broadcast to all clients, but reminders are per-user
      if (data.officer_id !== user?.id) {
        console.log(
          `[SocketHandler] consultation_reminder → skipping (for officer ${data.officer_id}, not current user ${user?.id})`
        );
        return;
      }

      console.log("[SocketHandler] consultation_reminder → showing reminder toast");

      // Reminders are special - they DO show toast directly (not through notification channel)
      // because they are time-critical alerts
      toast.warning(`⏰ Nhắc nhở: Lịch hẹn tư vấn`, {
        description: `Bạn có lịch hẹn gọi ${data.lead_name} (${data.lead_phone}) trong ${data.minutes_until} phút nữa.`,
        duration: 15000, // Long duration for reminders
        action: {
          label: "Xem Lead",
          onClick: () => (window.location.href = `/leads/${data.lead_id}`),
        },
      });

      // Play sound for reminders
      if (preferences?.sound_enabled) {
        playNotificationSound();
      }
    };

    // ✅ REAL-TIME APPLICATION DELETION: Lắng nghe sự kiện application_deleted
    const handleApplicationDeleted = (data: {
      application_id: number;
      lead_id: number;
      officer_id: number;
      lead_name: string;
      actor_id: number;
    }) => {
      console.log("[SocketHandler] application_deleted → invalidating queries (silent sync)");

      // Invalidate application and lead queries
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.removeQueries({ queryKey: ["application", data.application_id] });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      // ✅ NO TOAST - Per-user notification will show toast via "notification" event
    };

    // ✅ REAL-TIME USER DEACTIVATION: Lắng nghe sự kiện user_deactivated
    const handleUserDeactivated = (data: {
      user_id: number;
      username: string;
      old_status: string;
      reason: string;
      actor_id: number;
    }) => {
      console.log("[SocketHandler] user_deactivated → showing critical alert and logging out");

      // This is a critical event - user will be logged out
      toast.error("⚠️ Tài khoản đã bị vô hiệu hóa", {
        description: `Lý do: ${data.reason}. Bạn sẽ được đăng xuất tự động.`,
        duration: 10000,
      });

      // Auto logout after showing message
      setTimeout(() => {
        logoutRef.current();
      }, 3000);
    };

    // R1+R2 FIX: Handle pending login notifications from Redis queue
    // These are emitted on socket connect if there was a suspicious login
    const handleLoginNotification = (data: {
      type: string;
      login_id: number;
      login_at: string;
      ip_address: string;
      city?: string;
      country?: string;
      device_type: string;
      browser: string;
      os: string;
      risk_score: number;
      is_new_ip: boolean;
      is_new_device: boolean;
      is_new_location: boolean;
    }) => {
      console.log("[SocketHandler] Received login_notification (R1+R2):", data);

      // Build location string
      const location = [data.city, data.country].filter(Boolean).join(", ") || "Unknown";

      // Show warning toast with details
      toast.warning("⚠️ Phát hiện đăng nhập đáng ngờ", {
        description: `IP: ${data.ip_address} - ${location}\n${data.browser} / ${data.os}`,
        duration: 15000,
        action: {
          label: "Xem lịch sử",
          onClick: () => (window.location.href = "/settings/login-history"),
        },
      });

      // Play sound if enabled
      if (preferences?.sound_enabled) {
        playNotificationSound();
      }

      // Show browser notification
      if (preferences?.browser_enabled) {
        showBrowserNotification("⚠️ Đăng nhập đáng ngờ", {
          body: `Có đăng nhập từ ${location} (${data.ip_address})`,
          icon: "/favicon.ico",
          tag: `login-notification-${data.login_id}`,
        });
      }
    };

    // Đăng ký listeners
    socket.on("force_logout_batch", handleForceLogoutBatch);
    socket.on("force_logout_all", handleForceLogoutAll);
    socket.on("notification", handleNewNotification);
    socket.on("data_updated", handleDataUpdated);
    socket.on("lead_assigned", handleLeadAssigned);
    socket.on("lead_created", handleLeadCreated);
    socket.on("lead_assignment_failed", handleLeadAssignmentFailed);
    socket.on("lead_status_changed", handleLeadStatusChanged);
    socket.on("application_created", handleApplicationCreated);
    socket.on("application_status_changed", handleApplicationStatusChanged);
    socket.on("application_documents_updated", handleApplicationDocumentsUpdated);
    socket.on("pipeline_config_updated", handlePipelineConfigUpdated);
    socket.on("consultation_created", handleConsultationCreated);
    socket.on("consultation_deleted", handleConsultationDeleted);
    socket.on("consultation_updated", handleConsultationUpdated);
    socket.on("lead_updated", handleLeadUpdated);
    socket.on("lead_deleted", handleLeadDeleted);
    socket.on("officer_availability_changed", handleOfficerAvailabilityChanged);
    socket.on("user_role_changed", handleUserRoleChanged);
    socket.on("system_alert", handleSystemAlert);
    socket.on("system_announcement", handleSystemAnnouncement);
    socket.on("lead_reassigned", handleLeadReassigned);
    socket.on("consultation_reminder", handleConsultationReminder);
    socket.on("application_deleted", handleApplicationDeleted);
    socket.on("user_deactivated", handleUserDeactivated);
    socket.on("login_notification", handleLoginNotification);  // R1+R2 FIX

    // ✅ DEBUG: Log all incoming Socket.IO events to diagnose real-time sync issues
    const handleAnyEvent = (event: string, ...args: unknown[]) => {
      console.log(`[SocketHandler] 🔔 Event received: ${event}`, args);
    };
    socket.onAny(handleAnyEvent);

    // R1+R2 Client-Pull: Request pending login notifications AFTER all listeners registered
    // This ensures we don't miss any events due to race conditions
    console.log("[SocketHandler] 📤 Requesting pending login notifications (Client-Pull)");
    socket.emit("get_pending_login_notifications");

    // Cleanup listeners khi effect này chạy lại hoặc component unmount
    return () => {
      socket.off("force_logout_batch", handleForceLogoutBatch);
      socket.off("force_logout_all", handleForceLogoutAll);
      socket.off("notification", handleNewNotification);
      socket.off("data_updated", handleDataUpdated);
      socket.off("lead_assigned", handleLeadAssigned);
      socket.off("lead_created", handleLeadCreated);
      socket.off("lead_assignment_failed", handleLeadAssignmentFailed);
      socket.off("lead_status_changed", handleLeadStatusChanged);
      socket.off("application_created", handleApplicationCreated);
      socket.off("application_status_changed", handleApplicationStatusChanged);
      socket.off("application_documents_updated", handleApplicationDocumentsUpdated);
      socket.off("pipeline_config_updated", handlePipelineConfigUpdated);
      socket.off("consultation_created", handleConsultationCreated);
      socket.off("consultation_deleted", handleConsultationDeleted);
      socket.off("consultation_updated", handleConsultationUpdated);
      socket.off("lead_updated", handleLeadUpdated);
      socket.off("lead_deleted", handleLeadDeleted);
      socket.off("officer_availability_changed", handleOfficerAvailabilityChanged);
      socket.off("user_role_changed", handleUserRoleChanged);
      socket.off("system_alert", handleSystemAlert);
      socket.off("system_announcement", handleSystemAnnouncement);
      socket.off("lead_reassigned", handleLeadReassigned);
      socket.off("consultation_reminder", handleConsultationReminder);
      socket.off("application_deleted", handleApplicationDeleted);
      socket.off("user_deactivated", handleUserDeactivated);
      socket.off("login_notification", handleLoginNotification);  // R1+R2 FIX
      socket.offAny(handleAnyEvent);
    };
    // ✅ FIX: Added isSocketConnected to dependencies to trigger listener setup when socket connects
  }, [isAuthenticated, isSocketConnected, addNotification, preferences, queryClient]);

  return null; // Không render gì cả
}
