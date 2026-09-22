// src/app/(dashboard)/notifications/_components/NotificationTable.safe-link.test.tsx
/**
 * Bất biến ở TẦNG COMPONENT: `href` THẬT SỰ render ra DOM phải là đích nội bộ.
 *
 * Vì sao không dừng ở bộ ca của `resolveSafeUrl`: một vị từ xanh không chứng
 * minh component ĐÃ GỌI nó. Bốn sink `<Link href={notification.link}>` trước
 * bản vá này **không gọi guard nào** — `isSafeUrl` xanh suốt mà liên kết ngoài
 * site vẫn đi thẳng vào DOM. Bộ ca ở đây đọc chính thuộc tính `href` của thẻ
 * neo, tức thứ trình duyệt sẽ dùng.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { NotificationTable } from "./NotificationTable";
import type { Notification } from "@/types/api.types";

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

function taoThongBao(id: number, link: string | null): Notification {
  return {
    id,
    title: `Thông báo ${id}`,
    message: "nội dung",
    type: "info",
    is_read: false,
    created_at: new Date("2026-09-20T00:00:00Z").toISOString(),
    link,
    data: null,
  } as unknown as Notification;
}

const PROPS_CHUNG = {
  selectedIds: [] as number[],
  onSelect: vi.fn(),
  onSelectAll: vi.fn(),
  onMarkAsRead: vi.fn(),
  onDelete: vi.fn(),
  getNotificationIcon: () => <span data-testid="icon" />,
  getNotificationTypeBadge: () => <span data-testid="badge" />,
};

/** Mỗi tải trọng là MỘT cách thoát site khác nhau. */
const LIEN_KET_NGUY_HIEM: Array<[string, string]> = [
  ["TAB nội bộ", "/\t/evil.example"],
  ["backslash", "/\\evil.example"],
  ["domain nối đuôi", "https://qlts.example.evil.com/x"],
  ["userinfo @", "https://qlts.example@evil.com/x"],
  ["scheme-relative", "//evil.example/x"],
  ["javascript:", "javascript:alert(1)"],
  ["dot-segment tụt xuống `//`", "/..//evil.example"],
];

describe("NotificationTable — không bao giờ render href nguy hiểm", () => {
  it.each(LIEN_KET_NGUY_HIEM)(
    "%s: không có thẻ neo nào mang liên kết đó",
    (_ten, link) => {
      render(
        <NotificationTable
          {...PROPS_CHUNG}
          notifications={[taoThongBao(1, link)]}
        />,
      );

      // Tiêu đề vẫn hiển thị — chặn liên kết KHÔNG được nuốt mất nội dung.
      expect(screen.getAllByText("Thông báo 1").length).toBeGreaterThan(0);

      for (const neo of document.querySelectorAll("a[href]")) {
        const href = neo.getAttribute("href") ?? "";
        expect(href.startsWith("//")).toBe(false);
        expect(/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(href)).toBe(false);
        expect(href.includes("evil")).toBe(false);
      }
    },
  );

  it("liên kết nội bộ hợp lệ VẪN được render đúng", () => {
    render(
      <NotificationTable
        {...PROPS_CHUNG}
        notifications={[taoThongBao(2, "/ho-so/123?tab=a#b")]}
      />,
    );
    const neo = Array.from(document.querySelectorAll("a[href]")).filter(
      (a) => a.getAttribute("href") === "/ho-so/123?tab=a#b",
    );
    expect(neo.length).toBeGreaterThan(0);
  });
});
