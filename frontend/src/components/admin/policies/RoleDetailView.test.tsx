// src/components/admin/policies/RoleDetailView.test.tsx
/**
 * RoleDetailView — query explain hỏng thì phải NÓI RA.
 *
 * Bản cũ: `if (!data) return null;`. Endpoint explain chết ⇒ component biến mất
 * không một tín hiệu nào; màn "quyền đến từ đâu" rỗng ở MỌI role trông y hệt
 * "role này chưa có quyền" ⇒ một đường API chết sống sót rất lâu mà không ai
 * thấy.
 *
 * Bất biến được khoá ở đây: query hỏng ⇒ có trạng thái lỗi nhìn thấy được,
 * KHÔNG phải màn hình trắng, và không có bảng nào giả vờ là dữ liệu thật.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const hoisted = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    get: (...args: unknown[]) => hoisted.apiGet(...args),
  },
}));

import { RoleDetailView } from "./RoleDetailView";

const EXPLAIN_FAILURE = new Error("explain endpoint returned 404");

const EXPLAIN_PAYLOAD = {
  data: {
    role: "role:officer",
    policies_from_template: [
      { subject: "role:officer", object: "/api/leads", action: "GET" },
    ],
    policies_from_features: [],
    policies_manual: [],
    policies_inherited: [
      { subject: "role:officer", object: "/api/profile", action: "GET" },
    ],
  },
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

function renderDetail(roleName = "role:officer") {
  const Wrapper = makeWrapper();
  return render(
    <Wrapper>
      <RoleDetailView roleName={roleName} />
    </Wrapper>
  );
}

describe("RoleDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("query explain THẤT BẠI", () => {
    it("hiện trạng thái lỗi thay vì màn hình trắng", async () => {
      hoisted.apiGet.mockRejectedValue(EXPLAIN_FAILURE);

      const { container } = renderDetail();

      const errorBox = await screen.findByTestId("role-explain-error");
      expect(errorBox).toHaveTextContent("Không tải được phân rã quyền");
      expect(errorBox).toHaveTextContent("role:officer");
      // bản cũ `return null` cho ra đúng một container rỗng
      expect(container).not.toBeEmptyDOMElement();
    });

    it("KHÔNG vẽ bảng quyền rỗng như thể đó là dữ liệu thật", async () => {
      hoisted.apiGet.mockRejectedValue(EXPLAIN_FAILURE);

      renderDetail();

      await screen.findByTestId("role-explain-error");
      expect(screen.queryByText(/Permission Breakdown/)).not.toBeInTheDocument();
      expect(screen.queryByText("No policies found")).not.toBeInTheDocument();
      expect(screen.queryByText(/From Template/)).not.toBeInTheDocument();
    });

    it("kèm nguyên nhân và nút thử lại", async () => {
      hoisted.apiGet.mockRejectedValue(EXPLAIN_FAILURE);

      renderDetail();

      await screen.findByTestId("role-explain-error");
      expect(
        screen.getByText("explain endpoint returned 404")
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Thử lại/ })
      ).toBeInTheDocument();
    });
  });

  describe("ca đối chứng", () => {
    it("query thành công ⇒ vẽ bảng phân rã, không có trạng thái lỗi", async () => {
      hoisted.apiGet.mockResolvedValue(EXPLAIN_PAYLOAD);

      renderDetail();

      expect(
        await screen.findByText("Permission Breakdown for role:officer")
      ).toBeInTheDocument();
      expect(screen.getByText("From Template (1)")).toBeInTheDocument();
      expect(screen.getByText("Inherited Policies (1)")).toBeInTheDocument();
      expect(screen.queryByTestId("role-explain-error")).not.toBeInTheDocument();
    });
  });
});
