// lib/socket/client.ts
import { io, Socket } from "socket.io-client";
import { env } from "@/lib/config/env";
import { useAuthStore } from "../stores/auth.store";
import { toast } from "sonner";

class SocketService {
  private socket: Socket | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private revalidateInterval: NodeJS.Timeout | null = null; // ✅ FIX-3
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shutdownReconnectTimer: NodeJS.Timeout | null = null;
  private REVALIDATE_INTERVAL_MS = 5 * 60 * 1000; // ✅ FIX-3: 5 minutes

  // ✅ PRIORITY 3 (Deep Dive Audit): Reconnect callback for cache invalidation
  private onReconnectCallback: (() => void) | null = null;

  connect() {
    if (this.socket && this.socket.connected) {
      console.log("[SocketService] Already connected.");
      return;
    }

    // ✅ SECURITY FIX: No longer check token from store
    // Authentication now uses httpOnly cookies (sent automatically by browser)
    // Backend reads access_token from Cookie header

    console.log("[SocketService] Connecting to", env.NEXT_PUBLIC_API_URL);
    this.reconnectAttempts = 0;

    this.socket = io(env.NEXT_PUBLIC_API_URL, {
      path: "/socket.io",
      // ✅ SECURITY FIX: Removed auth dict - token comes from httpOnly cookie
      // OLD: auth: { token }, // ❌ Token sent in auth dict (XSS risk)
      withCredentials: true, // ✅ NEW: Browser sends httpOnly cookies automatically
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: this.maxReconnectAttempts,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    this.setupEventListeners();
  }

  private setupEventListeners() {
    if (!this.socket) return;

    this.socket.on("connect", () => {
      console.log("[SocketService] ✅ Connected:", this.socket?.id);
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      if (this.shutdownReconnectTimer) {
        clearTimeout(this.shutdownReconnectTimer);
        this.shutdownReconnectTimer = null;
      }
      this.startHeartbeat();
      this.startRevalidation(); // ✅ FIX-3: Start periodic auth revalidation

      // ✅ PRIORITY 3 FIX (Deep Dive Audit): Invalidate cache on reconnect
      // Solves: Stale data issue when socket disconnects and data changes on server
      if (this.onReconnectCallback) {
        console.log("[SocketService] 🔄 Triggering cache invalidation after reconnect...");
        this.onReconnectCallback();
      }
    });

    this.socket.on("disconnect", (reason) => {
      console.warn("[SocketService] ❌ Disconnected:", reason);
      this.stopHeartbeat();
      this.stopRevalidation(); // ✅ FIX-3: Stop revalidation on disconnect
      if (reason === "io server disconnect") {
        console.error("[SocketService] Server disconnected session. Forcing logout.");
        useAuthStore.getState().logout();
      }
    });

    this.socket.on("connect_error", (error) => {
      this.reconnectAttempts++;
      console.error(
        `[SocketService] Connection Error (Attempt ${this.reconnectAttempts}):`,
        error.message
      );
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error("[SocketService] Max reconnection attempts reached. Stopping.");
        this.disconnect();
      }
    });

    // Xử lý Shutdown
    this.socket.on("server_shutdown", (data: { message: string }) => {
      console.warn("[SocketService] Server is shutting down:", data.message);
      toast.info(data.message || "Server is restarting, please wait...", {
        duration: this.maxReconnectDelay,
      });

      // ✅ SỬA LỖI: Dùng `if` check thay vì `?.`
      if (this.socket) {
        this.socket.io.opts.reconnection = false;
      }
      this.disconnect();

      this.reconnectDelay = 1000;
      this.attemptReconnect();
    });
  }

  private attemptReconnect() {
    if (this.shutdownReconnectTimer) {
      clearTimeout(this.shutdownReconnectTimer);
    }

    this.shutdownReconnectTimer = setTimeout(() => {
      if (this.reconnectDelay > this.maxReconnectDelay) {
        console.error("[SocketService] Shutdown reconnect failed after max delay.");
        return;
      }

      console.log(`[SocketService] Attempting reconnect after ${this.reconnectDelay}ms (shutdown)`);

      // ✅ SỬA LỖI: Dùng `if` check thay vì `?.`
      if (this.socket) {
        this.socket.io.opts.reconnection = true;
      }
      this.connect();

      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      this.attemptReconnect();
    }, this.reconnectDelay);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.pingInterval = setInterval(() => {
      if (this.socket?.connected) {
        this.socket.emit("ping");
      }
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  // ✅ FIX-3: Periodic auth revalidation methods
  private startRevalidation() {
    this.stopRevalidation();

    this.revalidateInterval = setInterval(() => {
      if (this.socket?.connected) {
        console.log("[SocketService] 🔒 Revalidating auth...");

        this.socket.emit(
          "revalidate_auth",
          (response: { valid: boolean; reason?: string }) => {
            if (!response.valid) {
              console.error(
                "[SocketService] ❌ Revalidation failed:",
                response.reason
              );
              this.disconnect();

              // Force logout user
              const authStore = useAuthStore.getState();
              authStore.logout();

              toast.error("Your session is no longer valid. Please login again.", {
                duration: 5000,
              });

              if (typeof window !== "undefined") {
                window.location.href = "/login";
              }
            } else {
              console.log("[SocketService] ✅ Revalidation successful");
            }
          }
        );
      }
    }, this.REVALIDATE_INTERVAL_MS);
  }

  private stopRevalidation() {
    if (this.revalidateInterval) {
      clearInterval(this.revalidateInterval);
      this.revalidateInterval = null;
    }
  }

  disconnect() {
    this.stopHeartbeat();
    this.stopRevalidation(); // ✅ FIX-3: Stop revalidation on disconnect
    if (this.shutdownReconnectTimer) {
      clearTimeout(this.shutdownReconnectTimer);
      this.shutdownReconnectTimer = null;
    }
    if (this.socket) {
      console.log("[SocketService] Disconnecting...");
      this.socket.disconnect();
      this.socket = null;
    }
  }

  getSocket() {
    return this.socket;
  }

  /**
   * ✅ PRIORITY 3 (Deep Dive Audit): Register callback for cache invalidation
   *
   * This method allows React Query (or other cache systems) to register a callback
   * that will be invoked whenever the socket reconnects. This ensures fresh data
   * is fetched after connection loss.
   *
   * Problem Solved:
   * - When socket disconnects for extended period, server data may change
   * - With staleTime: Infinity, React Query never auto-refetches
   * - User sees stale data until manual refresh (F5)
   *
   * Solution:
   * - On reconnect, trigger invalidation of critical queries
   * - React Query automatically refetches invalidated data
   * - UI stays fresh without user intervention
   *
   * Usage (in providers.tsx):
   * ```tsx
   * socketService.onReconnect(() => {
   *   queryClient.invalidateQueries({ queryKey: ['users'] });
   *   queryClient.invalidateQueries({ queryKey: ['leads'] });
   * });
   * ```
   */
  onReconnect(callback: () => void) {
    this.onReconnectCallback = callback;
  }
}

export const socketService = new SocketService();
