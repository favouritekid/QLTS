// components/layouts/SocketHandler.tsx
"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useAuthStore } from "@/lib/stores/auth.store";
import { socketService } from "@/lib/socket/client";
import { toast } from "sonner";
import { useAddNotification, useMarkAsRead } from "@/hooks/useNotifications";
import { useNotificationPreferences } from "@/hooks/useNotificationPreferences";
import { playNotificationSound, showBrowserNotification } from "@/lib/sound";
import type { Notification } from "@/types/api.types";
import { useQueryClient } from "@tanstack/react-query";
import { leadsKeys } from "@/hooks/useLeads";
import { admissionsKeys } from "@/hooks/admissions/useAdmissions";
import { feesKeys } from "@/hooks/finance/useFees";
import { financeDashboardKeys } from "@/hooks/finance/useFinanceDashboard";
import { pipelineKeys } from "@/hooks/usePipeline";
import { isSafeUrl } from "@/lib/utils";
import { bumpSuspiciousLoginBanner } from "@/components/layouts/SecurityBanner";
import type { SuspiciousLoginSocketPayload } from "@/types/api.types";

// =============================================================================
// DEBOUNCED INVALIDATION HELPER
// =============================================================================
// ✅ PERFORMANCE FIX: Debounce cache invalidations to prevent browser freeze
// When multiple socket events fire rapidly, we batch the invalidations
// and only execute once after a delay, preventing excessive refetches.

interface PendingInvalidations {
  leadsLists: boolean;
  leadDetails: Set<number>;
  leadTimelines: Set<number>;
  pipeline: boolean;
  dashboard: boolean;
  // ADM-032 — single flag is enough; ``admissionsKeys.all`` cascades.
  admissionAll: boolean;
  // P2 (2026-05-22) — scope hẹp cho event KHÔNG đổi status/row contents
  // (doc mutations, minor corrections). Tránh refetch storm list +
  // status-counts + stats khi data_updated chỉ touch field hồ sơ.
  admissionDetails: Set<number>;
}

// F1 (review pass-2 2026-05-22) — export để test dùng fake timers
// (`vi.advanceTimersByTime(INVALIDATION_DEBOUNCE_MS + 1)`) thay vì
// hard-code magic number 400ms (flaky nếu bump debounce).
export const INVALIDATION_DEBOUNCE_MS = 300; // 300ms debounce

/**
 * Component "vô hình" (không render)
 * Quản lý kết nối Socket.IO và lắng nghe các sự kiện auth toàn cục.
 */
export function SocketHandler() {
  // ✅ PERF FIX: Granular selectors to avoid re-registering 30+ socket listeners on unrelated store changes
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const logout = useAuthStore(s => s.logout);
  const user = useAuthStore(s => s.user);
  const addNotification = useAddNotification();
  const markAsRead = useMarkAsRead();  // ✅ For marking as read when user clicks toast action
  const { data: preferences } = useNotificationPreferences();
  const queryClient = useQueryClient();

  // ==========================================================================
  // DEBOUNCED INVALIDATION SYSTEM
  // ==========================================================================
  // ✅ PERFORMANCE FIX: Batch rapid socket events into single invalidation

  const pendingInvalidationsRef = useRef<PendingInvalidations>({
    leadsLists: false,
    leadDetails: new Set(),
    leadTimelines: new Set(),
    pipeline: false,
    dashboard: false,
    // ADM-032 — cross-tab realtime for admission doc mutations. Single
    // boolean is enough because ``admissionsKeys.all`` cascades to
    // every detail/list/status-counts/stats query under the
    // ``["admissions"]`` root.
    admissionAll: false,
    // P2 (2026-05-22) — detail-only invalidation scope.
    admissionDetails: new Set(),
  });
  const invalidationTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const flushInvalidations = useCallback(() => {
    const pending = pendingInvalidationsRef.current;

    // Only log if there's something to flush
    const hasWork = pending.leadsLists ||
                    pending.leadDetails.size > 0 ||
                    pending.leadTimelines.size > 0 ||
                    pending.pipeline ||
                    pending.dashboard ||
                    pending.admissionAll ||
                    pending.admissionDetails.size > 0;

    if (!hasWork) return;

    console.log("[SocketHandler] Flushing batched invalidations:", {
      leadsLists: pending.leadsLists,
      leadDetailsCount: pending.leadDetails.size,
      leadTimelinesCount: pending.leadTimelines.size,
      pipeline: pending.pipeline,
      dashboard: pending.dashboard,
      admissionAll: pending.admissionAll,
      admissionDetailsCount: pending.admissionDetails.size,
    });

    // Invalidate leads list (only once, not per-lead)
    if (pending.leadsLists) {
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
    }

    // Invalidate specific lead details
    for (const leadId of pending.leadDetails) {
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(leadId) });
    }

    // Invalidate specific lead timelines
    for (const leadId of pending.leadTimelines) {
      queryClient.invalidateQueries({ queryKey: leadsKeys.timeline(leadId) });
    }

    // Invalidate pipeline
    if (pending.pipeline) {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    }

    // Invalidate dashboard
    if (pending.dashboard) {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    }

    // ADM-032 — admission profile cascade. ``admissionsKeys.all``
    // (root ``["admissions"]``) invalidates every detail/list/
    // status-counts/stats query rooted under it. One call covers
    // every status-flipping broadcast (create/delete/status_changed/
    // fee_calculated).
    if (pending.admissionAll) {
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all });
    } else if (pending.admissionDetails.size > 0) {
      // P2 (2026-05-22) — narrow scope cho event KHÔNG đổi status:
      // doc mutations + minor corrections. List/counts/stats không cần
      // refetch nên skip nếu chưa có admissionAll=true. Nếu cả 2 set
      // (admissionAll=true) thì cascade root đã cover detail rồi.
      for (const profileId of pending.admissionDetails) {
        queryClient.invalidateQueries({
          queryKey: admissionsKeys.detail(profileId),
        });
      }
    }

    // Reset pending state
    pendingInvalidationsRef.current = {
      leadsLists: false,
      leadDetails: new Set(),
      leadTimelines: new Set(),
      pipeline: false,
      dashboard: false,
      admissionAll: false,
      admissionDetails: new Set(),
    };
  }, [queryClient]);

  const scheduleInvalidation = useCallback((updates: {
    leadsLists?: boolean;
    leadDetail?: number;
    leadTimeline?: number;
    pipeline?: boolean;
    dashboard?: boolean;
    // ADM-032 — broad cascade (status-flipping events)
    admissionAll?: boolean;
    // P2 (2026-05-22) — detail-only scope (doc/minor-correction events)
    admissionDetail?: number;
  }) => {
    // Accumulate the requested invalidations
    if (updates.leadsLists) {
      pendingInvalidationsRef.current.leadsLists = true;
    }
    if (updates.leadDetail !== undefined) {
      pendingInvalidationsRef.current.leadDetails.add(updates.leadDetail);
    }
    if (updates.leadTimeline !== undefined) {
      pendingInvalidationsRef.current.leadTimelines.add(updates.leadTimeline);
    }
    if (updates.pipeline) {
      pendingInvalidationsRef.current.pipeline = true;
    }
    if (updates.dashboard) {
      pendingInvalidationsRef.current.dashboard = true;
    }
    if (updates.admissionAll) {
      pendingInvalidationsRef.current.admissionAll = true;
    }
    if (updates.admissionDetail !== undefined) {
      pendingInvalidationsRef.current.admissionDetails.add(updates.admissionDetail);
    }

    // Clear existing timeout and schedule new one
    if (invalidationTimeoutRef.current) {
      clearTimeout(invalidationTimeoutRef.current);
    }
    invalidationTimeoutRef.current = setTimeout(flushInvalidations, INVALIDATION_DEBOUNCE_MS);
  }, [flushInvalidations]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (invalidationTimeoutRef.current) {
        clearTimeout(invalidationTimeoutRef.current);
      }
    };
  }, []);

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

    // P2/P3 (2026-05-22) — opt-in payload logging. PII (name/phone/email),
    // status, officer_id... có thể appear trong payload nên KHÔNG log
    // unconditional ở production. Gate behind explicit env flag. Default:
    // log event name only, không dump payload.
    const debugSocketPayload =
      process.env.NEXT_PUBLIC_DEBUG_SOCKET === "1" ||
      process.env.NEXT_PUBLIC_DEBUG_SOCKET === "true";

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
      if (debugSocketPayload) {
        console.log("[SocketHandler] Received new notification:", notification);
      } else {
        console.log(
          `[SocketHandler] Received new notification (id=${notification.id}, type=${notification.type})`,
        );
      }

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
      // ✅ UX FIX: Add action button + markAsRead for ALL notification types
      const toastFn = notification.type === "reminder" || notification.type === "warning" 
        ? toast.warning 
        : notification.type === "error" 
          ? toast.error
          : toast.info;
      
      const duration = notification.type === "reminder" ? 15000 
        : notification.type === "warning" || notification.type === "error" ? 10000 
        : 8000;

      toastFn(notification.title, {
        description: notification.message,
        duration,
        id: `notification-${notification.id}`,  // Prevent duplicates
        action: notification.link
          ? {
              label: "Xem chi tiết",
              onClick: () => {
                // ✅ Mark as read BEFORE navigating (updates bell icon)
                markAsRead.mutate({ notification_ids: [notification.id] });
                if (notification.link && isSafeUrl(notification.link)) {
                  window.location.href = notification.link;
                }
              },
            }
          : undefined,
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
      if (debugSocketPayload) {
        console.log("[SocketHandler] Received data_updated event:", data);
      } else {
        console.log(
          `[SocketHandler] Received data_updated event (resource=${data.resource_type}, op=${data.operation}, id=${data.resource_id})`,
        );
      }

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
          // Forward-compatible branch: the backend does NOT currently emit
          // `data_updated` for leads (it uses the dedicated `lead_*` events
          // handled below). Kept so that if a future backend path ever falls
          // back to the generic channel, lead lists still refresh.
          // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
          scheduleInvalidation({ leadsLists: true });
          break;

        case "admission_profile":
          // ADM-032 — cross-tab realtime for doc mutations (upload /
          // paper / verify / reject / reset). Silent invalidate via
          // the shared 300ms debounce; no toast (officer phụ trách
          // nhiều hồ sơ sẽ thấy spam nếu enable).
          //
          // P2 (2026-05-22) — doc mutations KHÔNG đổi profile.status hay
          // row content trong list (docs ratio không hiển thị columns),
          // chỉ refetch detail. Tránh refetch storm list/counts/stats.
          // Status-flipping events đã có channel riêng (application_*).
          if (data.operation === "update" && typeof data.resource_id === "number") {
            scheduleInvalidation({ admissionDetail: data.resource_id });
          } else {
            // create/delete operations affect list rows
            scheduleInvalidation({ admissionAll: true });
          }
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
      console.log("[SocketHandler] lead_assigned → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
      });
      // Also invalidate insights immediately (not in debounce as it's not heavy)
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

      // Cascade to list + status-counts + stats + details via `admissionsKeys.all` root —
      // mirrors the mutation-hook invalidation pattern in useAdmissions.
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all });
      queryClient.invalidateQueries({ queryKey: leadsKeys.detail(data.lead_id) });
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

      // Cascade to list + status-counts + stats via `admissionsKeys.all` root;
      // detail gets a targeted refresh too so the open page updates instantly.
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all });
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(data.application_id) });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // PR #8 — realtime sync after POST /api/fees/calculate.
    // Broadcast-only event; no toast. Invalidates admission detail + list,
    // the finance caches that drive the Tuition tab, the finance dashboard
    // overview, and — only when backend says the lead pipeline actually
    // advanced — the lead pipeline caches. The conditional lead invalidation
    // avoids a pipeline refetch storm every time an officer calculates a
    // non-HK1 or non-tuition fee that doesn't move the lead stage.
    const handleFeeCalculated = (data: {
      admission_profile_id: number;
      lead_id: number;
      fee_id: number;
      fee_status: string;
      lead_stage_changed: boolean;
    }) => {
      console.log("[SocketHandler] fee_calculated → invalidating finance + admission caches");
      // Invalidate the entire admissionsKeys tree so detail + list +
      // status-counts + stats all refetch — calculating a fee can flip
      // the row's payment-status tab (no_fee → unpaid/paid), and
      // /admissions reads useAdmissionStatusCounts off the same root
      // key. Mirrors the cascade pattern already used by the
      // application_* handlers above.
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all });
      queryClient.invalidateQueries({ queryKey: feesKeys.lists() });
      queryClient.invalidateQueries({ queryKey: feesKeys.byProfile(data.admission_profile_id) });
      queryClient.invalidateQueries({ queryKey: feesKeys.profileSummary(data.admission_profile_id) });
      queryClient.invalidateQueries({ queryKey: financeDashboardKeys.all });
      if (data.lead_stage_changed) {
        queryClient.invalidateQueries({ queryKey: leadsKeys.lists() });
        queryClient.invalidateQueries({ queryKey: pipelineKeys.fullPipeline() });
      }
    };

    // Realtime sync after a post-approval minor correction. Payload
    // carries field NAMES only (no PII) — broadcast emit is scoped to
    // admin + unit + assigned officer rooms server-side, so just
    // refetch the admission tree on receipt. No lead/finance impact:
    // SAFE catalog excludes any field that lead_admission_sync would
    // project, so we don't need to touch lead/pipeline keys.
    const handleApplicationMinorCorrected = (data: {
      application_id: number;
      lead_id: number;
      changed_fields: string[];
      actor_id: number;
      corrected_at: string;
    }) => {
      console.log(
        "[SocketHandler] application_minor_corrected → invalidating admission caches",
        { profile: data.application_id, fields: data.changed_fields },
      );
      // P2 (2026-05-22) — minor correction post-approval chỉ touch field
      // hồ sơ, KHÔNG đổi status/badge trong list. Detail-only scope đủ.
      queryClient.invalidateQueries({
        queryKey: admissionsKeys.detail(data.application_id),
      });
    };

    // P2 (2026-05-22) — ADMISSION_* domain event consumer cho realtime
    // cross-tab/cross-user sync. BE notification_dispatcher.py:299 emit
    // mỗi event với `event.value` (snake_case) qua Socket.IO sau khi
    // outbox commit. Trước đây FE chỉ lắng nghe application_status_changed
    // (legacy event); ADMISSION_RESULT_PUBLISHED + 4 decision/waitlist
    // events là canonical Phase 3 PR-3B/3C events nhưng KHÔNG có consumer
    // → manager publish ở browser A thì browser B không refresh list/
    // counts/stats. Mọi event nhóm này đều flip profile.status → cascade
    // root key `admissionsKeys.all`. Payload chuẩn từ event_catalog.py
    // chứa application_id + lead_id (optional vài event).
    //
    // Events covered:
    //   - admission_result_published (T6 admin batch publish)
    //   - admission_decision_admitted (T7 per-profile admit)
    //   - admission_decision_waitlisted (T8 per-profile waitlist)
    //   - admission_decision_rejected (T9 per-profile reject)
    //   - admission_waitlist_promoted (T10 admin promote waitlist)
    //   - admission_waitlist_rejected (T11 admin reject waitlist)
    const handleAdmissionStatusFlipEvent = (data: {
      application_id?: number;
      lead_id?: number;
      [key: string]: unknown;
    }) => {
      console.log(
        "[SocketHandler] admission status-flip event → scheduling invalidation",
        { profile: data.application_id, lead: data.lead_id },
      );
      // P2-4 (review B-scope 2026-05-22) — DEBOUNCE thay vì sync invalidate.
      // T6 publish_result emit batch (~50 profile decision events liên tục)
      // → 50× sync `invalidateQueries(admissionsKeys.all)` cùng 1 frame =
      // React Query queue thrash. Match pattern PRIORITY_* listeners +
      // data_updated cùng dùng `scheduleInvalidation` (300ms debounce).
      scheduleInvalidation({ admissionAll: true });
      // Targeted detail refresh nếu có profile ID (cùng debounce queue).
      if (typeof data.application_id === "number") {
        scheduleInvalidation({ admissionDetail: data.application_id });
      }
      // Lead row projection từ admission decision (lead_admission_sync).
      if (typeof data.lead_id === "number") {
        scheduleInvalidation({ leadDetail: data.lead_id });
      }
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
      console.log("[SocketHandler] consultation_created → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        leadTimeline: data.lead_id,
        pipeline: true,
      });
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
      console.log("[SocketHandler] consultation_deleted → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        leadTimeline: data.lead_id,
        pipeline: true,
      });
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
      console.log("[SocketHandler] consultation_updated → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        leadTimeline: data.lead_id,
        pipeline: true,
      });
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
      console.log("[SocketHandler] lead_updated → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        leadTimeline: data.lead_id,
        pipeline: data.status_changed ? true : undefined,
      });
      // ✅ NO TOAST - Per-user notification will show toast via "new_notification" event
    };

    // ✅ REAL-TIME LEAD DELETION: Lắng nghe sự kiện lead_deleted
    const handleLeadDeleted = (data: {
      lead_id: number;
      lead_name: string;
      unit_id: number;
      officer_id: number;
      actor_id: number;
    }) => {
      console.log("[SocketHandler] lead_deleted → scheduling batched invalidation");

      // Remove specific lead queries immediately (no debounce needed for removal)
      queryClient.removeQueries({ queryKey: leadsKeys.detail(data.lead_id) });
      queryClient.removeQueries({ queryKey: leadsKeys.timeline(data.lead_id) });

      // ✅ PERFORMANCE FIX: Use debounced invalidation for list queries
      scheduleInvalidation({
        leadsLists: true,
        pipeline: true,
        dashboard: true,
      });
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
      console.log("[SocketHandler] lead_created → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        dashboard: true,
        // A newly created lead enters the pipeline at its initial stage, so the
        // Pipeline Board must refresh too — matches `lead_updated`/`lead_deleted`
        // which already invalidate pipeline. Without this, a lead created in
        // another tab/session never appears on an open Pipeline Board.
        pipeline: true,
      });
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
      console.log("[SocketHandler] lead_assignment_failed → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
      });
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
      console.log("[SocketHandler] lead_status_changed → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        pipeline: true,
      });
      // ✅ NO TOAST - This event is often triggered along with other events
      // Per-user notification will show toast via "new_notification" event if needed
    };

    // ✅ REAL-TIME USER ROLE: Lắng nghe sự kiện user_role_changed
    const handleUserRoleChanged = (data: {
      user_id: number;
      old_role: string;
      new_role: string;
    }) => {
      console.log("[SocketHandler] Received user_role_changed event:", data);

      // Important: User's role changed, should refresh permissions
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });

      // Show prominent toast
      toast.warning("Vai trò của bạn đã được thay đổi", {
        description: `${data.old_role} → ${data.new_role}. Vui lòng tải lại trang.`,
        duration: 10000,
        action: {
          label: "Tải lại",
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
        action: data.action_url && isSafeUrl(data.action_url)
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
      console.log("[SocketHandler] lead_reassigned → scheduling batched invalidation");

      // ✅ PERFORMANCE FIX: Use debounced invalidation instead of immediate
      scheduleInvalidation({
        leadsLists: true,
        leadDetail: data.lead_id,
        dashboard: true,
      });
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

      // Cascade to list + status-counts + stats via `admissionsKeys.all` root;
      // removeQueries on the detail drops the stale cached page so a later
      // visit refetches from scratch (GC the deleted profile).
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all });
      queryClient.removeQueries({ queryKey: admissionsKeys.detail(data.application_id) });
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

    // ✅ REAL-TIME SESSION LIST UPDATE: Lắng nghe sự kiện session_updated
    const handleSessionUpdated = (data: {
      user_id: number;
      timestamp: string;
    }) => {
      console.log("[SocketHandler] session_updated → invalidating sessions (silent sync)");
      if (data.user_id === user?.id) {
        queryClient.invalidateQueries({ queryKey: ["sessions", "list"] });
      }
    };

    // ✅ CTV EVENTS: Handlers for collaborator system real-time sync
    const handleCtvClaimSubmitted = (data: {
      collaborator_id: number;
      claim_id: number;
      lead_id: number;
      unit_id: number;
    }) => {
      console.log("[SocketHandler] ctv_claim_submitted → invalidating claims");
      queryClient.invalidateQueries({ queryKey: ["claims"] });
      queryClient.invalidateQueries({ queryKey: ["collaborator-stats"] });
    };

    const handleCtvClaimApproved = (data: {
      collaborator_id: number;
      claim_id: number;
      lead_id: number;
    }) => {
      console.log("[SocketHandler] ctv_claim_approved → invalidating claims & leads");
      queryClient.invalidateQueries({ queryKey: ["claims"] });
      queryClient.invalidateQueries({ queryKey: ["ctv-leads"] });
      queryClient.invalidateQueries({ queryKey: ["collaborator-stats"] });
    };

    const handleCtvClaimRejected = (data: {
      collaborator_id: number;
      claim_id: number;
      lead_id: number;
    }) => {
      console.log("[SocketHandler] ctv_claim_rejected → invalidating claims");
      queryClient.invalidateQueries({ queryKey: ["claims"] });
      queryClient.invalidateQueries({ queryKey: ["collaborator-stats"] });
    };

    const handleCtvApproved = (data: { collaborator_id: number }) => {
      console.log("[SocketHandler] ctv_approved → invalidating collaborator profile");
      queryClient.invalidateQueries({ queryKey: ["collaborators"] });
      queryClient.invalidateQueries({ queryKey: ["ctv-profile"] });
    };

    const handleCtvSuspended = (data: { collaborator_id: number }) => {
      console.log("[SocketHandler] ctv_suspended → invalidating collaborator profile");
      queryClient.invalidateQueries({ queryKey: ["collaborators"] });
      queryClient.invalidateQueries({ queryKey: ["ctv-profile"] });
    };

    const handleCtvCommissionCreated = (data: {
      collaborator_id: number;
      commission_id: number;
      amount: string;
      lead_id: number;
    }) => {
      console.log("[SocketHandler] ctv_commission_created → invalidating commissions");
      queryClient.invalidateQueries({ queryKey: ["commissions"] });
      queryClient.invalidateQueries({ queryKey: ["commission-stats"] });
      queryClient.invalidateQueries({ queryKey: ["collaborator-stats"] });
    };

    const handleCtvLeadConverted = (data: {
      collaborator_id: number;
      lead_id: number;
      new_status: string;
    }) => {
      console.log("[SocketHandler] ctv_lead_converted → invalidating ctv leads");
      queryClient.invalidateQueries({ queryKey: ["ctv-leads"] });
      queryClient.invalidateQueries({ queryKey: ["collaborator-stats"] });
    };

    // R1+R2: handleLoginNotification REMOVED
    // Login notification is now included in login API response and handled by useAuth.ts
    // See: useAuth.ts onSuccess handler

    // Option-B Commit 8 — real-time SUSPICIOUS_LOGIN banner bump.
    // BE (Commit 7) emits ``suspicious_login`` ONLY to the actor's
    // ``user_room_<uid>`` and ONLY if they passed the security/browser
    // preference filter — so by the time this fires, the user is
    // already eligible. We:
    //   1. bump the banner count by 1 (incremental — payload is one event)
    //   2. debounce-invalidate the loginHistory query so /settings/security
    //      reconciles the authoritative count + row on next view
    // We deliberately DO NOT show a toast here: the same event also
    // arrives via the ``notification`` channel handler (which already
    // renders the toast after full preference filtering). Toasting here
    // too would double-fire and could bypass the notification-level
    // preference. Banner bump is the only FE-owned reaction.
    const handleSuspiciousLogin = (data: SuspiciousLoginSocketPayload) => {
      if (debugSocketPayload) {
        console.log("[SocketHandler] Received suspicious_login event:", data);
      } else {
        console.log(
          `[SocketHandler] suspicious_login (login_history_id=${data?.login_history_id})`,
        );
      }
      bumpSuspiciousLoginBanner();
      // No dedicated debounce bucket for login history — invalidate
      // directly; this event is rare (one per anomalous login) so a
      // single immediate invalidate won't cause a refetch storm.
      queryClient.invalidateQueries({ queryKey: ["loginHistory"] });
    };

    // Đăng ký listeners
    socket.on("force_logout_batch", handleForceLogoutBatch);
    socket.on("force_logout_all", handleForceLogoutAll);
    socket.on("notification", handleNewNotification);
    socket.on("suspicious_login", handleSuspiciousLogin);
    socket.on("data_updated", handleDataUpdated);
    socket.on("lead_assigned", handleLeadAssigned);
    socket.on("lead_created", handleLeadCreated);
    socket.on("lead_assignment_failed", handleLeadAssignmentFailed);
    socket.on("lead_status_changed", handleLeadStatusChanged);
    socket.on("application_created", handleApplicationCreated);
    socket.on("application_status_changed", handleApplicationStatusChanged);
    socket.on("application_minor_corrected", handleApplicationMinorCorrected);
    socket.on("fee_calculated", handleFeeCalculated);
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
    socket.on("session_updated", handleSessionUpdated);
    socket.on("ctv_claim_submitted", handleCtvClaimSubmitted);
    socket.on("ctv_claim_approved", handleCtvClaimApproved);
    socket.on("ctv_claim_rejected", handleCtvClaimRejected);
    socket.on("ctv_approved", handleCtvApproved);
    socket.on("ctv_suspended", handleCtvSuspended);
    socket.on("ctv_commission_created", handleCtvCommissionCreated);
    socket.on("ctv_lead_converted", handleCtvLeadConverted);

    // P2 (2026-05-22) — ADMISSION_* domain events (BE event_catalog.py)
    socket.on("admission_result_published", handleAdmissionStatusFlipEvent);
    socket.on("admission_decision_admitted", handleAdmissionStatusFlipEvent);
    socket.on("admission_decision_waitlisted", handleAdmissionStatusFlipEvent);
    socket.on("admission_decision_rejected", handleAdmissionStatusFlipEvent);
    socket.on("admission_waitlist_promoted", handleAdmissionStatusFlipEvent);
    socket.on("admission_waitlist_rejected", handleAdmissionStatusFlipEvent);

    // P2 (2026-05-22) — PRIORITY_* events. BE event_catalog.py:1091/1130/1160
    // dispatch khi officer/admin override KV / verify object UT / reject
    // object UT. Trước đây FE listener thiếu — operator B (cùng hồ sơ
    // qua tab khác) thấy PriorityTab/preview stale tới manual refetch.
    // Detail-only scope: priority field thay đổi KHÔNG flip profile.status
    // hay row content list (priority chỉ hiển thị trong detail view).
    const handlePriorityEvent = (data: {
      application_id?: number;
      [key: string]: unknown;
    }) => {
      if (debugSocketPayload) {
        console.log("[SocketHandler] priority event → invalidating detail", data);
      } else {
        console.log(
          `[SocketHandler] priority event (profile=${data.application_id})`,
        );
      }
      if (typeof data.application_id === "number") {
        scheduleInvalidation({ admissionDetail: data.application_id });
      }
    };
    socket.on("priority_kv_overridden", handlePriorityEvent);
    socket.on("priority_object_verified", handlePriorityEvent);
    socket.on("priority_object_rejected", handlePriorityEvent);

    // DEBUG: Log incoming Socket.IO events to diagnose real-time sync.
    // (`debugSocketPayload` declared earlier at top of effect.)
    const handleAnyEvent = (event: string, ...args: unknown[]) => {
      if (debugSocketPayload) {
        console.log(`[SocketHandler] 🔔 Event received: ${event}`, args);
      } else {
        console.log(
          `[SocketHandler] 🔔 Event received: ${event} (${args.length} arg${args.length === 1 ? "" : "s"})`,
        );
      }
    };
    socket.onAny(handleAnyEvent);

    // R1+R2: Client-Pull code removed - login notification is now included directly
    // in the login API response and handled by useAuth.ts

    // Cleanup listeners khi effect này chạy lại hoặc component unmount
    return () => {
      socket.off("force_logout_batch", handleForceLogoutBatch);
      socket.off("force_logout_all", handleForceLogoutAll);
      socket.off("notification", handleNewNotification);
      socket.off("suspicious_login", handleSuspiciousLogin);
      socket.off("data_updated", handleDataUpdated);
      socket.off("lead_assigned", handleLeadAssigned);
      socket.off("lead_created", handleLeadCreated);
      socket.off("lead_assignment_failed", handleLeadAssignmentFailed);
      socket.off("lead_status_changed", handleLeadStatusChanged);
      socket.off("application_created", handleApplicationCreated);
      socket.off("application_status_changed", handleApplicationStatusChanged);
      socket.off("application_minor_corrected", handleApplicationMinorCorrected);
      socket.off("fee_calculated", handleFeeCalculated);
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
      socket.off("session_updated", handleSessionUpdated);
      socket.off("ctv_claim_submitted", handleCtvClaimSubmitted);
      socket.off("ctv_claim_approved", handleCtvClaimApproved);
      socket.off("ctv_claim_rejected", handleCtvClaimRejected);
      socket.off("ctv_approved", handleCtvApproved);
      socket.off("ctv_suspended", handleCtvSuspended);
      socket.off("ctv_commission_created", handleCtvCommissionCreated);
      socket.off("ctv_lead_converted", handleCtvLeadConverted);

      // P2 (2026-05-22) — ADMISSION_* cleanup
      socket.off("admission_result_published", handleAdmissionStatusFlipEvent);
      socket.off("admission_decision_admitted", handleAdmissionStatusFlipEvent);
      socket.off("admission_decision_waitlisted", handleAdmissionStatusFlipEvent);
      socket.off("admission_decision_rejected", handleAdmissionStatusFlipEvent);
      socket.off("admission_waitlist_promoted", handleAdmissionStatusFlipEvent);
      socket.off("admission_waitlist_rejected", handleAdmissionStatusFlipEvent);

      // P2 (2026-05-22) — PRIORITY_* cleanup
      socket.off("priority_kv_overridden", handlePriorityEvent);
      socket.off("priority_object_verified", handlePriorityEvent);
      socket.off("priority_object_rejected", handlePriorityEvent);

      socket.offAny(handleAnyEvent);
    };
    // ✅ FIX: Added isSocketConnected to dependencies to trigger listener setup when socket connects
    // ✅ PERFORMANCE FIX: Added scheduleInvalidation for debounced cache updates
  }, [isAuthenticated, isSocketConnected, addNotification, markAsRead, preferences, queryClient, scheduleInvalidation, user]);

  return null; // Không render gì cả
}
