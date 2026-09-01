// src/components/admin/policies/SyncDashboard.test.tsx
/**
 * SyncDashboard — cổng fail-closed cho trạng thái đồng bộ DB ↔ Casbin.
 *
 * Bản cũ đọc số liệu bằng `syncStatus?.x || 0`. Query hỏng ⇒ `undefined` ⇒ 0 ⇒
 * dashboard vẽ "Tổng số Users 0 · Đã đồng bộ 0 · Chưa đồng bộ 0" rồi rơi vào
 * nhánh `outOfSyncCount > 0 ? ... : <Alert>Hệ thống đã đồng bộ</Alert>`. Tức là
 * KHẲNG ĐỊNH hệ thống sạch đúng lúc nó không đo được gì — báo cáo sai, không
 * phải báo lỗi.
 *
 * Bất biến được khoá ở đây: API hỏng ⇒ không một con số nào, không banner
 * "đã đồng bộ"; thay vào đó là trạng thái lỗi tường minh + nút thử lại.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  getSyncStatus: vi.fn(),
  syncUsers: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: hoisted.toastSuccess,
    error: hoisted.toastError,
  },
}));

vi.mock("@/lib/api/policies", () => ({
  policiesApi: {
    getSyncStatus: () => hoisted.getSyncStatus(),
    syncUsers: (userIds: number[] | null) => hoisted.syncUsers(userIds),
  },
}));

import { SyncDashboard } from "./SyncDashboard";

const STATUS_FAILURE = new Error("sync-status endpoint returned 404");

// Kiểu của phản hồi được khai ở tầng API; dựng lại tại chỗ để bài test này
// không phải nhập kiểu xuyên tầng (guard kiến trúc cấm component chạm tầng đó).
const HEALTHY_STATUS = {
  total_users: 42,
  synced_count: 40,
  out_of_sync_count: 2,
  mismatched_users: [
    {
      user_id: 7,
      username: "officer.a",
      db_role: "officer",
      casbin_role: "manager",
      all_casbin_roles: ["role:manager"],
    },
    {
      user_id: 9,
      username: "officer.b",
      db_role: "user",
      casbin_role: "officer",
      all_casbin_roles: ["role:officer"],
    },
  ],
};

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

function renderDashboard() {
  const Wrapper = makeWrapper();
  return render(
    <Wrapper>
      <SyncDashboard />
    </Wrapper>
  );
}

describe("SyncDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("query trạng thái đồng bộ THẤT BẠI", () => {
    // Hai ca dưới CỐ Ý chờ `role="alert"` chứ không chờ testid của hộp lỗi:
    // cả trạng thái lỗi lẫn banner "đã đồng bộ" đều là `role="alert"`, nên khi
    // guard bị gỡ, bài test đỏ ngay ở mệnh đề thật (banner/số 0 xuất hiện) chứ
    // không đỏ vì hết giờ chờ một testid — đọc ra đúng nguyên nhân.
    it("KHÔNG hiển thị banner 'Hệ thống đã đồng bộ'", async () => {
      hoisted.getSyncStatus.mockRejectedValue(STATUS_FAILURE);

      renderDashboard();

      await screen.findByRole("alert");
      expect(screen.queryByText("Hệ thống đã đồng bộ")).not.toBeInTheDocument();
    });

    it("KHÔNG vẽ số liệu nào — kể cả số 0", async () => {
      hoisted.getSyncStatus.mockRejectedValue(STATUS_FAILURE);

      renderDashboard();

      await screen.findByRole("alert");
      expect(screen.queryByText("Tổng số Users")).not.toBeInTheDocument();
      expect(screen.queryByText(/^Đã đồng bộ$/)).not.toBeInTheDocument();
      expect(screen.queryByText(/^Chưa đồng bộ$/)).not.toBeInTheDocument();
      // `|| 0` cũ biến lỗi thành con số 0; không được có con số nào cả.
      expect(screen.queryByText("0")).not.toBeInTheDocument();
    });

    it("hiện trạng thái lỗi tường minh kèm nguyên nhân và nút thử lại", async () => {
      hoisted.getSyncStatus.mockRejectedValue(STATUS_FAILURE);

      renderDashboard();

      const errorBox = await screen.findByTestId("sync-status-error");
      expect(errorBox).toHaveTextContent("Không đọc được trạng thái đồng bộ");
      expect(
        screen.getByText("sync-status endpoint returned 404")
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Thử lại/ })
      ).toBeInTheDocument();
    });
  });

  describe("ca đối chứng", () => {
    it("API trả dữ liệu thật ⇒ MỚI vẽ số liệu, không có trạng thái lỗi", async () => {
      hoisted.getSyncStatus.mockResolvedValue(HEALTHY_STATUS);

      renderDashboard();

      expect(await screen.findByText("42")).toBeInTheDocument();
      expect(screen.getByText("40")).toBeInTheDocument();
      expect(
        screen.getByText("Phát hiện 2 user(s) chưa đồng bộ!")
      ).toBeInTheDocument();
      expect(screen.getByText("officer.a")).toBeInTheDocument();
      expect(screen.queryByTestId("sync-status-error")).not.toBeInTheDocument();
    });

    it("API trả 0 lệch THẬT ⇒ banner 'Hệ thống đã đồng bộ' vẫn xuất hiện", async () => {
      hoisted.getSyncStatus.mockResolvedValue({
        total_users: 42,
        synced_count: 42,
        out_of_sync_count: 0,
        mismatched_users: [],
      });

      renderDashboard();

      expect(await screen.findByText("Hệ thống đã đồng bộ")).toBeInTheDocument();
      expect(screen.queryByTestId("sync-status-error")).not.toBeInTheDocument();
    });
  });
});
