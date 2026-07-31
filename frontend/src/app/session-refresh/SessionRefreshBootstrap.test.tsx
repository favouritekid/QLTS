// @vitest-environment jsdom
/**
 * Tests cho bootstrap làm mới phiên.
 *
 * Ba quyết định phải khoá:
 *  1. Refresh xong → quay lại ĐÚNG URL cũ (đây là lý do trang này tồn tại).
 *  2. Refresh hỏng TẠM THỜI (429 rate limit / 5xx / mạng đứt) → KHÔNG đá về
 *     /login. Phiên vẫn còn hiệu lực; bắt đăng nhập lại là làm mất nó.
 *  3. Refresh hỏng THẬT (401/403) → mới sang /login?force_login=true.
 */
import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const refreshAccessToken = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/refresh", () => ({ refreshAccessToken }));

const searchParams = vi.hoisted(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { SessionRefreshBootstrap } from "./SessionRefreshBootstrap";

const replace = vi.fn();

function setRedirect(value: string | null) {
  searchParams.delete("redirect");
  if (value !== null) searchParams.set("redirect", value);
}

function axiosLikeError(status?: number, data: Record<string, unknown> = {}) {
  return {
    isAxiosError: true,
    response: status === undefined ? undefined : { status, data },
  };
}

describe("SessionRefreshBootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    replace.mockClear();
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { replace, pathname: "/session-refresh", search: "", href: "" },
    });
    setRedirect("/admissions/611");
  });

  it("refresh thành công → quay lại đúng URL cũ", async () => {
    refreshAccessToken.mockResolvedValueOnce(undefined);

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admissions/611"));
  });

  // Ca trung tâm: 429 RATE_LIMITED trên bucket dùng chung của cả trường.
  it("429 RATE_LIMITED → hiện nút thử lại, KHÔNG đá về /login", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(429, { error_code: "RATE_LIMITED" }));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  // 429 KHÔNG phải mã nào cũng như nhau: cổng chống lạm dụng M4 đã thu hồi
  // toàn bộ session trước đó. Mời "Thử lại" ở đây là nói dối người dùng.
  it("429 REFRESH_ABUSE_LOCKED → sang /login (phiên đã bị thu hồi)", async () => {
    refreshAccessToken.mockRejectedValueOnce(
      axiosLikeError(429, { error_code: "REFRESH_ABUSE_LOCKED" }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain("/login");
  });

  it("429 thiếu error_code → sang /login (fail-safe)", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(429));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain("/login");
  });

  it("429 mã lạ → sang /login (fail-safe)", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(429, { error_code: "HTTP_429" }));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain("/login");
  });

  it.each([400, 404, 422])("%i (4xx khác) → sang /login, không mời thử lại", async (status) => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(status));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain("/login");
  });

  it("refresh 5xx → hiện nút thử lại, KHÔNG đá về /login", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(503));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("mạng đứt (không có response) → hiện nút thử lại", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(undefined));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("refresh 401 → sang /login?force_login=true kèm return-url", async () => {
    refreshAccessToken.mockRejectedValueOnce(axiosLikeError(401));

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    const target = replace.mock.calls[0][0] as string;
    expect(target).toContain("/login");
    expect(target).toContain("force_login=true");
    expect(target).toContain("redirect=%2Fadmissions%2F611");
  });

  // Chặn open-redirect: `redirect` đến từ query string.
  it("redirect ngoại lai → rơi về /dashboard, không đi ra ngoài", async () => {
    setRedirect("https://evil.example.com/steal");
    refreshAccessToken.mockResolvedValueOnce(undefined);

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("thiếu redirect → về /dashboard", async () => {
    setRedirect(null);
    refreshAccessToken.mockResolvedValueOnce(undefined);

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  // StrictMode mount effect hai lần và cleanup lần đầu. Nếu chặn lần hai bằng
  // một ref "đã chạy rồi", kết quả lần đầu bị `cancelled` bỏ qua còn lần hai
  // không làm gì → trang treo mãi ở "Đang làm mới phiên đăng nhập…".
  it("dưới StrictMode → vẫn quay lại URL cũ, không treo", async () => {
    refreshAccessToken.mockResolvedValue(undefined);

    render(
      <StrictMode>
        <SessionRefreshBootstrap />
      </StrictMode>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admissions/611"));
  });

  it("dưới StrictMode + lỗi tạm thời → vẫn hiện nút thử lại", async () => {
    refreshAccessToken.mockRejectedValue(axiosLikeError(503));

    render(
      <StrictMode>
        <SessionRefreshBootstrap />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });
});
