/**
 * Hợp đồng route: gán / thu hồi vai trò admin.
 *
 * Vì sao tệp này tồn tại: `endpoints.ts` từng trỏ CẢ HAI hành động về
 * `/api/admin/assign-role` — một đường KHÔNG router nào phục vụ (đã grep toàn
 * `app/`). Không có ca kiểm nào nhìn thấy chuỗi ấy, nên lỗi sống qua nhiều đợt
 * và chỉ lộ ra ở 404 trong trình duyệt.
 *
 * Tệp gác HAI tầng, cố ý không gộp:
 *
 *   Tầng 1 — GIÁ TRỊ hằng. So chuỗi TUYỆT ĐỐI với đường thật đọc từ backend
 *   (`roles.py:61` prefix `/roles` · `admin/__init__.py:54` prefix `/admin` ·
 *   `main.py:957` prefix `/api`). Không dùng `toContain`/regex nới tay: một
 *   phép khớp lỏng sẽ xanh cho cả `/api/admin/assign-role`.
 *
 *   Tầng 2 — HÀNH VI hook. Tầng 1 một mình chỉ chứng minh bảng hằng đúng, chứ
 *   không chứng minh hook GỌI đúng hằng nào; bản cũ có sẵn `REMOVE_ROLE` với
 *   giá trị riêng mà hook xoá vẫn dùng `ASSIGN_ROLE`. Tầng 2 chặn đúng ca đó
 *   bằng cách đọc URL mà `api.post` / `api.delete` thật sự nhận.
 *
 * Mỗi `it` chỉ vi phạm được MỘT bất biến, để khi đỏ thì biết đỏ vì gì.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { createTestQueryClient } from "@/test/utils/test-utils";

vi.mock("@/lib/api/client", () => {
  const api = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { api, apiClient: api, default: api };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

// Import SAU `vi.mock` để hook nhận bản đã mock.
import { api } from "@/lib/api/client";
import { useAdminAssignRole, useAdminRemoveRole } from "@/hooks/useAdminUsers";

const PERMISSIONS = API_ENDPOINTS.ADMIN.PERMISSIONS;

/** Đường THẬT backend đăng ký — nguồn: app/routers/admin/roles.py. */
const DUONG_THAT = {
  ASSIGN: "/api/admin/roles/assign", // @router.post("/assign")   roles.py:358
  REVOKE: "/api/admin/roles/revoke", // @router.delete("/revoke") roles.py:394
  POLICIES: "/api/admin/roles/policies", // roles.py:166/181/262
  TEMPLATES: "/api/admin/roles/templates", // roles.py:859
  APPLY_TEMPLATE: "/api/admin/roles/templates/apply", // roles.py:895
} as const;

/**
 * Alias backend đã bị GỠ. Không đường nào trong `app/` phục vụ chúng, và commit
 * này cố ý KHÔNG dựng lại. Hằng frontend chạm vào bất kỳ chuỗi nào ở đây là lỗi.
 */
const DUONG_CHET = [
  "/api/admin/assign-role",
  "/api/admin/policies",
  "/api/admin/policy-templates",
  "/api/admin/roles/policies/apply-template",
] as const;

/**
 * Đọc đối số thứ `argIndex` của lời gọi thứ `callIndex`.
 *
 * Đi vòng qua `unknown` thay vì `vi.mocked(...)`: `AxiosInstance.post/delete` là
 * hàm GENERIC nhiều tham số kiểu, và việc suy `Parameters<>` của chúng phụ thuộc
 * phiên bản axios/vitest. Ca kiểm này nói về URL, nên nó không nên đỏ vì một bản
 * nâng cấp kiểu.
 */
function argCuaLoiGoi(fn: unknown, argIndex: number, callIndex = 0): unknown {
  const calls = (fn as { mock?: { calls?: unknown[][] } }).mock?.calls;
  if (!calls || calls.length <= callIndex) {
    throw new Error(`Không có lời gọi thứ ${callIndex}; đã ghi nhận ${calls?.length ?? 0}.`);
  }
  return calls[callIndex][argIndex];
}

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

describe("hợp đồng route — hằng số", () => {
  it("ASSIGN_ROLE trỏ đúng POST /api/admin/roles/assign", () => {
    expect(PERMISSIONS.ASSIGN_ROLE).toBe(DUONG_THAT.ASSIGN);
  });

  it("REVOKE_ROLE trỏ đúng DELETE /api/admin/roles/revoke", () => {
    expect(PERMISSIONS.REVOKE_ROLE).toBe(DUONG_THAT.REVOKE);
  });

  it("gán và thu hồi là HAI hằng khác nhau, không chung một chuỗi", () => {
    // Bất biến riêng: kể cả khi cả hai cùng trỏ về một đường CÓ THẬT (ví dụ ai
    // đó gộp lại thành `/roles/assign` cho cả hai rồi phân biệt bằng method),
    // ca này vẫn phải đỏ.
    expect(PERMISSIONS.ASSIGN_ROLE).not.toBe(PERMISSIONS.REVOKE_ROLE);
  });

  it("POLICIES trỏ đúng /api/admin/roles/policies", () => {
    expect(PERMISSIONS.POLICIES).toBe(DUONG_THAT.POLICIES);
  });

  it("TEMPLATES và APPLY_TEMPLATE trỏ đúng cụm /roles/templates", () => {
    expect(PERMISSIONS.TEMPLATES).toBe(DUONG_THAT.TEMPLATES);
    expect(PERMISSIONS.APPLY_TEMPLATE).toBe(DUONG_THAT.APPLY_TEMPLATE);
  });

  it("không hằng PERMISSIONS nào còn chạm alias backend đã gỡ", () => {
    const viPham = Object.entries(PERMISSIONS).filter(
      ([, url]) => typeof url === "string" && (DUONG_CHET as readonly string[]).includes(url)
    );
    expect(viPham).toEqual([]);
  });

  it("mọi hằng PERMISSIONS nằm trong cụm /api/admin/roles", () => {
    // Cụm này do MỘT router phục vụ (`APIRouter(prefix="/roles")`); một hằng
    // rơi ra ngoài `/api/admin/roles` là dấu hiệu nó trỏ vào đường không tồn
    // tại — đúng hình dạng của cả ba lỗi vừa vá.
    const ngoaiCum = Object.entries(PERMISSIONS).filter(
      ([, url]) => typeof url === "string" && !url.startsWith("/api/admin/roles")
    );
    expect(ngoaiCum).toEqual([]);
  });
});

describe("hợp đồng route — hook thật sự gọi đường nào", () => {
  // Cố ý KHÔNG gắn `mockResolvedValue`: `vitest.config.ts` bật `mockReset`, nên
  // mọi implementation bị xoá trước mỗi ca; `vi.fn()` trả `undefined` và
  // `await undefined` là hợp lệ — mutationFn ở đây trả `void`. Ca này đo URL,
  // không đo phản hồi.
  it("useAdminAssignRole gửi POST tới /api/admin/roles/assign", async () => {
    const { result } = renderHook(() => useAdminAssignRole(), { wrapper: createWrapper() });

    result.current.mutate({ user_id: 7, role: "role:manager" });

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.ASSIGN);
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("useAdminRemoveRole gửi DELETE tới /api/admin/roles/revoke", async () => {
    const { result } = renderHook(() => useAdminRemoveRole(), { wrapper: createWrapper() });

    result.current.mutate({ user_id: 7, role: "role:manager" });

    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.delete, 0)).toBe(DUONG_THAT.REVOKE);
    // Thu hồi KHÔNG được đi qua đường gán — đây là ca bắt được bản cũ, nơi hook
    // xoá dùng `ASSIGN_ROLE` với method DELETE.
    expect(api.post).not.toHaveBeenCalled();
  });

  it("payload thu hồi đi trong `data` của config, không phải body vị trí 2", async () => {
    // Axios `delete(url, config)` — truyền payload sai chỗ thì backend nhận
    // body rỗng và trả 422, một lỗi im lặng ở tầng client.
    const { result } = renderHook(() => useAdminRemoveRole(), { wrapper: createWrapper() });

    result.current.mutate({ user_id: 7, role: "role:manager" });

    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.delete, 1)).toEqual({
      data: { user_id: 7, role: "role:manager" },
    });
  });
});
