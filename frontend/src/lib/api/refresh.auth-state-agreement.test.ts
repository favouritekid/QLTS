// src/lib/api/refresh.auth-state-agreement.test.ts
/**
 * Hai nơi phía client hỏi "đây có phải 503 AUTH_STATE_UNAVAILABLE không?":
 *
 * - `isAuthStateUnavailable(response)` (`error-codes.ts`) — `LoginForm` dùng cho
 *   503 của `/login`, nhận nguyên response;
 * - `classify()` (`refresh.ts`) qua `isSafeRetryableResponse(status, errorCode)`
 *   (`safe-retry.ts`) — quyết định thử lại 503 của `/refresh`, và cũng là thứ
 *   `validateRecord()` dùng cho bản ghi nhật ký (chỉ có cặp, không có response).
 *
 * Backend trả CÙNG một 503 cho cả hai endpoint (`AuthStateUnavailable`), nên
 * hai câu trả lời phải trùng nhau trên mọi response: nới một bên thì màn đăng
 * nhập báo "hệ thống xác thực không sẵn sàng" cho thứ refresh coi là mơ hồ,
 * hoặc ngược lại. Test chạy `classify()` THẬT (qua `refreshAccessToken`), không
 * chép lại logic của nó.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { installFakeIdb, removeWebLocks } from "./refresh-coordination/test-harness";
import { isAuthStateUnavailable } from "./error-codes";

const post = vi.hoisted(() => vi.fn());

vi.mock("axios", async (importActual) => {
  const actual = await importActual<typeof import("axios")>();
  return {
    ...actual,
    default: { ...actual.default, post, isAxiosError: actual.default.isAxiosError },
  };
});

const NGINX_503_HTML =
  "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n" +
  "<body>\r\n<center><h1>503 Service Temporarily Unavailable</h1></center>\r\n" +
  "<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n";

const CORPUS: Array<[string, { status: number; data: unknown }]> = [
  [
    "503 của backend, đúng mã",
    {
      status: 503,
      data: {
        detail: "Hệ thống xác thực tạm thời không sẵn sàng. Vui lòng thử lại sau.",
        error_code: "AUTH_STATE_UNAVAILABLE",
      },
    },
  ],
  ["503 nginx, thân HTML", { status: 503, data: NGINX_503_HTML }],
  ["503 JSON rỗng", { status: 503, data: {} }],
  ["503 thân null", { status: 503, data: null }],
  ["503 mã khác", { status: 503, data: { error_code: "SERVICE_UNAVAILABLE" } }],
  ["503 HTTP_503 (sau khi rotation bắt đầu)", { status: 503, data: { error_code: "HTTP_503" } }],
  ["503 mã viết thường", { status: 503, data: { error_code: "auth_state_unavailable" } }],
  ["503 mã có khoảng trắng", { status: 503, data: { error_code: " AUTH_STATE_UNAVAILABLE" } }],
  [
    "503 mã lồng trong detail",
    { status: 503, data: { detail: { error_code: "AUTH_STATE_UNAVAILABLE" } } },
  ],
  ["500 kèm đúng mã", { status: 500, data: { error_code: "AUTH_STATE_UNAVAILABLE" } }],
  ["502 kèm đúng mã", { status: 502, data: { error_code: "AUTH_STATE_UNAVAILABLE" } }],
  ["429 kèm đúng mã", { status: 429, data: { error_code: "AUTH_STATE_UNAVAILABLE" } }],
];

function axiosError(response: { status: number; data: unknown }) {
  const error = new Error(`HTTP ${response.status}`) as Error & {
    isAxiosError: true;
    response: { status: number; data: unknown; headers: Record<string, string> };
  };
  error.isAxiosError = true;
  error.response = { ...response, headers: { "retry-after": "30" } };
  return error;
}

beforeEach(() => {
  post.mockReset();
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  document.cookie = "csrf_token=gen-old; path=/";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("classify() và isAuthStateUnavailable() trả lời CÙNG một câu", () => {
  it("kho mẫu có cả ca khớp lẫn ca không khớp (nếu không, phép so vô nghĩa)", () => {
    const answers = CORPUS.map(([, response]) => isAuthStateUnavailable(response));
    expect(answers).toContain(true);
    expect(answers).toContain(false);
  });

  it.each(CORPUS)("%s", async (_label, response) => {
    post.mockRejectedValue(axiosError(response));
    vi.resetModules();
    const { refreshAccessToken } = await import("./refresh");

    const error = await refreshAccessToken().catch((e) => e);

    expect(post).toHaveBeenCalledTimes(1);
    expect(error.outcome.kind === "safe-retryable").toBe(isAuthStateUnavailable(response));
  });
});
