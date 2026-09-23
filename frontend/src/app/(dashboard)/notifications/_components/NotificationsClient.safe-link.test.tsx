// src/app/(dashboard)/notifications/_components/NotificationsClient.safe-link.test.tsx
/**
 * Bất biến ở TẦNG SINK cho `<Link href={…}>` của **chế độ xem DANH SÁCH**
 * trong `NotificationsClient`.
 *
 * 🔴 VÌ SAO KHÔNG DỪNG Ở `NotificationTable.safe-link.test.tsx`
 * `NotificationsClient` có HAI đường render: `viewMode === "table"` uỷ quyền
 * cho `NotificationTable` (đã có ca canh), còn nhánh mặc-định-khác là danh
 * sách thẻ, với một sink `<Link>` RIÊNG dùng chính `notification.link`. Vì
 * `viewMode` khởi tạo là `"table"`, sink danh sách **không bao giờ render**
 * trong bộ ca cũ — gỡ guard ở đó ra thì 0/2.486 ca đỏ. Đây đúng là "vá một
 * nhánh thì còn bốn nhánh" (CLAUDE.md §6) ở quy mô một tệp.
 *
 * Bộ ca chuyển sang chế độ danh sách rồi đọc `href` THẬT trong DOM.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// ToggleGroup của Radix cần chuỗi sự kiện pointer mà jsdom không dựng đủ.
// Bất biến cần canh là `href` trong DOM, không phải cơ chế của Radix.
vi.mock("@/components/ui/toggle-group", () => ({
  ToggleGroup: ({
    children,
    onValueChange,
  }: {
    children: React.ReactNode;
    onValueChange?: (v: string) => void;
    value?: string;
    type?: string;
  }) => (
    <div
      data-testid="toggle-group"
      onClick={(e) => {
        const v = (e.target as HTMLElement).closest("[data-value]")?.getAttribute("data-value");
        if (v && onValueChange) onValueChange(v);
      }}
    >
      {children}
    </div>
  ),
  ToggleGroupItem: ({
    children,
    value,
    ...rest
  }: {
    children: React.ReactNode;
    value: string;
    [key: string]: unknown;
  }) => (
    <button data-value={value} {...rest}>
      {children}
    </button>
  ),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

const duLieuThongBao = vi.fn();

vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => duLieuThongBao(),
  useMarkAsRead: () => ({ mutate: vi.fn() }),
  useMarkAllAsRead: () => ({ mutate: vi.fn() }),
  useDeleteNotification: () => ({ mutate: vi.fn() }),
  useBulkDeleteNotifications: () => ({ mutate: vi.fn() }),
}));

import { NotificationsClient } from "./NotificationsClient";

function thongBao(id: number, link: string | null) {
  return {
    id,
    title: `Thông báo ${id}`,
    message: "nội dung",
    type: "info",
    is_read: false,
    created_at: new Date("2026-09-20T00:00:00Z").toISOString(),
    link,
    data: null,
  };
}

/** Chuyển sang chế độ xem DANH SÁCH — nơi sink `<Link>` riêng được render. */
function chuyenSangDanhSach() {
  fireEvent.click(screen.getByLabelText("List view"));
}

/**
 * Mỗi tải trọng là MỘT cách thoát site khác nhau.
 *
 * ⚠️ TAB/LF/CR là ký tự THẬT. WHATWG XOÁ chúng trước khi parse, nên
 * `"/\t/evil.example"` trở thành `"//evil.example"` — đổi origin. Một ca viết
 * literal `"%09"` sẽ XANH mà không chạm tới lỗ hổng.
 */
const LIEN_KET_NGUY_HIEM: Array<[string, string]> = [
  ["TAB nội bộ", "/\t/evil.example"],
  ["LF nội bộ", "/\n/evil.example"],
  ["CR nội bộ", "/\r/evil.example"],
  ["một backslash", "/\\evil.example"],
  ["domain nối đuôi", "https://qlts.example.evil.com/x"],
  ["userinfo @", "https://qlts.example@evil.com/x"],
  ["scheme-relative", "//evil.example/x"],
  ["javascript:", "javascript:alert(1)"],
  ["dot-segment tụt xuống `//`", "/..//evil.example"],
];

beforeEach(() => {
  duLieuThongBao.mockReset();
});

describe("NotificationsClient (chế độ DANH SÁCH) — href không bao giờ rời site", () => {
  it.each(LIEN_KET_NGUY_HIEM)(
    "%s: không thẻ neo nào mang liên kết đó",
    (_ten, link) => {
      duLieuThongBao.mockReturnValue({
        data: {
          notifications: [thongBao(1, link)],
          unread_count: 1,
          total_count: 1,
        },
        isLoading: false,
      });

      render(<NotificationsClient />);
      chuyenSangDanhSach();

      // Nội dung vẫn hiển thị — chặn liên kết KHÔNG được nuốt mất thông báo.
      expect(screen.getAllByText("Thông báo 1").length).toBeGreaterThan(0);

      for (const neo of document.querySelectorAll("a[href]")) {
        const href = neo.getAttribute("href") ?? "";
        expect(href.startsWith("//")).toBe(false);
        expect(/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(href)).toBe(false);
        expect(href.includes("evil")).toBe(false);
      }
    },
  );

  it("liên kết nội bộ hợp lệ VẪN render đúng đích", () => {
    duLieuThongBao.mockReturnValue({
      data: {
        notifications: [thongBao(2, "/ho-so/123?tab=a#b")],
        unread_count: 1,
        total_count: 1,
      },
      isLoading: false,
    });

    render(<NotificationsClient />);
    chuyenSangDanhSach();

    const khop = Array.from(document.querySelectorAll("a[href]")).filter(
      (a) => a.getAttribute("href") === "/ho-so/123?tab=a#b",
    );
    expect(khop.length).toBeGreaterThan(0);
  });

  it("`/a/../b` được CHUẨN HOÁ về `/b` trước khi vào DOM", () => {
    duLieuThongBao.mockReturnValue({
      data: {
        notifications: [thongBao(3, "/a/../b")],
        unread_count: 1,
        total_count: 1,
      },
      isLoading: false,
    });

    render(<NotificationsClient />);
    chuyenSangDanhSach();

    const khop = Array.from(document.querySelectorAll("a[href]")).filter(
      (a) => a.getAttribute("href") === "/b",
    );
    expect(khop.length).toBeGreaterThan(0);
  });
});
