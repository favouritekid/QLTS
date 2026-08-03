// @vitest-environment jsdom
/**
 * Tests cho bootstrap làm mới phiên.
 *
 * Ba quyết định phải khoá:
 *  1. Refresh xong → quay lại ĐÚNG URL cũ (đây là lý do trang này tồn tại).
 *  2. Refresh hỏng TẠM THỜI (429 rate limit / 5xx / mạng đứt) → KHÔNG đá về
 *     /login. Phiên vẫn còn hiệu lực; bắt đăng nhập lại là làm mất nó.
 *  3. Refresh hỏng THẬT (chỉ `terminal`: 401 / REFRESH_ABUSE_LOCKED) → mới
 *     sang /login?force_login=true. ⚠️ `403` lạ nay là `nonterminal-stop` —
 *     GIỮ phiên, xem `fail-preserve` trong `lib/api/refresh.ts`.
 */
import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

const refreshAccessToken = vi.hoisted(() => vi.fn());
// Chỉ thay `refreshAccessToken` (thứ cần điều khiển), GIỮ NGUYÊN phần còn lại
// của module — nhất là classifier. Mock cả module sẽ
// biến mọi test phân loại lỗi dưới đây thành test cho một hàm giả: chúng vẫn
// xanh kể cả khi classifier thật đảo ngược kết luận.
vi.mock("@/lib/api/refresh", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/refresh")>()),
  refreshAccessToken,
}));

const searchParams = vi.hoisted(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { RefreshFailure } from "@/lib/api/refresh";
import { useAuthStore } from "@/lib/stores/auth.store";
import { SessionRefreshBootstrap } from "./SessionRefreshBootstrap";

const replace = vi.fn();
const assign = vi.fn();

function setRedirect(value: string | null) {
  searchParams.delete("redirect");
  if (value !== null) searchParams.set("redirect", value);
}

/**
 * Lỗi KHÔNG phải `RefreshFailure` — chỉ dùng cho ca phòng thủ duy nhất bên
 * dưới. Mọi ca còn lại dựng `new RefreshFailure(...)` vì đó mới là thứ
 * `refreshAccessToken()` thật sự ném ở production.
 */
function nonRefreshFailureError() {
  return { isAxiosError: true, response: undefined };
}

describe("SessionRefreshBootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    replace.mockClear();
    assign.mockClear();
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: {
        replace,
        assign,
        origin: "https://qlts.tnpc.edu.vn",
        pathname: "/session-refresh",
        search: "",
        href: "",
      },
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
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({ kind: "safe-retryable", retryAt: Date.now() + 60_000 }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  /**
   * Lớp dọn state BÊN TRONG — không được để dành cho `LoginSessionResetGate`.
   *
   * Gate là lớp ngoài và chỉ chạy sau khi `/login` đã mount. Từ lúc quyết định
   * "phiên chết thật" tới lúc đó là một quãng hard navigation mà `auth.store`
   * vẫn còn `user` của phiên đã chết — đủ để bất kỳ component nào còn sống kịp
   * hỏi `/users/me` bằng danh tính đó.
   */
  it("terminal → dọn state client NGAY, không đợi trang /login mount", async () => {
    useAuthStore.setState({
      user: { id: 25, username: "officer1" } as never,
      isAuthenticated: true,
    });
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({ kind: "terminal", status: 401 }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  /**
   * 🔴 Hai nút này là caller DUY NHẤT của `?reauth=true` trong toàn ứng dụng —
   * trước đó cờ ấy chỉ có phía nhận ở `proxy.ts`, không ai phát.
   *
   * Và chúng phải được BẤM THẬT: `SessionRefreshBootstrap.test.tsx` trước đây
   * có 0 `fireEvent`, nên mọi assert chỉ chứng minh chữ hiện ra đúng, không
   * chứng minh bấm vào thì đi đâu.
   */
  describe("hai nút của màn lỗi tạm thời", () => {
    async function renderFailedScreen() {
      refreshAccessToken.mockRejectedValueOnce(
        new RefreshFailure({ kind: "safe-retryable", retryAt: Date.now() + 60_000 }),
      );
      render(<SessionRefreshBootstrap />);
      await waitFor(() =>
        expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument(),
      );
    }

    it("bấm *Đăng nhập lại* → /login?reauth=true, GIỮ return-url", async () => {
      await renderFailedScreen();

      fireEvent.click(screen.getByRole("button", { name: /Đăng nhập lại/i }));

      expect(assign).toHaveBeenCalledTimes(1);
      const target = decodeURIComponent(String(assign.mock.calls[0][0]));
      expect(target).toContain("/login");
      expect(target).toContain("reauth=true");
      expect(target).toContain("/admissions/611");
      // `force_login` ở đây là xoá phiên 30 ngày cho một lỗi TẠM THỜI.
      expect(target).not.toContain("force_login");
    });

    it("bấm *Thử lại* → sinh ĐÚNG MỘT attempt mới", async () => {
      await renderFailedScreen();
      const before = refreshAccessToken.mock.calls.length;
      refreshAccessToken.mockResolvedValueOnce(undefined);

      fireEvent.click(screen.getByRole("button", { name: /^Thử lại$/i }));

      await waitFor(() => expect(replace).toHaveBeenCalled());
      expect(refreshAccessToken.mock.calls.length - before).toBe(1);
    });
  });

  // Lỗi TẠM THỜI thì phiên vẫn còn — dọn state ở đây là tự tay đăng xuất một
  // người dùng mà ta vừa kết luận là chưa mất phiên.
  it("lỗi tạm thời → KHÔNG dọn state client", async () => {
    useAuthStore.setState({
      user: { id: 25, username: "officer1" } as never,
      isAuthenticated: true,
    });
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({ kind: "safe-retryable", retryAt: Date.now() + 60_000 }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument(),
    );
    expect(useAuthStore.getState().user).not.toBeNull();
  });

  // 429 KHÔNG phải mã nào cũng như nhau: cổng chống lạm dụng M4 đã thu hồi
  // toàn bộ session trước đó. Mời "Thử lại" ở đây là nói dối người dùng.
  it("429 REFRESH_ABUSE_LOCKED → sang /login (phiên đã bị thu hồi)", async () => {
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({
        kind: "terminal",
        status: 429,
        errorCode: "REFRESH_ABUSE_LOCKED",
      }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(replace.mock.calls[0][0]).toContain("/login");
  });

  /**
   * ⚠️ Contract ĐỔI: `nonterminal-stop` và `ambiguous` KHÔNG còn xoá phiên.
   *
   * Trước đây mọi 4xx lạ đều `force_login` (fail-safe). Nay chỉ `terminal` mới
   * được xoá cookie — một 404 vì sai `NEXT_PUBLIC_API_URL` hay một 403 từ WAF
   * không chứng minh refresh token 30 ngày đã chết.
   *
   * 🚧 Ở đây CHỈ khoá phần đã chốt: **không `force_login`, không xoá phiên**.
   * Giao diện cuối cho hai loại này là màn "Không xác định được trạng thái
   * phiên" với DUY NHẤT nút *Đăng nhập lại* (`reauth`) — thuộc hạng mục `2b`,
   * chưa triển khai. Cố ý KHÔNG assert giao diện tạm thời hiện có, để nó không
   * biến thành contract vĩnh viễn rồi chặn `2b`.
   */
  it.each([
    ["nonterminal-stop", { kind: "nonterminal-stop", status: 429 } as const],
    ["ambiguous", { kind: "ambiguous", reason: "server" } as const],
  ])("%s → GIỮ phiên: không force_login, không xoá cookie", async (_label, outcome) => {
    refreshAccessToken.mockRejectedValueOnce(new RefreshFailure(outcome));

    render(<SessionRefreshBootstrap />);
    await waitFor(() => expect(refreshAccessToken).toHaveBeenCalled());

    // Nếu có điều hướng thì tuyệt đối không được kèm `force_login` — nhánh đó
    // xoá sạch cả `refresh_token`.
    const target = (replace.mock.calls[0]?.[0] as string | undefined) ?? "";
    expect(target).not.toContain("force_login");
  });

  it.each([400, 404, 422])(
    "%i (4xx khác) → GIỮ phiên: không force_login",
    async (status) => {
      // Cùng lý do như khối trên: `400`/`404`/`422` nay là `nonterminal-stop`.
      // Giao diện cuối (`reauth`) thuộc `2b`, chưa chốt ở vòng này.
      refreshAccessToken.mockRejectedValueOnce(
        new RefreshFailure({ kind: "nonterminal-stop", status }),
      );

      render(<SessionRefreshBootstrap />);
      await waitFor(() => expect(refreshAccessToken).toHaveBeenCalled());

      const target = (replace.mock.calls[0]?.[0] as string | undefined) ?? "";
      expect(target).not.toContain("force_login");
    },
  );

  it("refresh 5xx → hiện nút thử lại, KHÔNG đá về /login", async () => {
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({ kind: "ambiguous", reason: "server" }),
    );

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  // Ca PHÒNG THỦ: production luôn ném `RefreshFailure`. Ở đây cố tình ném một
  // lỗi khác kiểu để chắc rằng mặc định vẫn là GIỮ phiên, không xoá cookie.
  it("lỗi lạ KHÔNG phải RefreshFailure → giữ phiên, không force_login", async () => {
    refreshAccessToken.mockRejectedValueOnce(nonRefreshFailureError());

    render(<SessionRefreshBootstrap />);

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("refresh 401 → sang /login?force_login=true kèm return-url", async () => {
    refreshAccessToken.mockRejectedValueOnce(
      new RefreshFailure({ kind: "terminal", status: 401 }),
    );

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
    refreshAccessToken.mockRejectedValue(
      new RefreshFailure({ kind: "ambiguous", reason: "server" }),
    );

    render(
      <StrictMode>
        <SessionRefreshBootstrap />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: /^Thử lại$/i })).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });
});
