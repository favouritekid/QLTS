// @vitest-environment jsdom
/**
 * Mục "Đồng bộ ký túc xá" trong sidebar — ai thấy, và thấy đúng đường nào.
 *
 * 🔴 Đi qua `useAppNavigation`, KHÔNG đọc thẳng `navigationConfig`.
 *
 * Đọc thẳng config chỉ chứng minh có người gõ đúng chuỗi `["admin"]` vào một
 * mảng. Nó không chứng minh phép lọc thật sự chạy — mà phép lọc mới là thứ
 * quyết định người dùng nhìn thấy gì. Một mục khai `roles` chuẩn vẫn hiện với
 * mọi vai trò nếu nhánh lọc bị bỏ qua ở đâu đó trên đường.
 *
 * ⚠️ `roles` ở đây chỉ quyết định MỤC CÓ HIỆN HAY KHÔNG, không phải hàng rào
 * quyền. Cổng thật nằm ở backend (`require_admin` trên cả ba endpoint); ai gõ
 * thẳng URL vẫn bị chặn ở đó. Sidebar giấu một đường dẫn không có nghĩa là
 * đường ấy đã đóng.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAppNavigation } from "@/hooks/useAppNavigation";

const { mockUser } = vi.hoisted(() => ({
  mockUser: { current: null as { role: string } | null },
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: mockUser.current }),
}));

const DUONG_DAN = "/admin/dorm-sync";

function timMuc(role: string | null) {
  mockUser.current = role === null ? null : { role };
  const { result } = renderHook(() => useAppNavigation());
  return result.current.navigation
    .flatMap((nhom) => nhom.items)
    .find((muc) => muc.href === DUONG_DAN);
}

describe("mục Đồng bộ ký túc xá", () => {
  it("admin thấy mục, đúng href và đúng nhãn", () => {
    const muc = timMuc("admin");

    expect(muc).toBeDefined();
    // Đúng ĐƯỜNG DẪN, không chỉ "có một mục nào đó". Màn hình nằm ở
    // `app/(dashboard)/admin/dorm-sync/page.tsx`; gõ sai một ký tự thì mục vẫn
    // hiện và vẫn bấm được, chỉ dẫn tới trang 404.
    expect(muc?.href).toBe(DUONG_DAN);
    expect(muc?.label).toBe("Đồng bộ ký túc xá");
  });

  it.each(["manager", "officer", "accountant", "user"])(
    "%s KHÔNG thấy mục",
    (role) => {
      expect(timMuc(role)).toBeUndefined();
    },
  );

  it("chưa đăng nhập thì KHÔNG thấy mục", () => {
    // Ca này không thừa: nhánh `!user?.role` trong `hasAccess` là một đường
    // riêng, và nó trả `true` cho mọi mục không khai `roles`. Một mục khai
    // thiếu `roles` sẽ lọt qua đúng ở đây chứ không phải ở các ca trên.
    expect(timMuc(null)).toBeUndefined();
  });

  it("mục nằm trong nhóm System, cạnh các màn quản trị khác", () => {
    mockUser.current = { role: "admin" };
    const { result } = renderHook(() => useAppNavigation());

    const nhom = result.current.navigation.find((g) =>
      g.items.some((muc) => muc.href === DUONG_DAN),
    );

    expect(nhom?.title).toBe("System");
  });
});
