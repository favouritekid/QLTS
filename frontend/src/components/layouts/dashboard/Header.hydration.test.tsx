// @vitest-environment jsdom
/**
 * GUARD — bất biến "lần render client ĐẦU TIÊN của mỗi instance `Header`
 * (`TopNav` bên trong nó) phải dùng đúng dữ liệu server (user chưa khả dụng)".
 *
 * `Header` nằm trong một biên <Suspense> RIÊNG (`DashboardLayout.tsx:224`) nên
 * có thể hydrate ở pha khác với sidebar. Với admin/manager, cổng vai trò làm
 * XUẤT HIỆN THÊM hẳn một <Link> "Người dùng" → cùng lớp mismatch persisted-user
 * như `useAppNavigation` và `NavUser`.
 *
 * Mọi thành phần anh em (ThemeToggle, NotificationDropdown, AppointmentReminder,
 * SecurityBanner, command palette, ui.store) đều được giả lập để một ca kiểm chỉ
 * vi phạm ĐÚNG MỘT bất biến — nếu không, đỏ ở đây không nói lên điều gì.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as React from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { act } from "react";

type GiaLapUser = { id: number; username: string; email: string; role: string };

const authState: { user: GiaLapUser | null } = { user: null };

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: authState.user }),
}));

vi.mock("@/hooks/useCommandPalette", () => ({
  useCommandPalette: () => ({ open: () => {}, isOpen: false, close: () => {}, toggle: () => {} }),
}));

vi.mock("@/lib/stores/ui.store", () => ({
  useUIStore: () => ({ isSidebarCollapsed: true, toggleSidebar: () => {} }),
}));

vi.mock("@/components/layouts/SecurityBanner", () => ({
  useShouldShowSecurityBanner: () => false,
  SECURITY_BANNER_HEIGHT: 40,
}));

vi.mock("@/components/ui/theme-toggle", () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}));
vi.mock("@/components/notifications/NotificationDropdown", () => ({
  NotificationDropdown: () => <div data-testid="notification-dropdown" />,
}));
vi.mock("@/components/leads/AppointmentReminder", () => ({
  AppointmentReminder: () => <div data-testid="appointment-reminder" />,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children?: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { Header } from "./Header";

const USER_ADMIN: GiaLapUser = { id: 15, username: "admintest", email: "admintest@example.com", role: "admin" };
const USER_OFFICER: GiaLapUser = { id: 1, username: "votest", email: "votest@example.com", role: "officer" };

async function hydrateVaThuLoi(container: HTMLElement, el: React.ReactElement): Promise<string[]> {
  const recoverable: string[] = [];
  await act(async () => {
    hydrateRoot(container, el, {
      onRecoverableError: (e) => recoverable.push(String((e as Error)?.message ?? e)),
    });
  });
  return recoverable.filter((m) => /[Hh]ydrat/.test(m));
}

describe("Header/TopNav — lần render client đầu tiên phải khớp server", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });
  afterEach(() => {
    container.remove();
    authState.user = null;
  });

  it("không sinh hydration mismatch khi client đã có persisted user vai trò admin", async () => {
    authState.user = null;
    const serverHtml = renderToString(<Header />);
    container.innerHTML = serverHtml;

    authState.user = USER_ADMIN;
    expect(await hydrateVaThuLoi(container, <Header />)).toEqual([]);
  });

  it("instance mount MUỘN cũng phải khớp server — cờ phải THEO TỪNG INSTANCE", async () => {
    authState.user = null;
    const serverHtml = renderToString(<Header />);

    const first = document.createElement("div");
    document.body.appendChild(first);
    first.innerHTML = serverHtml;
    authState.user = USER_ADMIN;
    await act(async () => {
      hydrateRoot(first, <Header />, { onRecoverableError: () => {} });
    });

    const late = document.createElement("div");
    document.body.appendChild(late);
    late.innerHTML = serverHtml;
    const loi = await hydrateVaThuLoi(late, <Header />);
    first.remove();
    late.remove();

    expect(loi).toEqual([]);
  });

  it("sau khi mount mới hiện link /admin/users cho admin", async () => {
    authState.user = null;
    const serverHtml = renderToString(<Header />);
    expect(serverHtml).not.toContain("/admin/users");
    container.innerHTML = serverHtml;

    authState.user = USER_ADMIN;
    await act(async () => {
      hydrateRoot(container, <Header />, { onRecoverableError: () => {} });
    });

    expect(container.innerHTML).toContain("/admin/users");
    expect(container.innerHTML).toContain("Người dùng");
  });

  it("officer KHÔNG được thấy link /admin/users kể cả sau khi mount", async () => {
    authState.user = null;
    const serverHtml = renderToString(<Header />);
    container.innerHTML = serverHtml;

    authState.user = USER_OFFICER;
    await act(async () => {
      hydrateRoot(container, <Header />, { onRecoverableError: () => {} });
    });

    expect(container.innerHTML).not.toContain("/admin/users");
  });
});
