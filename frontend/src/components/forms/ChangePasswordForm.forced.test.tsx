// @vitest-environment jsdom
/**
 * F131 — form đổi mật khẩu khi người dùng BỊ BUỘC đổi.
 *
 * Backend chặn `GET /api/sessions` (403) với người mang cờ; form chỉ dùng nó để
 * đếm thiết bị. Ở chế độ bị buộc (URL `?forced=true` HOẶC cờ của chính user)
 * form KHÔNG gọi nó, và vẫn hiện cảnh báo bắt buộc. Ngoài chế độ đó hành vi
 * như cũ.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const searchState = vi.hoisted(() => ({ query: "" }));
const authState = vi.hoisted(() => ({
  user: null as null | { password_reset_required?: boolean },
}));
const getActiveSessions = vi.hoisted(() =>
  vi.fn(async () => ({ total: 3, sessions: [] })),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchState.query),
  usePathname: () => "/settings",
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ changePassword: vi.fn(), isLoading: false, user: authState.user }),
}));

vi.mock("@/lib/api/sessions", () => ({ getActiveSessions }));

import { ChangePasswordForm } from "./ChangePasswordForm";

const FORCED_TITLE = "Yêu cầu Đổi Mật Khẩu";

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChangePasswordForm />
    </QueryClientProvider>,
  );
}

async function settle() {
  await new Promise((r) => setTimeout(r, 50));
}

beforeEach(() => {
  getActiveSessions.mockClear();
  searchState.query = "";
  authState.user = { password_reset_required: false };
});

describe("ChangePasswordForm — chế độ bị buộc đổi mật khẩu", () => {
  it("URL ?forced=true ⇒ không gọi GET /api/sessions, hiện cảnh báo bắt buộc", async () => {
    searchState.query = "forced=true";

    renderForm();
    await settle();

    expect(getActiveSessions).not.toHaveBeenCalled();
    expect(screen.getByText(FORCED_TITLE)).toBeTruthy();
  });

  it("vào thẳng /settings nhưng user mang cờ ⇒ vẫn là chế độ bị buộc", async () => {
    authState.user = { password_reset_required: true };

    renderForm();
    await settle();

    expect(getActiveSessions).not.toHaveBeenCalled();
    expect(screen.getByText(FORCED_TITLE)).toBeTruthy();
  });

  it("không bị buộc ⇒ như cũ: đếm thiết bị, không cảnh báo bắt buộc", async () => {
    renderForm();

    await waitFor(() => expect(getActiveSessions).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(FORCED_TITLE)).toBeNull();
  });
});
