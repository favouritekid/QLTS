/**
 * Bước 5 — 401 trong Server Component đi về đâu.
 *
 * Trước đây nó `redirect('/login?force_login=true')`, mà nhánh `force_login`
 * của proxy xoá SẠCH cả `refresh_token`: một access token hết hạn 15 phút biến
 * thành mất phiên 30 ngày. Server Component không phân biệt được hai thứ đó,
 * nên nó phải chuyển sang trang cứu phiên và để client hỏi backend.
 *
 * `source=server_401` là phần không được quên: nó báo cho proxy biết đừng
 * shortcut — server vừa từ chối thật, nên bằng chứng "token còn hạn" ở đó vô
 * nghĩa và sẽ tạo vòng lặp.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const headerStore = vi.hoisted(() => ({ value: null as string | null }));
const redirectMock = vi.hoisted(() => vi.fn());

vi.mock("next/headers", () => ({
  cookies: async () => ({ toString: () => "", get: () => undefined }),
  headers: async () => ({
    get: (name: string) =>
      name.toLowerCase() === "x-qlts-pathname" ? headerStore.value : null,
  }),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
  unstable_rethrow: (error: unknown) => {
    throw error;
  },
}));

const fetchMock = vi.fn();

beforeEach(() => {
  // Không có biến này thì `getBackendUrl()` trả `undefined` và `new URL(...)`
  // ném TRƯỚC khi luồng chạm nhánh 401 — mọi ca sẽ đỏ vì lý do chẳng liên quan.
  vi.stubEnv("BACKEND_INTERNAL_URL", "http://backend:8000");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  redirectMock.mockReset();
  headerStore.value = null;
  // 401 cho mọi request — đây là ca duy nhất tệp này quan tâm.
  fetchMock.mockResolvedValue({
    ok: false,
    status: 401,
    text: async () => "{}",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

async function callServerApi() {
  const { serverFetch } = await import("./server");
  try {
    await serverFetch("/admissions/611");
  } catch {
    // `redirect` bị mock nên luồng chạy tiếp và ném ở chỗ khác — không sao,
    // thứ cần khẳng định là ĐÃ gọi `redirect` với URL nào.
  }
}

function redirectedTo(): string {
  expect(redirectMock).toHaveBeenCalled();
  return decodeURIComponent(String(redirectMock.mock.calls[0][0]));
}

describe("serverFetch 401 → trang cứu phiên", () => {
  it("KHÔNG còn đi thẳng /login?force_login=true", async () => {
    headerStore.value = "/admissions/611?tab=ho-so";

    await callServerApi();

    const target = redirectedTo();
    expect(target).not.toContain("force_login");
    expect(target).toContain("/session-refresh");
  });

  it("giữ return-url từ x-qlts-pathname và gắn source=server_401", async () => {
    headerStore.value = "/admissions/611?tab=ho-so";

    await callServerApi();

    const target = redirectedTo();
    expect(target).toContain("/admissions/611");
    expect(target).toContain("tab=ho-so");
    expect(target).toContain("source=server_401");
  });

  it("gỡ `_rsc` khỏi return-url", async () => {
    headerStore.value = "/admissions/611?_rsc=abc&tab=ho-so";

    await callServerApi();

    const target = redirectedTo();
    expect(target).not.toContain("_rsc");
    expect(target).toContain("tab=ho-so");
  });

  // Header này điều khiển redirect. Proxy ghi đè nó ở mọi request đi qua, nhưng
  // nếu một đường nào đó lọt thì một giá trị ngoại lai không được biến trang
  // cứu phiên thành open redirect.
  it.each([
    ["thiếu hẳn", null],
    ["origin ngoại lai", "//evil.com/x"],
    ["URL tuyệt đối", "https://evil.com/x"],
  ])("header %s ⇒ fallback an toàn, không open redirect", async (_label, value) => {
    headerStore.value = value;

    await callServerApi();

    const target = redirectedTo();
    expect(target).not.toContain("evil.com");
    expect(target).toContain("/session-refresh");
    expect(target).toContain("redirect=/dashboard");
  });
});
