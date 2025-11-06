// lib/socket/client.ts
import { io, Socket } from "socket.io-client";
import { env } from "@/lib/config/env";
import { useAuthStore } from "../stores/auth.store";
import { toast } from "sonner";

class SocketService {
  private socket: Socket | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shutdownReconnectTimer: NodeJS.Timeout | null = null;

  connect() {
    if (this.socket && this.socket.connected) {
      console.log("[SocketService] Already connected.");
      return;
    }

    const token = useAuthStore.getState().token;
    if (!token) {
      console.error("[SocketService] No auth token, connection aborted.");
      return;
    }

    console.log("[SocketService] Connecting to", env.NEXT_PUBLIC_API_URL);
    this.reconnectAttempts = 0;

    this.socket = io(env.NEXT_PUBLIC_API_URL, {
      path: "/socket.io",
      auth: { token },
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
    });

    this.socket.on("disconnect", (reason) => {
      console.warn("[SocketService] ❌ Disconnected:", reason);
      this.stopHeartbeat();
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

  disconnect() {
    this.stopHeartbeat();
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
}

export const socketService = new SocketService();
