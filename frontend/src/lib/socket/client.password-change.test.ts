// @vitest-environment jsdom
/**
 * F128/F131 — socket bị server cắt vì phải đổi mật khẩu.
 *
 * Server gửi `password_change_required` NGAY TRƯỚC lệnh cắt (cùng websocket).
 * Lần "io server disconnect" sau đó KHÔNG được xoá auth store (người dùng sẽ
 * phải tự F5 mới dùng được form); mọi lần server cắt KHÁC vẫn đăng xuất như cũ.
 * Chạy đúng các handler mà `SocketService` đăng ký lên socket.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const handlers = vi.hoisted(() => ({} as Record<string, (...args: unknown[]) => void>));
const fakeSocket = vi.hoisted(() => ({
  connected: true,
  on: vi.fn(),
  emit: vi.fn(),
  disconnect: vi.fn(),
  io: { opts: {} as Record<string, unknown> },
}));

vi.mock("socket.io-client", () => ({ io: vi.fn(() => fakeSocket) }));

const authStore = vi.hoisted(() => ({ logout: vi.fn() }));
vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: { getState: () => authStore },
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { socketService } from "./client";

const assign = vi.fn();

function at(pathname: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { pathname, search: "", href: "", assign },
  });
}

function fire(event: string, ...args: unknown[]) {
  const h = handlers[event];
  expect(h, `SocketService không đăng ký handler "${event}"`).toBeTypeOf("function");
  h(...args);
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const k of Object.keys(handlers)) delete handlers[k];
  fakeSocket.on.mockImplementation((event: string, h: (...args: unknown[]) => void) => {
    handlers[event] = h;
  });
  at("/leads");
  socketService.connect();
});

afterEach(() => {
  socketService.disconnect();
});

describe("SocketService — cắt vì phải đổi mật khẩu", () => {
  it("báo trước rồi cắt ⇒ KHÔNG đăng xuất, tới form", () => {
    fire("password_change_required");
    fire("disconnect", "io server disconnect");

    expect(authStore.logout).not.toHaveBeenCalled();
    expect(assign).toHaveBeenCalledWith("/settings?forced=true");
  });

  it("server cắt KHÔNG báo trước ⇒ vẫn đăng xuất như cũ", () => {
    fire("disconnect", "io server disconnect");

    expect(authStore.logout).toHaveBeenCalledTimes(1);
  });

  it("cờ chỉ dành cho đúng lần cắt đã báo: kết nối lại thì một lần cắt sau vẫn đăng xuất", () => {
    fire("password_change_required");
    fire("connect");
    fire("disconnect", "io server disconnect");

    expect(authStore.logout).toHaveBeenCalledTimes(1);
  });

  it("đang ở /settings ⇒ không tải lại trang", () => {
    at("/settings");

    fire("password_change_required");
    fire("disconnect", "io server disconnect");

    expect(assign).not.toHaveBeenCalled();
    expect(authStore.logout).not.toHaveBeenCalled();
  });
});
