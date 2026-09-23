// src/components/notifications/NotificationDropdown.safe-link.test.tsx
/**
 * Bất biến ở TẦNG SINK cho `<Link href={…}>` của chuông thông báo.
 *
 * 🔴 VÌ SAO TỆP NÀY PHẢI TỒN TẠI
 * Trước 22-09, `NotificationDropdown.tsx` **không có tệp test nào**. Bản vá
 * `2c118b5a` đã thay `notification.link` thô bằng `resolveSafeUrl(...)` ở đây,
 * nhưng phép kiểm ngược cho thấy gỡ lại bản vá ấy ra thì **0 ca đỏ** trên toàn
 * bộ 240 tệp / 2.486 ca — nghĩa là bản vá không được ca nào canh. Một guard
 * không có ca canh là một guard sẽ bị gỡ lúc refactor mà không ai biết.
 *
 * Bộ ca đọc chính thuộc tính `href` render ra DOM — tức thứ trình duyệt thật
 * sự dùng — chứ không đọc giá trị trả về của `resolveSafeUrl`. Một vị từ xanh
 * KHÔNG chứng minh component đã gọi nó.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// DropdownMenu: render content luôn mở, theo đúng khuôn đã dùng ở
// `ProfileActionMenu.test.tsx`. Bất biến cần canh là **thuộc tính `href` đi
// vào DOM**, không phải cơ chế đóng/mở của Radix — và Radix cần chuỗi sự kiện
// pointer mà jsdom không dựng đủ.
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode; asChild?: boolean }) => (
    <>{children}</>
  ),
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dropdown-content">{children}</div>
  ),
  DropdownMenuLabel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
}));

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

const duLieuThongBao = vi.fn();

vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => duLieuThongBao(),
  useMarkAsRead: () => ({ mutate: vi.fn() }),
  useMarkAllAsRead: () => ({ mutate: vi.fn() }),
}));

import { NotificationDropdown } from "./NotificationDropdown";

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

/**
 * Mỗi tải trọng là MỘT cách thoát site khác nhau.
 *
 * ⚠️ TAB/LF/CR ở đây là ký tự THẬT. Trình phân giải URL của WHATWG XOÁ chúng
 * trước khi parse, nên `"/\t/evil.example"` trở thành `"//evil.example"` — đổi
 * origin. Một ca viết literal `"%09"` sẽ XANH mà không chạm tới lỗ hổng.
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

describe("NotificationDropdown — không bao giờ render href nguy hiểm", () => {
  it.each(LIEN_KET_NGUY_HIEM)(
    "%s: không thẻ neo nào mang liên kết đó",
    (_ten, link) => {
      duLieuThongBao.mockReturnValue({
        data: { notifications: [thongBao(1, link)], unread_count: 1 },
        isLoading: false,
        isError: false,
      });

      render(<NotificationDropdown />);

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
      },
      isLoading: false,
      isError: false,
    });

    render(<NotificationDropdown />);

    const khop = Array.from(document.querySelectorAll("a[href]")).filter(
      (a) => a.getAttribute("href") === "/ho-so/123?tab=a#b",
    );
    expect(khop.length).toBeGreaterThan(0);
  });

  it("`/a/../b` được CHUẨN HOÁ về `/b` trước khi vào DOM", () => {
    duLieuThongBao.mockReturnValue({
      data: { notifications: [thongBao(3, "/a/../b")], unread_count: 1 },
      isLoading: false,
      isError: false,
    });

    render(<NotificationDropdown />);

    const khop = Array.from(document.querySelectorAll("a[href]")).filter(
      (a) => a.getAttribute("href") === "/b",
    );
    expect(khop.length).toBeGreaterThan(0);
  });
});
