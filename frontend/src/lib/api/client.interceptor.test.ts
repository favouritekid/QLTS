/**
 * Lock-in test cho WIRING của interceptor 401 — không chỉ cho predicate.
 *
 * Vì sao cần: hành vi gây sự cố nằm ở chỗ interceptor QUYẾT ĐỊNH logout, chứ
 * không ở predicate phân loại. Nếu chỉ test predicate thì đảo
 * một dấu `!` trong client.ts vẫn xanh toàn bộ suite, và bug prod quay lại
 * nguyên trạng. Ở đây test chạy đúng handler mà `client.ts` đăng ký với axios,
 * dùng predicate THẬT, và khẳng định 3 tác dụng phụ có thật:
 * `setApiLoggedOut`, `window.location.href`, và request gốc có retry hay không.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Handler mà client.ts đăng ký ở import time — capture để gọi trực tiếp.
// `vi.hoisted` vì factory của `vi.mock` được hoist lên trước mọi khai báo
// thường; một `let` ở đây sẽ vướng TDZ khi factory chạy.
const captured = vi.hoisted(() => ({
  onError: undefined as ((error: unknown) => Promise<unknown>) | undefined,
}));

vi.mock("axios", async (importActual) => {
  // Giữ `AxiosError` và `isAxiosError` THẬT: các test dưới đây dựng lỗi bằng
  // `new AxiosError(...)` chứ không bịa `{ isAxiosError: true }`. Một object
  // bịa vẫn qua được `isAxiosError` giả, nên nó KHÔNG chứng minh được nhánh
  // `error instanceof AxiosError` mà predicate retry ở `providers.tsx` dùng.
  const actual = await importActual<typeof import("axios")>();
  const isAxiosError = actual.default.isAxiosError;

  const instance = vi.fn(() => Promise.resolve({ data: "retried" })) as unknown as {
    (config: unknown): Promise<unknown>;
    interceptors: {
      request: { use: ReturnType<typeof vi.fn> };
      response: { use: ReturnType<typeof vi.fn> };
    };
    defaults: { headers: { common: Record<string, unknown> } };
  };
  instance.interceptors = {
    request: { use: vi.fn() },
    response: {
      use: vi.fn((_onSuccess: unknown, onError: (error: unknown) => Promise<unknown>) => {
        captured.onError = onError;
      }),
    },
  };
  instance.defaults = { headers: { common: {} } };

  const mockAxios = {
    create: vi.fn(() => instance),
    post: vi.fn(),
    isAxiosError,
    Cancel: class Cancel extends Error {},
  };
  return {
    ...actual,
    default: mockAxios,
    ...mockAxios,
    AxiosError: actual.AxiosError,
  };
});

// Chỉ mock việc GỌI refresh; classifier giữ bản THẬT để
// test khoá được cả phân loại lẫn wiring.
vi.mock("./refresh", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./refresh")>();
  return { ...actual, refreshAccessToken: vi.fn() };
});

// Store thật khởi tạo zustand + persist; nhánh logout chỉ cần nó không nổ.
// `logout` phải là MỘT spy ổn định — nếu `getState()` tạo spy mới mỗi lần gọi
// thì không test nào giữ được tham chiếu tới hàm client.ts thực sự gọi, và
// việc xoá lời gọi `logout()` sẽ không làm đỏ test nào.
const authStore = vi.hoisted(() => ({ logout: vi.fn() }));
vi.mock("@/lib/stores/auth.store", () => ({
  useAuthStore: { getState: () => authStore },
}));

import { AxiosError } from "axios";
import {
  refreshAccessToken,
  RefreshFailure,
  isSessionKeptAliveError,
} from "./refresh";
import { isApiLoggedOut, setApiLoggedOut } from "./client";

const mockedRefresh = vi.mocked(refreshAccessToken);

/**
 * `AxiosError` THẬT, không phải object bịa.
 *
 * Predicate retry ở `providers.tsx` kiểm `error instanceof AxiosError` — một
 * object mang `isAxiosError: true` qua được `axios.isAxiosError` nhưng KHÔNG
 * qua được `instanceof`, nên test dựng bằng object bịa sẽ xanh trong khi
 * production vẫn retry và bắn thêm request refresh vào quota dùng chung.
 */
function requestError401(): AxiosError {
  return new AxiosError(
    "Unauthorized",
    "ERR_BAD_REQUEST",
    { url: "/api/admissions/611", headers: {} } as never,
    undefined,
    {
      status: 401,
      data: {},
      statusText: "Unauthorized",
      headers: {},
      config: {},
    } as never,
  );
}

/** Lỗi mà `refreshAccessToken()` thật sự ném: `RefreshFailure` có outcome. */
function refreshFailure(outcome: ConstructorParameters<typeof RefreshFailure>[0]) {
  return new RefreshFailure(outcome);
}

describe("interceptor 401 — quyết định logout khi refresh thất bại", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setApiLoggedOut(false);
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { pathname: "/admissions/611", search: "", href: "" },
    });
  });

  afterEach(() => {
    setApiLoggedOut(false);
  });

  it("handler đã được đăng ký (nếu không, mọi assert dưới đây là vô nghĩa)", () => {
    expect(captured.onError).toBeTypeOf("function");
  });

  /**
   * Ba tính chất phải cùng đúng khi GIỮ phiên, không chỉ "không redirect":
   *  1. trả lại CHÍNH `AxiosError 401` gốc (`toBe`), không phải bản sao;
   *  2. object đó mang cờ kept-alive để `useAuth` không tự đăng xuất;
   *  3. nó vẫn là `AxiosError` 4xx CÓ `response` — predicate ở `providers.tsx`
   *     dựa vào đúng ba điều kiện đó để KHÔNG retry. Trả một `RefreshFailure`
   *     ở đây là để React Query retry 3 lần, mỗi lần thêm một POST refresh.
   */
  async function expectKeptAlive(outcomeError: unknown) {
    mockedRefresh.mockRejectedValueOnce(outcomeError);
    const original = requestError401();

    const rejected = await captured.onError!(original).catch((e) => e);

    expect(rejected).toBe(original);
    expect(isSessionKeptAliveError(rejected)).toBe(true);
    expect(rejected).toBeInstanceOf(AxiosError);
    expect((rejected as AxiosError).response?.status).toBe(401);
    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  }

  // Ca gây sự cố prod: 32% request /auth/refresh bị slowapi chặn.
  it("safe-retryable (429 RATE_LIMITED) → GIỮ phiên, trả đúng 401 gốc", async () => {
    await expectKeptAlive(
      refreshFailure({ kind: "safe-retryable", retryAt: Date.now() + 60_000 }),
    );
  });

  it.each([
    [
      "nonterminal-stop (429 thiếu mã)",
      { kind: "nonterminal-stop", status: 429 } as const,
    ],
    [
      "nonterminal-stop (404 — sai NEXT_PUBLIC_API_URL)",
      { kind: "nonterminal-stop", status: 404 } as const,
    ],
    ["ambiguous (5xx)", { kind: "ambiguous", reason: "server" } as const],
    ["ambiguous (mạng đứt)", { kind: "ambiguous", reason: "network" } as const],
  ])("%s → GIỮ phiên, trả đúng 401 gốc", async (_label, outcome) => {
    // ⚠️ Contract ĐỔI so với bản cũ: trước đây mọi 4xx lạ đều logout
    // (fail-safe). Nay chỉ `terminal` mới xoá cookie — một 404 vì sai
    // `NEXT_PUBLIC_API_URL` không chứng minh phiên 30 ngày đã chết.
    await expectKeptAlive(refreshFailure(outcome));
  });

  it("terminal (REFRESH_ABUSE_LOCKED) → logout + redirect /login", async () => {
    mockedRefresh.mockRejectedValueOnce(
      refreshFailure({ kind: "terminal", status: 429, errorCode: "REFRESH_ABUSE_LOCKED" }),
    );

    await expect(captured.onError!(requestError401())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
    // Không clear store thì user cũ vẫn rehydrate từ localStorage và boot lại
    // như đang đăng nhập sau khi redirect.
    expect(authStore.logout).toHaveBeenCalled();
  });

  it("terminal (401 từ /auth/refresh) → logout", async () => {
    mockedRefresh.mockRejectedValueOnce(
      refreshFailure({ kind: "terminal", status: 401 }),
    );

    await expect(captured.onError!(requestError401())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
  });

  /**
   * Ca PHÒNG THỦ, không mô tả đường production.
   *
   * `refreshAccessToken()` luôn ném `RefreshFailure` (mạng đứt đã có ca
   * `ambiguous/network` ở helper phía trên). Ở đây cố tình ném một lỗi KHÁC
   * kiểu để chắc rằng nếu sau này có đường nào lọt ra một lỗi lạ, mặc định vẫn
   * là giữ phiên và trả lỗi gốc 401 — chứ không xoá cookie.
   */
  it("lỗi lạ KHÔNG phải RefreshFailure → vẫn giữ phiên, reject lỗi GỐC 401", async () => {
    mockedRefresh.mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" });

    await expect(captured.onError!(requestError401())).rejects.toMatchObject({
      response: { status: 401 },
    });

    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  });

  it("refresh thành công → retry request gốc, không logout", async () => {
    mockedRefresh.mockResolvedValueOnce(undefined);

    await expect(captured.onError!(requestError401())).resolves.toMatchObject({
      data: "retried",
    });

    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  });
});

// Nhánh CSRF-recovery dùng CHUNG triage với nhánh 401 — và hai nhánh này đã
// từng drift nhau. Không có test ở đây thì xoá/đảo lời gọi triage bên nhánh
// CSRF vẫn xanh toàn suite, trong khi một 429 RATE_LIMITED lại hard-redirect
// officer về /login giữa lúc nhập liệu.
describe("interceptor CSRF-recovery — cùng một triage với nhánh 401", () => {
  function csrfError403() {
    return {
      isAxiosError: true,
      message: "CSRF token invalid",
      response: { status: 403, data: { error_code: "CSRF_TOKEN_INVALID" } },
      config: { url: "/api/admissions/611", headers: {} },
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    setApiLoggedOut(false);
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { pathname: "/admissions/611", search: "", href: "" },
    });
  });

  afterEach(() => {
    setApiLoggedOut(false);
  });

  /**
   * Nhánh này trả NGUYÊN NHÂN (`RefreshFailure`), không trả 403 gốc.
   *
   * Khác nhánh 401 có chủ đích: ở đây `handleApiError` sẽ map 403 → "Bạn không
   * có quyền thực hiện thao tác này", báo sai hoàn toàn khi nguyên nhân thật là
   * backend 5xx hay rate limit. An toàn vì nhánh này chạy cho mutation, mà
   * `mutations: { retry: false }` nên không có nguy cơ retry storm.
   */
  async function expectRejectsWithCause(outcome: {
    kind: string;
    [k: string]: unknown;
  }) {
    const cause = refreshFailure(outcome as never);
    mockedRefresh.mockRejectedValueOnce(cause);

    const rejected = await captured.onError!(csrfError403()).catch((e) => e);

    expect(rejected).toBe(cause);
    expect(isSessionKeptAliveError(rejected)).toBe(true);
    // 403 gốc KHÔNG được nổi lên.
    expect((rejected as { response?: { status?: number } }).response?.status).not.toBe(403);
    expect(isApiLoggedOut()).toBe(false);
    expect(window.location.href).toBe("");
  }

  it("safe-retryable → GIỮ phiên, trả nguyên nhân chứ không phải 403 gốc", async () => {
    await expectRejectsWithCause({
      kind: "safe-retryable",
      retryAt: Date.now() + 60_000,
    });
  });

  it("ambiguous (5xx) → GIỮ phiên, trả nguyên nhân chứ không phải 403 gốc", async () => {
    await expectRejectsWithCause({ kind: "ambiguous", reason: "server" });
  });

  it("nonterminal-stop → GIỮ phiên, trả nguyên nhân", async () => {
    await expectRejectsWithCause({ kind: "nonterminal-stop", status: 404 });
  });

  it("terminal → logout + redirect /login + clear store (như nhánh 401)", async () => {
    mockedRefresh.mockRejectedValueOnce(
      refreshFailure({ kind: "terminal", status: 401 }),
    );

    await expect(captured.onError!(csrfError403())).rejects.toBeTruthy();

    expect(isApiLoggedOut()).toBe(true);
    expect(window.location.href).toContain("/login");
    expect(authStore.logout).toHaveBeenCalled();
  });
});
