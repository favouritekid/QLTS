// @vitest-environment jsdom
/**
 * GUARD — bất biến "lần render client ĐẦU TIÊN của mỗi instance `NavUser`
 * phải dùng đúng dữ liệu server (user chưa khả dụng)".
 *
 * Cách đo: `renderToString` với `useAuth().user = null` (điều kiện server), rồi
 * `hydrateRoot` ĐÚNG chuỗi HTML đó trong khi `useAuth()` ĐÃ có user (điều kiện
 * client có persisted user — `auth.store.ts:79-87` rehydrate ĐỒNG BỘ từ
 * localStorage TRƯỚC lần render React đầu tiên). Nếu component đọc thẳng
 * persisted user ở lần render đầu, React báo recoverable error.
 *
 * Node được canh: chữ tắt avatar (`??` ↔ `VO`) và nhánh skeleton ↔ nhánh button.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as React from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { act } from "react";

type GiaLapUser = {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: string;
  avatar_url: string | null;
};

const authState: { user: GiaLapUser | null; isLoading: boolean } = { user: null, isLoading: false };

// KHÔNG chạm `useAuth` thật: cổng này chỉ đổi THỜI ĐIỂM render, không đổi
// nguồn quyền hạn. Giả lập đúng hai điều kiện server/client.
// `isLoading` ĐỔI ĐƯỢC: nó do react-query quyết định nên hoàn toàn có thể khác
// nhau giữa lượt render server và lượt hydrate ở client.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: authState.user, logout: () => {}, isLoading: authState.isLoading }),
}));

// `next/link` cần router context của App Router; ở đây chỉ cần đúng thẻ <a>.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children?: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { NavUser } from "./NavUser";

const USER_OFFICER: GiaLapUser = {
  id: 1,
  username: "votest",
  full_name: "Vo Test",
  email: "votest@example.com",
  role: "officer",
  avatar_url: null,
};

async function hydrateVaThuLoi(container: HTMLElement, el: React.ReactElement): Promise<string[]> {
  const recoverable: string[] = [];
  await act(async () => {
    hydrateRoot(container, el, {
      onRecoverableError: (e) => recoverable.push(String((e as Error)?.message ?? e)),
    });
  });
  return recoverable.filter((m) => /[Hh]ydrat/.test(m));
}

describe("NavUser — lần render client đầu tiên phải khớp server", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });
  afterEach(() => {
    container.remove();
    authState.user = null;
    authState.isLoading = false;
  });

  it("không sinh hydration mismatch khi client ĐÃ có user từ persist", async () => {
    authState.user = null;
    authState.isLoading = false;
    const serverHtml = renderToString(<NavUser isCollapsed={false} />);
    container.innerHTML = serverHtml;

    authState.user = USER_OFFICER;
    expect(await hydrateVaThuLoi(container, <NavUser isCollapsed={false} />)).toEqual([]);
  });

  it("server và client BẤT ĐỒNG về `isLoading` thì cây đầu tiên vẫn phải khớp", async () => {
    // Điều kiện server: `/me` chưa chạy, `isLoading=false`, `user=null`.
    authState.user = null;
    authState.isLoading = false;
    const serverHtml = renderToString(<NavUser isCollapsed={false} />);
    container.innerHTML = serverHtml;

    // Điều kiện client lúc hydrate: persisted user ĐÃ có VÀ `/me` đang bay.
    // Nếu nhánh skeleton được chọn bằng `isLoading` THÔ (không qua `hasMounted`)
    // thì hai cây rẽ khác nhau ngay lần render đầu.
    authState.user = USER_OFFICER;
    authState.isLoading = true;
    expect(await hydrateVaThuLoi(container, <NavUser isCollapsed={false} />)).toEqual([]);
  });

  it("instance mount MUỘN cũng phải khớp server — cờ phải THEO TỪNG INSTANCE", async () => {
    // HTML server chỉ được dựng MỘT LẦN: server thật không biết gì về cờ client.
    authState.user = null;
    const serverHtml = renderToString(<NavUser isCollapsed={false} />);

    // Cây thứ nhất hydrate bình thường. Nếu readiness là TOÀN CỤC, nó bật ở đây.
    const first = document.createElement("div");
    document.body.appendChild(first);
    first.innerHTML = serverHtml;
    authState.user = USER_OFFICER;
    await act(async () => {
      hydrateRoot(first, <NavUser isCollapsed={false} />, { onRecoverableError: () => {} });
    });

    // Cây thứ hai: mô phỏng biên <Suspense> được GHÉP MUỘN — cùng HTML server.
    const late = document.createElement("div");
    document.body.appendChild(late);
    late.innerHTML = serverHtml;
    const loi = await hydrateVaThuLoi(late, <NavUser isCollapsed={false} />);
    first.remove();
    late.remove();

    expect(loi).toEqual([]);
  });

  it("sau khi mount mới hiện chữ tắt avatar và tên người dùng", async () => {
    authState.user = null;
    const serverHtml = renderToString(<NavUser isCollapsed={false} />);
    expect(serverHtml).not.toContain("VO");
    expect(serverHtml).not.toContain("Vo Test");
    container.innerHTML = serverHtml;

    authState.user = USER_OFFICER;
    await act(async () => {
      hydrateRoot(container, <NavUser isCollapsed={false} />, { onRecoverableError: () => {} });
    });

    expect(container.innerHTML).toContain("VO");
    expect(container.innerHTML).toContain("Vo Test");
  });
});
