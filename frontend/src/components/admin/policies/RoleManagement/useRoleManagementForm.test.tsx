// src/components/admin/policies/RoleManagement/useRoleManagementForm.test.tsx
/**
 * useRoleManagementForm — cổng "tạo role" phải fail-closed ở BƯỚC 2.
 *
 * Bối cảnh: tạo role gồm hai lần ghi vào Casbin.
 *   BƯỚC 1  POST policy cơ bản        → role tồn tại
 *   BƯỚC 2  POST grouping policy      → role kế thừa `role:user`
 *
 * Bản cũ nuốt lỗi bước 2 bằng `console.warn` rồi VẪN `toast.success(...)`:
 * admin đọc "created successfully" trong khi role thiếu toàn bộ quyền kế thừa.
 *
 * Bất biến được khoá ở đây: bước 2 hỏng ⇒ KHÔNG có tín hiệu thành công nào
 * (không toast success, không đi tiếp bước 3), và thông điệp lỗi phải mang đủ
 * dữ kiện để admin sửa tay (role nào, bước nào, lỗi gì).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  addPolicy: vi.fn(),
  addGroupingPolicy: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  apiGet: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: hoisted.toastSuccess,
    error: hoisted.toastError,
  },
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    get: (...args: unknown[]) => hoisted.apiGet(...args),
    delete: (...args: unknown[]) => hoisted.apiDelete(...args),
  },
}));

// Mock ở TẦNG HOOK (không ở tầng URL) một cách cố ý: bài test này phải độc lập
// với việc sửa đường API đang diễn ra song song trong `endpoints.ts`.
vi.mock("@/hooks/usePolicies", () => ({
  policyKeys: { all: ["policies"] },
  useRoles: () => ({ data: { roles: [] }, isLoading: false }),
  usePolicies: () => ({ data: [] }),
  useAddPolicy: () => ({ mutateAsync: hoisted.addPolicy }),
  useAddGroupingPolicy: () => ({ mutateAsync: hoisted.addGroupingPolicy }),
}));

import { useRoleManagementForm } from "./useRoleManagementForm";

/** Lấy đối số thứ nhất của một lần gọi mock mà không cần ép kiểu rộng. */
function messageOf(call: unknown[] | undefined): string {
  const first = call?.[0];
  return typeof first === "string" ? first : "";
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

/** Lỗi hình dáng AxiosError — `describeError` phải rút được `detail`. */
const INHERIT_FAILURE = {
  response: { data: { detail: "grouping policy route not found (404)" } },
};

describe("useRoleManagementForm.handleCreateRole", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("bước 2 (kế thừa role:user) THẤT BẠI sau khi bước 1 đã thành công", () => {
    async function createRoleWithFailingInheritance() {
      hoisted.addPolicy.mockResolvedValue({ ok: true });
      hoisted.addGroupingPolicy.mockRejectedValue(INHERIT_FAILURE);

      const { result } = renderHook(() => useRoleManagementForm(), {
        wrapper: makeWrapper(),
      });

      await act(async () => {
        await result.current.handleCreateRole("marketing", "Marketing team");
      });

      return result;
    }

    it("KHÔNG được toast thành công (đây là bất biến chính)", async () => {
      await createRoleWithFailingInheritance();

      // Cả hai bước đều đã được gọi — tức là ta thật sự đi qua đúng nhánh
      // "bước 1 xong, bước 2 hỏng", không phải hỏng từ trước.
      expect(hoisted.addPolicy).toHaveBeenCalledTimes(1);
      expect(hoisted.addGroupingPolicy).toHaveBeenCalledTimes(1);

      expect(hoisted.toastSuccess).not.toHaveBeenCalled();
    });

    it("báo partial creation kèm tên role, bước hỏng và lỗi gốc", async () => {
      await createRoleWithFailingInheritance();

      expect(hoisted.toastError).toHaveBeenCalledTimes(1);
      const message = messageOf(hoisted.toastError.mock.calls[0]);

      expect(message).toContain("Partial creation");
      expect(message).toContain("marketing");
      expect(message).toContain("role:marketing");
      expect(message).toContain("STEP 2");
      expect(message).toContain("role:user");
      // dữ kiện gốc từ backend phải đi kèm, không bị nuốt
      expect(message).toContain("grouping policy route not found (404)");
    });

    it("không đẩy admin sang bước tiếp theo như thể đã xong", async () => {
      const result = await createRoleWithFailingInheritance();

      expect(result.current.currentStep).toBe("SELECT_ROLE");
      expect(result.current.selectedRole).toBeNull();
    });

    it("KHÔNG rollback giả vờ: không có lần ghi bù nào sau khi bước 2 hỏng", async () => {
      await createRoleWithFailingInheritance();

      // đúng 1 lần ghi policy (bước 1) + 1 lần ghi grouping (bước 2 hỏng),
      // không có DELETE bù nào — trạng thái nửa vời được phơi ra, không bị che.
      expect(hoisted.addPolicy).toHaveBeenCalledTimes(1);
      expect(hoisted.apiDelete).not.toHaveBeenCalled();
    });
  });

  describe("ca đối chứng", () => {
    it("cả hai bước thành công ⇒ MỚI toast success và đi tiếp bước 3", async () => {
      hoisted.addPolicy.mockResolvedValue({ ok: true });
      hoisted.addGroupingPolicy.mockResolvedValue({ ok: true });

      const { result } = renderHook(() => useRoleManagementForm(), {
        wrapper: makeWrapper(),
      });

      await act(async () => {
        await result.current.handleCreateRole("marketing", "Marketing team");
      });

      expect(hoisted.toastSuccess).toHaveBeenCalledTimes(1);
      expect(messageOf(hoisted.toastSuccess.mock.calls[0])).toContain(
        "created successfully"
      );
      expect(hoisted.toastError).not.toHaveBeenCalled();
      expect(result.current.currentStep).toBe("MANAGE_FEATURES");
      expect(result.current.selectedRole).toBe("role:marketing");
    });

    it("bước 1 hỏng ⇒ lỗi 'Failed to create role', KHÔNG chạy bước 2", async () => {
      hoisted.addPolicy.mockRejectedValue(new Error("policy endpoint 500"));

      const { result } = renderHook(() => useRoleManagementForm(), {
        wrapper: makeWrapper(),
      });

      await act(async () => {
        await result.current.handleCreateRole("marketing", "Marketing team");
      });

      expect(hoisted.addGroupingPolicy).not.toHaveBeenCalled();
      expect(hoisted.toastSuccess).not.toHaveBeenCalled();
      expect(messageOf(hoisted.toastError.mock.calls[0])).toContain(
        "Failed to create role"
      );
    });
  });
});
